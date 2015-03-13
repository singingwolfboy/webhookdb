# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from celery import group
from webhookdb import db
from webhookdb.process import process_repository_hook
from webhookdb.models import RepositoryHook, Repository, Mutex
from webhookdb.exceptions import NotFound
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from webhookdb.tasks import celery, logger
from webhookdb.tasks.fetch import fetch_url_from_github
from urlobject import URLObject

LOCK_TEMPLATE = "Repository|{owner}/{repo}|hooks"


@celery.task(bind=True)
def sync_repository_hook(self, owner, repo, hook_id,
                         children=False, requestor_id=None):
    hook_url = "/repos/{owner}/{repo}/hooks/{hook_id}".format(
        owner=owner, repo=repo, hook_id=hook_id,
    )
    try:
        resp = fetch_url_from_github(hook_url, requestor_id=requestor_id)
    except NotFound:
        # add more context
        msg = "Hook #{hook_id} for {owner}/{repo} not found".format(
            hook_id=hook_id, owner=owner, repo=repo,
        )
        raise NotFound(msg, {
            "type": "repo_hook",
            "owner": owner,
            "repo": repo,
            "hook_id": hook_id,
        })
    hook_data = resp.json()
    try:
        hook = process_repository_hook(
            hook_data, via="api", fetched_at=datetime.now(), commit=True,
            requestor_id=requestor_id,
        )
    except IntegrityError as exc:
        self.retry(exc=exc)
    return hook.id


@celery.task(bind=True)
def sync_page_of_repository_hooks(self, owner, repo, children=False,
                                  requestor_id=None, per_page=100, page=1):
    hook_page_url = (
        "/repos/{owner}/{repo}/hooks?per_page={per_page}&page={page}"
    ).format(
        owner=owner, repo=repo, per_page=per_page, page=page,
    )
    resp = fetch_url_from_github(hook_page_url, requestor_id=requestor_id)
    fetched_at = datetime.now()
    hook_data_list = resp.json()
    results = []
    for hook_data in hook_data_list:
        try:
            hook = process_repository_hook(
                hook_data, via="api", fetched_at=fetched_at, commit=True,
                requestor_id=requestor_id,
            )
            results.append(hook.id)
        except IntegrityError as exc:
            self.retry(exc=exc)
    return results


@celery.task()
def hooks_scanned(owner, repo, requestor_id=None):
    """
    Update the timestamp on the repository object,
    and delete old hooks that weren't updated.
    """
    repo = Repository.get(owner, repo)
    prev_scan_at = repo.hooks_last_scanned_at
    pr.hooks_last_scanned_at = datetime.now()
    db.session.add(repo)

    if prev_scan_at:
        # delete any hooks that were not updated since the previous scan --
        # they have been removed from Github
        query = (
            RepositoryHook.query.filter_by(repo_id=repo.id)
            .filter(RepositoryHook.last_replicated_at < prev_scan_at)
        )
        query.delete()

    # delete the mutex
    lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo)
    Mutex.query.filter_by(name=lock_name).delete()

    db.session.commit()


@celery.task()
def spawn_page_tasks_for_repository_hooks(
            owner, repo, children=False, requestor_id=None, per_page=100,
    ):
    # acquire lock or fail (we're already in a transaction)
    lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo)
    existing = Mutex.query.get(lock_name)
    if existing:
        return False
    lock = Mutex(name=lock_name, user_id=requestor_id)
    db.session.add(lock)
    db.session.commit()

    hook_page_url = (
        "/repos/{owner}/{repo}/hooks?per_page={per_page}"
    ).format(
        owner=owner, repo=repo, type=type, per_page=per_page,
    )
    resp = fetch_url_from_github(
        hook_page_url, method="HEAD", requestor_id=requestor_id,
    )
    last_page_url = URLObject(resp.links.get('last', {}).get('url', ""))
    last_page_num = int(last_page_url.query.dict.get('page', 1))
    g = group(
        sync_page_of_repository_hooks.s(
            owner=owner, repo=repo,
            children=children, requestor_id=requestor_id,
            per_page=per_page, page=page,
        ) for page in xrange(1, last_page_num+1)
    )
    finisher = hooks_scanned.si(
        owner=owner, repo=repo, requestor_id=requestor_id,
    )
    return (g | finisher).delay()
