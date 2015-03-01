# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request, jsonify, url_for
from flask_login import current_user
import bugsnag
from . import load
from webhookdb.tasks.pull_request_file import spawn_page_tasks_for_pull_request_files

@load.route('/repos/<owner>/<repo>/pulls/<int:number>/files', methods=["POST"])
def pull_request_files(owner, repo, number):
    """
    Queue tasks to load the pull request files (diffs) for a single pull request
    into WebhookDB.

    :statuscode 202: task successfully queued
    """
    bugsnag_ctx = {"owner": owner, "repo": repo, "number": number}
    bugsnag.configure_request(meta_data=bugsnag_ctx)

    result = spawn_page_tasks_for_pull_request_files.delay(
        owner, repo, number, requestor_id=current_user.get_id(),
    )
    resp = jsonify({"message": "queued"})
    resp.status_code = 202
    resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
    return resp
