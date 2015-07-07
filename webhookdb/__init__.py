# coding=utf-8
from __future__ import print_function, unicode_literals

# UTF-8 stderr: http://stackoverflow.com/a/2001767/141395
import codecs
import sys
reload(sys)
sys.setdefaultencoding('utf-8')
sys.stdout = codecs.getwriter('utf-8')(sys.stdout)
sys.stderr = codecs.getwriter('utf-8')(sys.stderr)

import os

from flask import Flask
import bugsnag
from bugsnag.flask import handle_exceptions
from bugsnag.celery import connect_failure_handler
from flask.ext.sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from flask_bootstrap import Bootstrap
from flask_login import LoginManager
from celery import Celery

db = SQLAlchemy()
bootstrap = Bootstrap()
celery = Celery()

login_manager = LoginManager()
login_manager.session_protection = 'strong'
login_manager.login_view = 'github.login'


def expand_config(name):
    if not name:
        name = "default"
    return "webhookdb.config.{classname}Config".format(classname=name.capitalize())


def create_app(config=None):
    app = Flask(__name__)
    handle_exceptions(app)
    config = config or os.environ.get("WEBHOOKDB_CONFIG") or "default"
    app.config.from_object(expand_config(config))

    db.init_app(app)
    bootstrap.init_app(app)
    login_manager.init_app(app)
    create_celery_app(app)
    if not app.debug:
        SSLify(app)

    from .oauth import github_bp
    app.register_blueprint(github_bp, url_prefix="/login")

    from .replication import replication as repl_blueprint
    app.register_blueprint(repl_blueprint, url_prefix="/replication")

    from .load import load as load_blueprint
    app.register_blueprint(load_blueprint, url_prefix="/load")

    from .tasks import tasks as tasks_blueprint
    app.register_blueprint(tasks_blueprint, url_prefix="/tasks")

    from .ui import ui as ui_blueprint
    app.register_blueprint(ui_blueprint)

    return app


def create_celery_app(app=None, config="worker"):
    """
    adapted from http://flask.pocoo.org/docs/0.10/patterns/celery/
    """
    app = app or create_app(config=config)
    celery.main = app.import_name
    celery.conf["BROKER_URL"] = app.config["CELERY_BROKER_URL"]
    celery.conf.update(app.config)
    TaskBase = celery.Task
    class ContextTask(TaskBase):
        abstract = True
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)
    celery.Task = ContextTask
    connect_failure_handler()
    bugsnag.configure(ignore_classes=[
        "webhookdb.exceptions.StaleData",
        "webhookdb.exceptions.NothingToDo",
        "webhookdb.exceptions.RateLimited",
    ])
    return celery
