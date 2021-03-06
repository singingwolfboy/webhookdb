# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request, jsonify, url_for
from flask_login import current_user
import bugsnag
from . import load
from webhookdb.tasks.label import (
    sync_label, spawn_page_tasks_for_labels
)
from webhookdb.exceptions import NotFound


@load.route('/repos/<owner>/<repo>/labels/<name>', methods=["POST"])
def label(owner, repo, name):
    """
    Load a single label from Github into WebhookDB.

    :query children: scan all children objects. Defaults to ``false``
    :query inline: process the request inline instead of creating a task
      on the task queue. Defaults to ``false``.
    :statuscode 200: label successfully loaded inline
    :statuscode 202: task successfully queued
    :statuscode 404: specified label was not found on Github
    """
    inline = bool(request.args.get("inline", False))
    children = bool(request.args.get("children", False))
    bugsnag_ctx = {"owner": owner, "repo": repo, "name": name, "inline": inline}
    bugsnag.configure_request(meta_data=bugsnag_ctx)

    if inline and not children:
        try:
            sync_label(
                owner, repo, name, children=False,
                requestor_id=current_user.get_id(),
            )
        except NotFound as exc:
            return jsonify({"message": exc.message}), 404
        else:
            return jsonify({"message": "success"})
    else:
        result = sync_label.delay(owner, repo, name, children=children)
        resp = jsonify({"message": "queued"})
        resp.status_code = 202
        resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
        return resp

@load.route('/repos/<owner>/<repo>/labels', methods=["POST"])
def labels(owner, repo):
    """
    Queue tasks to load all labels on a single Github repository
    into WebhookDB.

    :statuscode 202: task successfully queued
    """
    bugsnag_ctx = {"owner": owner, "repo": repo}
    bugsnag.configure_request(meta_data=bugsnag_ctx)
    children = bool(request.args.get("children", False))

    result = spawn_page_tasks_for_labels.delay(
        owner, repo, requestor_id=current_user.get_id(),
    )
    resp = jsonify({"message": "queued"})
    resp.status_code = 202
    resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
    return resp
