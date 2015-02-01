# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from flask import request
import bugsnag
from . import replication
from .user import create_or_update_user
from webhookdb import db
from webhookdb.models import Repository
from webhookdb.tasks.repository import process_repository
from webhookdb.exceptions import StaleData, MissingData


@replication.route('/repository', methods=["POST"])
def repository():
    payload = request.get_json()
    bugsnag.configure_request(meta_data={"payload": payload})

    repo_data = payload.get("repository")
    if not repo_data:
        resp = jsonify({"error": "no repository in payload"})
        resp.status_code = 400
        return resp

    try:
        process_repository(repo_data)
    except MissingData as err:
        return jsonify({"error": err.message, "obj": err.obj}), 400
    except StaleData:
        return jsonify({"message": "stale data"})
    else:
        return jsonify({"message": "success"})
