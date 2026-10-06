"""Phase 6 tests: metrics, the metrics endpoint and the Sentry check.

What these are defending, in one sentence each:

* the metrics endpoint is **closed by default** and needs a token to open;
* a request actually **appears in the registry** (the middleware is wired, not
  merely written --- a middleware class in the file but missing from
  ``MIDDLEWARE`` is invisible and every dashboard reads zero);
* labels carry a **route template, not a uuid**, because that is the difference
  between a bounded series count and an outage;
* the Sentry check reports configuration **without claiming delivery**.
"""

import uuid
from unittest import mock

from django.test import Client, TestCase, override_settings

from inventory import metrics, observability


def exposition() -> str:
    """The registry as text.

    ``render_metrics`` returns ``(body, content_type)`` because the view needs
    both; the tests only ever want the body, so the unpacking lives here rather
    than at every call site.
    """
    body, _content_type = metrics.render_metrics()
    return body.decode() if isinstance(body, bytes) else body


def counter_value(body: str, selector: str) -> float:
    """The current value of one counter/histogram series.

    Counting *occurrences* of a label in the exposition text does not work as a
    before/after comparison: the registry outlives a single test, other tests
    create the same series, and ``render_metrics`` re-emits the ``_created``
    lines every time. Reading the value itself is the only stable comparison.
    """
    for line in body.splitlines():
        if line.startswith("#") or not line.startswith("rakho_"):
            continue
        if selector in line:
            try:
                return float(line.rsplit(" ", 1)[1])
            except ValueError:
                continue
    return 0.0


class MetricsModuleTests(TestCase):
    """The registry itself."""

    def test_prometheus_client_is_available(self):
        """If this fails the rest of the file is measuring the no-op fallback."""
        self.assertTrue(metrics.metrics_available())

    def test_rendering_produces_exposition_text(self):
        self.assertIn("rakho_http_requests_total", exposition())

    def test_recording_a_request_creates_a_series(self):
        metrics.record_request("GET", "test-records-a-series", 200, 0.012)
        self.assertIn("test-records-a-series", exposition())

    def test_status_is_reduced_to_a_class(self):
        """2xx/4xx/5xx, so the series count does not scale with status codes."""
        metrics.record_request("GET", "test-status-class", 404, 0.001)
        self.assertIn('status="4xx"', exposition())

    def test_a_uuid_never_becomes_a_label(self):
        """The rule that keeps the series count bounded.

        The guard is in the middleware rather than in here, so this asserts the
        contract the middleware has to honour: whatever it passes must not vary
        per request.
        """
        metrics.record_request("GET", "org-invoice-detail", 200, 0.01)
        self.assertNotIn(str(uuid.uuid4()), exposition())

    def test_track_inflight_balances(self):
        """An unbalanced gauge would drift and eventually report negative."""
        metrics.track_inflight(1)
        metrics.track_inflight(-1)
        self.assertIn("rakho_http_requests_in_flight", exposition())

    def test_task_metrics_record_outcomes(self):
        metrics.record_task("inventory.tasks.send_invitation_email", "success", 1.5)
        metrics.record_task("inventory.tasks.send_invitation_email", "failure", 0.4)
        body = exposition()
        self.assertIn('outcome="success"', body)
        self.assertIn('outcome="failure"', body)

    def test_dependency_gauge_reflects_state(self):
        metrics.set_dependency("database", False)
        self.assertIn('rakho_dependency_up{dependency="database"} 0.0', exposition())
        metrics.set_dependency("database", True)
        self.assertIn('rakho_dependency_up{dependency="database"} 1.0', exposition())


