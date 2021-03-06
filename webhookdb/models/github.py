# coding=utf-8
from __future__ import unicode_literals
from datetime import datetime
from sqlalchemy import func, and_
from sqlalchemy.orm import backref
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy_utils import JSONType, ColorType, ScalarListType
from flask_login import UserMixin
from webhookdb import db


class ReplicationTimestampMixin(object):
    """
    This allows us to keep track of how stale our local data is.
    """
    last_replicated_via_webhook_at = db.Column(db.DateTime)
    last_replicated_via_api_at = db.Column(db.DateTime)

    @hybrid_property
    def last_replicated_at(self):
        """
        Return whichever value is greater. If neither is set,
        return min date (for type consistency).
        """
        options = [
            self.last_replicated_via_webhook_at,
            self.last_replicated_via_api_at,
            datetime.min,
        ]
        return max(dt for dt in options if dt)

    @last_replicated_at.expression
    def last_replicated_at(cls):
        webhook = cls.last_replicated_via_webhook_at
        api = cls.last_replicated_via_api_at
        return func.greatest(webhook, api, datetime.min)


class User(db.Model, ReplicationTimestampMixin, UserMixin):
    __tablename__ = "github_user"

    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(256))
    site_admin = db.Column(db.Boolean)
    name = db.Column(db.String(256))
    company = db.Column(db.String(256))
    blog = db.Column(db.String(256))
    location = db.Column(db.String(256))
    email = db.Column(db.String(256))
    hireable = db.Column(db.Boolean)
    bio = db.Column(db.Text)
    public_repos_count = db.Column(db.Integer)
    public_gists_count = db.Column(db.Integer)
    followers_count = db.Column(db.Integer)
    following_count = db.Column(db.Integer)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)

    # not on github -- used for keeping track of scanning children
    repos_last_scanned_at = db.Column(db.DateTime)

    @classmethod
    def get(cls, username):
        """
        Fetch a user object by username.

        If the user doesn't exist in the webhookdb database, return None.
        This can still raise a MultipleResultsFound exception.
        """
        query = cls.query.filter_by(login=username)
        try:
            return query.one()
        except NoResultFound:
            return None

    def __unicode__(self):
        return "@{login}".format(login=self.login or "<unknown>")

    def __str__(self):
        return unicode(self).encode('utf-8')

    @property
    def github_json(self):
        url = "https://api.github.com/users/{login}".format(login=self.login)
        html_url = "https://github.com/{login}".format(login=self.login)
        avatar_url = "https://avatars.githubusercontent.com/u/{id}".format(
            id=self.id,
        )
        serialized = {
            "login": self.login,
            "id": self.id,
            "avatar_url": avatar_url,
            "gravatar_id": "",
            "url": url,
            "html_url": html_url,
            "followers_url": url + "/followers",
            "following_url": url + "/following{/other_user}",
            "gists_url": url + "/gists{/gist_id}",
            "starred_url": url + "/starred{/owner}{/repo}",
            "subscriptions_url": url + "/subscriptions",
            "organizations_url": url + "/orgs",
            "repos_url": url + "/repos",
            "events_url": url + "/events{/privacy}",
            "received_events_url": url + "/received_events",
            "type": "User",
            "site_admin": self.site_admin,
        }
        return serialized


