# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request, jsonify, url_for
from flask_login import current_user
import bugsnag
from . import load
from webhookdb.tasks.milestone import (
    sync_milestone, spawn_page_tasks_for_milestones
)
from webhookdb.exceptions import NotFound


@load.route('/repos/<owner>/<repo>/milestones/<int:number>', methods=["POST"])
def milestone(owner, repo, number):
    """
    Load a single milestone from Github into WebhookDB.

    :query inline: process the request inline instead of creating a task
      on the task queue. Defaults to ``false``.
    :statuscode 200: milestone successfully loaded inline
    :statuscode 202: task successfully queued
    :statuscode 404: specified milestone was not found on Github
    """
    inline = bool(request.args.get("inline", False))
    children = bool(request.args.get("children", False))
    bugsnag_ctx = {"owner": owner, "repo": repo, "number": number, "inline": inline}
    bugsnag.configure_request(meta_data=bugsnag_ctx)

    if inline and not children:
        try:
            sync_milestone(
                owner, repo, number, children=children,
                requestor_id=current_user.get_id(),
            )
        except NotFound as exc:
            return jsonify({"message": exc.message}), 404
        else:
            return jsonify({"message": "success"})
    else:
        result = sync_milestone.delay(
            owner, repo, number, children=children,
            requestor_id=current_user.get_id(),
        )
        resp = jsonify({"message": "queued"})
        resp.status_code = 202
        resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
        return resp

@load.route('/repos/<owner>/<repo>/milestones', methods=["POST"])
def milestones(owner, repo):
    """
    Queue tasks to load all milestones on a single Github repository
    into WebhookDB.

    :statuscode 202: task successfully queued
    """
    bugsnag_ctx = {"owner": owner, "repo": repo}
    bugsnag.configure_request(meta_data=bugsnag_ctx)
    state = request.args.get("state", "open")
    children = bool(request.args.get("children", False))

    result = spawn_page_tasks_for_milestones.delay(
        owner, repo, state, children=children,
        requestor_id=current_user.get_id(),
    )
    resp = jsonify({"message": "queued"})
    resp.status_code = 202
    resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
    return resp
