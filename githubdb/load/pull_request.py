# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from flask import request, jsonify
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
    state = request.args.get("state", "open")
    pulls_url = "/repos/{owner}/{repo}/pulls?state={state}".format(
        owner=owner, repo=repo, state=state,
    )
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
    if pr_resp.status_code == 404:
        msg = "PR {owner}/{repo}#{number} not found".format(
            owner=owner, repo=repo, number=number,
        )
        resp = jsonify({"message": msg})
        resp.status_code = 502
        return resp
    if "X-RateLimit-Remaining" in pr_resp.headers:
        ratelimit_remaining = int(pr_resp.headers["X-RateLimit-Remaining"])
        if pr_resp.status_code == 403 and ratelimit_remaining < 1:
            ratelimit_reset_epoch = int(pr_resp.headers["X-RateLimit-Reset"])
            ratelimit_reset = datetime.fromtimestamp(ratelimit_reset_epoch)
            wait_time = ratelimit_reset - datetime.now()
            wait_msg = "Try again in {sec} seconds.".format(
                sec=int(wait_time.total_seconds())
            )
            msg = "{upstream} {wait}".format(
                upstream=pr_resp.json()["message"],
                wait=wait_msg,
            )
            resp = jsonify({"error": msg})
            resp.status_code = 503
            return resp
    if not pr_resp.ok:
        raise requests.exceptions.RequestException(pr_resp.text)
    pr_obj = pr_resp.json()
    bugsnag_ctx["obj"] = pr_obj
    bugsnag.configure_request(meta_data=bugsnag_ctx)
    try:
        create_or_update_pull_request(pr_obj, via="api")
    except StaleData:
        return jsonify({"message": "stale data"})
    db.session.commit()
    return jsonify({"message": "success"})
