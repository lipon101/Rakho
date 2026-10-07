"""The ``/metrics/`` endpoint and the Sentry reachability check (Phase 6).

Kept out of ``views.py`` on purpose: ``views.py`` is the customer-facing API,
where every URL is part of a contract with the Android app. This module serves
machines that scrape and operators who poke, so mixing the two would blur which
paths a client may depend on.
"""

import hmac
import logging

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.views import View

from . import metrics

logger = logging.getLogger(__name__)


class MetricsView(View):
    """Serve the Prometheus registry, behind a bearer token.

    An open ``/metrics`` endpoint is a reconnaissance gift: it publishes the
    route table, the request volumes and the error rates, which together say
    where the load sits and which endpoints are already unhappy. The endpoint
    therefore refuses every request unless ``METRICS_TOKEN`` is configured *and*
    presented --- an unset token 404s rather than defaulting open, so a
    forgotten environment variable fails closed.

    Readiness is deliberately *not* reused as the guard. A scraper is not a load
    balancer: it must be able to fetch numbers precisely when the service is
    unhealthy, which is the moment those numbers are worth having.
    """

    def get(self, request):
        configured = getattr(settings, "METRICS_TOKEN", "") or metrics.METRICS_TOKEN
        if not configured:
            # 404 rather than 403: an endpoint that does not exist tells an
            # anonymous prober far less than one that exists and refuses.
            raise Http404("Not found.")

        presented = self._presented_token(request)
        # Constant-time compare: a plain ``==`` leaks the token a character at a
        # time to an attacker who can measure response latency.
        if not presented or not hmac.compare_digest(str(presented), str(configured)):
            logger.warning("metrics: rejected request with a missing or wrong token")
            return HttpResponse("Forbidden.\n", status=403, content_type="text/plain")

        # Refresh the dependency gauges from the live probes, so the scraped
        # file reflects the state at scrape time rather than at boot.
        self._publish_dependency_health()

        body, content_type = metrics.render_metrics()
        return HttpResponse(body, content_type=content_type)

    @staticmethod
    def _presented_token(request):
        """The caller's token, from ``Authorization: Bearer`` or ``?token=``.

        Both are accepted because Prometheus's ``bearer_token`` configuration is
        the tidy option while a hand-run ``curl`` during an incident is the
        hurried one, and demanding a header at that moment helps nobody.
        """
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return request.GET.get("token", "")

    @staticmethod
    def _publish_dependency_health():
        """Set ``rakho_dependency_up`` from the same probes ``/ready/`` runs.

        One implementation of "is the database up", used by both the probe that
        a load balancer reads and the gauge that a dashboard reads; two
        implementations would eventually disagree, and the disagreement would be
        discovered during an incident.
        """
        from inventory.views import ReadinessView

        if not metrics.metrics_available():
            return
        database = ReadinessView._check_database()
        cache = ReadinessView._check_cache()
        metrics.set_dependency("database", bool(database.get("ok")))
        metrics.set_dependency("cache", bool(cache.get("ok")))
        try:
            depth = metrics.queue_depth_from_broker()
        except Exception:  # noqa: BLE001 - a broker probe must never 500 the scrape
            depth = None
        if depth is not None:
            metrics.set_queue_depth(depth)


def sentry_status():
    """Report whether Sentry is wired up, without sending anything.

    Used by the deployment smoke test and by ``manage.py verify_sentry``. The
    distinction that matters is between *configured* and *reaching* Sentry:
    ``SENTRY_DSN`` being set proves nothing about whether events arrive, which
    is why the command that calls this also sends one.
    """
    dsn = getattr(settings, "SENTRY_DSN", "")
    client = None
    try:
        import sentry_sdk

        client = sentry_sdk.Hub.current.client
    except Exception:  # noqa: BLE001 - the SDK is optional at runtime
        client = None
    return {
        "configured": bool(dsn),
        "sdk_installed": client is not None,
        # ``send_default_pii=False`` is a rule, not a preference: a Sentry event
        # carries request data, and Rakho holds customer phone numbers and
        # payment references. Reported here so the smoke test can assert it.
        "send_default_pii": bool(getattr(client, "options", {}).get("send_default_pii", False)) if client else False,
        "environment": getattr(client, "options", {}).get("environment", "") if client else "",
    }


class VersionView(View):
    """Report the commit this process is actually running.

    A deploy is only verifiable against the running artefact, never against the
    dashboard that claims the deploy succeeded. This endpoint exists so
    ``scripts/render_deploy.py --expect-commit <sha>`` can poll the live host and
    wait for the *new* build to answer --- which is the difference between "the
    deploy was triggered" and "the new code is serving traffic".

    Deliberately public: the commit sha is already in the public GitHub
    repository, so hiding it buys nothing, and a check that needs a secret is a
    check that gets skipped during the incident when it finally matters. No
    secret, no internal host and no configuration is returned --- only the
    build's own identity.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request):
        return JsonResponse(
            {
                "service": "pharmacy-api",
                "version": "1.0.0",
                "commit": getattr(settings, "GIT_COMMIT", ""),
                "branch": getattr(settings, "GIT_BRANCH", ""),
                "environment": getattr(settings, "SENTRY_ENVIRONMENT", ""),
                "rls_enabled": bool(getattr(settings, "RLS_ENABLED", False)),
            }
        )


def sentry_check_view(request):
    """A tiny JSON endpoint the deploy smoke test can hit.

    Returns the same facts as ``sentry_status()``. Token-guarded with the same
    ``METRICS_TOKEN``, because "is error reporting configured" is operational
    detail a stranger has no reason to read.
    """
    configured = getattr(settings, "METRICS_TOKEN", "") or metrics.METRICS_TOKEN
    if not configured:
        raise Http404("Not found.")
    header = request.headers.get("Authorization", "")
    presented = header[7:].strip() if header.lower().startswith("bearer ") else request.GET.get("token", "")
    if not presented or not hmac.compare_digest(str(presented), str(configured)):
        return HttpResponse("Forbidden.\n", status=403, content_type="text/plain")
    return JsonResponse(sentry_status())
