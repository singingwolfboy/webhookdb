# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from webhookdb import db
from webhookdb.models import Issue
from webhookdb.process import process_user, process_label, process_milestone
from webhookdb.exceptions import MissingData, StaleData


def process_issue(issue_data, via="webhook", fetched_at=None, commit=True):
    issue_id = issue_data.get("id")
    if not issue_id:
        raise MissingData("no issue ID", obj=issue_data)

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    issue = Issue.query.get(issue_id)
    if not issue:
        issue = Issue(id=issue_id)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if issue.last_replicated_at > fetched_at:
        raise StaleData()

    # Most fields have the same name in our model as they do in Github's API.
    # However, some are different. This mapping contains just the differences.
    field_to_model = {
        "comments": "comments_count",
    }

    # update the object
    fields = (
        "number", "state", "title", "body", "comments",
    )
    for field in fields:
        if field in issue_data:
            mfield = field_to_model.get(field, field)
            setattr(issue, mfield, issue_data[field])
    dt_fields = ("created_at", "updated_at", "closed_at")
    for field in dt_fields:
        if issue_data.get(field):
            dt = parse_date(issue_data[field]).replace(tzinfo=None)
            mfield = field_to_model.get(field, field)
            setattr(issue, mfield, dt)

    # user references
    user_fields = ("user", "assignee", "closed_by")
    for user_field in user_fields:
        if user_field not in issue_data:
            continue
        user_data = issue_data[user_field]
        id_field = "{}_id".format(user_field)
        login_field = "{}_login".format(user_field)
        if user_data:
            setattr(issue, id_field, user_data["id"])
            if hasattr(issue, login_field):
                setattr(issue, login_field, user_data["login"])
            try:
                process_user(user_data, via=via, fetched_at=fetched_at)
            except StaleData:
                pass
        else:
            setattr(issue, id_field, None)
            if hasattr(issue, login_field):
                setattr(issue, login_field, None)

    # used for labels and milestone
    repo_id = None

    # label reference
    if "labels" in issue_data:
        label_data_list = issue_data["labels"]
        if label_data_list:
            labels = []
            for label_data in label_data_list:
                label = process_label(
                    label_data, via=via, fetched_at=fetched_at, commit=False,
                    repo_id=repo_id,
                )
                repo_id = repo_id or label.repo_id
                labels.append(label)
            issue.labels = labels
        else:
            issue.labels = []

    # milestone reference
    if "milestone" in issue_data:
        milestone_data = issue_data["milestone"]
        if milestone_data:
            milestone = process_milestone(
                milestone_data, via=via, fetched_at=fetched_at, commit=False,
                repo_id=repo_id,
            )
            repo_id = repo_id or milestone.repo_id
            issue.milestone_number = milestone.number
        else:
            issue.milestone = None

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(issue, replicated_dt_field):
        setattr(issue, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(issue)
    if commit:
        db.session.commit()

    return issue
