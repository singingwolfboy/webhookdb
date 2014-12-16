# coding=utf-8
from __future__ import unicode_literals, print_function

import os
from datetime import datetime

from flask import request, flash
from flask_dance.contrib.github import make_github_blueprint
from flask_dance.consumer.oauth2 import OAuth2SessionWithBaseURL
from flask_dance.consumer import oauth_authorized
from githubdb import db
from githubdb.models import OAuth


# Check for required environment variables

req_env_vars = {"GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"}
missing = req_env_vars - set(os.environ.keys())
if missing:
    raise Exception(
        "You must define the following variables in your environment: {vars} "
        "See the README for more information.".format(vars=", ".join(missing))
    )


class OAuth2SessionWithMemory(OAuth2SessionWithBaseURL):
    "A session that remembers the last request it made."
    last_response = None

    def request(self, method, url, data=None, headers=None, **kwargs):
        resp = super(OAuth2SessionWithBaseURL, self).request(
            method=method, url=url, data=data, headers=headers, **kwargs
        )
        self.last_response = resp
        return resp


github_bp = make_github_blueprint(
    client_id=os.environ["GITHUB_CLIENT_ID"],
    client_secret=os.environ["GITHUB_CLIENT_SECRET"],
    scope="write:repo_hook",
    redirect_to="ui.index",
    session_class=OAuth2SessionWithMemory,
)
github_bp.set_token_storage_sqlalchemy(OAuth, db.session)


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
        flash("Successfully signed in with Github")
