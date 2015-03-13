# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from celery import group
from webhookdb import db
from webhookdb.process import process_pull_request_file
from webhookdb.models import PullRequestFile, PullRequest, Mutex
from webhookdb.exceptions import (
    NotFound, NothingToDo, DatabaseError
)
from sqlalchemy.exc import IntegrityError
from webhookdb.tasks import celery
from webhookdb.tasks.fetch import fetch_url_from_github
from urlobject import URLObject

LOCK_TEMPLATE = "PullRequest|{owner}/{repo}#{number}|files"


@celery.task(bind=True)
def sync_page_of_pull_request_files(self, owner, repo, number, pull_request_id=None,
                                    children=False, requestor_id=None,
                                    per_page=100, page=1):
    if not pull_request_id:
        pull_request_id = PullRequest.get(owner, repo, number).id

    prf_page_url = (
        "/repos/{owner}/{repo}/pulls/{number}/files?"
        "per_page={per_page}&page={page}"
    ).format(
        owner=owner, repo=repo, number=number,
        per_page=per_page, page=page,
    )
    resp = fetch_url_from_github(prf_page_url, requestor_id=requestor_id)
    fetched_at = datetime.now()
    prf_data_list = resp.json()
    results = []
    for prf_data in prf_data_list:
        try:
            prf = process_pull_request_file(
                prf_data, via="api", fetched_at=fetched_at, commit=True,
                pull_request_id=pull_request_id,
            )
            results.append(prf.sha)
        except IntegrityError as exc:
            self.retry(exc=exc)
        except NothingToDo:
            pass
    return results


@celery.task()
def pull_request_files_scanned(owner, repo, number, requestor_id=None):
    """
    Update the timestamp on the pull request object,
    and delete old pull request files that weren't updated.
    """
    pr = PullRequest.get(owner, repo, number)
    prev_scan_at = pr.files_last_scanned_at
    pr.files_last_scanned_at = datetime.now()
    db.session.add(pr)

    if prev_scan_at:
        # delete any files that were not updated since the previous scan --
        # they have been removed from Github
        query = (
            PullRequestFile.query.filter_by(pull_request_id=pr.id)
            .filter(PullRequestFile.last_replicated_at < prev_scan_at)
        )
        query.delete()

    # delete the mutex
    lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo, number=number)
    Mutex.query.filter_by(name=lock_name).delete()

    db.session.commit()


@celery.task()
def spawn_page_tasks_for_pull_request_files(owner, repo, number, children=False,
                                            requestor_id=None, per_page=100):
    # acquire lock or fail
    with db.session.begin():
        lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo, number=number)
        existing = Mutex.query.get(lock_name)
        if existing:
            return False
        lock = Mutex(name=lock_name, user_id=requestor_id)
        db.session.add(lock)

    prf_list_url = (
        "/repos/{owner}/{repo}/pulls/{number}/files?"
        "per_page={per_page}"
    ).format(
        owner=owner, repo=repo, number=number,
        per_page=per_page,
    )
    resp = fetch_url_from_github(
        prf_list_url, method="HEAD", requestor_id=requestor_id,
    )
    last_page_url = URLObject(resp.links.get('last', {}).get('url', ""))
    last_page_num = int(last_page_url.query.dict.get('page', 1))

    g = group(
        sync_page_of_pull_request_files.s(
            owner=owner, repo=repo, number=number, pull_request_id=pr.id,
            children=children, requestor_id=requestor_id,
            per_page=per_page, page=page,
        ) for page in xrange(1, last_page_num+1)
    )
    finisher = pull_request_files_scanned.si(
        owner=owner, repo=repo, number=number, requestor_id=requestor_id,
    )
    return (g | finisher).delay()
