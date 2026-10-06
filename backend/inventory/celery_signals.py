"""Celery signal handlers that feed the Prometheus metrics (Phase 6).

Connected from ``InventoryConfig.ready`` so that every process which imports the
app --- the web worker, the Celery worker, and the test runner --- publishes the
same series. Connecting these from ``tasks.py`` instead would have instrumented
only the worker, and the dashboard's task panel would have gone blank the moment
it was read from anywhere else.

Two signals are used rather than a decorator on each task:

* ``task_success`` / ``task_failure`` / ``task_retry`` give the outcome, which is
  what the alert rule reads ("task failure rate over 5%").
* ``task_prerun`` records a start time on the request so the duration measured in
  the terminal signal is the task body, excluding the queue wait --- the queue
  wait is already a gauge of its own, and adding it to the body's latency would
  hide a slow task behind a slow queue.

Everything here is defensive. A metrics failure must never turn a successful
background job into a failed one, so each handler swallows its own exceptions.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

#: Where ``task_prerun`` stashes the monotonic start time. A dict keyed by task
#: id rather than an attribute on the task instance: with ``acks_late`` a worker
#: may hold several instances of the same task, and an attribute would have them
#: overwrite one another's start time.
_STARTED: dict[str, float] = {}


def _task_name(sender) -> str:
    """The task's registered name, falling back to its Python path."""
    return getattr(sender, "name", None) or sender.__class__.__name__


def _duration(task_id: str) -> float | None:
    started = _STARTED.pop(task_id, None)
    if started is None:
        return None
    return max(time.monotonic() - started, 0.0)


def task_prerun_handler(sender=None, task_id=None, **kwargs):  # noqa: ARG001
    """Stamp the moment the task body begins."""
    try:
        if task_id:
            _STARTED[task_id] = time.monotonic()
    except Exception:  # noqa: BLE001
        logger.debug("metrics: could not record task start", exc_info=True)


def task_success_handler(sender=None, task_id=None, **kwargs):  # noqa: ARG001
    """Count a finished task and observe its duration."""
    try:
        from inventory import metrics

        metrics.record_task(_task_name(sender), "success", _duration(task_id))
    except Exception:  # noqa: BLE001
        logger.debug("metrics: could not record task success", exc_info=True)


def task_failure_handler(sender=None, task_id=None, **kwargs):  # noqa: ARG001
    """Count a failed task.

    Failure is counted and *not* raised further: the exception is already in the
    log with its traceback, and re-raising from a signal handler would turn one
    failure into a worker-level crash.
    """
    try:
        from inventory import metrics

        metrics.record_task(_task_name(sender), "failure", _duration(task_id))
    except Exception:  # noqa: BLE001
        logger.debug("metrics: could not record task failure", exc_info=True)


def task_retry_handler(sender=None, task_id=None, **kwargs):  # noqa: ARG001
    """Count a retry.

    Counted separately from a failure on purpose: a task that retries and
    succeeds is not an incident, while a rising retry rate is the earliest
    warning that a dependency is degrading.
    """
    try:
        from inventory import metrics

        # A retry is not the end of this attempt's lifecycle --- the body will
        # run again --- so the start time is consumed here to keep the durations
        # per-attempt rather than cumulative.
        metrics.record_task(_task_name(sender), "retry", _duration(task_id))
    except Exception:  # noqa: BLE001
        logger.debug("metrics: could not record task retry", exc_info=True)


def connect_signals():
    """Register the handlers. Safe to call more than once.

    ``dispatch_uid`` makes the registration idempotent: Django can call
    ``ready()`` more than once in a long-lived process (a reloader, a test that
    reconfigures the app), and without it every signal would fire the handler
    once per registration and multiply the counters.
    """
    from celery.signals import task_failure, task_prerun, task_retry, task_success

    task_prerun.connect(task_prerun_handler, dispatch_uid="rakho.metrics.prerun")
    task_success.connect(task_success_handler, dispatch_uid="rakho.metrics.success")
    task_failure.connect(task_failure_handler, dispatch_uid="rakho.metrics.failure")
    task_retry.connect(task_retry_handler, dispatch_uid="rakho.metrics.retry")
