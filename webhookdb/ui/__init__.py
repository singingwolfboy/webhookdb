# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import Blueprint, request, render_template, jsonify, url_for
from flask_login import current_user
from flask_dance.contrib.github import github
from sqlalchemy.sql import func
from webhookdb import db
from webhookdb.models import Repository, RepositoryHook, UserRepoAssociation
import bugsnag

ui = Blueprint('ui', __name__)


@ui.route("/")
def index():
    """
    Home page.

    If the user is not currently logged in with Github, explain what WebhookDB
    is, and ask them to log in.

    If the user *is* logged in with Github, show them their Github repos,
    and allow them to re-sync repos from Github.
    """
    if current_user.is_anonymous():
        return render_template("home-anonymous.html")
    else:
        secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "http") == "https"
        replication_url = url_for(
            "replication.pull_request",
            _external=True,
            _scheme="https" if secure else "http",
        )
        is_self_hook = (RepositoryHook.url == replication_url)
        repos = (
            db.session.query(Repository, func.sum(is_self_hook))
            .outerjoin(RepositoryHook, RepositoryHook.repo_id == Repository.id)
            .join(UserRepoAssociation, UserRepoAssociation.repo_id == Repository.id)
            .filter(UserRepoAssociation.user_id == current_user.id)
            .filter(UserRepoAssociation.can_admin == True)
            .group_by(Repository)
            .order_by(
                (Repository.owner_id == current_user.id).desc(),
                Repository.owner_login,
                Repository.name,
            )
        )
        return render_template("home.html", repos=repos)


@ui.route("/install", methods=("GET", "POST"))
def install():
    if request.method == "GET":
        return render_template("install.html")
    repo = request.form.get("repo", "")
    if not repo:
        resp = jsonify({"error": "missing repo param"})
        resp.status_code = 400
        return resp

    secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "http") == "https"
    hook_url = "/repos/{repo}/hooks".format(repo=repo)
    for event in ("pull_request", "issue"):
        api_url = url_for(
            "replication.{endpoint}".format(endpoint=event),
            _external=True,
            _scheme="https" if secure else "http",
        )
        body = {
            "name": "web",
            "events": [event],
            "config": {
                "url": api_url,
                "content_type": "json",
            }
        }
        bugsnag_context = {"repo": repo, "body": body}
        bugsnag.configure_request(meta_data=bugsnag_context)

        hook_resp = github.post(hook_url, json=body)
        if not hook_resp.ok:
            error_obj = hook_resp.json()
            resp = jsonify({"error": error_obj["message"]})
            resp.status_code = 503
            return resp

    return jsonify({"message": "success"})
