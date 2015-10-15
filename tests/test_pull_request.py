import pytest
from datetime import datetime
from webhookdb.models import (
    User, Repository, UserRepoAssociation, RepositoryHook, Milestone,
    PullRequest, PullRequestFile, IssueLabel, Issue
)

pytestmark = pytest.mark.usefixtures("github_betamax")


def test_happy_path(app, user_factory, repo_factory, pull_request_factory):
    # make some models to use for generating test data, but don't save them
    octocat = user_factory.build(login="octocat")
    repo = repo_factory.build(name="Hello-World", owner=octocat, fork=False)
    unoju = user_factory.build(login="unoju")
    repo2 = repo_factory.build(name="Hello-World", owner=unoju, fork=True)
    pr = pull_request_factory.build(
        base_repo=repo, head_repo=repo2, number=1, user=unoju,
        title="Edited README via GitHub",
        body="Please pull these awesome changes",
    )

    # double-check that database is empty
    with app.test_request_context('/'):
        assert User.query.count() == 0
        assert Repository.query.count() == 0
        assert PullRequest.query.count() == 0

    # make a client and simulate a webhook notification from GitHub
    client = app.test_client()
    response = client.pull_request_webhook(sender=unoju, pull_request=pr)
    assert response.status_code == 200

    # check that the database is populated
    with app.test_request_context('/'):
        assert User.query.count() == 2
        assert User.query.filter_by(login="octocat").one()
        assert User.query.filter_by(login="unoju").one()

        assert Repository.query.count() == 2
        repo1 = Repository.query.filter_by(owner_login="octocat").one()
        assert repo1.name == "Hello-World"
        assert not repo1.fork
        repo2 = Repository.query.filter_by(owner_login="unoju").one()
        assert repo2.name == "Hello-World"
        assert repo2.fork

        assert PullRequest.query.count() == 1
        pr = PullRequest.query.first()
        assert pr.title == "Edited README via GitHub"
        assert pr.body == "Please pull these awesome changes"
        assert pr.user.login == "unoju"

