# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import jsonify
from flask_dance.contrib.github import github
import bugsnag
import requests
from . import load
from githubdb import db
from githubdb.utils import paginated_get
from githubdb.replication.pull_request import create_or_update_pull_request
from githubdb.exceptions import StaleData

@load.route('/repos/<owner>/<repo>/pulls', methods=["POST"])
def load_pulls(owner, repo):
    bugsnag_ctx = {"owner": owner, "repo": repo}
    bugsnag.configure_request(meta_data=bugsnag_ctx)
    pulls_url = "/repos/{owner}/{repo}/pulls".format(owner=owner, repo=repo)
    pulls = paginated_get(pulls_url, session=github)
    for pull_obj in pulls:
        bugsnag_ctx["obj"] = pull_obj
        bugsnag.configure_request(meta_data=bugsnag_ctx)
        try:
            create_or_update_pull_request(pull_obj, via="api")
        except StaleData:
            pass
    db.session.commit()
    return jsonify({"message": "success"})


@load.route('/repos/<owner>/<repo>/pulls/<int:number>', methods=["POST"])
def load_pull(owner, repo, number):
    bugsnag_ctx = {"owner": owner, "repo": repo, "number": number}
    bugsnag.configure_request(meta_data=bugsnag_ctx)
    pr_url = "/repos/{owner}/{repo}/pulls/{number}".format(
        owner=owner, repo=repo, number=number,
    )
    pr_resp = github.get(pr_url)
    if not pr_resp.ok:
        raise requests.exceptions.RequestsException(pr_resp.text)
    pr_obj = pr_resp.json()
    bugsnag_ctx["obj"] = pr_obj
    bugsnag.configure_request(meta_data=bugsnag_ctx)
    try:
        create_or_update_pull_request(pr_obj, via="api")
    except StaleData:
        return jsonify({"message": "stale data"})
    db.session.commit()
    return jsonify({"message": "success"})

