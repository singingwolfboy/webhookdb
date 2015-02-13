# coding=utf-8
from __future__ import unicode_literals, print_function

import logging
from webhookdb import celery
from webhookdb.oauth import github_bp
from celery.utils.log import get_task_logger
from flask import Blueprint, jsonify

# set up logging
logger = get_task_logger(__name__)
logger.setLevel(logging.INFO)

# create a Flask blueprint for getting task status info
tasks = Blueprint('tasks', __name__)

@tasks.route('/status/<task_id>')
def status(task_id):
    result = celery.AsyncResult(task_id)
    return jsonify({"status": result.state})

# Working in a Celery task means we can't take advantage of Flask-Dance's
# session proxies, so we'll explicitly define the Github session here.
github = github_bp.session
