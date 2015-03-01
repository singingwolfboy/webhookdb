# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from webhookdb import db, celery
from webhookdb.models import User
from webhookdb.exceptions import NotFound, StaleData, MissingData
from sqlalchemy.exc import IntegrityError
from webhookdb.tasks.fetch import fetch_url_from_github


def process_user(user_data, via="webhook", fetched_at=None, commit=True):
    user_id = user_data.get("id")
    if not user_id:
        raise MissingData("no user ID")

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    user = User.query.get(user_id)
    if not user:
        user = User(id=user_id)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if user.last_replicated_at > fetched_at:
        raise StaleData()

    # Most fields have the same name in our model as they do in Github's API.
    # However, some are different. This mapping contains just the differences.
    field_to_model = {
        "public_repos": "public_repos_count",
        "public_gists": "public_gists_count",
        "followers": "followers_count",
        "following": "following_count",
    }

    # update the object
    fields = (
        "login", "site_admin", "name", "company", "blog", "location",
        "email", "hireable", "bio", "public_repos",
        "public_gists", "followers", "following",
    )
    for field in fields:
        if field in user_data:
            mfield = field_to_model.get(field, field)
            setattr(user, mfield, user_data[field])
    dt_fields = ("created_at", "updated_at")
    for field in dt_fields:
        if user_data.get(field):
            dt = parse_date(user_data[field]).replace(tzinfo=None)
            setattr(user, field, dt)

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(user, replicated_dt_field):
        setattr(user, replicated_dt_field, fetched_at)

    # add to DB session, so that it will be committed
    db.session.add(user)
    if commit:
        db.session.commit()

    return user


@celery.task(bind=True, ignore_result=True)
def sync_user(self, username, requestor_id=None):
    user_url = "/users/{username}".format(username=username)

    if requestor_id:
        requestor = User.query.get(int(requestor_id))
        assert requestor
        if requestor.login == username:
            # we can use the API for getting the authenticated user
            user_url = "/user"

    try:
        resp = fetch_url_from_github(user_url, requestor_id=requestor_id)
    except NotFound:
        # add more context
        msg = "User @{username} not found".format(username=username)
        raise NotFound(msg, {
            "type": "user",
            "username": username,
        })
    user_data = resp.json()
    try:
        user = process_user(
            user_data, via="api", fetched_at=datetime.now(), commit=True,
        )
    except IntegrityError as exc:
        # multiple workers tried to insert the same user simulataneously. Retry!
        self.retry(exc=exc)
    return user
