# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from celery import group
from urlobject import URLObject
from webhookdb import db, celery
from webhookdb.models import Milestone, Repository, Mutex
from webhookdb.exceptions import NotFound, StaleData, MissingData, DatabaseError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from webhookdb.tasks.fetch import fetch_url_from_github
from webhookdb.tasks.user import process_user

LOCK_TEMPLATE = "Repository|{owner}/{repo}|milestones"


def process_milestone(milestone_data, via="webhook", fetched_at=None, commit=True,
                      repo_id=None):
    number = milestone_data.get("number")
    if not number:
        raise MissingData("no milestone number")

    if not repo_id:
        url = milestone_data.get("url")
        if not url:
            raise MissingData("no milestone url")

        # parse repo info from url
        path = URLObject(url).path
        assert path.segments[0] == "repos"
        repo_owner = path.segments[1]
        repo_name = path.segments[2]

        # fetch repo from database
        try:
            repo = Repository.get(repo_owner, repo_name)
        except MultipleResultsFound:
            msg = "Repo {owner}/{repo} found multiple times!".format(
                owner=repo_owner, repo=repo_name,
            )
            raise DatabaseError(msg, {
                "type": "milestone",
                "owner": repo_owner,
                "repo": repo_name,
            })
        if not repo:
            msg = "Repo {owner}/{repo} not loaded in webhookdb".format(
                owner=repo_owner, repo=repo_name,
            )
            raise NotFound(msg, {
                "type": "milestone",
                "owner": repo_owner,
                "repo": repo_name,
            })
        repo_id = repo.id

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    milestone = Milestone.query.get((repo_id, number))
    if not milestone:
        milestone = Milestone(repo_id=repo_id, number=number)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if milestone.last_replicated_at > fetched_at:
        raise StaleData()

    # Most fields have the same name in our model as they do in Github's API.
    # However, some are different. This mapping contains just the differences.
    field_to_model = {
        "open_issues": "open_issues_count",
        "closed_issues": "closed_issues_count",
        "due_on": "due_at",
    }

    # update the object
    fields = (
        "state", "title", "description", "open_issues", "closed_issues",
    )
    for field in fields:
        if field in milestone_data:
            mfield = field_to_model.get(field, field)
            setattr(milestone, mfield, milestone_data[field])
    dt_fields = ("created_at", "updated_at", "closed_at", "due_on")
    for field in dt_fields:
        if milestone_data.get(field):
            dt = parse_date(milestone_data[field]).replace(tzinfo=None)
            mfield = field_to_model.get(field, field)
            setattr(milestone, mfield, dt)

    # user references
    user_fields = ("creator",)
    for user_field in user_fields:
        if user_field not in milestone_data:
            continue
        user_data = milestone_data[user_field]
        id_field = "{}_id".format(user_field)
        login_field = "{}_login".format(user_field)
        if user_data:
            setattr(milestone, id_field, user_data["id"])
            if hasattr(milestone, login_field):
                setattr(milestone, login_field, user_data["login"])
            try:
                process_user(user_data, via=via, fetched_at=fetched_at)
            except StaleData:
                pass
        else:
            setattr(milestone, id_field, None)
            if hasattr(milestone, login_field):
                setattr(milestone, login_field, None)

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(milestone, replicated_dt_field):
        setattr(milestone, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(milestone)
    if commit:
        db.session.commit()

    return milestone


@celery.task(bind=True)
def sync_milestone(self, owner, repo, number, requestor_id=None):
    milestone_url = "/repos/{owner}/{repo}/milestones/{number}".format(
        owner=owner, repo=repo, number=number,
    )
    try:
        resp = fetch_url_from_github(milestone_url, requestor_id=requestor_id)
    except NotFound:
        # add more context
        msg = "Milestone #{number} on {owner}/{repo} not found".format(
            number=number, owner=owner, repo=repo,
        )
        raise NotFound(msg, {
            "type": "milestone",
            "number": number,
            "owner": owner,
            "repo": repo,
        })
    milestone_data = resp.json()
    try:
        milestone = process_user(
            milestone_data, via="api", fetched_at=datetime.now(), commit=True,
        )
    except IntegrityError as exc:
        # multiple workers tried to insert the same milestone simulataneously. Retry!
        self.retry(exc=exc)
    return milestone.number


@celery.task(bind=True)
def sync_page_of_milestones(self, owner, repo, state="all", requestor_id=None,
                            per_page=100, page=1):
    milestone_page_url = (
        "/repos/{owner}/{repo}/milestones?"
        "state={state}&per_page={per_page}&page={page}"
    ).format(
        owner=owner, repo=repo,
        state=state, per_page=per_page, page=page
    )
    resp = fetch_url_from_github(milestone_page_url, requestor_id=requestor_id)
    fetched_at = datetime.now()
    milestone_data_list = resp.json()
    results = []
    repo_id = None
    for milestone_data in milestone_data_list:
        try:
            milestone = process_milestone(
                milestone_data, via="api", fetched_at=fetched_at, commit=True,
                repo_id=repo_id,
            )
            repo_id = repo_id or milestone.repo_id
            results.append(milestone.number)
        except IntegrityError as exc:
            self.retry(exc=exc)
    return results


@celery.task()
def milestones_scanned(owner, repo, requestor_id=None):
    """
    Update the timestamp on the repository object,
    and delete old milestones that weren't updated.
    """
    repo = Repository.get(owner, repo)
    prev_scan_at = repo.milestones_last_scanned_at
    pr.milestones_last_scanned_at = datetime.now()
    db.session.add(repo)

    if prev_scan_at:
        # delete any milestones that were not updated since the previous scan --
        # they have been removed from Github
        query = (
            Milestone.query.filter_by(repo_id=repo.id)
            .filter(Milestone.last_replicated_at < prev_scan_at)
        )
        query.delete()

    # delete the mutex
    lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo)
    Mutex.query.filter_by(name=lock_name).delete()

    db.session.commit()


@celery.task()
def spawn_page_tasks_for_milestones(owner, repo, state="all", requestor_id=None,
                                    per_page=100):
    # acquire lock or fail
    with db.session.begin():
        lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo)
        existing = Mutex.query.get(lock_name)
        if existing:
            return False
        lock = Mutex(name=lock_name, user_id=requestor_id)
        db.session.add(lock)

    milestone_list_url = (
        "/repos/{owner}/{repo}/pulls?"
        "state={state}&per_page={per_page}"
    ).format(
        owner=owner, repo=repo,
        state=state, per_page=per_page,
    )
    resp = fetch_url_from_github(
        milestone_list_url, method="HEAD", requestor_id=requestor_id,
    )
    last_page_url = URLObject(resp.links.get('last', {}).get('url', ""))
    last_page_num = int(last_page_url.query.dict.get('page', 1))
    g = group(
        sync_page_of_milestones.s(
            owner=owner, repo=repo, state=state, requestor_id=requestor_id,
            per_page=per_page, page=page,
        ) for page in xrange(1, last_page_num+1)
    )
    finisher = milestones_scanned.si(
        owner=owner, repo=repo, requestor_id=requestor_id,
    )
    return (g | finisher).delay()