class Repository(db.Model, ReplicationTimestampMixin):
    __tablename__ = "github_repository"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256))
    owner_id = db.Column(db.Integer, index=True)
    owner_login = db.Column(db.String(256))
    owner = db.relationship(
        User,
        primaryjoin=(owner_id == User.id),
        foreign_keys=owner_id,
        remote_side=User.id,
        backref="owned_repos",
    )
    organization_id = db.Column(db.Integer, index=True)
    organization_login = db.Column(db.String(256))
    organization = db.relationship(
        User,
        primaryjoin=(organization_id == User.id),
        foreign_keys=organization_id,
        remote_side=User.id,
    )
    private = db.Column(db.Boolean)
    description = db.Column(db.String(1024))
    fork = db.Column(db.Boolean)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
    pushed_at = db.Column(db.DateTime)
    homepage = db.Column(db.String(256))
    size = db.Column(db.Integer)
    stargazers_count = db.Column(db.Integer)
    watchers_count = db.Column(db.Integer)
    language = db.Column(db.String(256))
    has_issues = db.Column(db.Boolean)
    has_downloads = db.Column(db.Boolean)
    has_wiki = db.Column(db.Boolean)
    has_pages = db.Column(db.Boolean)
    forks_count = db.Column(db.Integer)
    open_issues_count = db.Column(db.Integer)
    default_branch = db.Column(db.String(256), default="master")

    # not on github -- used for keeping track of scanning children
    hooks_last_scanned_at = db.Column(db.DateTime)
    issues_last_scanned_at = db.Column(db.DateTime)
    pull_requests_last_scanned_at = db.Column(db.DateTime)
    labels_last_scanned_at = db.Column(db.DateTime)
    milestones_last_scanned_at = db.Column(db.DateTime)

    # just for finding all the admins on a repo
    admin_assocs = db.relationship(
        lambda: UserRepoAssociation,
        primaryjoin=lambda: and_(
            Repository.id == UserRepoAssociation.repo_id,
            UserRepoAssociation.can_admin == True,
        ),
        foreign_keys=id,
        uselist=True,
    )
    admins = association_proxy("admin_assocs", "user")

    @hybrid_property
    def full_name(self):
        return "{owner_login}/{name}".format(
            owner_login=self.owner_login or "<unknown>",
            name=self.name or "<unknown>",
        )

    @full_name.expression
    def full_name(cls):
        name = func.coalesce(cls.name, "<unknown>")
        owner_login = func.coalesce(cls.owner_login, "<unknown>")
        return func.concat(name, '/', owner_login)

    @classmethod
    def get(cls, owner, name):
        """
        Fetch a single repository given two things:
        * the username of the repo's owner, as a string
        * the name of the repo, as a string

        If the repository doesn't exist in the webhookdb database, return None.
        This can still raise a MultipleResultsFound exception.
        """
        query = cls.query.filter_by(owner_login=owner, name=name)
        try:
            return query.one()
        except NoResultFound:
            return None

    def __unicode__(self):
        return self.full_name

    def __str__(self):
        return unicode(self).encode('utf-8')

    @property
    def github_json(self):
        url = "https://api.github.com/repos/{owner}/{repo}".format(
            owner=self.owner_login,
            repo=self.name,
        )
        html_url = "https://github.com/{owner}/{repo}".format(
            owner=self.owner_login,
            repo=self.name,
        )
        git_url = "git://github.com/{owner}/{repo}.git".format(
            owner=self.owner_login,
            repo=self.name,
        )
        ssh_url = "git@github.com:{owner}/{repo}.git".format(
            owner=self.owner_login,
            repo=self.name,
        )
        svn_url = "https://github.com/{owner}/{repo}".format(
            owner=self.owner_login,
            repo=self.name,
        )
        clone_url = svn_url + ".git"
        serialized = {
            "id": self.id,
            "name": self.name,
            "full_name": self.full_name,
            "owner": self.owner.github_json,
            "private": self.private,
            "html_url": html_url,
            "description": self.description,
            "fork": self.fork,
            "url": url,
            "forks_url": url + "/forks",
            "keys_url": url + "/keys{/key_id}",
            "collaborators_url": url + "/collaborators{/collaborator}",
            "teams_url": url + "/teams",
            "hooks_url": url + "/hooks",
            "issue_events_url": url + "/issues/events{/number}",
            "events_url": url + "/events",
            "assignees_url": url + "/assignees{/user}",
            "branches_url": url + "/branches{/branch}",
            "tags_url": url + "/tags",
            "blobs_url": url + "/git/blobs{/sha}",
            "git_tags_url": url + "/git/tags{/sha}",
            "git_refs_url": url + "/git/refs{/sha}",
            "trees_url": url + "/git/trees{/sha}",
            "statuses_url": url + "/statuses/{sha}",
            "languages_url": url + "/languages",
            "stargazers_url": url + "/stargazers",
            "contributors_url": url + "/contributors",
            "subscribers_url": url + "/subscribers",
            "subscription_url": url + "/subscription",
            "commits_url": url + "/commits{/sha}",
            "git_commits_url": url + "/git/commits{/sha}",
            "comments_url": url + "/comments{/number}",
            "issue_comment_url": url + "/issues/comments{/number}",
            "contents_url": url + "/contents/{+path}",
            "compare_url": url + "/compare/{base}...{head}",
            "merges_url": url + "/merges",
            "archive_url": url + "/{archive_format}{/ref}",
            "downloads_url": url +"/downloads",
            "issues_url": url + "/issues{/number}",
            "pulls_url": url + "/pulls{/number}",
            "milestones_url": url + "/milestones{/number}",
            "notifications_url": url + "/notifications{?since,all,participating}",
            "labels_url": url + "/labels{/name}",
            "releases_url": url + "/releases{/id}",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pushed_at": self.pushed_at,
            "git_url": git_url,
            "ssh_url": ssh_url,
            "clone_url": clone_url,
            "svn_url": svn_url,
            "homepage": self.homepage,
            "size": self.size,
            "stargazers_count": self.stargazers_count,
            "watchers_count": self.watchers_count,
            "language": self.language,
            "has_issues": self.has_issues,
            "has_downloads": self.has_downloads,
            "has_wiki": self.has_wiki,
            "has_pages": self.has_pages,
            "forks_count": self.forks_count,
            "mirror_url": None,  # FIXME
            "open_issues_count": self.open_issues_count,
            "forks": self.forks_count,
            "open_issues": self.open_issues_count,
            "watchers": self.watchers_count,
            "default_branch": self.default_branch,
        }
        return serialized


