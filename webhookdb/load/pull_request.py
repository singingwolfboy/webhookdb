# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request, jsonify, url_for
from flask_login import current_user
import bugsnag
from . import load
from webhookdb.tasks.pull_request import (
    sync_pull_request, spawn_page_tasks_for_pull_requests
)
from webhookdb.exceptions import NotFound


@load.route('/repos/<owner>/<repo>/pulls/<int:number>', methods=["POST"])
def pull_request(owner, repo, number):
    """
    Load a single pull request from Github into WebhookDB.

    :query inline: process the request inline instead of creating a task
      on the task queue. Defaults to ``false``.
    :statuscode 200: pull request successfully loaded inline
    :statuscode 202: task successfully queued
    :statuscode 404: specified pull request was not found on Github
    """
    inline = bool(request.args.get("inline", False))
    children = bool(request.args.get("children", False))
    bugsnag_ctx = {"owner": owner, "repo": repo, "number": number, "inline": inline}
    bugsnag.configure_request(meta_data=bugsnag_ctx)

    if inline and not children:
        try:
            sync_pull_request(
                owner, repo, number, children=False,
                requestor_id=current_user.get_id(),
            )
        except NotFound as exc:
            return jsonify({"message": exc.message}), 404
        else:
            return jsonify({"message": "success"})
    else:
        result = sync_pull_request.delay(
            owner, repo, number, children=children,
            requestor_id=current_user.get_id(),
        )
        resp = jsonify({"message": "queued"})
        resp.status_code = 202
        resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
        return resp

@load.route('/repos/<owner>/<repo>/pulls', methods=["POST"])
def pull_requests(owner, repo):
    """
    Queue tasks to load all pull requests on a single Github repository
    into WebhookDB.

    :query state: one of ``all``, ``open``, or ``closed``. This parameter
      is proxied to the `Github API for listing pull requests`_.
    :statuscode 202: task successfully queued

    .. _Github API for listing pull requests: https://developer.github.com/v3/pulls/#list-pull-requests
    """
    bugsnag_ctx = {"owner": owner, "repo": repo}
    bugsnag.configure_request(meta_data=bugsnag_ctx)
    state = request.args.get("state", "open")
    children = bool(request.args.get("children", False))

    result = spawn_page_tasks_for_pull_requests.delay(
        owner, repo, state, children=children,
        requestor_id=current_user.get_id(),
    )
    resp = jsonify({"message": "queued"})
    resp.status_code = 202
    resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
    return resp
