# coding=utf-8
from __future__ import unicode_literals
import os

RABBITMQ_PROVIDER = "bigwig"
REDIS_PROVIDER = "rediscloud"


class DefaultConfig(object):
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "secrettoeveryone")
    GITHUB_OAUTH_CLIENT_ID = os.environ.get("GITHUB_OAUTH_CLIENT_ID")
    GITHUB_OAUTH_CLIENT_SECRET = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///github.db")
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_TASK_SERIALIZER = "json"
    CELERY_RESULT_SERIALIZER = 'json'
    CELERY_EAGER_PROPAGATES_EXCEPTIONS = True
    if RABBITMQ_PROVIDER == "bigwig":
        # TX_URL for producers
        CELERY_BROKER_URL = os.environ.get("RABBITMQ_BIGWIG_TX_URL", "amqp://")
    elif RABBITMQ_PROVIDER == "cloudamqp":
        CELERY_BROKER_URL = os.environ.get("CLOUDAMQP_URL", "amqp://")
        # recommended by CloudAMQP for their free plan
        BROKER_POOL_LIMIT = 1
    if REDIS_PROVIDER == "rediscloud":
        CELERY_RESULT_BACKEND = os.environ.get("REDISCLOUD_URL", "redis://")


class WorkerConfig(DefaultConfig):
    if RABBITMQ_PROVIDER == "bigwig":
        # RX_URL for consumers
        CELERY_BROKER_URL = os.environ.get("RABBITMQ_BIGWIG_RX_URL", "amqp://")


class DevelopmentConfig(DefaultConfig):
    DEBUG = True


class TestConfig(DefaultConfig):
    TESTING = True
