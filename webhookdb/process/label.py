# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from urlobject import URLObject
from colour import Color
from webhookdb import db
from webhookdb.models import IssueLabel, Repository
from webhookdb.exceptions import MissingData, StaleData, NotFound
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound


def process_label(label_data, via="webhook", fetched_at=None, commit=True,
                  repo_id=None):
    name = label_data.get("name")
    if not name:
        raise MissingData("no label name")

    if not repo_id:
        url = label_data.get("url")
        if not url:
            raise MissingData("no label url")

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
                "type": "label",
                "owner": repo_owner,
                "repo": repo_name,
            })
        if not repo:
            msg = "Repo {owner}/{repo} not loaded in webhookdb".format(
                owner=repo_owner, repo=repo_name,
            )
            raise NotFound(msg, {
                "type": "label",
                "owner": repo_owner,
                "repo": repo_name,
            })
        repo_id = repo.id

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    label = IssueLabel.query.get((repo_id, name))
    if not label:
        label = IssueLabel(repo_id=repo_id, name=name)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if label.last_replicated_at > fetched_at:
        raise StaleData()

    # color reference
    if "color" in label_data:
        color_hex = label_data["color"]
        if color_hex:
            label.color = Color("#{hex}".format(hex=color_hex))
        else:
            label.color = None

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(label, replicated_dt_field):
        setattr(label, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(label)
    if commit:
        db.session.commit()

    return label
