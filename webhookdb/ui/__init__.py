# coding=utf-8
from __future__ import unicode_literals, print_function

import logging
from datetime import datetime
from flask import Blueprint, request, render_template, jsonify, url_for
from flask_login import current_user
from flask_dance.contrib.github import github
from sqlalchemy.sql import func, cast
from webhookdb import db
from webhookdb.models import Repository, RepositoryHook, UserRepoAssociation
from webhookdb.tasks.repository_hook import process_repository_hook
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
        replication_url = url_for(
            "replication.pull_request",
            _external=True,
        )
        is_self_hook = (RepositoryHook.url == replication_url)
        repos = (
            db.session.query(Repository, func.sum(cast(is_self_hook, db.Integer)))
            .outerjoin(RepositoryHook, RepositoryHook.repo_id == Repository.id)
            .join(UserRepoAssociation, UserRepoAssociation.repo_id == Repository.id)
            .filter(UserRepoAssociation.user_id == current_user.id)
            .filter(UserRepoAssociation.can_admin == True)
            .group_by(Repository)
            .order_by(
                (Repository.owner_id == current_user.id).desc(),
                func.lower(Repository.owner_login),
                func.lower(Repository.name),
            )
        )
        return render_template("home.html", repos=repos)


@ui.route("/install", methods=("GET", "POST"))
def install():
    if request.method == "GET":
        return render_template("install.html")
    owner_login = request.values.get("owner", "")
    if not owner_login:
        return jsonify({"error": "missing owner param"}), 400
    repo_name = request.values.get("repo", "")
    if not repo_name:
        return jsonify({"error": "missing repo param"}), 400

    hook_url = "/repos/{owner}/{repo}/hooks".format(
        owner=owner_login, repo=repo_name,
    )
    body = {
        "name": "web",
        "events": ["pull_request", "issue"],
        "config": {
            "url": url_for("replication.main", _external=True),
            "content_type": "json",
        }
    }
    bugsnag_context = {"owner": owner_login, "repo": repo_name, "body": body}
    bugsnag.configure_request(meta_data=bugsnag_context)

    logging.info("POST {}".format(hook_url))
    hook_resp = github.post(hook_url, json=body)
    if not hook_resp.ok:
        error_obj = hook_resp.json()
        resp = jsonify({"error": error_obj["message"]})
        resp.status_code = 503
        return resp
    else:
        hook_data = hook_resp.json()
        process_repository_hook(
            hook_data, via="api", fetched_at=datetime.now(), commit=True,
            requestor_id=current_user.get_id(),
        )

    return jsonify({"message": "success"})


@ui.route("/uninstall", methods=("GET", "POST"))
def uninstall():
    if request.method == "GET":
        return render_template("uninstall.html")
    owner_login = request.values.get("owner", "")
    if not owner_login:
        return jsonify({"error": "missing owner param"}), 400
    repo_name = request.values.get("repo", "")
    if not repo_name:
        return jsonify({"error": "missing repo param"}), 400

    replication_urls = [
        url_for(
            "replication.{endpoint}".format(endpoint=endpoint),
            _external=True,
        )
        for endpoint in ("main", "pull_request", "issue")
    ]

    repo_hooks = (
        RepositoryHook.query
        .join(Repository, Repository.id == RepositoryHook.repo_id)
        .filter(Repository.owner_login == owner_login)
        .filter(Repository.name == repo_name)
        .filter(RepositoryHook.url.in_(replication_urls))
    )

    deleted_ids = []
    errored_ids = []
    for repo_hook in repo_hooks:
        api_url = "/repos/{owner}/{repo}/hooks/{hook_id}".format(
            owner=owner_login, repo=repo_name, hook_id=repo_hook.id,
        )
        logging.info("DELETE {}".format(api_url))
        hook_resp = github.delete(api_url)
        if hook_resp.ok:
            deleted_ids.append(repo_hook.id)
        else:
            errored_ids.append(repo_hook.id)

    # delete from local database
    if deleted_ids:
        query = RepositoryHook.query.filter(RepositoryHook.id.in_(deleted_ids))
        query.delete(synchronize_session=False)
        db.session.commit()
        return jsonify({"message": "deleted", "ids": deleted_ids})
    else:
        return jsonify({"message": "no hooks deleted", "ids": []})
