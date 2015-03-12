# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from celery import group
from urlobject import URLObject
from colour import Color
from webhookdb import db, celery
from webhookdb.models import IssueLabel, Repository, Mutex
from webhookdb.exceptions import NotFound, StaleData, MissingData, DatabaseError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from webhookdb.tasks.fetch import fetch_url_from_github

LOCK_TEMPLATE = "Repository|{owner}/{repo}|labels"


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
        try:
            repo = Repository.get(repo_owner, repo_name)
        except MultipleResultsFound:
            msg = "Repo {owner}/{repo} found multiple times!".format(
                owner=repo_owner, repo=repo_name,
            )
            raise DatabaseError(msg, {
                "type": "label",
                "owner": repo_owner,
                "repo": repo_name,
            })
        if not repo:
            msg = "Repo {owner}/{repo} not loaded in webhookdb".format(
                owner=repo_owner, repo=repo_name,
            )
            raise NotFound(msg, {
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

    # color reference
    if "color" in label_data:
        color_hex = label_data["color"]
        if color_hex:
            label.color = Color("#{hex}".format(hex=color_hex))
        else:
            label.color = None

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(label, replicated_dt_field):
        setattr(label, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(label)
    if commit:
        db.session.commit()

    return label


@celery.task(bind=True)
def sync_label(self, owner, repo, name, requestor_id=None):
    label_url = "/repos/{owner}/{repo}/labels/{name}".format(
        owner=owner, repo=repo, name=name,
    )
    try:
        resp = fetch_url_from_github(label_url, requestor_id=requestor_id)
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
    return label.name


@celery.task(bind=True)
def sync_page_of_labels(self, owner, repo, requestor_id=None,
                        per_page=100, page=1):
    label_page_url = (
        "/repos/{owner}/{repo}/labels?"
        "per_page={per_page}&page={page}"
    ).format(
        owner=owner, repo=repo,
        per_page=per_page, page=page
    )
    resp = fetch_url_from_github(label_page_url, requestor_id=requestor_id)
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
            results.append(label.name)
        except IntegrityError as exc:
            self.retry(exc=exc)
    return results


@celery.task()
def labels_scanned(owner, repo, requestor_id=None):
    """
    Update the timestamp on the repository object,
    and delete old labels that weren't updated.
    """
    repo = Repository.get(owner, repo)
    prev_scan_at = repo.labels_last_scanned_at
    pr.labels_last_scanned_at = datetime.now()
    db.session.add(repo)

    if prev_scan_at:
        # delete any labels that were not updated since the previous scan --
        # they have been removed from Github
        query = (
            Label.query.filter_by(repo_id=repo.id)
            .filter(Label.last_replicated_at < prev_scan_at)
        )
        query.delete()

    # delete the mutex
    lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo)
    Mutex.query.filter_by(name=lock_name).delete()

    db.session.commit()


@celery.task()
def spawn_page_tasks_for_labels(owner, repo, requestor_id=None, per_page=100):
    # acquire lock or fail
    with db.session.begin():
        lock_name = LOCK_TEMPLATE.format(owner=owner, repo=repo)
        existing = Mutex.query.get(lock_name)
        if existing:
            return False
        lock = Mutex(name=lock_name, user_id=requestor_id)
        db.session.add(lock)

    label_list_url = (
        "/repos/{owner}/{repo}/labels?per_page={per_page}"
    ).format(
        owner=owner, repo=repo, per_page=per_page,
    )
    resp = fetch_url_from_github(
        label_list_url, method="HEAD", requestor_id=requestor_id,
    )
    last_page_url = URLObject(resp.links.get('last', {}).get('url', ""))
    last_page_num = int(last_page_url.query.dict.get('page', 1))
    g = group(
        sync_page_of_labels.s(
            owner=owner, repo=repo, requestor_id=requestor_id,
            per_page=per_page, page=page
        ) for page in xrange(1, last_page_num+1)
    )
    finisher = labels_scanned.si(
        owner=owner, repo=repo, requestor_id=requestor_id,
    )
    return (g | finisher).delay()
