# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from celery import group
from webhookdb import db
from webhookdb.models import PullRequestFile, Repository, PullRequest, Mutex
from webhookdb.exceptions import (
    MissingData, StaleData, NotFound, NothingToDo, DatabaseError
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from webhookdb.tasks import celery
from webhookdb.tasks.fetch import fetch_url_from_github
from urlobject import URLObject

LOCK_TEMPLATE = "PullRequest|{owner}/{repo}#{number}|files"


def process_pull_request_file(
            prf_data, via="webhook", fetched_at=None, commit=True,
            pull_request_id=None,
    ):
    sha = prf_data.get("sha")
    if not sha:
        # This indicates a moved file: for example, moving /tmp/a.txt
        # to /tmp/b.txt. I don't know why Github marks moved files this
        # way, but it's not actually an error.
        raise NothingToDo("no pull request file SHA")

    pr_id = pull_request_id
    if not pr_id:
        raise MissingData("no pull_request_id", obj=prf_data)

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    prf = PullRequestFile.query.get((pr_id, sha))
    if not prf:
        prf = PullRequestFile(sha=sha, pull_request_id=pr_id)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if prf.last_replicated_at > fetched_at:
        raise StaleData()

    # update the object
    fields = (
        "filename", "status", "additions", "deletions", "changes", "patch",
    )
    for field in fields:
        if field in prf_data:
            setattr(prf, field, prf_data[field])

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(prf, replicated_dt_field):
        setattr(prf, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(prf)
    if commit:
        db.session.commit()

    return prf


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
