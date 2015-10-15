import pytest
import json
from datetime import datetime
from webhookdb import create_app, db
from flask.testing import FlaskClient


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

