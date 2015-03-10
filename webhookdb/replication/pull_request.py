# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request, jsonify
import bugsnag
from . import replication
from webhookdb.models import PullRequestFile
from webhookdb.exceptions import MissingData, StaleData
from webhookdb.tasks.pull_request import process_pull_request
from webhookdb.tasks.pull_request_file import (
    sync_page_of_pull_request_files, spawn_page_tasks_for_pull_request_files
)


@replication.route('/pull_request', methods=["POST"])
def pull_request():
    """
    Webhook endpoint for ``pull_request`` events on Github.
    """
    payload = request.get_json()
    bugsnag.configure_request(meta_data={"payload": payload})

    pr_data = payload.get("pull_request")
    if not pr_data:
        resp = jsonify({"error": "no pull_request in payload"})
        resp.status_code = 400
        return resp

    try:
        pr = process_pull_request(pr_data)
    except MissingData as err:
        return jsonify({"error": err.message, "obj": err.obj}), 400
    except StaleData:
        return jsonify({"message": "stale data"})

    # Fetch the pull request files, too!
    if pr.changed_files < 100:
        # If there are fewer than 100, do it inline
        PullRequestFile.query.filter_by(pull_request_id=pr.id).delete()
        sync_page_of_pull_request_files(
            owner=pr.base_repo.owner_login, repo=pr.base_repo.name,
            number=pr.number, pull_request_id=pr.id,
        )
    else:
        # otherwise, spawn tasks
        spawn_page_tasks_for_pull_request_files.delay(
            pr.base_repo.owner_login, pr.base_repo.name, pr.number
        )

    return jsonify({"message": "success"})
