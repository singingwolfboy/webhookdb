# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request, jsonify
import bugsnag
from . import replication
from webhookdb.exceptions import MissingData, StaleData
from webhookdb.tasks.issue import process_issue


@replication.route('/issue', methods=["POST"])
def issue():
    """
    Webhook endpoint for ``issues`` events on Github.
    """
    payload = request.get_json()
    bugsnag.configure_request(meta_data={"payload": payload})

    issue_data = payload.get("issue")
    if not issue_data:
        resp = jsonify({"error": "no issue in payload"})
        resp.status_code = 400
        return resp

    try:
        issue = process_issue(issue_data)
    except MissingData as err:
        return jsonify({"error": err.message, "obj": err.obj}), 400
    except StaleData:
        return jsonify({"message": "stale data"})

    return jsonify({"message": "success"})
