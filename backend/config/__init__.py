"""The Celery application, and the reason it is imported here.

Django's ``manage.py`` imports ``config`` before it loads settings, so importing
the Celery app from this package is what guarantees the ``@shared_task``
decorator has an app to attach to. Without it every task is bound at import time
to the default app --- which is a different object from the one the worker
starts --- and the symptom is not an error but silence: ``.delay()`` returns a
result id and nothing ever runs it.

Django is set up inside ``config/celery.py`` before the app is built, so the
settings are available when the broker URL and the task annotations are read.
"""

from config.celery import app as celery_app

__all__ = ("celery_app",)
