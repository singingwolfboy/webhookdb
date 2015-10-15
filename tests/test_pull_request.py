import pytest
from datetime import datetime
from webhookdb.models import (
    User, Repository, UserRepoAssociation, RepositoryHook, Milestone,
    PullRequest, PullRequestFile, IssueLabel, Issue
)

pytestmark = pytest.mark.usefixtures("github_betamax")


def test_happy_path(app):
    # make some models to use for generating test data, but don't save them
    octocat = User(
        id=1,
        login="octocat",
        site_admin=False,
        name="monalisa octocat",
        company="GitHub",
        blog="https://github.com/blog",
        email="octocat@github.com",
        bio="There once was...",
        public_repos_count=2,
        public_gists_count=1,
        followers_count=20,
        following_count=0,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    repo = Repository(
        id=1296269,
        name="Hello-World",
        owner=octocat,
        owner_login=octocat.login,
        private=False,
        fork=False,
        description="This your first repo!",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        size=7654321,
        stargazers_count=100,
        watchers_count=80,
        language="Python",
        has_issues=True,
        has_downloads=True,
        has_wiki=True,
        has_pages=False,
        forks_count=10,
        open_issues_count=4,
        default_branch="master",
    )
    unoju = User(
        id=777449,
        login="unoju",
        site_admin=False,
    )
    unoju_repo = Repository(
        id=1724195,
        name="Hello-World",
        owner=unoju,
        owner_login=unoju.login,
        private=False,
        fork=True,
    )
    pr = PullRequest(
        id=140900,
        number=1,
        state="open",
        locked=False,
        user=unoju,
        user_login=unoju.login,
        title="Edited README via GitHub",
        body="Please pull these awesome changes",
        base_repo=repo,
        base_ref="master",
        head_repo=unoju_repo,
        head_ref="patch-1",
        merged=False,
        mergeable=True,
        mergeable_state="clean",
        comments_count=4,
        additions=2,
        deletions=4,
        changed_files=1,
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
        octo = User.query.get(1)
        assert octo.login == "octocat"
        user2 = User.query.get(777449)
        assert user2.login == "unoju"

        assert Repository.query.count() == 2

        assert PullRequest.query.count() == 1
        pr = PullRequest.query.get(140900)
        assert pr.title == "Edited README via GitHub"
        assert pr.body == "Please pull these awesome changes"
        assert pr.user == user2

