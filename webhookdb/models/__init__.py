# coding=utf-8
from __future__ import unicode_literals
from datetime import datetime
from flask_dance.consumer.backend.sqla import OAuthConsumerMixin
from sqlalchemy import text
from webhookdb import db, login_manager
from .github import (
    User, Repository, UserRepoAssociation, RepositoryHook, Milestone,
    PullRequest, PullRequestFile, IssueLabel, Issue
)


class OAuth(db.Model, OAuthConsumerMixin):
    "Used by Flask-Dance"
    user_id = db.Column(db.Integer, db.ForeignKey(User.id))
    user = db.relationship(User)


class Mutex(db.Model):
    __tablename__ = "webhookdb_mutex"

    name = db.Column(db.String(256), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, index=True)
    user = db.relationship(
        User,
        primaryjoin=(user_id == User.id),
        foreign_keys=user_id,
        remote_side=User.id,
        backref="held_locks",
    )


@login_manager.user_loader
def load_user(user_id):
    "Used by Flask-Login"
    return User.query.get(int(user_id))
