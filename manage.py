#!/usr/bin/env python
from __future__ import unicode_literals, print_function
import flask
from flask.ext.script import Manager, prompt_bool
import sqlalchemy
from webhookdb import create_app, db, celery
from webhookdb.models import (
    OAuth, User, Repository, UserRepoAssociation, RepositoryHook, Milestone,
    PullRequest, PullRequestFile, IssueLabel, Issue, Mutex
)

manager = Manager(create_app)
manager.add_option('-c', '--config', dest='config', required=False)


@manager.command
def dbcreate():
    "Creates database tables from SQLAlchemy models"
    db.create_all()
    db.session.commit()


@manager.command
def dbdrop():
    "Drops database tables"
    if prompt_bool("Are you sure you want to lose all your data"):
        db.drop_all()
        db.session.commit()


@manager.command
def sql():
    "Dumps SQL for creating database tables"
    def dump(sql, *multiparams, **params):
        print(sql.compile(dialect=engine.dialect))
    engine = sqlalchemy.create_engine('postgresql://', strategy='mock', executor=dump)
    db.metadata.create_all(engine, checkfirst=False)


@manager.command
def worker():
    "Start a Celery worker"
    worker = celery.Worker()
    worker.start()


@manager.shell
def make_shell_context():
    return dict(
        app=flask.current_app, celery=celery,
        db=db, OAuth=OAuth,
        User=User, Repository=Repository, UserRepoAssociation=UserRepoAssociation,
        RepositoryHook=RepositoryHook, Milestone=Milestone,
        PullRequest=PullRequest, PullRequestFile=PullRequestFile,
        IssueLabel=IssueLabel, Issue=Issue,
        Mutex=Mutex,
    )


if __name__ == "__main__":
    manager.run()
