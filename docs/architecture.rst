Architecture
============

WebhookDB's codebase is separated into a multilayered architecture. This
document will describe the layers from the ground up.

Database Models
---------------
Like all web applications, WebhookDB stores information in a database. The
information is organized into conceptual models, most of which are directly
pulled from GitHub. These models are defined using the `SQLAlchemy`_ ORM, and
they are located in the ``models`` directory of the project.

Many of these models inherit from the
:class:`~webhookdb.models.github.ReplicationTimestampMixin`, which automatically
adds two database columns: ``last_replicated_via_webhook_at`` and
``last_replicated_via_api_at``. This allows future database queries to determine
how stale the data is. There is also a virtual property simply called
``last_replicated_at`` -- this returns the more recent of these two columns.

Data Processing
---------------
The next layer is the data processing layer, which is stored in the ``process``
directory of the project. This layer consists of functions which accept
the parsed JSON output of the GitHub API responses, and updates the database
to reflect the information provided in that parsed JSON. Each data model has its
own data processing function: the :class:`~webhookdb.models.github.User` model
has a corresponding :func:`~webhookdb.process.user.process_user` function, for
example, and the :class:`~webhookdb.models.github.PullRequest` model has a
corresponding :func:`~webhookdb.process.pull_request.process_pull_request`
function.

API responses often include nested data: for example, if you request information
about a pull request from GitHub's `pull request API`_, it will include detailed
user information about the author of the pull request, even though that is
information that should be stored in the :class:`~webhookdb.models.github.User`
model, not the :class:`~webhookdb.models.github.PullRequest` model. Each
data processing function will *only* process the data for the model that it
is named for, but it will delegate nested data to the data processing function
for that nested data type. This means that
:func:`~webhookdb.process.pull_request.process_pull_request` calls
:func:`~webhookdb.process.user.process_user`, for example.

It's important to note that functions in the data processing layer do not know
where the data came from, and for the most part, they don't care. The data might
come from an API response, or from a webhook notification. It might be top-level,
or it might be some nested data that a different data processing function passed
to it. These functions never seek out data on their own, but instead they are
called by functions that retrieve the data. This means that functions in the
data processing layer never make HTTP requests, although they can and do make
database queries.

Celery Tasks
------------
The next layer is the `Celery`_ tasks, which are stored in the ``tasks``
directory. This layer makes HTTP requests to GitHub's API, and passes the
results of those requests on to the data processing layer. HTTP requests can be
slow, and they can fail for any number of reasons (networking problems, problems
on GitHub's end, rate limiting issues, etc), so we use the `Celery`_ task queue
to make these tasks more robust against failure.

Fetching data for an individual model, such as a single user or a single pull
request, is relatively straightforward, and is handled by the "sync" task
for the data model. For example, :func:`webhookdb.tasks.user.sync_user`
will fetch data for an individual user, and
:func:`webhookdb.tasks.pull_request.sync_pull_request` will fetch data for an
individual pull request.

Fetching data for a group of models, such as *all* pull requests
in a repository, is much more complicated. GitHub's API responses are paginated,
so it's natural to work on a per-page basis. For each data model, there is a
"spawn page tasks" task, which makes a single API call to determine
how many pages there are in the response. Based on that information, it calls
the "sync page" task as many times as necessary: that task will make
a single HTTP request to retrieve the indicated page of the API response,
and will call the data processing functions for each item in the page. (Note
that all of the "sync page" functions can be processed in parallel with each
other.) Once all of the "sync page" tasks have completed, there is a "scanned"
task that gets called, which handles any cleanup work necessary to indicate
that the group of models is done being scanned. For example, to fetch data
for all pull requests in a repository, the relevant tasks are
:func:`webhookdb.tasks.pull_request.spawn_page_tasks_for_pull_requests`,
:func:`webhookdb.tasks.pull_request.sync_page_of_pull_requests`,
and :func:`webhookdb.tasks.pull_request.pull_requests_scanned`.

Note that this uses Celery's :ref:`chord workflow <celery:canvas-chord>`,
and it is subject to all of the performance issues of that workflow.

Replication HTTP endpoints
--------------------------
The replication layer is stored in the ``replication`` directory, and it
consists of a :ref:`Flask blueprint <flask:blueprints>` designed to be used
by the webhook system on GitHub. Once your repository on GitHub has its
replication webhooks set up properly, GitHub will make an HTTP request to
this endpoint every time an event happens on GitHub. The replication endpoint
will pass the data in that request to the data processing layer, and will
queue celery tasks to update other information if necessary. (For example,
when a pull request is updated, the pull request files must be rescanned,
so the replication endpoint will queue the
:func:`webhookdb.tasks.pull_request_file.spawn_page_tasks_for_pull_request_files`
task.) This layer also handles the ``ping`` event that GitHub sends to all
webhook endpoints as a test.

Load HTTP endpoints
-------------------
Sometimes, users want to tell WebhookDB that it should load data from GitHub
directly, rather than waiting for that data to replicate to WebhookDB via
webhooks. The load layer is stored in the ``load`` directory, and it consists
of a :ref:`Flask blueprint <flask:blueprints>` that is designed to mirror the
GitHub API fairly closely. When a user sends a POST request to one of these
endpoints, WebhookDB will queue a Celery task to load the requested data from
the GitHub API.

User Interface
--------------
The user interface is stored in the ``ui`` directory, and it consists of a
:ref:`Flask blueprint <flask:blueprints>` of pages that return HTML web pages,
rather than a JSON API.


.. _SQLAlchemy: http://www.sqlalchemy.org/
.. _Celery: http://www.celeryproject.org/
.. _pull request API: https://developer.github.com/v3/pulls/#get-a-single-pull-request
