# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from celery import group
from webhookdb import db
from webhookdb.models import PullRequest
from webhookdb.exceptions import (
    MissingData, StaleData, NotFound
)
from sqlalchemy.exc import IntegrityError
from webhookdb.tasks import celery
from webhookdb.tasks.fetch import fetch_url_from_github
from webhookdb.tasks.user import process_user
from webhookdb.tasks.repository import process_repository
from urlobject import URLObject


def process_pull_request(pr_data, via="webhook", fetched_at=None, commit=True):
    pr_id = pr_data.get("id")
    if not pr_id:
        raise MissingData("no pull_request ID", obj=pr_data)

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    pr = PullRequest.query.get(pr_id)
    if not pr:
        pr = PullRequest(id=pr_id)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if pr.last_replicated_at > fetched_at:
        raise StaleData()

    # update the object
    fields = (
        "number", "state", "locked", "title", "body", "merge_commit_sha",
        "milestone", "merged", "mergeable", "mergeable_state",
        "comments", "review_comments", "commits", "additions", "deletions",
        "changed_files",
    )
    for field in fields:
        if field in pr_data:
            setattr(pr, field, pr_data[field])
    dt_fields = ("created_at", "updated_at", "closed_at", "merged_at")
    for field in dt_fields:
        if pr_data.get(field):
            dt = parse_date(pr_data[field]).replace(tzinfo=None)
            setattr(pr, field, dt)

    # user references
    user_fields = ("user", "assignee", "merged_by")
    for user_field in user_fields:
        if user_field not in pr_data:
            continue
        user_data = pr_data[user_field]
        id_field = "{}_id".format(user_field)
        login_field = "{}_login".format(user_field)
        if user_data:
            setattr(pr, id_field, user_data["id"])
            if hasattr(pr, login_field):
                setattr(pr, login_field, user_data["login"])
            try:
                process_user(user_data, via=via, fetched_at=fetched_at, commit=False)
            except StaleData:
                pass
        else:
            setattr(pr, id_field, None)
            if hasattr(pr, login_field):
                setattr(pr, login_field, None)

    # repository references
    refs = ("base", "head")
    for ref in refs:
        if not ref in pr_data:
            continue
        ref_data = pr_data[ref]
        ref_field = "{}_ref".format(ref)
        setattr(pr, ref_field, ref_data["ref"])
        repo_data = ref_data["repo"]
        repo_id_field = "{}_repo_id".format(ref)
        if repo_data:
            setattr(pr, repo_id_field, repo_data["id"])
            try:
                process_repository(repo_data, via=via, fetched_at=fetched_at, commit=False)
            except StaleData:
                pass
        else:
            setattr(pr, repo_id_field, None)

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(pr, replicated_dt_field):
        setattr(pr, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(pr)
    if commit:
        db.session.commit()

    return pr


@celery.task(bind=True, ignore_result=True)
def sync_pull_request(self, owner, repo, number):
    pr_url = "/repos/{owner}/{repo}/pulls/{number}".format(
        owner=owner, repo=repo, number=number,
    )
    try:
        resp = fetch_url_from_github(pr_url)
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
    return pr


@celery.task(bind=True, ignore_result=True)
def sync_page_of_pull_requests(self, owner, repo, state="all", per_page=100, page=1):
    pr_page_url = (
        "/repos/{owner}/{repo}/pulls?"
        "state={state}&per_page={per_page}&page={page}"
    ).format(
        owner=owner, repo=repo,
        state=state, per_page=per_page, page=page
    )
    resp = fetch_url_from_github(pr_page_url)
    fetched_at = datetime.now()
    pr_data_list = resp.json()
    results = []
    for pr_data in pr_data_list:
        try:
            pr = process_pull_request(
                pr_data, via="api", fetched_at=fetched_at, commit=True,
            )
            results.append(pr)
        except IntegrityError as exc:
            self.retry(exc=exc)
    return results


@celery.task(ignore_result=True)
def spawn_page_tasks_for_pull_requests(owner, repo, state="all", per_page=100):
    pr_list_url = (
        "/repos/{owner}/{repo}/pulls?"
        "state={state}&per_page={per_page}"
    ).format(
        owner=owner, repo=repo,
        state=state, per_page=per_page,
    )
    resp = fetch_url_from_github(pr_list_url, method="HEAD")
    last_page_url = URLObject(resp.links['last']['url'])
    last_page_num = int(last_page_url.query.dict['page'])
    g = group(
        sync_page_of_pull_requests.s(
            owner=owner, repo=repo, state=state, per_page=per_page, page=page
        ) for page in xrange(1, last_page_num+1)
    )
    return g.delay()
