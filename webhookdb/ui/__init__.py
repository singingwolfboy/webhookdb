# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import Blueprint, request, render_template, jsonify, url_for
from flask_dance.contrib.github import github
import bugsnag

ui = Blueprint('ui', __name__)


@ui.route("/")
def index():
    """
    Just to verify that things are working
    """
    return render_template("main.html")


@ui.route("/install", methods=("GET", "POST"))
def install():
    if request.method == "GET":
        return render_template("install.html")
    repo = request.form.get("repo", "")
    if not repo:
        resp = jsonify({"error": "missing repo param"})
        resp.status_code = 400
        return resp

    secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "http") == "https"
    hook_url = "/repos/{repo}/hooks".format(repo=repo)
    for event in ("pull_request", "issue"):
        api_url = url_for(
            "replication.{endpoint}".format(endpoint=event),
            _external=True,
            _scheme="https" if secure else "http",
        )
        body = {
            "name": "web",
            "events": [event],
            "config": {
                "url": api_url,
                "content_type": "json",
            }
        }
        bugsnag_context = {"repo": repo, "body": body}
        bugsnag.configure_request(meta_data=bugsnag_context)

        hook_resp = github.post(hook_url, json=body)
        if not hook_resp.ok:
            error_obj = hook_resp.json()
            resp = jsonify({"error": error_obj["message"]})
            resp.status_code = 503
            return resp

    return jsonify({"message": "success"})
