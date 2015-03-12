# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from celery import group
from webhookdb import db
from webhookdb.models import Repository, User, UserRepoAssociation, Mutex
from webhookdb.exceptions import NotFound, StaleData, MissingData
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from webhookdb.tasks import celery
from webhookdb.tasks.fetch import fetch_url_from_github
from webhookdb.tasks.user import process_user
from urlobject import URLObject

LOCK_TEMPLATE = "User|{username}|repos"


def process_repository(repo_data, via="webhook", fetched_at=None, commit=True,
                       requestor_id=None):
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
                process_user(user_data, via=via, fetched_at=fetched_at)
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

    # if we have requestor_id and permissions, update the permissions object
    if requestor_id and repo_data.get("permissions"):
        permissions_data = repo_data["permissions"]
        assoc = UserRepoAssociation.query.get((requestor_id, repo_id))
        if not assoc:
            assoc = UserRepoAssociation(user_id=requestor_id, repo_id=repo_id)
        for perm in ("admin", "push", "pull"):
            if perm in permissions_data:
                perm_attr = "can_{perm}".format(perm=perm)
                setattr(assoc, perm_attr, permissions_data[perm])
        db.session.add(assoc)

    if commit:
        db.session.commit()

    return repo


@celery.task(bind=True, ignore_result=True)
def sync_repository(self, owner, repo, requestor_id=None):
    repo_url = "/repos/{owner}/{repo}".format(owner=owner, repo=repo)
    try:
        resp = fetch_url_from_github(repo_url, requestor_id=requestor_id)
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
            requestor_id=requestor_id,
        )
    except IntegrityError as exc:
        self.retry(exc=exc)
    return repo


@celery.task(bind=True, ignore_result=True)
def sync_page_of_repositories_for_user(self, username, type="all",
                                       requestor_id=None, per_page=100, page=1):
    repo_page_url = (
        "/users/{username}/repos?type={type}&per_page={per_page}&page={page}"
    ).format(
        username=username, type=type, per_page=per_page, page=page,
    )

    if requestor_id:
        requestor = User.query.get(int(requestor_id))
        assert requestor
        if requestor.login == username:
            # we can use the API for getting your *own* repos
            repo_page_url = (
                "/user/repos?type={type}&per_page={per_page}&page={page}"
            ).format(
                type=type, per_page=per_page, page=page
            )

    resp = fetch_url_from_github(
        repo_page_url, requestor_id=requestor_id,
        headers={"Accept": "application/vnd.github.moondragon+json"},
    )
    fetched_at = datetime.now()
    repo_data_list = resp.json()
    results = []
    for repo_data in repo_data_list:
        try:
            repo = process_repository(
                repo_data, via="api", fetched_at=fetched_at, commit=True,
                requestor_id=requestor_id,
            )
            results.append(repo)
        except IntegrityError as exc:
            self.retry(exc=exc)
    return results


@celery.task()
def user_repositories_scanned(username, requestor_id=None):
    """
    Update the timestamp on the pull request object,
    and delete old pull request files that weren't updated.
    """
    user = User.get(username)
    prev_scan_at = user.repos_last_scanned_at
    user.repos_last_scanned_at = datetime.now()
    db.session.add(user)

    if prev_scan_at:
        # delete any repos that the user owns that were not updated
        # since the previous scan -- the user must have deleted those
        # repos from Github
        query = (
            Repository.query.filter_by(owner_id=user.id)
            .filter(Repository.last_replicated_at < prev_scan_at)
        )
        query.delete()

    # delete the mutex
    lock_name = LOCK_TEMPLATE.format(username=username)
    Mutex.query.filter_by(name=lock_name).delete()

    db.session.commit()


@celery.task(ignore_result=True)
def spawn_page_tasks_for_user_repositories(
            username, type="all", requestor_id=None, per_page=100,
    ):
    # acquire lock or fail
    with db.session.begin():
        lock_name = LOCK_TEMPLATE.format(username=username)
        existing = Mutex.query.get(lock_name)
        if existing:
            return False
        lock = Mutex(name=lock_name, user_id=requestor_id)
        db.session.add(lock)

    repo_page_url = (
        "/users/{username}/repos?type={type}&per_page={per_page}"
    ).format(
        username=username, type=type, per_page=per_page,
    )

    if requestor_id:
        requestor = User.query.get(int(requestor_id))
        assert requestor
        if requestor.login == username:
            # we can use the API for getting your *own* repos
            repo_page_url = (
                "/user/repos?type={type}&per_page={per_page}"
            ).format(
                type=type, per_page=per_page,
            )

    resp = fetch_url_from_github(
        repo_page_url, method="HEAD", requestor_id=requestor_id,
        headers={"Accept": "application/vnd.github.moondragon+json"},
    )
    last_page_url = URLObject(resp.links.get('last', {}).get('url', ""))
    last_page_num = int(last_page_url.query.dict.get('page', 1))
    g = group(
        sync_page_of_repositories_for_user.s(
            username=username, type=type, requestor_id=requestor_id,
            per_page=per_page, page=page,
        ) for page in xrange(1, last_page_num+1)
    )
    finisher = user_repositories_scanned.si(
        username=username, requestor_id=requestor_id,
    )
    return (g | finisher).delay()
