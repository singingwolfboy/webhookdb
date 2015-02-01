"""
This file only exists because celery can't handle a factory function
being passed as the application instance, like this:

  $ celery worker --app=webhookdb.create_celery_app()

If celery ever gets this capability, this file can be deleted.
"""

from webhookdb import create_celery_app

application = create_celery_app()
