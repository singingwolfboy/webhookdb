# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from flask import request, jsonify, url_for
import bugsnag
import requests
from . import replication
from .user import create_or_update_user
from .repository import create_or_update_repository
from githubdb import db
from githubdb.models import PullRequest, PullRequestFile
from githubdb.exceptions import MissingData, StaleData


@replication.route('/pull_request', methods=["POST"])
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
        pr = create_or_update_pull_request(pr_obj)
    except MissingData as err:
        esp = jsonify({"error": err.message, "obj": err.obj})
        resp.status_code = 400
        return resp
    except StaleData:
        return jsonify({"message": "stale data"})

    db.session.commit()

    # Poor man's job queue: send an HTTP request to load the PR files,
    # and don't wait for it to complete.
    pr_file_url = url_for("load.pull_request_files",
        owner=pr.base_repo.owner_login, repo=pr.base_repo.name,
        number=pr.number,
        _external=True,
    )
    # First number is connect timeout: time to wait for connection to remote server.
    # Second number is read timeout: time to wait for the server to send a response.
    # Wait long enough to connect, and then we're done!
    try:
        requests.post(pr_file_url, timeout=(3.05, 0.1))
    except requests.exceptions.ReadTimeout:
        pass

    return jsonify({"message": "success"})


def create_or_update_pull_request(pr_obj, via="webhook"):
    pr_id = pr_obj.get("id")
    if not pr_id:
        raise MissingData("no pull_request ID", obj=pr_obj)

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    pr = PullRequest.query.get(pr_id)
    if not pr:
        pr = PullRequest(id=pr_id)

    now = datetime.now()

    # should we update the object?
    if pr.last_replicated_at > datetime.now():
        raise StaleData()

    # update the object
    fields = (
        "number", "state", "locked", "title", "body", "merge_commit_sha",
        "milestone", "merged", "mergeable", "mergeable_state",
        "comments", "review_comments", "commits", "additions", "deletions",
        "changed_files",
    )
    for field in fields:
        if field in pr_obj:
            setattr(pr, field, pr_obj[field])
    dt_fields = ("created_at", "updated_at", "closed_at", "merged_at")
    for field in dt_fields:
        if pr_obj.get(field):
            dt = parse_date(pr_obj[field]).replace(tzinfo=None)
            setattr(pr, field, dt)

    # user references
    user_fields = ("user", "assignee", "merged_by")
    for user_field in user_fields:
        if user_field not in pr_obj:
            continue
        user_obj = pr_obj[user_field]
        id_field = "{}_id".format(user_field)
        login_field = "{}_login".format(user_field)
        if user_obj:
            setattr(pr, id_field, user_obj["id"])
            if hasattr(pr, login_field):
                setattr(pr, login_field, user_obj["login"])
            try:
                create_or_update_user(user_obj, via=via)
            except StaleData:
                pass
        else:
            setattr(pr, id_field, None)
            if hasattr(pr, login_field):
                setattr(pr, login_field, None)

    # repository references
    refs = ("base", "head")
    for ref in refs:
        if not ref in pr_obj:
            continue
        ref_obj = pr_obj[ref]
        ref_field = "{}_ref".format(ref)
        setattr(pr, ref_field, ref_obj["ref"])
        repo_obj = ref_obj["repo"]
        repo_id_field = "{}_repo_id".format(ref)
        if repo_obj:
            setattr(pr, repo_id_field, repo_obj["id"])
            try:
                create_or_update_repository(repo_obj, via=via)
            except StaleData:
                pass
        else:
            setattr(pr, repo_id_field, None)

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(pr, replicated_dt_field):
        setattr(pr, replicated_dt_field, datetime.now())

    # add to DB session, so that it will be committed
    db.session.add(pr)

    return pr


def create_or_update_pull_request_file(prf_obj, via="webhook"):
    sha = prf_obj.get("sha")
    if not sha:
        raise MissingData("no pull request file SHA", obj=prf_obj)
    pr_id = prf_obj.get("pull_request_id")
    if not pr_id:
        raise MissingData("no pull_request_id", obj=prf_obj)

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    prf = PullRequestFile.query.get(sha)
    if not prf:
        prf = PullRequestFile(sha=sha)

    now = datetime.now()

    # should we update the object?
    if prf.last_replicated_at > datetime.now():
        raise StaleData()

    # update the object
    fields = (
        "filename", "status", "additions", "deletions", "changes", "patch",
        "pull_request_id",
    )
    for field in fields:
        if field in prf_obj:
            setattr(prf, field, prf_obj[field])

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(prf, replicated_dt_field):
        setattr(prf, replicated_dt_field, datetime.now())

    # add to DB session, so that it will be committed
    db.session.add(prf)

    return prf
