# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from urlobject import URLObject
from webhookdb import db
from webhookdb.models import Milestone, Repository
from webhookdb.process import process_user
from webhookdb.exceptions import MissingData, StaleData


def process_milestone(milestone_data, via="webhook", fetched_at=None, commit=True,
                      repo_id=None):
    number = milestone_data.get("number")
    if not number:
        raise MissingData("no milestone number")

    if not repo_id:
        url = milestone_data.get("url")
        if not url:
            raise MissingData("no milestone url")

        # parse repo info from url
        path = URLObject(url).path
        assert path.segments[0] == "repos"
        repo_owner = path.segments[1]
        repo_name = path.segments[2]

        # fetch repo from database
        try:
            repo = Repository.get(repo_owner, repo_name)
        except MultipleResultsFound:
            msg = "Repo {owner}/{repo} found multiple times!".format(
                owner=repo_owner, repo=repo_name,
            )
            raise DatabaseError(msg, {
                "type": "milestone",
                "owner": repo_owner,
                "repo": repo_name,
            })
        if not repo:
            msg = "Repo {owner}/{repo} not loaded in webhookdb".format(
                owner=repo_owner, repo=repo_name,
            )
            raise NotFound(msg, {
                "type": "milestone",
                "owner": repo_owner,
                "repo": repo_name,
            })
        repo_id = repo.id

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    milestone = Milestone.query.get((repo_id, number))
    if not milestone:
        milestone = Milestone(repo_id=repo_id, number=number)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if milestone.last_replicated_at > fetched_at:
        raise StaleData()

    # Most fields have the same name in our model as they do in Github's API.
    # However, some are different. This mapping contains just the differences.
    field_to_model = {
        "open_issues": "open_issues_count",
        "closed_issues": "closed_issues_count",
        "due_on": "due_at",
    }

    # update the object
    fields = (
        "state", "title", "description", "open_issues", "closed_issues",
    )
    for field in fields:
        if field in milestone_data:
            mfield = field_to_model.get(field, field)
            setattr(milestone, mfield, milestone_data[field])
    dt_fields = ("created_at", "updated_at", "closed_at", "due_on")
    for field in dt_fields:
        if milestone_data.get(field):
            dt = parse_date(milestone_data[field]).replace(tzinfo=None)
            mfield = field_to_model.get(field, field)
            setattr(milestone, mfield, dt)

    # user references
    user_fields = ("creator",)
    for user_field in user_fields:
        if user_field not in milestone_data:
            continue
        user_data = milestone_data[user_field]
        id_field = "{}_id".format(user_field)
        login_field = "{}_login".format(user_field)
        if user_data:
            setattr(milestone, id_field, user_data["id"])
            if hasattr(milestone, login_field):
                setattr(milestone, login_field, user_data["login"])
            try:
                process_user(user_data, via=via, fetched_at=fetched_at)
            except StaleData:
                pass
        else:
            setattr(milestone, id_field, None)
            if hasattr(milestone, login_field):
                setattr(milestone, login_field, None)

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(milestone, replicated_dt_field):
        setattr(milestone, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(milestone)
    if commit:
        db.session.commit()

    return milestone
