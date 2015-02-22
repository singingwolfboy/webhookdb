# coding=utf-8
from __future__ import unicode_literals
from flask_dance.models import OAuthConsumerMixin
from webhookdb import db
from .github import (
    User, Repository, UserRepoAssociation, Milestone,
    PullRequest, PullRequestFile, IssueLabel, Issue
)


class OAuth(db.Model, OAuthConsumerMixin):
    "Used by Flask-Dance"
    pass
