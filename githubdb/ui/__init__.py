# coding=utf-8
from __future__ import unicode_literals, print_function

from flask import Blueprint, render_template

ui = Blueprint('ui', __name__)


@ui.route("/")
def index():
    """
    Just to verify that things are working
    """
    return render_template("main.html")
