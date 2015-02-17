# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request, jsonify, url_for
import bugsnag
from . import load
from webhookdb.tasks.label import (
    sync_label, spawn_page_tasks_for_labels
)
from webhookdb.exceptions import NotFound


@load.route('/repos/<owner>/<repo>/labels/<name>', methods=["POST"])
def label(owner, repo, name):
    inline = bool(request.args.get("inline", False))
    bugsnag_ctx = {"owner": owner, "repo": repo, "name": name, "inline": inline}
    bugsnag.configure_request(meta_data=bugsnag_ctx)

    if inline:
        try:
            sync_label(owner, repo, name)
        except NotFound as exc:
            return jsonify({"message": exc.message}), 404
        else:
            return jsonify({"message": "success"})
    else:
        result = sync_label.delay(owner, repo, name)
        resp = jsonify({"message": "queued"})
        resp.status_code = 202
        resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
        return resp

@load.route('/repos/<owner>/<repo>/labels', methods=["POST"])
def labels(owner, repo):
    bugsnag_ctx = {"owner": owner, "repo": repo}
    bugsnag.configure_request(meta_data=bugsnag_ctx)

    result = spawn_page_tasks_for_labels.delay(owner, repo)
    resp = jsonify({"message": "queued"})
    resp.status_code = 202
    resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
    return resp
