# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from urlobject import URLObject
from webhookdb import db, celery
from webhookdb.models import Milestone, Repository, User
from webhookdb.exceptions import NotFound, StaleData, MissingData
from sqlalchemy.exc import IntegrityError
from webhookdb.tasks.fetch import fetch_url_from_github
from webhookdb.tasks.user import process_user


def process_milestone(milestone_data, via="webhook", fetched_at=None, commit=True,
                      repo=None):
    number = milestone_data.get("number")
    if not number:
        raise MissingData("no milestone number")

    if not repo:
        url = milestone_data.get("url")
        if not url:
            raise MissingData("no milestone url")

        # parse repo info from url
        path = URLObject(url).path
        assert path.segments[0] == "repos"
        repo_owner = path.segments[1]
        repo_name = path.segments[2]

        # fetch repo from database
        repo_query = (Repository.query
            .filter(Repository.owner_login == repo_owner)
            .filter(Repository.name == repo_name)
        )
        try:
            repo = repo_query.one()
        except NoResultFound:
            msg = "Repo {owner}/{repo} not loaded in webhookdb".format(
                owner=repo_owner, repo=repo_name,
            )
            raise NotFound(msg, {
                "type": "milestone",
                "owner": owner,
                "repo": repo,
            })
        except MultipleResultsFound:
            msg = "Repo {owner}/{repo} found multiple times!".format(
                owner=owner, repo=repo,
            )
            raise DatabaseError(msg, {
                "type": "milestone",
                "owner": owner,
                "repo": repo,
            })

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    milestone = Milestone.query.get((repo.id, number))
    if not milestone:
        milestone = Milestone(repo_id=repo.id, number=number)

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
            setattr(pr, id_field, user_data["id"])
            if hasattr(pr, login_field):
                setattr(pr, login_field, user_data["login"])
            try:
                process_user(user_data, via=via, fetched_at=fetched_at)
            except StaleData:
                pass
        else:
            setattr(pr, id_field, None)
            if hasattr(pr, login_field):
                setattr(pr, login_field, None)

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(milestone, replicated_dt_field):
        setattr(milestone, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(milestone)
    if commit:
        db.session.commit()

    return milestone


@celery.task(bind=True, ignore_result=True)
def sync_milestone(self, owner, repo, number):
    milestone_url = "/repos/{owner}/{repo}/milestones/{number}".format(
        owner=owner, repo=repo, number=number,
    )
    try:
        resp = fetch_url_from_github(milestone_url)
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
    return milestone


@celery.task(bind=True, ignore_result=True)
def sync_page_of_milestones(self, owner, repo, state="all", per_page=100, page=1):
    milestone_page_url = (
        "/repos/{owner}/{repo}/milestones?"
        "state={state}&per_page={per_page}&page={page}"
    ).format(
        owner=owner, repo=repo,
        state=state, per_page=per_page, page=page
    )
    resp = fetch_url_from_github(milestone_page_url)
    fetched_at = datetime.now()
    milestone_data_list = resp.json()
    results = []
    repo = None
    for milestone_data in milestone_data_list:
        try:
            milestone = process_milestone(
                milestone_data, via="api", fetched_at=fetched_at, commit=True,
                repo=repo,
            )
            repo = repo or milestone.repo
            results.append(milestone)
        except IntegrityError as exc:
            self.retry(exc=exc)
    return results


@celery.task(ignore_result=True)
def spawn_page_tasks_for_milestones(owner, repo, state="all", per_page=100):
    milestone_list_url = (
        "/repos/{owner}/{repo}/pulls?"
        "state={state}&per_page={per_page}"
    ).format(
        owner=owner, repo=repo,
        state=state, per_page=per_page,
    )
    resp = fetch_url_from_github(milestone_list_url, method="HEAD")
    last_page_url = URLObject(resp.links.get('last', {}).get('url', ""))
    last_page_num = int(last_page_url.query.dict.get('page', 1))
    g = group(
        sync_page_of_milestones.s(
            owner=owner, repo=repo, state=state, per_page=per_page, page=page
        ) for page in xrange(1, last_page_num+1)
    )
    return g.delay()
