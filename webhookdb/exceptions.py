# coding=utf-8
from __future__ import unicode_literals
from datetime import datetime

class WebhookDBException(Exception):
    "Base exception class that all others in this package inherit from"
    pass

class MissingData(WebhookDBException):
    def __init__(self, message, obj):
        self.message = message
        self.obj = obj
        WebhookDBException.__init__(self, message, obj)


class StaleData(WebhookDBException):
    pass

class NothingToDo(WebhookDBException):
    pass


class RateLimited(WebhookDBException):
    def __init__(self, response):
        self.response = response
        WebhookDBException.__init__(self, response)

    @property
    def reset(self):
        """
        If set, a datetime that indicates when the rate limit will
        be reset. If not set, the reset time is unknown.
        """
        if self.response is None:
            return None
        reset_epoch_str = self.response.headers.get("X-RateLimit-Reset")
        if not reset_epoch_str:
            return None
        try:
            reset_epoch = int(reset_epoch_str)
        except Exception:
            return None
        return datetime.fromtimestamp(reset_epoch)


class NotFound(WebhookDBException):
    def __init__(self, message, info=None):
        self.message = message
        self.info = info or {}
        WebhookDBException.__init__(self, message, info)


class DatabaseError(WebhookDBException):
    def __init__(self, message, info=None):
        self.message = message
        self.info = info or {}
        WebhookDBException.__init__(self, message, info)
