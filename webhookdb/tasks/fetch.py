# coding=utf-8
from __future__ import unicode_literals, print_function

from webhookdb.tasks import celery, github, logger
from webhookdb.exceptions import NotFound, RateLimited
from requests.exceptions import RequestException


@celery.task(bind=True)
def fetch_url_from_github(self, url, as_user=None, requestor_id=None, **kwargs):
    if "method" in kwargs:
        method = kwargs.pop("method")
    else:
        method = "GET"
    if method.upper() == "HEAD":
        kwargs.setdefault("allow_redirects", False)

    username = "anonymous"
    if as_user:
        github.blueprint.config["user"] = as_user
        username = "@{login}".format(login=as_user.login)
    elif requestor_id:
        github.blueprint.config["user_id"] = int(requestor_id)
        username = "user {}".format(requestor_id)

    logger.info("{method} {url} as {username}".format(
        method=method, url=url, username=username,
    ))

    try:
        resp = github.request(method=method, url=url, **kwargs)
    except RateLimited as exc:
        logger.info("rate limited: {url}".format(url=url))
        # if this task is being executed inline, let the exception raise
        # so that Flask's error-handling mechanisms can catch it
        if self.request.is_eager:
            raise
        # otherwise, schedule this task to retry when the rate limit is reset
        else:
            logger.warn("Retrying {url} at {reset}".format(url=url, reset=exc.reset))
            self.retry(exc=exc, eta=exc.reset)

    if resp.status_code == 404:
        logger.info("not found: {url}".format(url=url))
        raise NotFound(url)
    if not resp.ok:
        raise RequestException(resp.text)
    return resp
