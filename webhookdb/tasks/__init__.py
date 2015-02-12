# coding=utf-8
from __future__ import unicode_literals, print_function

from webhookdb import celery
from webhookdb.oauth import github_bp
from celery.utils.log import get_task_logger
from celery.signals import task_prerun
from flask import Blueprint, jsonify

# set up logging
logger = get_task_logger(__name__)

# create a Flask blueprint for getting task status info
tasks = Blueprint('tasks', __name__)

@tasks.route('/status/<task_id>')
def status(task_id):
    result = celery.AsyncResult(task_id)
    return jsonify({"status": result.state})

# Working in a Celery task means we can't take advantage of Flask-Dance's
# session proxies, so we'll explicitly define the Github session here.
github = github_bp.session

# We also have to explicitly connect the `assign_token_to_session` method
# to the `task_prerun` signal, so it happens before each task.
@task_prerun.connect
def load_github_oauth_token(sender, task_id, task, args, kwargs, **extra):
    github_bp.before_app_request(github_bp.load_config)
    github_bp.before_app_request(github_bp.load_token)
