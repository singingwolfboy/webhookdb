# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from celery import group
from webhookdb import db
from webhookdb.process import process_pull_request
from webhookdb.models import PullRequest, Repository, Mutex
from webhookdb.exceptions import NotFound
from sqlalchemy.exc import IntegrityError
from webhookdb.tasks import celery
from webhookdb.tasks.fetch import fetch_url_from_github
from webhookdb.tasks.pull_request_file import spawn_page_tasks_for_pull_request_files
from urlobject import URLObject

LOCK_TEMPLATE = "Repository|{owner}/{repo}|pulls"


@celery.task(bind=True)
def sync_pull_request(self, owner, repo, number,
                      children=False, requestor_id=None):
    pr_url = "/repos/{owner}/{repo}/pulls/{number}".format(
        owner=owner, repo=repo, number=number,
    )
    try:
        resp = fetch_url_from_github(pr_url, requestor_id=requestor_id)
    except NotFound:
        # add more context
        msg = "PR {owner}/{repo}#{number} not found".format(
            owner=owner, repo=repo, number=number,
        )
        raise NotFound(msg, {
            "type": "pull_request",
            "owner": owner,
            "repo": repo,
            "number": number,
        })
    pr_data = resp.json()
    try:
        pr = process_pull_request(
            pr_data, via="api", fetched_at=datetime.now(), commit=True,
        )
    except IntegrityError as exc:
        self.retry(exc=exc)

    if children:
        spawn_page_tasks_for_pull_request_files.delay(
            owner, repo, number, children=children, requestor_id=requestor_id,
        )

    return pr.id


@celery.task(bind=True)
def sync_page_of_pull_requests(self, owner, repo, state="all", children=False,
                               requestor_id=None, per_page=100, page=1):
    pr_page_url = (
        "/repos/{owner}/{repo}/pulls?"
        "state={state}&per_page={per_page}&page={page}"
    ).format(
        owner=owner, repo=repo,
        state=state, per_page=per_page, page=page
    )
    resp = fetch_url_from_github(pr_page_url, requestor_id=requestor_id)
    fetched_at = datetime.now()
    pr_data_list = resp.json()
    results = []
    for pr_data in pr_data_list:
        try:
            pr = process_pull_request(
                pr_data, via="api", fetched_at=fetched_at, commit=True,
            )
            results.append(pr.id)
        except IntegrityError as exc:
            self.retry(exc=exc)

        if children:
            spawn_page_tasks_for_pull_request_files.delay(
                owner, repo, pr.number, children=children,
                requestor_id=requestor_id,
            )
    return results


@celery.task()
def pull_requests_scanned(owner, repo, requestor_id=None):
    """
    Update the timestamp on the repository object,
    and delete old pull request that weren't updated.
    """
    repo = Repository.get(owner, repo)
    prev_scan_at = repo.pull_requests_last_scanned_at
    pr.pull_requests_last_scanned_at = datetime.now()
    db.session.add(repo)

    if prev_scan_at:
        # delete any PRs that were not updated since the previous scan --
        # they have been removed from Github
        query = (
            PullRequest.query.filter_by(repo_id=repo.id)
            .filter(PullRequest.last_replicated_at < prev_scan_at)
        )
        query.delete()

    # delete the mutex
    lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo)
    Mutex.query.filter_by(name=lock_name).delete()

    db.session.commit()


@celery.task()
def spawn_page_tasks_for_pull_requests(owner, repo, state="all", children=False,
                                       requestor_id=None, per_page=100):
    # acquire lock or fail
    with db.session.begin():
        lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo)
        existing = Mutex.query.get(lock_name)
        if existing:
            return False
        lock = Mutex(name=lock_name, user_id=requestor_id)
        db.session.add(lock)

    pr_list_url = (
        "/repos/{owner}/{repo}/pulls?"
        "state={state}&per_page={per_page}"
    ).format(
        owner=owner, repo=repo,
        state=state, per_page=per_page,
    )
    resp = fetch_url_from_github(
        pr_list_url, method="HEAD", requestor_id=requestor_id,
    )
    last_page_url = URLObject(resp.links.get('last', {}).get('url', ""))
    last_page_num = int(last_page_url.query.dict.get('page', 1))
    g = group(
        sync_page_of_pull_requests.s(
            owner=owner, repo=repo, state=state,
            children=children, requestor_id=requestor_id,
            per_page=per_page, page=page
        ) for page in xrange(1, last_page_num+1)
    )
    finisher = pull_requests_scanned.si(
        owner=owner, repo=repo, requestor_id=requestor_id,
    )
    return (g | finisher).delay()
