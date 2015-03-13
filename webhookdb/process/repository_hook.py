# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from urlobject import URLObject
from webhookdb import db
from webhookdb.models import RepositoryHook, Repository
from webhookdb.exceptions import MissingData, StaleData
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound


def process_repository_hook(hook_data, via="webhook", fetched_at=None, commit=True,
                            requestor_id=None, repo_id=None):
    hook_id = hook_data.get("id")
    if not hook_id:
        raise MissingData("no hook ID")

    if not repo_id:
        url = hook_data.get("url")
        if not url:
            raise MissingData("no hook url")

        # parse repo info from url
        path = URLObject(url).path
        assert path.segments[0] == "repos"
        repo_owner = path.segments[1]
        repo_name = path.segments[2]

        # fetch repo from database
        repo_query = (Repository.query
            .filter(Repository.owner_login == repo_owner)
            .filter(Repository.name == repo_name)
        )
        try:
            repo = repo_query.one()
        except NoResultFound:
            msg = "Repo {owner}/{repo} not loaded in webhookdb".format(
                owner=repo_owner, repo=repo_name,
            )
            raise NotFound(msg, {
                "type": "repo_hook",
                "owner": repo_owner,
                "repo": repo_name,
            })
        except MultipleResultsFound:
            msg = "Repo {owner}/{repo} found multiple times!".format(
                owner=repo_owner, repo=repo_name,
            )
            raise DatabaseError(msg, {
                "type": "repo_hook",
                "owner": repo_owner,
                "repo": repo_name,
            })
        repo_id = repo.id

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    hook = RepositoryHook.query.get(hook_id)
    if not hook:
        hook = RepositoryHook(id=hook_id, repo_id=repo_id)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if hook.last_replicated_at > fetched_at:
        raise StaleData()

    # update the object
    fields = (
        "name", "config", "events", "active", "last_response",
    )
    for field in fields:
        if field in hook_data:
            setattr(hook, field, hook_data[field])
    dt_fields = ("created_at", "updated_at")
    for field in dt_fields:
        if hook_data.get(field):
            dt = parse_date(hook_data[field]).replace(tzinfo=None)
            setattr(hook, field, dt)

    # `url` is special -- it's the value in the `config` object,
    # NOT the top-level `url` property
    hook.url = hook_data.get("config", {}).get("url")

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(hook, replicated_dt_field):
        setattr(hook, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(hook)

    if commit:
        db.session.commit()

    return hook
