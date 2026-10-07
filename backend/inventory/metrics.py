"""Prometheus metrics for Rakho (Phase 6).

The Definition of Done asks for metrics and dashboards that are *live*, and for
one screen showing queue depth, error rate and p95 latency together. This module
is the source of those numbers.

Design choices, in order of how much they matter:

1. **The HTTP instrumentation is written here rather than imported.** The
   obvious choice, ``django-prometheus``, ships its own middleware with its own
   opinion about labels, and — more importantly — would leave the metric names
   outside this repository's control. The names below (``rakho_*``) are what the
   dashboards and alerts reference, so they belong in code the team owns.

2. **Never a tenant id in a label.** A label value is a new time series, so one
   label per organisation would turn a single counter into an unbounded set, and
   a Prometheus instance whose series count grows with the customer base is a
   Prometheus instance that falls over on a good day. Requests are labelled by
   method, a *route pattern* (never a raw path — ``/org/invoices/<uuid>/`` and
   not the uuid) and status class. Per-tenant usage is answered by the Phase 4
   usage endpoint, which reads the database, not by metrics.

3. **Path templates, always.** Labelling by ``request.path`` would produce one
   series per uuid, which is the same unbounded problem arriving through the
   front door.

4. **A multiprocess-safe registry when asked for one.** gunicorn runs more than
   one worker by default, and the default Prometheus registry is per-process —
   scraping worker A reports half the traffic with no sign that anything is
   missing. ``prometheus_client.multiprocess`` fixes that, and it needs an
   environment variable and a directory set *before* the registry is built,
   which is why the selection happens at import time here and the deployment
   sets ``PROMETHEUS_MULTIPROC_DIR``.

The module degrades to no-ops if ``prometheus_client`` is absent, so a
deployment that has not installed it still boots and still serves every request.
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

#: Enabled by default; set ``METRICS_ENABLED=false`` to stop instrumenting
#: entirely (useful for a very small deployment that does not scrape).
METRICS_ENABLED = os.environ.get("METRICS_ENABLED", "true").lower() != "false"

#: Bearer token required by ``/metrics/``. A open metrics endpoint publishes
#: route names, traffic volumes and error rates to anyone who asks, which is a
#: map of where to attack; the endpoint therefore refuses every request unless a
#: token is configured *and* presented. Empty token = endpoint 404s, so a
#: forgotten variable fails closed rather than exposing the numbers.
METRICS_TOKEN = os.environ.get("METRICS_TOKEN", "")


#: Mirror onto Django settings so a view can read it from ``settings`` without
#: importing this module's globals. Production can also set it explicitly.
def publish_to_settings():
    """Copy the token onto Django's settings namespace. Idempotent."""
    try:
        from django.conf import settings

        settings.METRICS_TOKEN = METRICS_TOKEN
    except Exception:  # noqa: BLE001 - settings may not be configured yet
        pass


# Set to "1" by the deployment when more than one worker runs. Must be read
# before prometheus_client builds its registry, hence module scope.
MULTIPROCESS = os.environ.get("PROMETHEUS_MULTIPROC_DIR", "") != ""


class _NoopMetric:
    """Stand-in used when prometheus_client is not installed."""

    def labels(self, *args, **kwargs):
        return self

    def inc(self, *args, **kwargs):
        return None

    def dec(self, *args, **kwargs):
        return None

    def observe(self, *args, **kwargs):
        return None

    def set(self, *args, **kwargs):
        return None

    def set_to_current_time(self, *args, **kwargs):
        return None


_AVAILABLE = False
_registry = None
_requests_total = _NoopMetric()
_request_duration = _NoopMetric()
_inflight = _NoopMetric()
_jobs_total = _NoopMetric()
_job_duration = _NoopMetric()
_queue_depth = _NoopMetric()
_db_up = _NoopMetric()
_cache_up = _NoopMetric()
_broker_up = _NoopMetric()
_last_scrape = _NoopMetric()

try:  # pragma: no cover - exercised by presence/absence of the dependency
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

    if MULTIPROCESS:
        from prometheus_client import multiprocess

        _registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(_registry)
    else:
        _registry = CollectorRegistry()

    _AVAILABLE = True
except Exception:  # noqa: BLE001 - a missing/incompatible client must not stop the app
    logger.warning("prometheus_client unavailable; metrics are disabled", exc_info=True)