class UserRepoAssociation(db.Model, ReplicationTimestampMixin):
    __tablename__ = "github_user_repository_association"

    user_id = db.Column(db.Integer, primary_key=True)
    user = db.relationship(
        User,
        primaryjoin=(user_id == User.id),
        foreign_keys=user_id,
        backref=backref("user_repo_assocs", cascade="all, delete-orphan"),
    )
    repo_id = db.Column(db.Integer, primary_key=True)
    repo = db.relationship(
        Repository,
        primaryjoin=(repo_id == Repository.id),
        foreign_keys=repo_id,
        backref=backref("user_repo_assocs", cascade="all, delete-orphan"),
    )

    # permissions
    can_pull = db.Column(db.Boolean, default=True)
    can_push = db.Column(db.Boolean, default=False)
    can_admin = db.Column(db.Boolean, default=False)


class RepositoryHook(db.Model, ReplicationTimestampMixin):
    __tablename__ = "github_repository_hook"

    repo_id = db.Column(db.Integer, index=True)
    repo = db.relationship(
        Repository,
        primaryjoin=(repo_id == Repository.id),
        foreign_keys=repo_id,
        backref="hooks",
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64))
    url = db.Column(db.Text)  # the webhook URL
    config = db.Column(MutableDict.as_mutable(JSONType))
    events = db.Column(ScalarListType)
    active = db.Column(db.Boolean)
    last_response = db.Column(MutableDict.as_mutable(JSONType))
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)


