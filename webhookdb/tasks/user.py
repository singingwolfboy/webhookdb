# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from webhookdb import db, celery
from webhookdb.process import process_user
from webhookdb.models import User
from webhookdb.exceptions import NotFound, StaleData, MissingData
from sqlalchemy.exc import IntegrityError
from webhookdb.tasks.fetch import fetch_url_from_github
from webhookdb.tasks.repository import spawn_page_tasks_for_user_repositories


@celery.task(bind=True)
def sync_user(self, username, children=False, requestor_id=None):
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

    if children:
        spawn_page_tasks_for_user_repositories.delay(
            username, children=children, requestor_id=requestor_id,
        )

    return user.id
