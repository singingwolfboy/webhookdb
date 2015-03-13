# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from celery import group
from urlobject import URLObject
from webhookdb import db
from webhookdb.models import Issue, Repository, Mutex
from webhookdb.process import process_issue
from webhookdb.tasks import celery
from webhookdb.tasks.fetch import fetch_url_from_github
from webhookdb.exceptions import NotFound
from sqlalchemy.exc import IntegrityError

LOCK_TEMPLATE = "Repository|{owner}/{repo}|issues"


@celery.task(bind=True)
def sync_issue(self, owner, repo, number, children=False, requestor_id=None):
    issue_url = "/repos/{owner}/{repo}/issues/{number}".format(
        owner=owner, repo=repo, number=number,
    )
    try:
        resp = fetch_url_from_github(issue_url, requestor_id=requestor_id)
    except NotFound:
        # add more context
        msg = "Issue {owner}/{repo}#{number} not found".format(
            owner=owner, repo=repo, number=number,
        )
        raise NotFound(msg, {
            "type": "issue",
            "owner": owner,
            "repo": repo,
            "number": number,
        })
    issue_data = resp.json()
    try:
        issue = process_issue(
            issue_data, via="api", fetched_at=datetime.now(), commit=True,
        )
    except IntegrityError as exc:
        self.retry(exc=exc)
    # ignore `children` attribute for now
    return issue.id


@celery.task(bind=True)
def sync_page_of_issues(self, owner, repo, state="all", children=False,
                        requestor_id=None, per_page=100, page=1):
    issue_page_url = (
        "/repos/{owner}/{repo}/issues?"
        "state={state}&per_page={per_page}&page={page}"
    ).format(
        owner=owner, repo=repo,
        state=state, per_page=per_page, page=page
    )
    resp = fetch_url_from_github(issue_page_url, requestor_id=requestor_id)
    fetched_at = datetime.now()
    issue_data_list = resp.json()
    results = []
    for issue_data in issue_data_list:
        try:
            issue = process_issue(
                issue_data, via="api", fetched_at=fetched_at, commit=True,
            )
            # ignore `children` attribute for now
            results.append(issue.id)
        except IntegrityError as exc:
            self.retry(exc=exc)
    return results


@celery.task()
def issues_scanned(owner, repo, requestor_id=None):
    """
    Update the timestamp on the repository object,
    and delete old issues that weren't updated.
    """
    repo = Repository.get(owner, repo)
    prev_scan_at = repo.issues_last_scanned_at
    repo.issues_last_scanned_at = datetime.now()
    db.session.add(repo)

    if prev_scan_at:
        # delete any issues that were not updated since the previous scan --
        # they have been removed from Github
        query = (
            Issue.query.filter_by(repo_id=repo.id)
            .filter(Issue.last_replicated_at < prev_scan_at)
        )
        query.delete()

    # delete the mutex
    lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo)
    Mutex.query.filter_by(name=lock_name).delete()

    db.session.commit()


@celery.task()
def spawn_page_tasks_for_issues(owner, repo, state="all", children=False,
                                requestor_id=None, per_page=100):
    # acquire lock or fail (we're already in a transaction)
    lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo)
    existing = Mutex.query.get(lock_name)
    if existing:
        return False
    lock = Mutex(name=lock_name, user_id=requestor_id)
    db.session.add(lock)
    db.session.commit()

    issue_list_url = (
        "/repos/{owner}/{repo}/issues?"
        "state={state}&per_page={per_page}"
    ).format(
        owner=owner, repo=repo,
        state=state, per_page=per_page,
    )
    resp = fetch_url_from_github(
        issue_list_url, method="HEAD", requestor_id=requestor_id,
    )
    last_page_url = URLObject(resp.links.get('last', {}).get('url', ""))
    last_page_num = int(last_page_url.query.dict.get('page', 1))
    g = group(
        sync_page_of_issues.s(
            owner=owner, repo=repo, state=state, children=children,
            requestor_id=requestor_id,
            per_page=per_page, page=page,
        ) for page in xrange(1, last_page_num+1)
    )
    finisher = issues_scanned.si(
        owner=owner, repo=repo, requestor_id=requestor_id,
    )
    return (g | finisher).delay()