class Milestone(db.Model, ReplicationTimestampMixin):
    __tablename__ = "github_milestone"

    repo_id = db.Column(db.Integer, primary_key=True)
    repo = db.relationship(
        Repository,
        primaryjoin=(repo_id == Repository.id),
        foreign_keys=repo_id,
        backref="milestones",
    )
    number = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String(64))
    title = db.Column(db.String(256))
    description = db.Column(db.Text)
    creator_id = db.Column(db.Integer, index=True)
    creator_login = db.Column(db.String(256))
    creator = db.relationship(
        User,
        primaryjoin=(creator_id == User.id),
        foreign_keys=creator_id,
        remote_side=User.id,
        backref="created_milestones",
    )
    open_issues_count = db.Column(db.Integer)
    closed_issues_count = db.Column(db.Integer)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    due_at = db.Column(db.DateTime)

    @classmethod
    def get(cls, repo_owner, repo_name, number):
        """
        Fetch a single milestone given three things:
        * the username of the repo's owner, as a string
        * the name of the repo, as a string
        * the number of the milestone, as an integer

        If the milestone doesn't exist in the webhookdb database, return None.
        This can still raise a MultipleResultsFound exception.
        """
        query = (
            cls.query.join(Repository, cls.repo_id == Repository.id)
            .filter(Repository.owner_login == repo_owner)
            .filter(Repository.name == repo_name)
            .filter(cls.number == number)
        )
        try:
            return query.one()
        except NoResultFound:
            return None

    @property
    def github_json(self):
        url = "https://api.github.com/repos/{owner}/{repo}/milestones/{number}".format(
            owner=self.repo.owner_login,
            repo=self.repo.name,
            number=self.number,
        )
        html_url = "https://github.com/{owner}/{repo}/milestones/{title}".format(
            owner=self.repo.owner_login,
            repo=self.repo.name,
            title=self.title,
        )
        serialized = {
            "url": url,
            "html_url": html_url,
            "labels_url": url + "/labels",
            "id": self.id,
            "number": self.number,
            "state": self.state,
            "title": self.title,
            "description": self.description,
            "creator": self.creator.github_json,
            "open_issues": self.open_issues_count,
            "closed_issues": self.closed_issues_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "closed_at": self.closed_at,
            "due_on": self.due_at,
        }
        return serialized


