# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request
import bugsnag
from . import replication
from .user import create_or_update_user


@replication.route('/repository')
def repository():
    payload = request.get_json()
    bugsnag.configure_request(meta_data={"payload": payload})
    if not payload:
        resp = jsonify({"error": "no payload"})
        resp.status_code = 400
        return resp

    if request.headers.get("X-Github-Event", "").lower() == "ping":
        return jsonify({"message": "pong"})

    repo_obj = payload.get("repository")
    if not repo_obj:
        resp = jsonify({"error": "no repository in payload"})
        resp.status_code = 400
        return resp

    try:
        create_or_update_repository(repo_obj)
    except MissingInfo as err:
        esp = jsonify({"error": err.message, "obj": err.obj})
        resp.status_code = 400
        return resp
    except StaleInfo:
        return jsonify({"message": "stale information"})

    return jsonify({"message": "success"})


def create_or_update_repository(repo_obj, via="webhook"):
    repo_id = repo_obj.get("id")
    if not repo_id:
        raise MissingInfo("no repo ID")

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    repo = Repository.get(pr_id)
    if not repo:
        repo = Repository(id=repo_id)

    # should we update the object?
    if user.last_replicated_at > datetime.now():
        raise StaleInfo()

    # update the object
    fields = (
        "name", "private", "description", "fork", "homepage", "size",
        "stargazers_count", "watchers_count", "language", "has_issues",
        "has_downloads", "has_wiki", "has_pages", "forks_count",
        "open_issues_count", "default_branch",
    )
    for field in fields:
        setattr(repo, field, repo_obj[field])
    dt_fields = ("created_at", "updated_at", "pushed_at")
    for field in dt_fields:
        dt = parse_date(repo_obj[field]).replace(tzinfo=None)
        setattr(user, field, dt)

    # user references
    user_fields = ("owner", "organization")
    for user_field in user_fields:
        user_obj = repo_obj[user_field]
        id_field = "{}_id".format(user_field)
        login_field = "{}_login".format(user_field)
        if user_obj:
            setattr(pr, id_field, user_obj["id"])
            if hasattr(pr, login_field):
                setattr(pr, login_field, user_obj["login"])
            try:
                create_or_update_user(user_obj, via=via)
            except StaleInfo:
                pass
        else:
            setattr(repo, id_field, None)
            if hasattr(repo, login_field):
                setattr(repo, login_field, None)


    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(repo, replicated_dt_field):
        setattr(repo, replicated_dt_field, datetime.now())

    # add to DB session, so that it will be committed
    db.session.add(repo)

    return repo
