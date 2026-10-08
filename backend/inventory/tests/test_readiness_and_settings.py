"""Sprint 0.2 / 0.3 invariants: settings resolution and the readiness probe.

Both pieces are the kind of infrastructure that silently stops working. A
settings resolver that quietly returns the permissive module, or a readiness
probe that answers 200 while the database is unreachable, produces no error at
the moment it breaks --- only an incident later. So each one gets a test that
fails for exactly that reason.

The settings tests run in a fresh interpreter: the resolver reads ``os.environ``
at import time and Django caches the settings object, so anything asserted
in-process would be asserting the *test runner's* configuration rather than the
one under test.
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase

from inventory.views import ReadinessView

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _run_subprocess(code, **environment):
    """Run ``code`` in a fresh interpreter with a controlled environment."""
    env = {key: value for key, value in os.environ.items() if key not in environment}
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env.update({key: str(value) for key, value in environment.items()})
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


class SettingsResolutionTests(SimpleTestCase):
    """The environments the resolver has to tell apart."""

    SECRET = "test-only-key-0000000000000000000000"

    def test_local_module_refuses_a_debug_false_environment(self):
        """Loaded as the development module while DEBUG=false: refuse loudly.

        This is the deploy-by-accident case --- the permissive module selected
        on a server --- so it is worth more than the happy path.
        """
        result = _run_subprocess(
            "import django; django.setup()",
            DJANGO_SETTINGS_MODULE="config.settings.local",
            DEBUG="false",
            DJANGO_TESTING="false",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("config.settings.production", result.stderr)

    def test_local_module_loads_for_a_developer(self):
        result = _run_subprocess(
            "import django; django.setup(); from django.conf import settings; print(settings.DEBUG)",
            DJANGO_SETTINGS_MODULE="config.settings.local",
            DEBUG="true",
            DJANGO_TESTING="false",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("True", result.stdout)

    def test_production_refuses_a_placeholder_secret(self):
        result = _run_subprocess(
            "import django; django.setup()",
            DJANGO_SETTINGS_MODULE="config.settings.production",
            DJANGO_SECRET_KEY="unsafe-development-only-key-change-me",
            DEBUG="false",
            ALLOWED_HOSTS="rakho.example.com",
            REDIS_URL="redis://example.invalid:6379/0",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_production_refuses_a_short_secret(self):
        result = _run_subprocess(
            "import django; django.setup()",
            DJANGO_SETTINGS_MODULE="config.settings.production",
            DJANGO_SECRET_KEY="too-short",
            DEBUG="false",
            ALLOWED_HOSTS="rakho.example.com",
            REDIS_URL="redis://example.invalid:6379/0",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at least 32 characters", result.stderr)

    def test_production_refuses_an_empty_allowed_hosts(self):
        """With DEBUG off Django answers 400 to everything: refuse at import."""
        result = _run_subprocess(
            "import django; django.setup()",
            DJANGO_SETTINGS_MODULE="config.settings.production",
            DJANGO_SECRET_KEY=self.SECRET,
            DEBUG="false",
            ALLOWED_HOSTS="",
            REDIS_URL="redis://example.invalid:6379/0",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ALLOWED_HOSTS", result.stderr)

    def test_production_refuses_a_wildcard_cors(self):
        result = _run_subprocess(
            "import django; django.setup()",
            DJANGO_SETTINGS_MODULE="config.settings.production",
            DJANGO_SECRET_KEY=self.SECRET,
            DEBUG="false",
            ALLOWED_HOSTS="rakho.example.com",
            REDIS_URL="redis://example.invalid:6379/0",
            CORS_ALLOW_ALL_ORIGINS="true",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CORS_ALLOW_ALL_ORIGINS", result.stderr)

    def test_production_requires_redis(self):
        result = _run_subprocess(
            "import django; django.setup()",
            DJANGO_SETTINGS_MODULE="config.settings.production",
            DJANGO_SECRET_KEY=self.SECRET,
            DEBUG="false",
            ALLOWED_HOSTS="rakho.example.com",
            REDIS_URL="",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REDIS_URL", result.stderr)

    def test_production_refuses_the_sqlite_fallback(self):
        """A missing DATABASE_URL would boot on a throwaway file --- every
        write lost at the next restart, which is a demo database wearing a
        production URL. The checklist promises "Startup fails" here."""
        result = _run_subprocess(
            "import django; django.setup()",
            DJANGO_SETTINGS_MODULE="config.settings.production",
            DJANGO_SECRET_KEY=self.SECRET,
            DEBUG="false",
            ALLOWED_HOSTS="rakho.example.com",
            REDIS_URL="redis://example.invalid:6379/0",
            DATABASE_URL="",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_URL", result.stderr)

    def test_production_loads_when_configured(self):
        """The guard must be a guard, not a wall: a real config has to load."""
        result = _run_subprocess(
            "import django; django.setup(); from django.conf import settings; " "print(settings.DEBUG, settings.CACHES['default']['BACKEND'])",
            DJANGO_SETTINGS_MODULE="config.settings.production",
            DJANGO_SECRET_KEY=self.SECRET,
            DEBUG="false",
            ALLOWED_HOSTS="rakho.example.com",
            SITE_URL="https://rakho.example.com",
            REDIS_URL="redis://example.invalid:6379/0",
            DATABASE_URL="postgres://user:pw@host:5432/db",
            SENTRY_DSN="",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("False", result.stdout)
        self.assertIn("RedisCache", result.stdout)


class SettingsPackageResolverTests(SimpleTestCase):
    """Naming the package itself must never be the permissive choice.

    These set the literal ``config.settings`` rather than leaving the variable
    blank, because that is the scenario that actually occurs: ``manage.py``,
    ``wsgi.py`` and ``config/celery.py`` all fill the variable in when nothing
    else has, so the only way to arrive at the package resolver is to name the
    package explicitly.
    """

    SECRET = "test-only-key-0000000000000000000000"

    def test_package_resolves_to_production_without_debug(self):
        result = _run_subprocess(
            "import config.settings as s; print('DEBUG' in dir(s))",
            DJANGO_SETTINGS_MODULE="config.settings",
            DJANGO_SECRET_KEY=self.SECRET,
            DEBUG="false",
            DJANGO_TESTING="false",
            ALLOWED_HOSTS="rakho.example.com",
            SITE_URL="https://rakho.example.com",
            REDIS_URL="redis://example.invalid:6379/0",
            DATABASE_URL="postgres://user:pw@host:5432/db",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("True", result.stdout)

    def test_package_refuses_a_wildcard_cors(self):
        """Proof the imported module is production, not merely that it imported."""
        result = _run_subprocess(
            "import config.settings",
            DJANGO_SETTINGS_MODULE="config.settings",
            DJANGO_SECRET_KEY=self.SECRET,
            DEBUG="false",
            DJANGO_TESTING="false",
            ALLOWED_HOSTS="rakho.example.com",
            SITE_URL="https://rakho.example.com",
            REDIS_URL="redis://example.invalid:6379/0",
            CORS_ALLOW_ALL_ORIGINS="true",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CORS_ALLOW_ALL_ORIGINS", result.stderr)

    def test_package_resolves_to_local_when_debug_is_on(self):
        """A developer naming the package still gets the convenient module."""
        result = _run_subprocess(
            "import config.settings as s; print(s.DEBUG, 'local' in s.SECRET_KEY)",
            DJANGO_SETTINGS_MODULE="config.settings",
            DEBUG="true",
            DJANGO_TESTING="false",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("True", result.stdout)

    def test_naming_a_submodule_leaves_the_package_namespace_empty(self):
        """The guard that made ``manage.py test`` runnable again.

        Importing ``config.settings.local`` executes ``config.settings`` first.
        If that ran the resolver, it would import *production* and trip the
        hardening checks --- so the package must stay inert when a submodule is
        named.
        """
        result = _run_subprocess(
            "import config.settings.local; import sys; " "print('DEBUG' in dir(sys.modules['config.settings']))",
            DJANGO_SETTINGS_MODULE="config.settings.local",
            DEBUG="true",
            DJANGO_TESTING="false",
            RENDER_EXTERNAL_HOSTNAME="",
            ALLOWED_HOSTS="",
            REDIS_URL="",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("False", result.stdout)


class ReadinessProbeTests(TestCase):
    """The probe has to answer the question it claims to answer.

    A ``TestCase`` (not ``SimpleTestCase``) because the database check opens a
    real connection, which Django deliberately forbids in a test class that has
    no database.
    """

    url = "/api/v1/ready/"

    def test_reports_each_dependency_by_name(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (200, 503))
        body = response.json()
        self.assertIn("status", body)
        # Named individually, so the response says *which* dependency is down
        # rather than only that something is.
        for dependency in ("database", "cache", "broker"):
            self.assertIn(dependency, body["checks"], msg=f"{dependency} is not reported")
            self.assertIn("ok", body["checks"][dependency])

    def test_database_is_reachable_under_test(self):
        response = self.client.get(self.url)
        self.assertTrue(response.json()["checks"]["database"]["ok"])

    def test_ready_under_a_test_configuration(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")

    def test_returns_503_when_the_database_is_down(self):
        """The whole point: alive but useless must not answer 200.

        The check helper is replaced rather than the database itself. What is
        under test is the *aggregation* --- one failed dependency must make the
        whole probe unhealthy --- and pointing the connection at an unreachable
        host would instead test the driver's error handling, which is not what
        a load balancer depends on.
        """
        with mock.patch.object(ReadinessView, "_check_database", return_value={"ok": False, "detail": "OperationalError"}):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["status"], "not_ready")
        self.assertFalse(body["checks"]["database"]["ok"])

    def test_returns_503_when_the_cache_is_down(self):
        """A broken cache is not cosmetic: DRF's throttles live in it."""
        with mock.patch.object(ReadinessView, "_check_cache", return_value={"ok": False, "detail": "ConnectionError"}):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["checks"]["cache"]["ok"])

    def test_each_dependency_is_reported_independently(self):
        """A failed broker must not hide a healthy database, or the log would
        say only that *something* was wrong."""
        with mock.patch.object(ReadinessView, "_check_broker", return_value={"ok": False, "configured": True, "detail": "TimeoutError"}):
            response = self.client.get(self.url)
        body = response.json()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(body["checks"]["broker"]["ok"])
        self.assertTrue(body["checks"]["database"]["ok"])

    def test_optional_broker_absence_is_not_a_failure(self):
        """A single-instance deployment without Redis still serves correctly."""
        response = self.client.get(self.url)
        broker = response.json()["checks"]["broker"]
        if not broker.get("configured", False):
            self.assertTrue(broker["ok"])

    def test_probe_needs_no_authentication(self):
        """A load balancer has no API key, and a probe it cannot read is useless."""
        response = self.client.get(self.url)
        self.assertNotIn(response.status_code, (401, 403))

    def test_probe_is_not_rate_limited(self):
        """A monitor polls this every few seconds; a throttle would page someone."""
        for _ in range(5):
            response = self.client.get(self.url)
        self.assertNotEqual(response.status_code, 429)