class PullRequest(db.Model, ReplicationTimestampMixin):
    __tablename__ = "github_pull_request"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer)
    state = db.Column(db.String(64))
    locked = db.Column(db.Boolean)
    user_id = db.Column(db.Integer, index=True)
    user_login = db.Column(db.String(256))
    user = db.relationship(
        User,
        primaryjoin=(user_id == User.id),
        foreign_keys=user_id,
        remote_side=User.id,
        backref=backref("created_pull_requests", order_by=number)
    )
    title = db.Column(db.String(256))
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    merged_at = db.Column(db.DateTime)
    assignee_id = db.Column(db.Integer, index=True)
    assignee_login = db.Column(db.String(256))
    assignee = db.relationship(
        User,
        primaryjoin=(assignee_id == User.id),
        foreign_keys=assignee_id,
        remote_side=User.id,
        backref=backref("assigned_pull_requests", order_by=number),
    )
    base_repo_id = db.Column(db.Integer, index=True)
    base_repo = db.relationship(
        Repository,
        primaryjoin=(base_repo_id == Repository.id),
        foreign_keys=base_repo_id,
        remote_side=Repository.id,
        backref=backref("pull_requests", order_by=number),
    )
    base_ref = db.Column(db.String(256))
    head_repo_id = db.Column(db.Integer, index=True)
    head_repo = db.relationship(
        Repository,
        primaryjoin=(head_repo_id == Repository.id),
        foreign_keys=head_repo_id,
        remote_side=Repository.id,
    )
    head_ref = db.Column(db.String(256))
    milestone_number = db.Column(db.Integer)
    milestone = db.relationship(
        Milestone,
        primaryjoin=and_(
            milestone_number == Milestone.number,
            head_repo_id == Milestone.repo_id
        ),
        foreign_keys=[milestone_number, head_repo_id],
        backref=backref("pull_requests", order_by=number),
    )
    merged = db.Column(db.Boolean)
    mergeable = db.Column(db.Boolean)
    mergeable_state = db.Column(db.String(64))
    merged_by_id = db.Column(db.Integer, index=True)
    merged_by_login = db.Column(db.String(256))
    merged_by = db.relationship(
        User,
        primaryjoin=(merged_by_id == User.id),
        foreign_keys=merged_by_id,
        remote_side=User.id,
        backref=backref("merged_pull_requests", order_by=number),
    )
    comments_count = db.Column(db.Integer)
    review_comments_count = db.Column(db.Integer)
    commits_count = db.Column(db.Integer)
    additions = db.Column(db.Integer)
    deletions = db.Column(db.Integer)
    changed_files = db.Column(db.Integer)

    # not on github -- used for keeping track of scanning children
    files_last_scanned_at = db.Column(db.DateTime)

    @classmethod
    def get(cls, repo_owner, repo_name, number):
        """
        Fetch a single pull request given three things:
        * the username of the repo's owner, as a string
        * the name of the repo, as a string
        * the number of the pull request, as an integer

        If the pull request doesn't exist in the webhookdb database, return None.
        This can still raise a MultipleResultsFound exception.
        """
        query = (
            cls.query.join(Repository, cls.base_repo_id == Repository.id)
            .filter(Repository.owner_login == repo_owner)
            .filter(Repository.name == repo_name)
            .filter(cls.number == number)
        )
        try:
            return query.one()
        except NoResultFound:
            return None

    def __unicode__(self):
        return "{base_repo}#{number}".format(
            base_repo=self.base_repo or "<unknown>/<unknown>",
            number=self.number or "<unknown>",
        )

    def __str__(self):
        return unicode(self).encode('utf-8')

    @property
    def github_json(self):
        """
        Serialize to a JSON-serializable dict that matches GitHub's
        JSON serialization.
        """
        url = "https://api.github.com/repos/{owner}/{repo}/pulls/{number}".format(
            owner=self.base_repo.owner_login,
            repo=self.base_repo.name,
            number=self.number,
        )
        issue_url = "https://api.github.com/repos/{owner}/{repo}/issues/{number}".format(
            owner=self.base_repo.owner_login,
            repo=self.base_repo.name,
            number=self.number,
        )
        html_url = "https://github.com/{owner}/{repo}/pull/{number}".format(
            owner=self.base_repo.owner_login,
            repo=self.base_repo.name,
            number=self.number,
        )
        serialized = {
            "id": self.id,
            "url": url,
            "issue_url": issue_url,
            "html_url": html_url,
            "diff_url": html_url + ".diff",
            "patch_url": html_url + ".patch",
            "commits_url": url + "/commits",
            "comments_url": issue_url + "/comments",
            "review_comments_url": url + "/comments",
            "review_comment_url": url + "/comment{/number}",
            "statuses_url": url + "/statuses/1234567890abcdef",
            "_links": {
                "self": {
                    "href": url,
                },
                "html": {
                    "href": html_url,
                },
                "issue": {
                    "href": issue_url,
                },
                "comments": {
                    "href": issue_url + "/comments",
                },
                "review_comments": {
                    "href": url + "/comments",
                },
                "review_comment": {
                    "href": url + "/comment{/number}",
                },
                "commits": {
                    "href": url + "/commits",
                },
                "statuses": {
                    "href": url + "/statuses/1234567890abcdef",
                }
            },
            "number": self.number,
            "state": self.state,
            "locked": self.locked,
            "title": self.title,
            "user": self.user.github_json,
            "body": self.body,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "closed_at": self.closed_at,
            "merged_at": self.merged_at,
            "assignee": getattr(self.assignee, "github_json", None),
            "milestone": getattr(self.milestone, "github_json", None),
            "head": {
                "label": "{owner}:{ref}".format(
                    owner=self.head_repo.owner_login, ref=self.head_ref
                ),
                "ref": self.head_ref,
                "sha": "1234567890abcdef",
                "user": self.head_repo.owner.github_json,
                "repo": self.head_repo.github_json,
            },
            "base": {
                "label": "{owner}:{ref}".format(
                    owner=self.base_repo.owner_login, ref=self.base_ref
                ),
                "ref": self.base_ref,
                "sha": "1234567890abcdef",
                "user": self.base_repo.owner.github_json,
                "repo": self.base_repo.github_json,
            },
            "merged": self.merged,
            "mergeable": self.mergeable,
            "mergeable_state": self.mergeable_state,
            "merged_by": getattr(self.assignee, "github_json", None),
            "comments": self.comments_count,
            "review_comments": self.review_comments_count,
            "commits": self.commits_count,
            "additions": self.additions,
            "deletions": self.deletions,
            "changed_files": self.changed_files,
            "repository": self.base_repo.github_json,
            "organization": getattr(self.base_repo.organization, "github_json", None),
        }
        return serialized


