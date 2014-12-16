# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import Blueprint

load = Blueprint('load', __name__)

from .repository import load_repo
from .pull_request import load_pulls, load_pull
