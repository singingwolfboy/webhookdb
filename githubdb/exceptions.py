# coding=utf-8
from __future__ import unicode_literals


class MissingData(Exception):
    def __init__(self, message, obj):
        self.message = message
        self.obj = obj


class StaleData(Exception):
    pass