class PullRequestFile(db.Model, ReplicationTimestampMixin):
    __tablename__ = "github_pull_request_file"

    pull_request_id = db.Column(db.Integer, db.ForeignKey(PullRequest.id), primary_key=True)
    pull_request = db.relationship(PullRequest)

    sha = db.Column(db.String(40), primary_key=True)
    filename = db.Column(db.String(256))
    status = db.Column(db.String(64))
    additions = db.Column(db.Integer)
    deletions = db.Column(db.Integer)
    changes = db.Column(db.Integer)
    patch = db.Column(db.Text)


    def __unicode__(self):
        return "{pr} {filename}".format(
            pr=self.pull_request or "<unknown>/<unknown>#<unknown>",
            filename=self.filename or "<unknown>",
        )

    def __str__(self):
        return unicode(self).encode('utf-8')


class IssueLabel(db.Model, ReplicationTimestampMixin):
    __tablename__ = "github_issue_label"

    repo_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), primary_key=True)
    color = db.Column(ColorType)

    repo = db.relationship(
        Repository,
        primaryjoin=(repo_id == Repository.id),
        foreign_keys=repo_id,
        remote_side=Repository.id,
        backref="labels",
    )

    @classmethod
    def get(cls, repo_owner, repo_name, name):
        """
        Fetch a single label given three things:
        * the username of the repo's owner, as a string
        * the name of the repo, as a string
        * the name of the label, as a string

        If the label doesn't exist in the webhookdb database, return None.
        This can still raise a MultipleResultsFound exception.
        """
        query = (
            cls.query.join(Repository, cls.repo_id == Repository.id)
            .filter(Repository.owner_login == repo_owner)
            .filter(Repository.name == repo_name)
            .filter(cls.name == name)
        )
        try:
            return query.one()
        except NoResultFound:
            return None

    def __unicode__(self):
        return self.name

    def __str__(self):
        return unicode(self).encode('utf-8')

    def __repr__(self):
        return "<{cls} {name} {repo}>".format(
            cls=self.__class__.__name__,
            name=self.name,
            repo=self.repo,
        )

    @property
    def github_json(self):
        url = "https://api.github.com/repos/{owner}/{repo}/labels/{name}",
        serialized = {
            "url": url,
            "name": self.name,
            "color": str(self.color).replace("#", ""),
        }
        return serialized


label_association_table = db.Table("github_issue_label_association", db.Model.metadata,
    db.Column("issue_id", db.Integer, index=True),
    db.Column("label_name", db.String(256), index=True),
)


