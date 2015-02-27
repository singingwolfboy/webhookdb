# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request, jsonify, url_for
from flask_login import login_required, current_user
import bugsnag
from . import load
from webhookdb.tasks.user import sync_user
from webhookdb.tasks.repository import spawn_page_tasks_for_user_repositories
from webhookdb.exceptions import NotFound
from sqlalchemy.orm.exc import NoResultFound


@load.route('/user/<username>/repos', methods=["POST"])
def user_repositories(username):
    """
    Queue tasks to load all of the given user's repositories into WebhookDB.

    :query type: one of ``all``, ``owner``, ``member``. Default: ``owner``.
      This parameter is proxied to the `Github API for listing user repositories`_.
    :statuscode 202: task successfully queued

    .. _Github API for listing user repositories: https://developer.github.com/v3/repos/#list-user-repositories
    """
    bugsnag_ctx = {"username": username}
    bugsnag.configure_request(meta_data=bugsnag_ctx)
    type = request.args.get("type", "owner")

    try:
        User.query.filter_by(login=username).one()
    except NoResultFound:
        # queue a task to load the user
        sync_user.delay(username)

    result = spawn_page_tasks_for_user_repositories.delay(username, type=type)
    resp = jsonify({"message": "queued"})
    resp.status_code = 202
    resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
    return resp


@load.route('/user/repos', methods=["POST"])
@login_required
def own_repositories():
    """
    Queue tasks to load all of the logged-in user's repositories into WebhookDB.

    :query type: one of ``all``, ``owner``, ``public``, ``private``, ``member``.
      Default: ``all``. This parameter is proxied to the
      `Github API for listing your repositories`_.
    :statuscode 202: task successfully queued

    .. _Github API for listing your repositories: https://developer.github.com/v3/repos/#list-your-repositories
    """
    type = request.args.get("type", "all")

    result = spawn_page_tasks_for_user_repositories.delay(current_user.login, type=type)
    resp = jsonify({"message": "queued"})
    resp.status_code = 202
    resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
    return resp
