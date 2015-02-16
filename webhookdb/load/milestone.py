# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request, jsonify, url_for
import bugsnag
from . import load
from webhookdb.tasks.milestone import (
    sync_milestone, spawn_page_tasks_for_milestones
)
from webhookdb.exceptions import NotFound


@load.route('/repos/<owner>/<repo>/milestones/<int:number>', methods=["POST"])
def milestone(owner, repo, number):
    inline = bool(request.args.get("inline", False))
    bugsnag_ctx = {"owner": owner, "repo": repo, "number": number, "inline": inline}
    bugsnag.configure_request(meta_data=bugsnag_ctx)

    if inline:
        try:
            sync_milestone(owner, repo, number)
        except NotFound as exc:
            return jsonify({"message": exc.message}), 404
        else:
            return jsonify({"message": "success"})
    else:
        result = sync_milestone.delay(owner, repo, number)
        resp = jsonify({"message": "queued"})
        resp.status_code = 202
        resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
        return resp

@load.route('/repos/<owner>/<repo>/milestones', methods=["POST"])
def milestones(owner, repo):
    bugsnag_ctx = {"owner": owner, "repo": repo}
    bugsnag.configure_request(meta_data=bugsnag_ctx)
    state = request.args.get("state", "open")

    result = spawn_page_tasks_for_milestones.delay(owner, repo, state)
    resp = jsonify({"message": "queued"})
    resp.status_code = 202
    resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
    return resp