class Issue(db.Model, ReplicationTimestampMixin):
    __tablename__ = "github_issue"

    id = db.Column(db.Integer, primary_key=True)
    repo_id = db.Column(db.Integer, index=True)
    repo = db.relationship(
        Repository,
        primaryjoin=(repo_id == Repository.id),
        foreign_keys=repo_id,
        backref=backref("issues", order_by=lambda: Issue.number),
    )
    number = db.Column(db.Integer)
    state = db.Column(db.String(64))
    title = db.Column(db.String(256))
    body = db.Column(db.Text)
    user_id = db.Column(db.Integer, index=True)
    user_login = db.Column(db.String(256))
    user = db.relationship(
        User,
        primaryjoin=(user_id == User.id),
        foreign_keys=user_id,
        remote_side=User.id,
        backref=backref("created_issues", order_by=lambda: Issue.number),
    )
    labels = db.relationship(
        IssueLabel,
        secondary=label_association_table,
        primaryjoin=and_(
            label_association_table.c.label_name == IssueLabel.name,
            repo_id == IssueLabel.repo_id
        ),
        secondaryjoin=(id == label_association_table.c.issue_id),
        foreign_keys=[id, repo_id],
        backref=backref("issues", order_by=lambda: Issue.number),
    )
    assignee_id = db.Column(db.Integer, index=True)
    assignee_login = db.Column(db.String(256))
    assignee = db.relationship(
        User,
        primaryjoin=(assignee_id == User.id),
        foreign_keys=assignee_id,
        remote_side=User.id,
        backref=backref("assigned_issues", order_by=lambda: Issue.number),
    )
    milestone_number = db.Column(db.Integer)
    milestone = db.relationship(
        Milestone,
        primaryjoin=and_(
            milestone_number == Milestone.number,
            repo_id == Milestone.repo_id
        ),
        foreign_keys=[milestone_number, repo_id],
        backref=backref("issues", order_by=lambda: Issue.number),
    )
    comments_count = db.Column(db.Integer)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    closed_by_id = db.Column(db.Integer, index=True)
    closed_by_login = db.Column(db.String(256))
    closed_by = db.relationship(
        User,
        primaryjoin=(closed_by_id == User.id),
        foreign_keys=closed_by_id,
        backref=backref("closed_issues", order_by=lambda: Issue.number),
    )

    @classmethod
    def get(cls, repo_owner, repo_name, number):
        """
        Fetch a single issue given three things:
        * the username of the repo's owner, as a string
        * the name of the repo, as a string
        * the number of the issue, as an integer

        If the issue doesn't exist in the webhookdb database, return None.
        This can still raise a MultipleResultsFound exception.
        """
        query = (
            cls.query.join(Repository, cls.repo_id == Repository.id)
            .filter(Repository.owner_login == repo_owner)
            .filter(Repository.name == repo_name)
            .filter(cls.number == number)
        )
        try:
            return query.one()
        except NoResultFound:
            return None

    @property
    def github_json(self):
        url = "https://api.github.com/repos/{owner}/{repo}/issues/{number}".format(
            owner=self.repo.owner_login,
            repo=self.repo.name,
            number=self.number,
        )
        html_url = "https://github.com/{owner}/{repo}/issues/{number}".format(
            owner=self.repo.owner_login,
            repo=self.repo.name,
            number=self.number,
        )
        pr_url = "https://api.github.com/repos/{owner}/{repo}/pulls/{number}".format(
            owner=self.repo.owner_login,
            repo=self.repo.name,
            number=self.number,
        )
        html_pr_url = "https://github.com/{owner}/{repo}/pulls/{number}".format(
            owner=self.repo.owner_login,
            repo=self.repo.name,
            number=self.number,
        )
        serialized = {
            "id": self.id,
            "url": url,
            "labels_url": url + "/labels{/name}",
            "comments_url": url + "/comments",
            "events_url": url + "/events",
            "html_url": html_url,
            "number": self.number,
            "state": self.state,
            "title": self.title,
            "body": self.body,
            "user": self.user.github_json,
            "labels": [label.github_json for label in self.labels],
            "assignee": getattr(self.assignee, "github_json", None),
            "milestone": getattr(self.milestone, "github_json", None),
            "locked": self.locked,
            "comments": self.comments_count,
            "pull_request": {
                "url": pr_url,
                "html_url": html_pr_url,
                "diff_url": html_pr_url + ".diff",
                "patch_url": html_pr_url + ".patch",
            },
            "closed_at": self.closed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "closed_by": getattr(self.closed_by, "github_json", None),
        }
        return serialized