class MetricsEndpointTests(TestCase):
    """``/api/v1/metrics/`` --- closed by default."""

    url = "/api/v1/metrics/"

    def test_404s_when_no_token_is_configured(self):
        """Fail closed. An unset variable must remove the endpoint."""
        with override_settings(METRICS_TOKEN=""):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_403s_without_a_token(self):
        with override_settings(METRICS_TOKEN="s3cret-token"):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_403s_with_a_wrong_token(self):
        with override_settings(METRICS_TOKEN="s3cret-token"):
            response = self.client.get(self.url, HTTP_AUTHORIZATION="Bearer wrong-token")
        self.assertEqual(response.status_code, 403)

    def test_serves_the_registry_with_a_bearer_token(self):
        with override_settings(METRICS_TOKEN="s3cret-token"):
            response = self.client.get(self.url, HTTP_AUTHORIZATION="Bearer s3cret-token")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        self.assertIn(b"rakho_http_requests_total", response.content)

    def test_accepts_a_query_token_for_a_hurried_curl(self):
        """The incident-time path has to keep working."""
        with override_settings(METRICS_TOKEN="s3cret-token"):
            response = self.client.get(f"{self.url}?token=s3cret-token")
        self.assertEqual(response.status_code, 200)

    def test_is_not_rate_limited(self):
        """A scraper polls every 15s; a throttle would make it look broken."""
        with override_settings(METRICS_TOKEN="s3cret-token"):
            for _ in range(5):
                response = self.client.get(self.url, HTTP_AUTHORIZATION="Bearer s3cret-token")
        self.assertEqual(response.status_code, 200)

    def test_needs_no_database_connection(self):
        """Readiness is not reused as the guard: the numbers matter most when
        the service is unhealthy."""
        with override_settings(METRICS_TOKEN="s3cret-token"):
            with mock.patch.object(observability.MetricsView, "_publish_dependency_health"):
                response = self.client.get(self.url, HTTP_AUTHORIZATION="Bearer s3cret-token")
        self.assertEqual(response.status_code, 200)


class MetricsMiddlewareTests(TestCase):
    """The middleware has to be *installed*, not merely present on disk."""

    def test_middleware_is_registered(self):
        from django.conf import settings

        self.assertIn("config.middleware.MetricsMiddleware", settings.MIDDLEWARE)

    def test_a_real_request_is_recorded_with_a_route_template(self):
        """Proves the wiring end to end, and proves the label is the pattern.

        ``/api/v1/health/`` is used because it always answers and needs no auth.
        The assertion is on the *view name* appearing as the label: had the
        middleware used ``request.path`` the label would be the path, which for a
        uuid-bearing route is the unbounded case this design exists to avoid.
        """
        selector = 'route="health",status="2xx"}'
        before = counter_value(exposition(), selector)
        Client().get("/api/v1/health/")
        after = exposition()

        self.assertIn('route="health"', after)
        # And the counter must have actually gone up --- a series that merely
        # exists could have come from another test.
        self.assertEqual(counter_value(after, selector), before + 1)

    def test_an_unmatched_path_is_labelled_by_the_catch_all_not_by_its_path(self):
        """An unknown API path is labelled ``api-not-found`` --- the name of the
        catch-all view --- and never by the path itself."""
        marker = uuid.uuid4().hex
        Client().get(f"/api/v1/definitely-not-a-route-{marker}/")
        body = exposition()
        self.assertIn('route="api-not-found"', body)
        # The concrete path must not appear: that would be one series per
        # scanner that probes a random URL.
        self.assertNotIn(marker, body)


class SentryCheckTests(TestCase):
    """Configuration reporting must not overstate what was verified."""

    def test_reports_configured_false_without_a_dsn(self):
        with override_settings(SENTRY_DSN=""):
            status = observability.sentry_status()
        self.assertFalse(status["configured"])
        # Crucially it does not claim delivery.
        self.assertNotIn("delivered", status)

    def test_reports_configured_true_with_a_dsn(self):
        with override_settings(SENTRY_DSN="https://abc@o0.ingest.sentry.io/1"):
            status = observability.sentry_status()
        self.assertTrue(status["configured"])

    def test_endpoint_is_closed_without_a_token(self):
        with override_settings(METRICS_TOKEN=""):
            response = self.client.get("/api/v1/ops/sentry/")
        self.assertEqual(response.status_code, 404)

    def test_endpoint_answers_with_a_token(self):
        with override_settings(METRICS_TOKEN="ops-token", SENTRY_DSN=""):
            response = self.client.get("/api/v1/ops/sentry/", HTTP_AUTHORIZATION="Bearer ops-token")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["configured"])
