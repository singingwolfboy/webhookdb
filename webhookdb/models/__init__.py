# coding=utf-8
from __future__ import unicode_literals
from flask_dance.models import OAuthConsumerMixin
from webhookdb import db, login_manager
from .github import (
    User, Repository, UserRepoAssociation, RepositoryHook, Milestone,
    PullRequest, PullRequestFile, IssueLabel, Issue
)


class OAuth(db.Model, OAuthConsumerMixin):
    "Used by Flask-Dance"
    user_id = db.Column(db.Integer, db.ForeignKey(User.id))
    user = db.relationship(User)


@login_manager.user_loader
def load_user(user_id):
    "Used by Flask-Login"
    return User.query.get(int(user_id))
