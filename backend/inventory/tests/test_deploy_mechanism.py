"""Tests for the deploy mechanism (Phase 6 follow-up): build identity + the hook script.

Two things are being protected here, and both are about a *check* rather than a
feature, so they are easy to get subtly wrong in a way nobody notices:

* **`/api/v1/version/` must report the truth.** The entire deploy verification
  rests on it. A version endpoint that reported a hard-coded string would make
  ``render_deploy.py --expect-commit`` pass on every build --- including the
  builds that never deployed --- which is worse than having no check at all,
  because it would be trusted.
* **`render_deploy.py` must refuse to invent a hook.** The hook URL is a
  credential. If the script guessed a URL when the variable was missing, the
  failure mode would be a POST to an unknown host, not a clear message.

The polling loop, the retry semantics and the "which commit is live" comparison
are pure functions of a URL, so they are tested directly against a localhost
HTTP server instead of a mocked ``urlopen``. A mock would assert that a call was
made; the real server asserts what the call *did*.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings

# ── The version endpoint ─────────────────────────────────────────────────────


class VersionEndpointTests(TestCase):
    """`/api/v1/version/` reports the process's own build identity."""

    def test_reports_the_configured_commit(self):
        with override_settings(GIT_COMMIT="abc1234def", GIT_BRANCH="main", RLS_ENABLED=True):
            response = self.client.get("/api/v1/version/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["commit"], "abc1234def")
        self.assertEqual(body["branch"], "main")
        self.assertTrue(body["rls_enabled"])

    def test_is_public_so_the_deploy_check_needs_no_secret(self):
        """A check that requires a credential is a check that gets skipped."""
        response = self.client.get("/api/v1/version/")
        self.assertEqual(response.status_code, 200)

    def test_rls_false_is_reported_as_false_not_absent(self):
        """The rollout runbook reads this field, so ``false`` must be present.

        "missing" and "false" would look identical to a careless reader, and the
        difference decides whether an operator thinks the RLS switch was applied.
        """
        with override_settings(RLS_ENABLED=False):
            body = self.client.get("/api/v1/version/").json()
        self.assertIn("rls_enabled", body)
        self.assertFalse(body["rls_enabled"])

    def test_an_unset_commit_is_reported_as_empty_not_invented(self):
        with override_settings(GIT_COMMIT=""):
            body = self.client.get("/api/v1/version/").json()
        self.assertEqual(body["commit"], "")

    def test_leaks_no_secrets(self):
        """The endpoint must stay a build identity, not a configuration dump."""
        body = self.client.get("/api/v1/version/").json()
        for forbidden in ("secret", "token", "password", "dsn", "key"):
            self.assertNotIn(forbidden, json.dumps(body).lower())


# ── A localhost HTTP server, for exercising the real polling code ────────────


class _Handler(BaseHTTPRequestHandler):
    """A tiny stand-in for Render: records hook POSTs, serves a chosen commit."""

    commit = ""
    triggers = 0
    #: When True, ``/api/v1/version/`` answers 404 --- exactly what the live host
    #: did while it was still running a build from before the endpoint existed.
    hide_version = False
    #: The status the hook POST answers with. 202 is what the real Render hook
    #: returns, and an earlier script revision accepted only 200/201 --- so it
    #: rejected the real answer and started duplicate builds — a failure mode
    #: worth freezing in a test.
    hook_status = 202

    def do_POST(self) -> None:  # noqa: N802
        # Only the real hook path accepts a trigger, so a wrong URL behaves the
        # way Render's does --- a 404, which the script must treat as
        # non-transient rather than retrying forever.
        if not self.path.startswith("/hook"):
            self._send(404, {"error": "not found"})
            return
        type(self).triggers += 1
        self._send(type(self).hook_status, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/v1/version/") and not type(self).hide_version:
            self._send(200, {"commit": type(self).commit, "branch": "main", "rls_enabled": False})
        else:
            self._send(404, {"error": "not found"})

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A002
        return


def _load_script():
    """Import ``scripts/render_deploy.py`` as a module, without a package."""
    # `inventory/tests/<this file>` -> tests -> inventory -> backend, which is
    # where `scripts/` lives; one level less would look inside the app package.
    path = Path(__file__).resolve().parents[2] / "scripts" / "render_deploy.py"
    spec = importlib.util.spec_from_file_location("render_deploy_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeployScriptTests(SimpleTestCase):
    """The hook trigger and the commit check, against a real localhost server."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = _load_script()
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        super().tearDownClass()

    def setUp(self):
        _Handler.triggers = 0
        _Handler.commit = ""
        _Handler.hide_version = False
        _Handler.hook_status = 202
        # Point the encrypted store at a path that does not exist, so these tests
        # see "no store configured" and fall back to the environment variable.
        # Without this, a developer who has stored the real hook at the default
        # path would make the script resolve it --- and the "missing hook" test
        # would POST to the real Render hook and then poll for fifteen minutes.
        # A test must never be able to trigger a real deploy.
        self._saved_store = os.environ.get("RAKHO_SECRET_STORE")
        os.environ["RAKHO_SECRET_STORE"] = str(Path(tempfile.gettempdir()) / "rakho-no-such-store" / "deploy.enc")

    def tearDown(self):
        if self._saved_store is None:
            os.environ.pop("RAKHO_SECRET_STORE", None)
        else:
            os.environ["RAKHO_SECRET_STORE"] = self._saved_store

    def test_the_hook_202_is_accepted_not_retried(self):
        """Render answers **202 Accepted**; treating it as a failure starts
        duplicate builds and reports a false failure on a deploy that worked."""
        self.assertTrue(self.script.trigger_hook(f"{self.base}/hook", attempts=3, backoff=0))
        self.assertEqual(_Handler.triggers, 1)

    def test_the_hook_200_is_still_accepted(self):
        _Handler.hook_status = 200
        self.assertTrue(self.script.trigger_hook(f"{self.base}/hook", attempts=1))

    def test_reads_the_commit_the_host_is_serving(self):
        _Handler.commit = "deadbeefcafe"
        body = self.script.read_live_commit(self.base)
        self.assertIsNotNone(body)
        self.assertEqual(body["commit"], "deadbeefcafe")

    def test_a_host_without_the_endpoint_reports_none_rather_than_a_guess(self):
        """404 must read as "cannot say", which is how the old build presents."""
        _Handler.hide_version = True
        self.assertIsNone(self.script.read_live_commit(self.base))

    def test_an_unreachable_host_reports_none_instead_of_raising(self):
        """A sleeping free-tier instance is a normal state, not a crash."""
        self.assertIsNone(self.script.read_live_commit("http://127.0.0.1:1"))

    def test_triggers_the_hook_and_confirms_success(self):
        self.assertTrue(self.script.trigger_hook(f"{self.base}/hook", attempts=1))
        self.assertEqual(_Handler.triggers, 1)

    def test_a_wrong_hook_url_is_not_retried(self):
        """401/403/404 mean the credential is bad; hammering it cannot help."""
        self.assertFalse(self.script.trigger_hook(f"{self.base}/nope", attempts=3, backoff=0))
        self.assertEqual(_Handler.triggers, 0)

    def test_waits_until_the_new_commit_appears(self):
        """The core promise: it returns only once the NEW build is answering."""
        _Handler.commit = "oldcommit"
        ok, body = self.script.wait_for_commit(self.base, "newcommit", timeout=2, interval=0)
        self.assertFalse(ok)
        self.assertEqual(body["commit"], "oldcommit")

    def test_a_short_sha_matches_the_full_one(self):
        """An operator types `git rev-parse --short`; Render reports all 40 chars."""
        _Handler.commit = "1234567890abcdef1234567890abcdef12345678"
        ok, body = self.script.wait_for_commit(self.base, "1234567", timeout=2, interval=0)
        self.assertTrue(ok)
        self.assertEqual(body["commit"], _Handler.commit)

    def test_missing_hook_env_var_returns_instructions_not_a_fabricated_url(self):
        """Exit code 2 and no POST. Inventing a URL would hit an unknown host."""
        import argparse

        args = argparse.Namespace(hook_url="")
        with _no_env("RENDER_DEPLOY_HOOK_URL"):
            self.assertIsNone(self.script._resolve_hook(args))

    def test_end_to_end_check_only_makes_no_post(self):
        _Handler.commit = "feedface"
        self.assertEqual(self.script.main(["--base", self.base, "--check-only"]), 0)
        self.assertEqual(_Handler.triggers, 0)

    def test_end_to_end_missing_hook_exits_2_without_posting(self):
        with _no_env("RENDER_DEPLOY_HOOK_URL"):
            code = self.script.main(["--base", self.base, "--expect-commit", "abc"])
        self.assertEqual(code, 2)
        self.assertEqual(_Handler.triggers, 0)

    def test_end_to_end_successful_deploy_verifies_the_commit(self):
        _Handler.commit = "cafebabe1234"
        code = self.script.main(
            [
                "--base",
                self.base,
                "--hook-url",
                f"{self.base}/hook",
                "--expect-commit",
                "cafebabe1234",
                "--timeout",
                "5",
                "--interval",
                "0",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(_Handler.triggers, 1)

    def test_end_to_end_failed_deploy_exits_non_zero(self):
        """The old build still serving must be a failure, not a silent pass."""
        _Handler.commit = "theoldbuild"
        code = self.script.main(
            [
                "--base",
                self.base,
                "--hook-url",
                f"{self.base}/hook",
                "--expect-commit",
                "the-new-build",
                "--timeout",
                "1",
                "--interval",
                "0",
            ]
        )
        self.assertEqual(code, 1)
        self.assertEqual(_Handler.triggers, 1)

    def test_end_to_end_writes_the_observed_verdict(self):
        """The recorded sha must be the one the host reported, never a guess."""
        _Handler.commit = "cafebabe1234"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "verdict.md"
            code = self.script.main(
                [
                    "--base",
                    self.base,
                    "--hook-url",
                    f"{self.base}/hook",
                    "--expect-commit",
                    "cafebabe1234",
                    "--timeout",
                    "5",
                    "--interval",
                    "0",
                    "--write-markdown",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)
            text = out.read_text(encoding="utf-8")
        self.assertIn("verdict: verified", text)
        self.assertIn("cafebabe1234", text)
        self.assertNotIn("http", text, "the hook URL must never be written to the verdict file")


class _no_env:
    """Context manager that removes an environment variable for the block.

    Used instead of ``mock.patch.dict`` so the test states plainly what it is
    doing: the variable is *absent*, which is the case that must be handled.
    """

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        import os

        self.saved = os.environ.pop(self.name, None)
        return self

    def __exit__(self, *exc):
        import os

        if self.saved is not None:
            os.environ[self.name] = self.saved
        return False
