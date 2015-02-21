# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import Blueprint, request, jsonify

replication = Blueprint('replication', __name__)

from .repository import repository
from .pull_request import pull_request
from .issue import issue

@replication.before_request
def ping():
    """
    Handle the "ping" event
    https://developer.github.com/webhooks/#ping-event
    """
    if request.headers.get("X-Github-Event", "").lower() == "ping":
        return jsonify({"message": "pong"})

@replication.before_request
def payload():
    """
    Every request should have a payload, or it's invalid.
    """
    if not request.get_json():
        return jsonify({"error": "no payload"}), 400
