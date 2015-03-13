# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from celery import group
from urlobject import URLObject
from webhookdb import db
from webhookdb.models import Issue, Mutex
from webhookdb.tasks import celery
from webhookdb.tasks.fetch import fetch_url_from_github
from webhookdb.tasks.user import process_user
from webhookdb.tasks.label import process_label
from webhookdb.tasks.milestone import process_milestone
from webhookdb.exceptions import (
    MissingData, StaleData, NotFound
)
from sqlalchemy.exc import IntegrityError

LOCK_TEMPLATE = "Repository|{owner}/{repo}|issues"


def process_issue(issue_data, via="webhook", fetched_at=None, commit=True):
    issue_id = issue_data.get("id")
    if not issue_id:
        raise MissingData("no issue ID", obj=issue_data)

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    issue = Issue.query.get(issue_id)
    if not issue:
        issue = Issue(id=issue_id)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if issue.last_replicated_at > fetched_at:
        raise StaleData()

    # Most fields have the same name in our model as they do in Github's API.
    # However, some are different. This mapping contains just the differences.
    field_to_model = {
        "comments": "comments_count",
    }

    # update the object
    fields = (
        "number", "state", "title", "body", "comments",
    )
    for field in fields:
        if field in issue_data:
            mfield = field_to_model.get(field, field)
            setattr(issue, mfield, issue_data[field])
    dt_fields = ("created_at", "updated_at", "closed_at")
    for field in dt_fields:
        if issue_data.get(field):
            dt = parse_date(issue_data[field]).replace(tzinfo=None)
            mfield = field_to_model.get(field, field)
            setattr(issue, mfield, dt)

    # user references
    user_fields = ("user", "assignee", "closed_by")
    for user_field in user_fields:
        if user_field not in issue_data:
            continue
        user_data = issue_data[user_field]
        id_field = "{}_id".format(user_field)
        login_field = "{}_login".format(user_field)
        if user_data:
            setattr(issue, id_field, user_data["id"])
            if hasattr(issue, login_field):
                setattr(issue, login_field, user_data["login"])
            try:
                process_user(user_data, via=via, fetched_at=fetched_at)
            except StaleData:
                pass
        else:
            setattr(issue, id_field, None)
            if hasattr(issue, login_field):
                setattr(issue, login_field, None)

    # used for labels and milestone
    repo_id = None

    # label reference
    if "labels" in issue_data:
        label_data_list = issue_data["labels"]
        if label_data_list:
            labels = []
            for label_data in label_data_list:
                label = process_label(
                    label_data, via=via, fetched_at=fetched_at, commit=False,
                    repo_id=repo_id,
                )
                repo_id = repo_id or label.repo_id
                labels.append(label)
            issue.labels = labels
        else:
            issue.labels = []

    # milestone reference
    if "milestone" in issue_data:
        milestone_data = issue_data["milestone"]
        if milestone_data:
            milestone = process_milestone(
                milestone_data, via=via, fetched_at=fetched_at, commit=False,
                repo_id=repo_id,
            )
            repo_id = repo_id or milestone.repo_id
            issue.milestone_number = milestone.number
        else:
            issue.milestone = None

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(issue, replicated_dt_field):
        setattr(issue, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(issue)
    if commit:
        db.session.commit()

    return issue


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
    pr.issues_last_scanned_at = datetime.now()
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
    # acquire lock or fail
    with db.session.begin():
        lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo)
        existing = Mutex.query.get(lock_name)
        if existing:
            return False
        lock = Mutex(name=lock_name, user_id=requestor_id)
        db.session.add(lock)

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
