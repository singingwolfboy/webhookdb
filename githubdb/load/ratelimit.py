# coding=utf-8
from __future__ import unicode_literals, print_function

import sys
from datetime import datetime
from . import load
from flask import jsonify
from flask_dance.contrib.github import github
from githubdb.exceptions import RateLimited


@load.after_request
def attach_ratelimit_headers(response, gh_response=None):
    gh_response = gh_response or getattr(github, "last_response", None)
    if not gh_response:
        print("no gh_response", file=sys.stderr)
        return response
    headers = ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")
    for h in headers:
        if h in gh_response:
            print(h + " in gh_response", file=sys.stderr)
            response.headers[h] = gh_response.headers[h]
    return response


@load.app_errorhandler(RateLimited)
def request_rate_limited(error):
    gh_resp = error.response
    try:
        upstream_msg = gh_resp.json()["message"]
    except Exception:
        upstream_msg = "Rate limited."

    ratelimit_reset_epoch = int(gh_resp.headers["X-RateLimit-Reset"])
    ratelimit_reset = datetime.fromtimestamp(ratelimit_reset_epoch)
    wait_time = ratelimit_reset - datetime.now()
    sec = int(wait_time.total_seconds())
    wait_msg = "Try again in {sec} {unit}.".format(
        sec=sec, unit="second" if sec == 1 else "seconds",
    )

    msg = "{upstream} {wait}".format(
        upstream=upstream_msg,
        wait=wait_msg,
    )
    resp = jsonify({"error": msg})
    resp.status_code = 503
    print(gh_resp.headers, file=sys.stderr)
    return attach_ratelimit_headers(resp, gh_resp)
