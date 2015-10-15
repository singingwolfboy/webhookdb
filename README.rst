WebhookDB
=========

This project allows you to replicate Github's database over HTTP using webhooks.
It's useful if you want to treat Github's APIs as a database, querying over
pull requests and issues. Github doesn't like that, and you'll quickly hit the
API's rate limits -- but if you use WebhookDB, you don't have to worry about it!
Just populate the initial data into the database, set up the webhook replication
to keep it in sync, and query your local database however you'd like!

|build-status| |coverage-status| |docs|

|heroku-deploy|

.. |heroku-deploy| image:: https://www.herokucdn.com/deploy/button.png
   :target: https://heroku.com/deploy
   :alt: Deploy to Heroku
.. |build-status| image:: https://travis-ci.org/singingwolfboy/webhookdb.svg?branch=master
   :target: https://travis-ci.org/singingwolfboy/webhookdb
.. |coverage-status| image:: http://codecov.io/github/singingwolfboy/webhookdb/coverage.svg?branch=master
   :target: http://codecov.io/github/singingwolfboy/webhookdb?branch=master
.. |docs| image:: https://readthedocs.org/projects/webhookdb/badge/?version=latest
   :target: http://webhookdb.readthedocs.org/en/latest/
   :alt: Documentation badge
