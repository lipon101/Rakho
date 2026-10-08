"""Tests for the deploy preflight.

The preflight exists to convert a silent failure --- a deploy that never lands,
leaving the previous version serving --- into a named diagnosis. The tests
therefore focus on exactly that: every missing requirement is reported *together*
rather than one per failed deploy, and a broken environment exits non-zero,
because a preflight that passes a broken environment is worse than none at all.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from inventory.management.commands.deploy_preflight import INSECURE_SECRET_KEYS, _checks

HEALTHY = {
    "DJANGO_SECRET_KEY": "a-fully-valid-production-secret-key-of-length",
    "REDIS_URL": "redis://localhost:6379/0",
    "RENDER_EXTERNAL_HOSTNAME": "rakho-api.onrender.com",
    "DATABASE_URL": "postgres://user:pw@host:5432/db",
}

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _run(env: dict[str, str]) -> dict[str, tuple[bool, str]]:
    """Evaluate the checks against exactly ``env`` and nothing else.

    ``clear=True`` is deliberate: leaking the ambient environment would let a
    developer's own exports make an incomplete production environment look
    complete, which is the one mistake this command exists to prevent.
    """
    with mock.patch.dict("os.environ", env, clear=True):
        return {name: (ok, detail) for ok, name, detail in _checks()}


class ChecksTests(SimpleTestCase):
    def test_a_complete_environment_passes_every_check(self):
        results = _run(HEALTHY)
        failed = {name: detail for name, (ok, detail) in results.items() if not ok}
        self.assertEqual(failed, {})

    def test_every_missing_requirement_is_reported_at_once(self):
        """One failed deploy per missing variable would be five wasted deploys."""
        results = _run({})
        failed = {name for name, (ok, _) in results.items() if not ok}
        self.assertGreaterEqual(
            failed,
            {"DJANGO_SECRET_KEY", "ALLOWED_HOSTS", "REDIS_URL", "DATABASE_URL"},
        )

    def test_the_development_secret_key_is_refused_by_name(self):
        for insecure in INSECURE_SECRET_KEYS:
            with self.subTest(key=insecure):
                results = _run({**HEALTHY, "DJANGO_SECRET_KEY": insecure})
                self.assertFalse(results["DJANGO_SECRET_KEY"][0])

    def test_a_short_secret_key_is_refused_with_its_length(self):
        results = _run({**HEALTHY, "DJANGO_SECRET_KEY": "too-short"})
        ok, detail = results["DJANGO_SECRET_KEY"]
        self.assertFalse(ok)
        self.assertIn("9", detail)  # the actual length, so the fix is obvious

    def test_localhost_only_allowed_hosts_is_refused_without_a_render_hostname(self):
        """Django answers 400 to every request in that state, so the deployment
        would be down rather than merely misconfigured."""
        env = {k: v for k, v in HEALTHY.items() if k != "RENDER_EXTERNAL_HOSTNAME"}
        env["ALLOWED_HOSTS"] = "localhost,127.0.0.1"
        self.assertFalse(_run(env)["ALLOWED_HOSTS"][0])

    def test_allowed_hosts_may_come_from_the_render_hostname(self):
        self.assertTrue(_run(HEALTHY)["ALLOWED_HOSTS"][0])

    def test_a_wildcard_cors_origin_is_refused(self):
        """A wildcard would let any site on the internet read a pharmacy's stock
        with a leaked API key."""
        results = _run({**HEALTHY, "CORS_ALLOW_ALL_ORIGINS": "true"})
        self.assertFalse(results["CORS_ALLOW_ALL_ORIGINS"][0])

    def test_redis_is_required_because_throttles_and_the_broker_need_it(self):
        env = {k: v for k, v in HEALTHY.items() if k != "REDIS_URL"}
        self.assertFalse(_run(env)["REDIS_URL"][0])

    def test_the_redis_finding_names_where_the_variable_comes_from(self):
        """A dashboard environment that lost REDIS_URL cannot be fixed from the
        repo, so the finding has to point at where render.yaml sources the
        value and the exact page to set it back on."""
        detail = _run({k: v for k, v in HEALTHY.items() if k != "REDIS_URL"})["REDIS_URL"][1]
        self.assertIn("rakho-redis", detail)
        self.assertIn("Render: rakho-api -> Environment", detail)

    def test_details_name_the_variable_rather_than_describing_the_fault(self):
        """The reader is looking at a failed deploy at the worst moment; the
        message has to say what to set."""
        results = _run({})
        for name in ("DJANGO_SECRET_KEY", "REDIS_URL", "DATABASE_URL"):
            self.assertTrue(results[name][1], f"{name} must carry an actionable detail")


class CommandTests(SimpleTestCase):
    def test_a_broken_environment_exits_non_zero(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(CommandError):
                call_command("deploy_preflight")

    def test_json_output_is_machine_readable_and_reports_not_ready(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("sys.stdout") as stdout:
                with self.assertRaises(CommandError):
                    call_command("deploy_preflight", json=True)
                payload = stdout.write.call_args.args[0]

        parsed = json.loads(payload)
        self.assertFalse(parsed["ready"])
        self.assertTrue(parsed["failures"])
        self.assertIn("variable", parsed["failures"][0])


class ManagePyDiagnosisTests(SimpleTestCase):
    """The diagnosis has to survive Django's own management machinery.

    Regression: ``production.py`` refused to import *inside* ``get_commands()``
    (which reads ``settings.INSTALLED_APPS`` to locate the command), so
    ``manage.py deploy_preflight`` --- written for exactly this moment --- died
    with a raw traceback and the failed-build log named only the single guard
    that fired first. These run the real ``manage.py`` in a fresh interpreter,
    because that is where the failure lived: no in-process test can observe
    what happens before a command runs.
    """

    def _run_manage(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {key: value for key, value in os.environ.items() if key != "DJANGO_SETTINGS_MODULE"}
        env.update(
            {
                # RENDER is what makes manage.py choose production on the host,
                # so the test exercises the same choice the deploy makes.
                "RENDER": "true",
                "DJANGO_SECRET_KEY": HEALTHY["DJANGO_SECRET_KEY"],
                "ALLOWED_HOSTS": "rakho-api.onrender.com",
                "DATABASE_URL": HEALTHY["DATABASE_URL"],
                "CORS_ALLOW_ALL_ORIGINS": "false",
                "REDIS_URL": "",  # the state the failed deploy was actually in
            }
        )
        return subprocess.run(
            [sys.executable, "manage.py", *args],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_a_broken_production_import_is_reported_not_tracebacked(self):
        result = self._run_manage("deploy_preflight")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[FAIL] REDIS_URL", result.stdout)
        # The settings refusal itself, carried through the report:
        self.assertIn("REDIS_URL must be set in production", result.stdout)
        # ...and the exact page to fix it on, the 0ef53ee contract:
        self.assertIn("rakho-api -> Environment", result.stdout)
        self.assertNotIn("Traceback (most recent call last)", result.stdout + result.stderr)
        self.assertIn("deploy preflight failed", result.stderr)

    def test_the_json_report_is_still_machine_readable_after_a_refusal(self):
        result = self._run_manage("deploy_preflight", "--json")

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback (most recent call last)", result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ready"])
        self.assertFalse(payload["settings_imported"])
        self.assertIn("REDIS_URL", payload["import_error"])
        self.assertEqual([failure["variable"] for failure in payload["failures"]], ["REDIS_URL"])
