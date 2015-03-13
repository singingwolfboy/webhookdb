# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from webhookdb import db
from webhookdb.models import PullRequestFile
from webhookdb.exceptions import MissingData, StaleData, NothingToDo


def process_pull_request_file(
            prf_data, via="webhook", fetched_at=None, commit=True,
            pull_request_id=None,
    ):
    sha = prf_data.get("sha")
    if not sha:
        # This indicates a moved file: for example, moving /tmp/a.txt
        # to /tmp/b.txt. I don't know why Github marks moved files this
        # way, but it's not actually an error.
        raise NothingToDo("no pull request file SHA")

    pr_id = pull_request_id
    if not pr_id:
        raise MissingData("no pull_request_id", obj=prf_data)

    # fetch the object from the database,
    # or create it if it doesn't exist in the DB
    prf = PullRequestFile.query.get((pr_id, sha))
    if not prf:
        prf = PullRequestFile(sha=sha, pull_request_id=pr_id)

    # should we update the object?
    fetched_at = fetched_at or datetime.now()
    if prf.last_replicated_at > fetched_at:
        raise StaleData()

    # update the object
    fields = (
        "filename", "status", "additions", "deletions", "changes", "patch",
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
