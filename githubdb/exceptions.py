# coding=utf-8
from __future__ import unicode_literals


class MissingInfo(Exception):
    def __init__(self, message, obj):
        self.message = message
        self.obj = obj


class StaleInfo(Exception):
    pass
