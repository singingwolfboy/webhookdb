Adding a New Repo
=================

Adding a new repo to WebhookDB is a two-step process.

Install the Github Webhooks
---------------------------
You can do this by going to the admin page for the Github repo, and setting up
the webhooks manually. Alternatively, you can visit WebhookDB's
:http:get:`/install` page and put in the info for the repo you want to install
the hooks into. Note that WebhookDB will only be able to install these hooks
for you if the Github user associated with WebhookDB has admin permissions
on the repo you request -- otherwise, Github will return a "404 Not Found"
response to WebhookDB's attempts to install the webhooks.

The webhooks that should exist are:

* :http:post:`/replication/pull_request` (for the ``pull_request`` event)
* :http:post:`/replication/issue` (for the ``issues`` event)

Load past history
-----------------
The webhooks will ensure that any new events that occur in your repository are
captured by WebhookDB, but if you want to load in the past history of your
repo, you'll need to do that separately. Right now, the simplest way to do this
is using ``curl`` or a similar tool to make HTTP requests to the WebhookDB server.

To load pull requests for a repo, use :http:post:`/load/repos/(owner)/(repo)/pulls`.
If you want to load *all* pull requests, including closed pull requests, you'll
need to use the ``?state=all`` query parameter. This API endpoint will create
tasks on the task queue, but those tasks won't get run unless there is a worker
process, so check to be sure that a worker is running.