if _AVAILABLE:
    # Histogram buckets chosen for the DoD's own targets: read p95 < 300ms and
    # write p95 < 800ms. A default bucketing that stops at 10s would put both
    # targets inside one bucket and answer no question anyone is asking.
    _LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 5.0)

    _requests_total = Counter(
        "rakho_http_requests_total",
        "HTTP requests handled, by method, route template and status class.",
        ["method", "route", "status"],
        registry=_registry,
    )
    _request_duration = Histogram(
        "rakho_http_request_duration_seconds",
        "HTTP request latency in seconds, by method and route template.",
        ["method", "route"],
        buckets=_LATENCY_BUCKETS,
        registry=_registry,
    )
    _inflight = Gauge(
        "rakho_http_requests_in_flight",
        "Requests currently being handled by this process.",
        registry=_registry,
    )
    _jobs_total = Counter(
        "rakho_celery_tasks_total",
        "Background tasks finished, by task name and outcome.",
        ["task", "outcome"],
        registry=_registry,
    )
    _job_duration = Histogram(
        "rakho_celery_task_duration_seconds",
        "Background task duration in seconds, by task name.",
        ["task"],
        buckets=(0.05, 0.25, 1.0, 5.0, 15.0, 60.0, 300.0, 1800.0),
        registry=_registry,
    )
    # Queue depth, not queue size: the gauge is set from the broker's own
    # ``LLEN`` on each scrape, so it survives a worker restart and cannot drift.
    _queue_depth = Gauge(
        "rakho_celery_queue_depth",
        "Messages waiting on the default Celery queue.",
        registry=_registry,
    )
    _db_up = Gauge("rakho_dependency_up", "1 when a dependency answered its probe.", ["dependency"], registry=_registry)
    _last_scrape = Gauge(
        "rakho_metrics_last_scrape_timestamp_seconds",
        "Unix time of the last metrics scrape (a staleness canary).",
        registry=_registry,
    )


def metrics_available() -> bool:
    """True when a real registry is in play (not the no-op fallback)."""
    return _AVAILABLE


def render_metrics() -> bytes:
    """Render the registry in the Prometheus text exposition format."""
    if not _AVAILABLE:
        return b"# prometheus_client is not installed\n"
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    _last_scrape.set(time.time())
    return generate_latest(_registry), CONTENT_TYPE_LATEST


def record_request(method: str, route: str, status_code: int, duration: float) -> None:
    """Record one finished request.

    ``route`` must be a URL *pattern* (``org-invoice-detail`` or
    ``/api/v1/org/invoices/<uuid>/``), never a concrete path --- see the module
    docstring for why a raw path is not merely untidy but unbounded.
    """
    if not _AVAILABLE:
        return
    # Status *class* (2xx/4xx/5xx) rather than the exact code: 404 and 403 are
    # the same to a dashboard, and the exact code is already in the access log.
    status_class = f"{status_code // 100}xx"
    _requests_total.labels(method=method, route=route, status=status_class).inc()
    _request_duration.labels(method=method, route=route).observe(duration)


def track_inflight(delta: int) -> None:
    """Adjust the in-flight gauge. Called by the middleware."""
    if not _AVAILABLE:
        return
    if delta > 0:
        _inflight.inc()
    else:
        _inflight.dec()


def record_task(task_name: str, outcome: str, duration: float | None = None) -> None:
    """Record one finished Celery task.

    ``outcome`` is one of ``success`` / ``failure`` / ``retry``. The Celery
    signal handlers in ``inventory.celery_signals`` call this.
    """
    if not _AVAILABLE:
        return
    _jobs_total.labels(task=task_name, outcome=outcome).inc()
    if duration is not None:
        _job_duration.labels(task=task_name).observe(duration)


def set_queue_depth(value: int) -> None:
    """Publish the broker's queue length."""
    if not _AVAILABLE:
        return
    _queue_depth.set(value)


def set_dependency(name: str, up: bool) -> None:
    """Publish a dependency's health (database, cache, broker)."""
    if not _AVAILABLE:
        return
    _db_up.labels(dependency=name).set(1 if up else 0)


def queue_depth_from_broker() -> int | None:
    """Read the waiting-message count straight from Redis.

    Returns ``None`` when there is no broker to ask, which the caller reports as
    "not configured" rather than as zero --- zero would claim a healthy empty
    queue, which is a different statement from "there is no queue".

    The Celery default queue is a Redis *list* (or, with the newer priority
    steps, a sorted set); ``LLEN`` covers the ordinary case, and a ``ZCARD``
    fallback covers a deployment that enabled priorities.
    """
    import redis
    from django.conf import settings

    broker = getattr(settings, "CELERY_BROKER_URL", "")
    if not broker or (broker.startswith("redis://localhost") and not os.environ.get("REDIS_URL")):
        return None
    client = redis.Redis.from_url(broker, socket_connect_timeout=2, socket_timeout=2)
    queue = getattr(settings, "CELERY_DEFAULT_QUEUE", "celery")
    try:
        return int(client.llen(queue))
    except Exception:  # noqa: BLE001 - a sorted-set queue is not a list
        return int(client.zcard(queue))
