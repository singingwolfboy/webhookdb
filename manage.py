#!/usr/bin/env python
import flask
from flask.ext.script import Manager, prompt_bool
import sqlalchemy
from githubdb import create_app, db
from githubdb.models import OAuth, User, Repository, PullRequest

manager = Manager(create_app)


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


@manager.shell
def make_shell_context():
    return dict(
        app=flask.current_app, db=db, OAuth=OAuth,
        User=User, Repository=Repository, PullRequest=PullRequest,
    )


if __name__ == "__main__":
    manager.run()
