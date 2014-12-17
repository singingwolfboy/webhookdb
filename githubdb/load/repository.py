# coding=utf-8
from __future__ import unicode_literals, print_function

from datetime import datetime
from flask import jsonify
from flask_dance.contrib.github import github
import bugsnag
import requests
from . import load
from githubdb import db
from githubdb.replication.repository import create_or_update_repository
from githubdb.exceptions import StaleData


@load.route('/repos/<owner>/<repo>', methods=["POST"])
def repository(owner, repo):
    bugsnag_ctx = {"owner": owner, "repo": repo}
    bugsnag.configure_request(meta_data=bugsnag_ctx)
    repo_url = "/repos/{owner}/{repo}".format(owner=owner, repo=repo)
    repo_resp = github.get(repo_url)
    if repo_resp.status_code == 404:
        msg = "Repo {owner}/{repo} not found".format(owner=owner, repo=repo)
        resp = jsonify({"message": msg})
        resp.status_code = 502
        return resp
    if not repo_resp.ok:
        raise requests.exceptions.RequestException(repo_resp.text)
    repo_obj = repo_resp.json()
    bugsnag_ctx["obj"] = repo_obj
    bugsnag.configure_request(meta_data=bugsnag_ctx)
    try:
        create_or_update_repository(repo_obj, via="api")
    except StaleData:
        return jsonify({"message": "stale data"})
    db.session.commit()
    return jsonify({"message": "success"})
