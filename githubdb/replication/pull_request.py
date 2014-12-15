# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import request
import bugsnag
from . import replication


@replication.route('/pull_request')
def pull_request():
    payload = request.get_json()
    bugsnag.configure_request(meta_data={"payload": payload})
    return "pr"
