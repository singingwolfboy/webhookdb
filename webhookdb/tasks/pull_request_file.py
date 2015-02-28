# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from celery import group
from webhookdb import db
from webhookdb.models import PullRequestFile, Repository, PullRequest
from webhookdb.exceptions import (
    MissingData, StaleData, NotFound, NothingToDo, DatabaseError
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from webhookdb.tasks import celery
from webhookdb.tasks.fetch import fetch_url_from_github
from urlobject import URLObject


def process_pull_request_file(prf_data, via="webhook", fetched_at=None, commit=True):
    sha = prf_data.get("sha")
    if not sha:
        # This indicates a moved file: for example, moving /tmp/a.txt
        # to /tmp/b.txt. I don't know why Github marks moved files this
        # way, but it's not actually an error.
        raise NothingToDo("no pull request file SHA")

    pr_id = prf_data.get("pull_request_id")
    if not pr_id:
        raise MissingData("no pull_request_id", obj=prf_data)

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    prf = PullRequestFile.query.get(sha)
    if not prf:
        prf = PullRequestFile(sha=sha)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if prf.last_replicated_at > fetched_at:
        raise StaleData()

    # update the object
    fields = (
        "filename", "status", "additions", "deletions", "changes", "patch",
        "pull_request_id",
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


@celery.task(bind=True, ignore_result=True)
def sync_page_of_pull_request_files(self, owner, repo, number, pr_id=None,
                                    requestor_id=None, per_page=100, page=1):
    if not pr_id:
        # get pull request from DB
        pr_query = (
            PullRequest.query.join(Repository, PullRequest.base_repo_id == Repository.id)
            .filter(Repository.owner_login == owner)
            .filter(Repository.name == repo)
            .filter(PullRequest.number == number)
        )
        pr = pr_query.one()
        pr_id = pr.id

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
        prf_data["pull_request_id"] = pr_id
        try:
            prf = process_pull_request_file(
                prf_data, via="api", fetched_at=fetched_at, commit=True,
            )
            results.append(prf)
        except IntegrityError as exc:
            self.retry(exc=exc)
        except NothingToDo:
            pass
    return results


@celery.task(ignore_result=True)
def spawn_page_tasks_for_pull_request_files(owner, repo, number,
                                            requestor_id=None, per_page=100):
    prf_list_url = (
        "/repos/{owner}/{repo}/pulls/{number}/files?"
        "per_page={per_page}"
    ).format(
        owner=owner, repo=repo, number=number,
        per_page=per_page,
    )
    # first, make sure we get a response from Github
    resp = fetch_url_from_github(
        prf_list_url, method="HEAD", requestor_id=requestor_id,
    )
    last_page_url = URLObject(resp.links.get('last', {}).get('url', ""))
    last_page_num = int(last_page_url.query.dict.get('page', 1))

    # Then, clear all old pull request files for this PR from the DB
    # get the pull request object from the database
    pr_query = (
        PullRequest.query.join(Repository, PullRequest.base_repo_id == Repository.id)
        .filter(Repository.owner_login == owner)
        .filter(Repository.name == repo)
        .filter(PullRequest.number == number)
    )
    try:
        pr = pr_query.one()
    except NoResultFound:
        msg = "PR {owner}/{repo}#{number} not loaded in webhookdb".format(
            owner=owner, repo=repo, number=number,
        )
        raise NotFound(msg, {
            "type": "pull_request_file",
            "owner": owner,
            "repo": repo,
            "number": number,
        })
    except MultipleResultsFound:
        msg = "PR {owner}/{repo}#{number} found multiple times!".format(
            owner=owner, repo=repo, number=number,
        )
        raise DatabaseError(msg, {
            "type": "pull_request_file",
            "owner": owner,
            "repo": repo,
            "number": number,
        })

    # clear all old pull request files for this PR from the DB
    PullRequestFile.query.filter_by(pull_request_id=pr.id).delete()

    # spawn tasks to repopulate the DB
    g = group(
        sync_page_of_pull_request_files.s(
            owner=owner, repo=repo, number=number, pr_id=pr.id,
            requestor_id=requestor_id, per_page=per_page, page=page,
        ) for page in xrange(1, last_page_num+1)
    )
    result = g.delay()

    # commit the deletion to the DB, and return
    db.session.commit()
    return result
