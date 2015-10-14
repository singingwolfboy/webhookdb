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
from werkzeug.contrib.fixers import ProxyFix
from opbeat.contrib.flask import Opbeat
from opbeat.handlers.logging import OpbeatHandler
from opbeat.contrib.celery import register_signal
from flask.ext.sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from flask_bootstrap import Bootstrap
from flask_login import LoginManager
from celery import Celery

opbeat = Opbeat()
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
    app.wsgi_app = ProxyFix(app.wsgi_app)
    config = config or os.environ.get("WEBHOOKDB_CONFIG") or "default"
    app.config.from_object(expand_config(config))

    if not app.config["TESTING"]:
        opbeat.init_app(app)
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
    register_signal(opbeat.client)
    return celery
