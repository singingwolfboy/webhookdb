# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from flask import request, jsonify
import bugsnag
from . import replication
from githubdb.models import User, Repository, PullRequest
from githubdb.exceptions import MissingInfo, StaleInfo


@replication.route('/pull_request')
def pull_request():
    payload = request.get_json()
    bugsnag.configure_request(meta_data={"payload": payload})
    if not payload:
        resp = jsonify({"error": "no payload"})
        resp.status_code = 400
        return resp

    if request.headers.get("X-Github-Event", "").lower() == "ping":
        return jsonify({"message": "pong"})

    pr_obj = payload.get("pull_request")
    if not pr_obj:
        resp = jsonify({"error": "no pull_request in payload"})
        resp.status_code = 400
        return resp

    try:
        pr = update_pr(pr_obj)
    except MissingInfo as err:
        esp = jsonify({"error": err.message})
        resp.status_code = 400
        return resp
    except StaleInfo:
        return jsonify({"message": "stale information"})

    return jsonify({"message": "success"})


def update_pr(pr_obj):
    pr_id = pr_obj.get("id")
    if not pr_id:
        raise MissingInfo("no pull_request ID")

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    pr = PullRequest.get(pr_id)
    if not pr:
        pr = PullRequest(id=pr_id)

    now = datetime.now()

    # should we update the object?
    last_updated = pr.last_updated_via_event_at
    if last_updated and last_updated > now:
        raise StaleInfo()

    # update the object
    fields = (
        "number", "statue", "locked", "title", "body", "merge_commit_sha",
        "milestone", "merged", "mergeable", "mergeable_state",
        "comments", "review_comments", "commits", "additions", "deletions",
        "changed_files",
    )
    for field in fields:
        setattr(pr, field, pr_obj[field])
    dt_fields = ("created_at", "updated_at", "closed_at", "merged_at")
    for field in dt_fields:
        dt = parse_date(pr_obj[field]).replace(tzinfo=None)
        setattr(pr, field, dt)
    # user references
    user_fields = ("user", "assignee", "merged_by")
    for user_field in user_fields:
        user_obj = pr_obj[user_field]
        id_field = "{}_id".format(user_field)
        login_field = "{}_login".format(user_field)
        if user_obj:
            setattr(pr, id_field, user_obj["id"])
            if hasattr(pr, login_field):
                setattr(pr, login_field, user_obj["login"])
            # TODO: update user object in DB
            # update_user(user_obj)
        else:
            setattr(pr, id_field, None)
            if hasattr(pr, login_field):
                setattr(pr, login_field, None)

    # TODO: repository references

    return pr
