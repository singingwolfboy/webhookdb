# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from celery import group
from webhookdb import db
from webhookdb.process import process_repository
from webhookdb.models import Repository, User, Mutex
from webhookdb.exceptions import NotFound, StaleData, MissingData
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from webhookdb.tasks import celery
from webhookdb.tasks.fetch import fetch_url_from_github
from webhookdb.tasks.issue import spawn_page_tasks_for_issues
from webhookdb.tasks.label import spawn_page_tasks_for_labels
from webhookdb.tasks.milestone import spawn_page_tasks_for_milestones
from webhookdb.tasks.pull_request import spawn_page_tasks_for_pull_requests
from webhookdb.tasks.repository_hook import spawn_page_tasks_for_repository_hooks
from urlobject import URLObject

LOCK_TEMPLATE = "User|{username}|repos"



@celery.task(bind=True)
def sync_repository(self, owner, repo, children=False, requestor_id=None):
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

    if children:
        spawn_page_tasks_for_issues.delay(
            owner, repo, children=children, requestor_id=requestor_id,
        )
        spawn_page_tasks_for_labels.delay(
            owner, repo, children=children, requestor_id=requestor_id,
        )
        spawn_page_tasks_for_milestones.delay(
            owner, repo, children=children, requestor_id=requestor_id,
        )
        spawn_page_tasks_for_pull_requests.delay(
            owner, repo, children=children, requestor_id=requestor_id,
        )
        spawn_page_tasks_for_repository_hooks.delay(
            owner, repo, children=children, requestor_id=requestor_id,
        )

    return repo.id


@celery.task(bind=True)
def sync_page_of_repositories_for_user(self, username, type="all",
                                       children=False, requestor_id=None,
                                       per_page=100, page=1):
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
            results.append(repo.id)
        except IntegrityError as exc:
            self.retry(exc=exc)

        if children:
            owner = repo.owner_login
            repo = repo.name
            spawn_page_tasks_for_issues.delay(
                owner, repo, children=children, requestor_id=requestor_id,
            )
            spawn_page_tasks_for_labels.delay(
                owner, repo, children=children, requestor_id=requestor_id,
            )
            spawn_page_tasks_for_milestones.delay(
                owner, repo, children=children, requestor_id=requestor_id,
            )
            spawn_page_tasks_for_pull_requests.delay(
                owner, repo, children=children, requestor_id=requestor_id,
            )
            spawn_page_tasks_for_repository_hooks.delay(
                owner, repo, children=children, requestor_id=requestor_id,
            )

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


@celery.task()
def spawn_page_tasks_for_user_repositories(
            username, type="all", children=False, requestor_id=None, per_page=100,
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
            username=username, type=type,
            children=children, requestor_id=requestor_id,
            per_page=per_page, page=page,
        ) for page in xrange(1, last_page_num+1)
    )
    finisher = user_repositories_scanned.si(
        username=username, requestor_id=requestor_id,
    )
    return (g | finisher).delay()
