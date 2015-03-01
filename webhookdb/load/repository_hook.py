# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request, jsonify, url_for
from flask_login import current_user
import bugsnag
from . import load
from webhookdb.tasks.repository_hook import (
    sync_repository_hook, spawn_page_tasks_for_repository_hooks
)
from webhookdb.exceptions import NotFound


@load.route('/repos/<owner>/<repo>/hooks/<int:hook_id>', methods=["POST"])
def repository_hook(owner, repo, hook_id):
    """
    Load a single repository hook from Github into WebhookDB.

    :query inline: process the request inline instead of creating a task
      on the task queue. Defaults to ``false``.
    :statuscode 200: hook successfully loaded inline
    :statuscode 202: task successfully queued
    :statuscode 404: specified hook was not found on Github
    """
    inline = bool(request.args.get("inline", False))
    bugsnag_ctx = {"owner": owner, "repo": repo, "hook_id": hook_id, "inline": inline}
    bugsnag.configure_request(meta_data=bugsnag_ctx)

    if inline:
        try:
            sync_repository_hook(
                owner, repo, hook_id, requestor_id=current_user.get_id(),
            )
        except NotFound as exc:
            return jsonify({"message": exc.message}), 404
        else:
            return jsonify({"message": "success"})
    else:
        result = sync_repository_hook.delay(
            owner, repo, number, requestor_id=current_user.get_id(),
        )
        resp = jsonify({"message": "queued"})
        resp.status_code = 202
        resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
        return resp

@load.route('/repos/<owner>/<repo>/hooks', methods=["POST"])
def repository_hooks(owner, repo):
    """
    Queue tasks to load all hooks on a single Github repository into WebhookDB.

    :statuscode 202: task successfully queued
    """
    bugsnag_ctx = {"owner": owner, "repo": repo}
    bugsnag.configure_request(meta_data=bugsnag_ctx)

    result = spawn_page_tasks_for_repository_hooks.delay(
        owner, repo, requestor_id=current_user.get_id(),
    )
    resp = jsonify({"message": "queued"})
    resp.status_code = 202
    resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
    return resp
