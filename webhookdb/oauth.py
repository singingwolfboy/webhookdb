# coding=utf-8
from __future__ import unicode_literals, print_function

import os
from datetime import datetime

from flask import request, flash
from flask_dance.contrib.github import make_github_blueprint
from flask_dance.consumer.oauth2 import OAuth2SessionWithBaseURL
from flask_dance.consumer import oauth_authorized
from flask_login import login_user, current_user
from webhookdb import db
from webhookdb.models import OAuth
from webhookdb.exceptions import RateLimited


class GithubSession(OAuth2SessionWithBaseURL):
    """
    A requests.Session subclass with a few special properties:

    * base_url relative resolution (from OAuth2SessionWithBaseURL)
    * remembers the last request it made, using the `last_response` property
    * raises a RateLimited exception if our Github rate limit has expired
    """
    last_response = None

    def request(self, method, url, data=None, headers=None, **kwargs):
        resp = super(GithubSession, self).request(
            method=method, url=url, data=data, headers=headers, **kwargs
        )
        self.last_response = resp
        if resp.headers.get("X-RateLimit-Remaining"):
            rl_remaining = int(resp.headers["X-RateLimit-Remaining"])
            if rl_remaining < 1:
                raise RateLimited(response=resp)
        return resp


github_bp = make_github_blueprint(
    scope="admin:repo_hook",
    redirect_to="ui.index",
    session_class=GithubSession,
)
github_bp.set_token_storage_sqlalchemy(OAuth, db.session, user=current_user)


@oauth_authorized.connect_via(github_bp)
def github_logged_in(blueprint, token):
    if not token:
        flash("Failed to log in with Github")
    if "error_reason" in token:
        msg = "Access denied. Reason={reason} error={error}".format(
            reason=request.args["error_reason"],
            error=request.args["error_description"],
        )
        flash(msg)
    else:
        # figure out who the user is
        resp = blueprint.session.get("/user")
        assert resp.ok

        from webhookdb.tasks.user import process_user
        user = process_user(resp.json(), via="api", fetched_at=datetime.now())
        login_user(user)
        flash("Successfully signed in with Github")
