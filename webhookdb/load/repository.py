# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request, jsonify, url_for
from flask_login import current_user
import bugsnag
from . import load
from webhookdb.tasks.repository import sync_repository
from webhookdb.exceptions import NotFound


@load.route('/repos/<owner>/<repo>', methods=["POST"])
def repository(owner, repo):
    """
    Load a single repository from Github into WebhookDB. Note that this does
    not load issues, pull requests, etc for that repository into WebhookDB.

    :query inline: process the request inline instead of creating a task
      on the task queue. Defaults to ``false``.
    :statuscode 200: repository successfully loaded inline
    :statuscode 202: task successfully queued
    :statuscode 404: specified repository was not found on Github
    """
    inline = bool(request.args.get("inline", False))
    children = bool(request.args.get("children", False))
    bugsnag_ctx = {
        "owner": owner, "repo": repo,
        "inline": inline, "children": children,
    }
    bugsnag.configure_request(meta_data=bugsnag_ctx)

    if inline and not children:
        try:
            sync_repository(
                owner, repo, children=children,
                requestor_id=current_user.get_id(),
            )
        except NotFound as exc:
            return jsonify({"message": exc.message}), 404
        else:
            return jsonify({"message": "success"})
    else:
        result = sync_repository.delay(
            owner, repo, children=children,
            requestor_id=current_user.get_id(),
        )
        resp = jsonify({"message": "queued"})
        resp.status_code = 202
        resp.headers["Location"] = url_for("tasks.status", task_id=result.id)
        return resp
