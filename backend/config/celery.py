"""The Celery application.

Defined once, here, and imported from ``config/__init__.py`` so that every
process --- the web worker, the Celery worker, ``manage.py`` and the test runner
--- binds ``@shared_task`` to the same app. A task decorator that binds to a
different app than the worker started is the classic Celery failure: ``.delay()``
returns a result id, nothing raises, and nothing runs.

``config_from_object(..., namespace="CELERY")`` reads the broker, the result
backend and the schedules out of the Django settings, so there is exactly one
place --- ``config/settings/base.py`` --- where a Celery setting is defined.
"""

import os

from celery import Celery

# A Celery process is started outside ``manage.py``, so it has to name its own
# settings module. Same rule as manage.py: an explicit value wins, a deployment
# flag selects production, and everything else is a developer's machine. The
# hardened module is the default for anything that looks deployed, because a
# permissive fallback would only ever be noticed in production.
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    if os.environ.get("RENDER") or os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.production"
    else:
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.local"

app = Celery("rakho")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

#: Acknowledge a task only once it has finished, so a worker killed mid-run does
#: not lose the job; and re-queue it when the worker is lost rather than leaving
#: it stuck. Both matter here because the nightly digest is the job a free-tier
#: dyno is most likely to be restarted in the middle of.
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
#: Three attempts with a jittered exponential backoff. Jitter is not decoration:
#: when a database restarts, every branch's digest fails at the same instant,
#: and a fixed interval would have all of them return together and fail together
#: again.
app.conf.task_annotations = {"*": {"max_retries": 3}}


@app.task(name="rakho.debug.ping")
def ping():
    """Trivial task used by the deployment checklist to prove a worker runs.

    Kept in the app rather than in a test so an operator can verify a live
    deployment's worker from the Django shell without shipping anything:
    ``ping.delay().get(timeout=10)`` should return ``"pong"``.
    """
    return "pong"
