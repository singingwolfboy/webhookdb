# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from webhookdb import db
from webhookdb.models import PullRequest, Repository
from webhookdb.process import process_user, process_repository
from webhookdb.exceptions import MissingData, StaleData


def process_pull_request(pr_data, via="webhook", fetched_at=None, commit=True):
    pr_id = pr_data.get("id")
    if not pr_id:
        raise MissingData("no pull_request ID", obj=pr_data)

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    pr = PullRequest.query.get(pr_id)
    if not pr:
        pr = PullRequest(id=pr_id)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if pr.last_replicated_at > fetched_at:
        raise StaleData()

    # Most fields have the same name in our model as they do in Github's API.
    # However, some are different. This mapping contains just the differences.
    field_to_model = {
        "comments": "comments_count",
        "review_comments": "review_comments_count",
        "commits": "commits_count",
    }

    # update the object
    fields = (
        "number", "state", "locked", "title", "body", "merged", "mergeable",
        "comments", "review_comments", "commits", "additions", "deletions",
        "changed_files",
    )
    for field in fields:
        if field in pr_data:
            mfield = field_to_model.get(field, field)
            setattr(pr, mfield, pr_data[field])
    dt_fields = ("created_at", "updated_at", "closed_at", "merged_at")
    for field in dt_fields:
        if pr_data.get(field):
            dt = parse_date(pr_data[field]).replace(tzinfo=None)
            mfield = field_to_model.get(field, field)
            setattr(pr, mfield, dt)

    # user references
    user_fields = ("user", "assignee", "merged_by")
    for user_field in user_fields:
        if user_field not in pr_data:
            continue
        user_data = pr_data[user_field]
        id_field = "{}_id".format(user_field)
        login_field = "{}_login".format(user_field)
        if user_data:
            setattr(pr, id_field, user_data["id"])
            if hasattr(pr, login_field):
                setattr(pr, login_field, user_data["login"])
            try:
                process_user(user_data, via=via, fetched_at=fetched_at)
            except StaleData:
                pass
        else:
            setattr(pr, id_field, None)
            if hasattr(pr, login_field):
                setattr(pr, login_field, None)

    # repository references
    refs = ("base", "head")
    for ref in refs:
        if not ref in pr_data:
            continue
        ref_data = pr_data[ref]
        ref_field = "{}_ref".format(ref)
        setattr(pr, ref_field, ref_data["ref"])
        repo_data = ref_data["repo"]
        repo_id_field = "{}_repo_id".format(ref)
        if repo_data:
            setattr(pr, repo_id_field, repo_data["id"])
            try:
                process_repository(repo_data, via=via, fetched_at=fetched_at)
            except StaleData:
                pass
        else:
            setattr(pr, repo_id_field, None)

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(pr, replicated_dt_field):
        setattr(pr, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(pr)
    if commit:
        db.session.commit()

    return pr
