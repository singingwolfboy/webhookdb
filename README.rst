GithubDB
========

This project allows you to replicate Github's database over HTTP using webhooks.
It's useful if you want to treat Github's APIs as a database, querying over
pull requests and issues. Github doesn't like that, and you'll quickly hit the
API's rate limits -- but if you use GithubDB, you don't have to worry about it!
Just populate the initial data into the database, set up the webhook replication
to keep it in sync, and query your local database however you'd like!
