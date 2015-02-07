# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from webhookdb import db
from webhookdb.models import Repository
from webhookdb.exceptions import NotFound, StaleData, MissingData
from sqlalchemy.exc import IntegrityError
from webhookdb.tasks import celery
from webhookdb.tasks.fetch import fetch_url_from_github
from .user import process_user


def process_repository(repo_data, via="webhook", fetched_at=None, commit=True):
    repo_id = repo_data.get("id")
    if not repo_id:
        raise MissingData("no repo ID")

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    repo = Repository.query.get(repo_id)
    if not repo:
        repo = Repository(id=repo_id)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if repo.last_replicated_at > fetched_at:
        raise StaleData()

    # update the object
    fields = (
        "name", "private", "description", "fork", "homepage", "size",
        "stargazers_count", "watchers_count", "language", "has_issues",
        "has_downloads", "has_wiki", "has_pages", "forks_count",
        "open_issues_count", "default_branch",
    )
    for field in fields:
        if field in repo_data:
            setattr(repo, field, repo_data[field])
    dt_fields = ("created_at", "updated_at", "pushed_at")
    for field in dt_fields:
        if repo_data.get(field):
            dt = parse_date(repo_data[field]).replace(tzinfo=None)
            setattr(repo, field, dt)

    # user references
    user_fields = ("owner", "organization")
    for user_field in user_fields:
        if user_field not in repo_data:
            continue
        user_data = repo_data[user_field]
        id_field = "{}_id".format(user_field)
        login_field = "{}_login".format(user_field)
        if user_data:
            setattr(repo, id_field, user_data["id"])
            if hasattr(repo, login_field):
                setattr(repo, login_field, user_data["login"])
            try:
                process_user(user_data, via=via, fetched_at=fetched_at, commit=False)
            except StaleData:
                pass
        else:
            setattr(repo, id_field, None)
            if hasattr(repo, login_field):
                setattr(repo, login_field, None)

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(repo, replicated_dt_field):
        setattr(repo, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(repo)
    if commit:
        db.session.commit()

    return repo


@celery.task(bind=True, ignore_result=True)
def sync_repository(self, owner, repo):
    repo_url = "/repos/{owner}/{repo}".format(owner=owner, repo=repo)
    try:
        resp = fetch_url_from_github(repo_url)
    except NotFound:
        # add more context
        msg = "Repo {owner}/{repo} not found".format(owner=owner, repo=repo)
        raise NotFound(msg, {
            "type": "repository",
            "owner": owner,
            "repo": repo,
        })
    repo_data = resp.json()
    try:
        repo = process_repository(
            repo_data, via="api", fetched_at=datetime.now(), commit=True,
        )
    except IntegrityError as exc:
        self.retry(exc=exc)
    return repo
