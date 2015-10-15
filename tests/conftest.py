import pytest
import betamax
import os
import json
from datetime import datetime
from webhookdb import create_app, db
from webhookdb.oauth import GithubSession
from webhookdb.tasks.fetch import github
from flask.testing import FlaskClient
from factories import (
    UserFactory, RepoFactory, MilestoneFactory, PullRequestFactory
)
from pytest_factoryboy import register


register(UserFactory)
register(RepoFactory)
register(MilestoneFactory)
register(PullRequestFactory)


record_mode = 'none' if os.environ.get("CI") else 'once'

with betamax.Betamax.configure() as config:
    config.cassette_library_dir = 'tests/cassettes'
    config.default_cassette_options['record_mode'] = record_mode


class GitHubJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            stripped = o.replace(microsecond=0)
            return stripped.isoformat() + "Z"
        if hasattr(o, "github_json"):
            return o.github_json
        return json.JSONEncoder.default(self, o)


class WebhookExtendedClient(FlaskClient):
    def pull_request_webhook(
            self, path="/replication", base_url="https://webhookdb.herokuapp.com/",
            pull_request=None, action="opened", sender=None,
            *args, **kwargs
        ):
        if not pull_request:
            raise ValueError("pull_request required")
        if not sender:
            raise ValueError("sender required")
        data = {
            "action": action,
            "number": pull_request.number,
            "pull_request": pull_request.github_json,
            "organization": pull_request.user.github_json,
            "sender": sender.github_json,
        }
        headers = {
            "User-Agent": "GitHub-Hookshot/044aadd",
            "Content-Type": "application/json",
            "X-Github-Event": "pull_request",
        }
        return self.post(
            base_url=base_url,
            path=path,
            headers=headers,
            data=json.dumps(data, cls=GitHubJSONEncoder),
        )


@pytest.fixture
def app(request):
    """
    Return a WebhookDB Flask app, set up in testing mode.
    """
    _app = create_app(config="test")
    _app.test_client_class = WebhookExtendedClient
    db.create_all(app=_app)
    def teardown():
        db.drop_all(app=_app)
    request.addfinalizer(teardown)
    return _app


@pytest.fixture
def github_betamax(request):
    """
    Copied from Betamax's `betamax_session` fixture, but using the Flask-Dance
    `github` session that is used in the Celery tasks.
    """
    cassette_name = ''

    if request.module is not None:
        cassette_name += request.module.__name__ + '.'

    if request.cls is not None:
        cassette_name += request.cls.__name__ + '.'

    cassette_name += request.function.__name__

    recorder = betamax.Betamax(github)
    recorder.use_cassette(cassette_name)
    recorder.start()
    request.addfinalizer(recorder.stop)

    return github
