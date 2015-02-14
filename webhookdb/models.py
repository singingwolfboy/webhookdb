# coding=utf-8
from __future__ import unicode_literals
from datetime import datetime
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import func, join, and_
from sqlalchemy_utils.types.color import ColorType
from flask_dance.models import OAuthConsumerMixin
from webhookdb import db


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
    __tablename__ = "webhookdb_user"

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
    __tablename__ = "webhookdb_repository"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256))
    owner_id = db.Column(db.Integer, index=True)
    owner_login = db.Column(db.String(256))
    owner = db.relationship(
        User,
        primaryjoin=(owner_id == User.id),
        foreign_keys=owner_id,
        remote_side=User.id,
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

    labels = db.relationship(
        "IssueLabel",
        primaryjoin="Repository.id == IssueLabel.repo_id",
        foreign_keys="Repository.id",
        uselist=True,
    )

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

    def __unicode__(self):
        return self.full_name

    def __str__(self):
        return unicode(self).encode('utf-8')


class Milestone(db.Model, ReplicationTimestampMixin):
    __tablename__ = "webhookdb_milestone"

    number = db.Column(db.Integer, primary_key=True)
    repo_id = db.Column(db.Integer, primary_key=True)
    repo = db.relationship(
        Repository,
        primaryjoin=(repo_id == Repository.id),
        foreign_keys=repo_id,
    )
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
    )
    open_issues_count = db.Column(db.Integer)
    closed_issues_count = db.Column(db.Integer)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    due_at = db.Column(db.DateTime)


class PullRequest(db.Model, ReplicationTimestampMixin):
    __tablename__ = "webhookdb_pull_request"

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
    )
    title = db.Column(db.String(256))
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)
    merged_at = db.Column(db.DateTime)
    merge_commit_sha = db.Column(db.String(40))
    assignee_id = db.Column(db.Integer, index=True)
    assignee_login = db.Column(db.String(256))
    assignee = db.relationship(
        User,
        primaryjoin=(assignee_id == User.id),
        foreign_keys=assignee_id,
        remote_side=User.id,
    )
    base_repo_id = db.Column(db.Integer, index=True)
    base_repo = db.relationship(
        Repository,
        primaryjoin=(base_repo_id == Repository.id),
        foreign_keys=base_repo_id,
        remote_side=Repository.id,
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
    )
    merged = db.Column(db.Boolean)
    mergable = db.Column(db.Boolean)
    mergable_state = db.Column(db.String(64))
    merged_by_id = db.Column(db.Integer, index=True)
    merged_by_login = db.Column(db.String(256))
    merged_by = db.relationship(
        User,
        primaryjoin=(merged_by_id == User.id),
        foreign_keys=merged_by_id,
        remote_side=User.id,
    )
    comments_count = db.Column(db.Integer)
    review_comments_count = db.Column(db.Integer)
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


class PullRequestFile(db.Model, ReplicationTimestampMixin):
    __tablename__ = "webhookdb_pull_request_file"

    sha = db.Column(db.String(40), primary_key=True)
    filename = db.Column(db.String(256))
    status = db.Column(db.String(64))
    additions = db.Column(db.Integer)
    deletions = db.Column(db.Integer)
    changes = db.Column(db.Integer)
    patch = db.Column(db.Text)

    pull_request_id = db.Column(db.Integer, db.ForeignKey(PullRequest.id), index=True)
    pull_request = db.relationship(PullRequest)

    def __unicode__(self):
        return "{pr} {filename}".format(
            pr=self.pull_request or "<unknown>/<unknown>#<unknown>",
            filename=self.filename or "<unknown>",
        )

    def __str__(self):
        return unicode(self).encode('utf-8')


class IssueLabel(db.Model, ReplicationTimestampMixin):
    __tablename__ = "webhookdb_issue_label"

    repo_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), primary_key=True)
    color = db.Column(ColorType)

    repo = db.relationship(
        Repository,
        primaryjoin=(repo_id == Repository.id),
        foreign_keys=repo_id,
        remote_side=Repository.id,
    )

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


label_association_table = db.Table("webhookdb_issue_label_association", db.Model.metadata,
    db.Column("issue_id", db.Integer, db.ForeignKey("webhookdb_issue.id")),
    db.Column("label_name", db.String(256), db.ForeignKey(IssueLabel.name)),
)


class Issue(db.Model, ReplicationTimestampMixin):
    __tablename__ = "webhookdb_issue"

    id = db.Column(db.Integer, primary_key=True)
    repo_id = db.Column(db.Integer, index=True)
    repo = db.relationship(
        Repository,
        primaryjoin=(repo_id == Repository.id),
        foreign_keys=repo_id,
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
    )
    labels = db.relationship(
        IssueLabel,
        secondary=label_association_table,
        primaryjoin=and_(
            label_association_table.c.label_name == IssueLabel.name,
            repo_id == IssueLabel.repo_id
        ),
        backref="issues",
    )
    assignee_id = db.Column(db.Integer, index=True)
    assignee_login = db.Column(db.String(256))
    assignee = db.relationship(
        User,
        primaryjoin=(assignee_id == User.id),
        foreign_keys=assignee_id,
        remote_side=User.id,
    )
    milestone_number = db.Column(db.Integer)
    milestone = db.relationship(
        Milestone,
        primaryjoin=and_(
            milestone_number == Milestone.number,
            repo_id == Milestone.repo_id
        ),
        foreign_keys=[milestone_number, repo_id],
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
    )
