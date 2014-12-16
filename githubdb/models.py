# coding=utf-8
from __future__ import unicode_literals
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import func
from flask_dance.models import OAuthConsumerMixin
from githubdb import db


class OAuth(db.Model, OAuthConsumerMixin):
    "Used by Flask-Dance"
    pass


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


class User(db.Model, ReplicationTimestampMixin):
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
    public_repos = db.Column(db.Integer)
    public_gists = db.Column(db.Integer)
    followers = db.Column(db.Integer)
    following = db.Column(db.Integer)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)

    def __unicode__(self):
        return "@{login}".format(login=self.login or "<unknown>")

    def __str__(self):
        return unicode(self).encode('utf-8')


class Repository(db.Model, ReplicationTimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256))
    owner_id = db.Column(db.Integer)
    owner_login = db.Column(db.String(256))
    owner = db.relationship(
        User,
        primaryjoin=(owner_id == User.id),
        foreign_keys=owner_id,
        remote_side=User.id,
    )
    organization_id = db.Column(db.Integer)
    organization_login = db.Column(db.String(256))
    organization = db.relationship(
        User,
        primaryjoin=(organization_id == User.id),
        foreign_keys=organization_id,
        remote_side=User.id,
    )
    private = db.Column(db.Boolean)
    description = db.Column(db.String(256))
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
    default_branch = db.Column(db.String(256))

    @hybrid_property
    def full_name(self):
        return "{name}/{owner_login}".format(
            name=self.name or "<unknown>",
            owner_login=self.owner_login or "<unknown>",
        )

    @full_name.expression
    def full_name(cls):
        name = func.coalesce(cls.name, "<unknown>")
        owner_login = func.coalesce(cls.owner_login, "<unknown>")
        return func.concat(name, '/', owner_login)

    def __unicode__(self):
        return self.full_name

    def __str__(self):
        return unicode(self).encode('utf-8')


class PullRequest(db.Model, ReplicationTimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer)
    state = db.Column(db.String(64))
    locked = db.Column(db.Boolean)
    user_id = db.Column(db.Integer)
    user_login = db.Column(db.String(256))
    user = db.relationship(
        User,
        primaryjoin=(user_id == User.id),
        foreign_keys=user_id,
        remote_side=User.id,
    )
    title = db.Column(db.String(256))
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    merged_at = db.Column(db.DateTime)
    merge_commit_sha = db.Column(db.String(40))
    assignee_id = db.Column(db.Integer)
    assignee_login = db.Column(db.String(256))
    assignee = db.relationship(
        User,
        primaryjoin=(assignee_id == User.id),
        foreign_keys=assignee_id,
        remote_side=User.id,
    )
    milestone = db.Column(db.String(256))
    base_repo_id = db.Column(db.Integer)
    base_repo = db.relationship(
        Repository,
        primaryjoin=(base_repo_id == Repository.id),
        foreign_keys=base_repo_id,
        remote_side=Repository.id,
    )
    base_ref = db.Column(db.String(256))
    head_repo_id = db.Column(db.Integer)
    head_repo = db.relationship(
        Repository,
        primaryjoin=(head_repo_id == Repository.id),
        foreign_keys=head_repo_id,
        remote_side=Repository.id,
    )
    head_ref = db.Column(db.String(256))
    merged = db.Column(db.Boolean)
    mergable = db.Column(db.Boolean)
    mergable_state = db.Column(db.String(64))
    merged_by_id = db.Column(db.Integer)
    merged_by_login = db.Column(db.String(256))
    merged_by = db.relationship(
        User,
        primaryjoin=(merged_by_id == User.id),
        foreign_keys=merged_by_id,
        remote_side=User.id,
    )
    comments = db.Column(db.Integer)
    review_comments = db.Column(db.Integer)
    commits = db.Column(db.Integer)
    additions = db.Column(db.Integer)
    deletions = db.Column(db.Integer)
    changed_files = db.Column(db.Integer)

    def __unicode__(self):
        return "{base_repo}#{number}".format(
            base_repo=self.base_repo or "<unknown>/<unknown>",
            number=self.number or "<unknown>",
        )

    def __str__(self):
        return unicode(self).encode('utf-8')
