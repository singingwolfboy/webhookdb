from . import load
from flask_dance.contrib.github import github


@load.after_request
def attach_ratelimit_headers(response):
    if not getattr(github, "last_response", None):
        return response
    headers = ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")
    for h in headers:
        if h in github.last_response.headers:
            response.headers[h] = github.last_response.headers[h]
    return response
