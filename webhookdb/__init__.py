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
from bugsnag.flask import handle_exceptions
from flask.ext.sqlalchemy import SQLAlchemy
from flask_sslify import SSLify

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)
    handle_exceptions(app)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///github.db")
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secrettoeveryone")

    db.init_app(app)
    if not app.debug:
        sslify = SSLify(app)

    from .oauth import github_bp
    app.register_blueprint(github_bp, url_prefix="/login")

    from .replication import replication as repl_blueprint
    app.register_blueprint(repl_blueprint, url_prefix="/replication")

    from .load import load as load_blueprint
    app.register_blueprint(load_blueprint, url_prefix="/load")

    from .ui import ui as ui_blueprint
    app.register_blueprint(ui_blueprint)

    return app
