# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from urlobject import URLObject
from webhookdb import db, celery
from webhookdb.models import IssueLabel, Repository
from webhookdb.exceptions import NotFound, StaleData, MissingData, DatabaseError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from webhookdb.tasks.fetch import fetch_url_from_github


def process_label(label_data, via="webhook", fetched_at=None, commit=True,
                  repo_id=None):
    name = label_data.get("name")
    if not name:
        raise MissingData("no label name")

    if not repo_id:
        url = label_data.get("url")
        if not url:
            raise MissingData("no label url")

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
                "type": "label",
                "owner": repo_owner,
                "repo": repo_name,
            })
        except MultipleResultsFound:
            msg = "Repo {owner}/{repo} found multiple times!".format(
                owner=repo_owner, repo=repo_name,
            )
            raise DatabaseError(msg, {
                "type": "label",
                "owner": repo_owner,
                "repo": repo_name,
            })
        repo_id = repo.id

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    label = IssueLabel.query.get((repo_id, name))
    if not label:
        label = IssueLabel(repo_id=repo_id, name=name)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if label.last_replicated_at > fetched_at:
        raise StaleData()

    # update the object
    fields = (
        "color",
    )
    for field in fields:
        if field in label_data:
            setattr(milestone, field, label_data[field])

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(label, replicated_dt_field):
        setattr(label, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(label)
    if commit:
        db.session.commit()

    return label


@celery.task(bind=True, ignore_result=True)
def sync_label(self, owner, repo, name):
    label_url = "/repos/{owner}/{repo}/labels/{name}".format(
        owner=owner, repo=repo, name=name,
    )
    try:
        resp = fetch_url_from_github(label_url)
    except NotFound:
        # add more context
        msg = "Label {name} on {owner}/{repo} not found".format(
            name=name, owner=owner, repo=repo,
        )
        raise NotFound(msg, {
            "type": "label",
            "name": name,
            "owner": owner,
            "repo": repo,
        })
    label_data = resp.json()
    try:
        label = process_label(
            label_data, via="api", fetched_at=datetime.now(), commit=True,
        )
    except IntegrityError as exc:
        # multiple workers tried to insert the same label simulataneously. Retry!
        self.retry(exc=exc)
    return label


@celery.task(bind=True, ignore_result=True)
def sync_page_of_labels(self, owner, repo, per_page=100, page=1):
    label_page_url = (
        "/repos/{owner}/{repo}/labels?"
        "per_page={per_page}&page={page}"
    ).format(
        owner=owner, repo=repo,
        per_page=per_page, page=page
    )
    resp = fetch_url_from_github(label_page_url)
    fetched_at = datetime.now()
    label_data_list = resp.json()
    results = []
    repo_id = None
    for label_data in label_data_list:
        try:
            label = process_label(
                label_data, via="api", fetched_at=fetched_at, commit=True,
                repo_id=repo_id,
            )
            repo_id = repo_id or label.repo_id
            results.append(label)
        except IntegrityError as exc:
            self.retry(exc=exc)
    return results


@celery.task(ignore_result=True)
def spawn_page_tasks_for_labels(owner, repo, per_page=100):
    label_list_url = (
        "/repos/{owner}/{repo}/labels?per_page={per_page}"
    ).format(
        owner=owner, repo=repo, per_page=per_page,
    )
    resp = fetch_url_from_github(label_list_url, method="HEAD")
    last_page_url = URLObject(resp.links.get('last', {}).get('url', ""))
    last_page_num = int(last_page_url.query.dict.get('page', 1))
    g = group(
        sync_page_of_labels.s(
            owner=owner, repo=repo, per_page=per_page, page=page
        ) for page in xrange(1, last_page_num+1)
    )
    return g.delay()
