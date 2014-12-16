# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from iso8601 import parse_date
from flask import request, jsonify
import bugsnag
from . import replication
from githubdb import db
from githubdb.models import User, Repository, PullRequest
from githubdb.exceptions import MissingInfo, StaleInfo


def create_or_update_user(user_obj, via="webhook"):
    user_id = user_obj.get("id")
    if not user_id:
        raise MissingInfo("no user ID")

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    user = User.get(pr_id)
    if not user:
        user = User(id=user_id)

    # should we update the object?
    if user.last_replicated_at > datetime.now():
        raise StaleInfo()

    # update the object
    fields = (
        "login", "site_admin", "name", "company", "blog", "location",
        "email", "hireable", "bio", "public_repos",
        "public_gists", "followers", "following",
    )
    for field in fields:
        setattr(user, field, user_obj[field])
    dt_fields = ("created_at", "updated_at")
    for field in dt_fields:
        dt = parse_date(user_obj[field]).replace(tzinfo=None)
        setattr(user, field, dt)

    # update replication timestamp
    replicated_dt_field = "last_replicated_via_{}_at".format(via)
    if hasattr(user, replicated_dt_field):
        setattr(user, replicated_dt_field, datetime.now())

    # add to DB session, so that it will be committed
    db.session.add(user)

    return user
