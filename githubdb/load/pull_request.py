# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from flask import request, jsonify
from flask_dance.contrib.github import github
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
import bugsnag
import requests
from . import load
from githubdb import db
from githubdb.models import Repository, PullRequest, PullRequestFile
from githubdb.utils import paginated_get
from githubdb.replication.pull_request import (
    create_or_update_pull_request, create_or_update_pull_request_file
)
from githubdb.exceptions import StaleData, MissingData


@load.route('/repos/<owner>/<repo>/pulls', methods=["POST"])
def pull_requests(owner, repo):
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
def pull_request(owner, repo, number):
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


@load.route('/repos/<owner>/<repo>/pulls/<int:number>/files', methods=["POST"])
def pull_request_files(owner, repo, number):
    bugsnag_ctx = {"owner": owner, "repo": repo, "number": number}
    bugsnag.configure_request(meta_data=bugsnag_ctx)

    # get pull request from DB
    pr_query = (
        PullRequest.query.join(Repository, PullRequest.base_repo_id == Repository.id)
        .filter(Repository.owner_login == owner)
        .filter(Repository.name == repo)
        .filter(PullRequest.number == number)
    )
    try:
        pr = pr_query.one()
    except NoResultFound:
        msg = "PR {owner}/{repo}#{number} not loaded in githubdb".format(
            owner=owner, repo=repo, number=number,
        )
        resp = jsonify({"error": msg})
        resp.status_code = 404
        return resp
    except MultipleResultsFound:
        msg = "PR {owner}/{repo}#{number} found multiple times!".format(
            owner=owner, repo=repo, number=number,
        )
        resp = jsonify({"error": msg})
        resp.status_code = 500
        return resp

    # delete all previous pull request files associated with this PR
    PullRequestFile.query.filter_by(pull_request_id=pr.id).delete()

    missing_data = set()

    # re-populate DB from Github API
    prfs_url = "/repos/{owner}/{repo}/pulls/{number}/files".format(
        owner=owner, repo=repo, number=number,
    )
    prfs = paginated_get(prfs_url, session=github)
    for prf_obj in prfs:
        prf_obj["pull_request_id"] = pr.id
        bugsnag_ctx["obj"] = prf_obj
        bugsnag.configure_request(meta_data=bugsnag_ctx)
        try:
            create_or_update_pull_request_file(prf_obj, via="api")
        except StaleData:
            pass
        except MissingData:
            # This SHOULDN'T HAPPEN, but it does. Sweep it under the rug.
            missing_data.add(prf_obj.get("filename"))

    # deletes and additions don't take effect until we commit
    db.session.commit()

    if missing_data:
        return jsonify({
            "message": "success with API issues",
            "failures": list(missing_data),
        })
    else:
        return jsonify({"message": "success"})
