"""Tests for encrypted secret handling: the store, the leak guards, the wiring.

What is actually being protected here
-------------------------------------
Three separate promises, each of which fails silently on its own, so each is
tested against the real thing rather than a mock:

* **The store really encrypts.** A round-trip test proves the code can read back
  what it wrote; it does *not* prove the file is unreadable. So the tests also
  assert the plaintext is absent from the file's bytes, that a wrong passphrase
  fails, and that a modified ciphertext or header fails --- the last of which is
  what stops an attacker from rewriting the KDF cost down to nothing.
* **The guards really guard.** The scanner is run against a real temporary git
  repository with a real committed credential, because a scanner tested only on
  strings it is handed proves nothing about whether it reads git correctly.
* **The deploy script really redacts.** The hook URL is passed in and the
  script's own stdout and stderr are captured and searched for it. A redaction
  helper that is never wired into the output path is the classic way this is
  wrong.

Fake credentials are assembled at runtime by concatenation. A literal
``ghp_...`` in this file would be flagged by the very scanner these tests
exercise --- and, worse, would train everyone to ignore the scanner.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path

from django.test import SimpleTestCase

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    """Import a script from ``backend/scripts/`` as a module, without a package."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


secret_store = _load("secret_store")
check_secrets = _load("check_secrets")
render_deploy = _load("render_deploy")


# ── Fake credentials, assembled so this file is not itself a finding ──────────
def fake_github_token() -> str:
    return "ghp_" + "A1b2C3d4E5f6G7h8I9j0" + "K1l2M3n4O5p6"


def fake_render_hook() -> str:
    return "https://api.render.com/deploy/srv-" + "abc123def456" + "?key=" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2"


@contextmanager
def _env(**values):
    """Set environment variables for the block, restoring them afterwards."""
    saved = {k: os.environ.get(k) for k in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _captured():
    """Capture stdout and stderr as text, for asserting on what was printed."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        yield out, err


class SecretStoreCryptoTests(SimpleTestCase):
    """The encryption itself: round-trip, and the three ways it must fail."""

    def test_round_trip_returns_the_payload(self):
        payload = {"secrets": {"RENDER_DEPLOY_HOOK_URL": fake_render_hook()}}
        envelope = secret_store.encrypt_payload(payload, "correct horse battery staple")
        self.assertEqual(secret_store.decrypt_payload(envelope, "correct horse battery staple"), payload)

    def test_the_plaintext_is_not_in_the_file(self):
        """The whole point. A round-trip test alone would pass on a no-op cipher."""
        hook = fake_render_hook()
        envelope = secret_store.encrypt_payload({"secrets": {"h": hook}}, "passphrase-123")
        blob = json.dumps(envelope)
        self.assertNotIn(hook, blob)
        self.assertNotIn("api.render.com", blob)
        self.assertNotIn("passphrase-123", blob)

    def test_a_wrong_passphrase_fails_rather_than_returning_garbage(self):
        envelope = secret_store.encrypt_payload({"secrets": {"h": "value"}}, "right")
        with self.assertRaises(secret_store.SecretStoreError):
            secret_store.decrypt_payload(envelope, "wrong")

    def test_a_modified_ciphertext_is_rejected(self):
        """GCM is authenticated: a flipped bit must fail, not decrypt to noise."""
        envelope = secret_store.encrypt_payload({"secrets": {"h": "value"}}, "pass")
        raw = bytearray(secret_store._b64d(envelope["ciphertext"]))
        raw[0] ^= 0x01
        envelope["ciphertext"] = secret_store._b64e(bytes(raw))
        with self.assertRaises(secret_store.SecretStoreError):
            secret_store.decrypt_payload(envelope, "pass")

    def test_downgrading_the_kdf_cost_is_rejected(self):
        """The header is authenticated, so an attacker cannot make the key cheap.

        Without the associated-data binding, rewriting ``n`` to 2 would let a
        stolen file be brute-forced in seconds --- and the decryption would
        happily succeed, which is the dangerous part.
        """
        envelope = secret_store.encrypt_payload({"secrets": {"h": "value"}}, "pass")
        envelope["kdf"]["n"] = 2
        with self.assertRaises(secret_store.SecretStoreError):
            secret_store.decrypt_payload(envelope, "pass")

    def test_a_foreign_file_is_rejected_with_a_clear_message(self):
        with self.assertRaises(secret_store.SecretStoreError) as ctx:
            secret_store.decrypt_payload({"format": "something-else"}, "pass")
        self.assertIn("rakho-secret-store", str(ctx.exception))

    def test_each_encryption_uses_a_fresh_salt_and_nonce(self):
        """Reusing a nonce under one key is the classic GCM break."""
        payload = {"secrets": {"h": "value"}}
        first = secret_store.encrypt_payload(payload, "pass")
        second = secret_store.encrypt_payload(payload, "pass")
        self.assertNotEqual(first["kdf"]["salt"], second["kdf"]["salt"])
        self.assertNotEqual(first["nonce"], second["nonce"])
        self.assertNotEqual(first["ciphertext"], second["ciphertext"])


class SecretStoreFileTests(SimpleTestCase):
    """The store on disk: permissions, atomicity, and the key-beside rule."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "deploy.enc"

    def test_the_store_is_written_0600(self):
        secret_store.write_store(self.store, {"secrets": {"h": "v"}}, "pass")
        mode = self.store.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"store mode is {oct(mode)}, expected 0o600")

    def test_a_key_beside_the_store_is_refused(self):
        """The rule that makes encryption-at-rest mean anything."""
        key = self.root / "secret.key"
        key.write_text("pass", encoding="utf-8")
        with self.assertRaises(secret_store.SecretStoreError) as ctx:
            secret_store.assert_key_not_beside_store(self.store, key)
        self.assertIn("same directory", str(ctx.exception))

    def test_a_key_elsewhere_is_allowed(self):
        other = self.root / "elsewhere"
        other.mkdir()
        secret_store.assert_key_not_beside_store(self.store, other / "secret.key")

    def test_a_world_readable_passphrase_file_is_refused(self):
        key = self.root / "secret.key"
        key.write_text("pass", encoding="utf-8")
        key.chmod(0o644)
        with self.assertRaises(secret_store.SecretStoreError) as ctx:
            secret_store._read_key_file(key)
        self.assertIn("chmod 600", str(ctx.exception))

    def test_a_0600_passphrase_file_is_read(self):
        key = self.root / "secret.key"
        key.write_text("  pass  \n", encoding="utf-8")
        key.chmod(0o600)
        self.assertEqual(secret_store._read_key_file(key), "pass")

    def test_load_secret_returns_none_when_the_store_is_absent(self):
        """Absent is not an error: it is what lets the env-var fallback work."""
        self.assertIsNone(secret_store.load_secret("h", store_path=self.store))

    def test_load_secret_round_trips_through_the_file(self):
        secret_store.write_store(self.store, {"secrets": {"h": fake_render_hook()}}, "pass")
        self.assertEqual(secret_store.load_secret("h", store_path=self.store, passphrase="pass"), fake_render_hook())

    def test_a_corrupt_store_raises_rather_than_returning_none(self):
        """A store that exists but will not open is a problem, not an absence."""
        self.store.write_text("{not json", encoding="utf-8")
        with self.assertRaises(secret_store.SecretStoreError):
            secret_store.load_secret("h", store_path=self.store, passphrase="pass")


class SecretStoreCliTests(SimpleTestCase):
    """The CLI, driven the way an operator drives it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "deploy.enc"
        self.key = self.root / "elsewhere" / "secret.key"
        self.key.parent.mkdir()
        self.key.write_text("operator-passphrase", encoding="utf-8")
        self.key.chmod(0o600)

    def _run(self, *args, **env):
        base = {"RAKHO_SECRET_PASSPHRASE_FILE": str(self.key)}
        base.update(env)
        with _env(**base), _captured() as (out, err):
            code = secret_store.main([*args, "--store", str(self.store)])
        return code, out.getvalue(), err.getvalue()

    def test_set_then_get_round_trips(self):
        hook = fake_render_hook()
        code, _, _ = self._run("set", "--name", "RENDER_DEPLOY_HOOK_URL", "--from-env", "SRC", SRC=hook)
        self.assertEqual(code, 0)
        code, out, _ = self._run("get", "--name", "RENDER_DEPLOY_HOOK_URL")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), hook)

    def test_set_from_an_empty_env_var_fails_without_writing(self):
        code, _, err = self._run("set", "--name", "X", "--from-env", "EMPTY", EMPTY="")
        self.assertEqual(code, 2)
        self.assertIn("empty or unset", err)
        self.assertFalse(self.store.exists())

    def test_list_shows_names_but_never_values(self):
        hook = fake_render_hook()
        self._run("set", "--name", "RENDER_DEPLOY_HOOK_URL", "--from-env", "SRC", SRC=hook)
        code, out, _ = self._run("list")
        self.assertEqual(code, 0)
        self.assertIn("RENDER_DEPLOY_HOOK_URL", out)
        self.assertNotIn(hook, out)
        self.assertNotIn("api.render.com", out)

    def test_remove_deletes_the_secret(self):
        self._run("set", "--name", "A", "--from-env", "SRC", SRC="value-a")
        code, _, _ = self._run("remove", "--name", "A")
        self.assertEqual(code, 0)
        code, _, err = self._run("get", "--name", "A")
        self.assertEqual(code, 1)
        self.assertIn("no secret named A", err)

    def test_rotate_re_encrypts_under_the_new_passphrase(self):
        hook = fake_render_hook()
        self._run("set", "--name", "RENDER_DEPLOY_HOOK_URL", "--from-env", "SRC", SRC=hook)
        before = self.store.read_bytes()

        new_key = self.root / "elsewhere" / "new.key"
        new_key.write_text("the-new-passphrase", encoding="utf-8")
        new_key.chmod(0o600)
        code, _, _ = self._run("rotate", RAKHO_SECRET_NEW_PASSPHRASE="the-new-passphrase")
        self.assertEqual(code, 0)

        # The ciphertext changed: rotation re-encrypts with a fresh salt and
        # nonce, so the old and new files cannot be compared to confirm a guess.
        self.assertNotEqual(before, self.store.read_bytes())

        # The old passphrase no longer opens it...
        with _env(RAKHO_SECRET_PASSPHRASE="operator-passphrase", RAKHO_SECRET_PASSPHRASE_FILE=None):
            with self.assertRaises(secret_store.SecretStoreError):
                secret_store.load_secret("RENDER_DEPLOY_HOOK_URL", store_path=self.store)
        # ...and the new one does, with the value intact.
        self.assertEqual(
            secret_store.load_secret("RENDER_DEPLOY_HOOK_URL", store_path=self.store, passphrase="the-new-passphrase"),
            hook,
        )

    def test_rotate_to_the_same_passphrase_is_refused(self):
        self._run("set", "--name", "A", "--from-env", "SRC", SRC="value-a")
        code, _, err = self._run("rotate", RAKHO_SECRET_NEW_PASSPHRASE="operator-passphrase")
        self.assertEqual(code, 2)
        self.assertIn("identical", err)

    def test_rotate_without_a_new_passphrase_is_refused(self):
        self._run("set", "--name", "A", "--from-env", "SRC", SRC="value-a")
        code, _, err = self._run("rotate", RAKHO_SECRET_NEW_PASSPHRASE="")
        self.assertEqual(code, 2)
        self.assertIn("RAKHO_SECRET_NEW_PASSPHRASE", err)

    def test_a_missing_passphrase_is_reported_not_guessed(self):
        # RAKHO_SECRET_KEY_FILE is pointed at a path that does not exist so the
        # test is hermetic: without it, a developer who happens to have the real
        # default key file (~/.config/rakho/secret.key) would make this test
        # resolve a passphrase and fail for the wrong reason.
        missing = self.root / "no-such-key-file"
        with _env(RAKHO_SECRET_PASSPHRASE=None, RAKHO_SECRET_PASSPHRASE_FILE=None, RAKHO_SECRET_KEY_FILE=str(missing)):
            with _captured() as (_, err):
                code = secret_store.main(["list", "--store", str(self.store)])
        self.assertEqual(code, 1)
        self.assertIn("No passphrase found", err.getvalue())


class RedactionTests(SimpleTestCase):
    """Redaction: the exact values, and the shapes that were never in-process."""

    def test_an_exact_value_is_scrubbed(self):
        hook = fake_render_hook()
        self.assertNotIn(hook, secret_store.redact(f"failed to POST {hook}", (hook,)))

    def test_a_github_token_shape_is_scrubbed_without_being_known(self):
        """The case a value-only scrubber misses: a token from somewhere else."""
        token = fake_github_token()
        self.assertNotIn(token, secret_store.redact(f"Authorization: Bearer {token}"))

    def test_a_render_hook_shape_is_scrubbed_without_being_known(self):
        self.assertNotIn("api.render.com", secret_store.redact(f"POST {fake_render_hook()}"))

    def test_ordinary_prose_is_left_alone(self):
        text = "The deploy hook is configured in the Render dashboard under Settings."
        self.assertEqual(secret_store.redact(text), text)

    def test_the_documented_placeholder_is_not_a_false_positive(self):
        """A scanner that flags its own documentation gets switched off."""
        text = "export RENDER_DEPLOY_HOOK_URL='https://api.render.com/deploy/srv-...?key=...'"
        self.assertEqual(secret_store.redact(text), text)

    def test_a_longer_secret_is_replaced_before_a_shorter_one_inside_it(self):
        """Otherwise a fragment of the longer secret survives the scrub."""
        long_value = "ghp_" + "A" * 30
        short_value = long_value[:20]
        result = secret_store.redact(f"value={long_value}", (short_value, long_value))
        self.assertNotIn("ghp_", result)


class SecretScannerTests(SimpleTestCase):
    """The scanner: what it catches, what it must not, and how it reads git."""

    def test_it_catches_a_github_token(self):
        hits = check_secrets.scan_text(f"token = '{fake_github_token()}'")
        self.assertTrue(any("GitHub" in label for label, _ in hits))

    def test_it_catches_a_render_deploy_hook(self):
        hits = check_secrets.scan_text(f"hook={fake_render_hook()}")
        self.assertTrue(any("Render" in label for label, _ in hits))

    def test_it_catches_private_key_material(self):
        # Assembled at runtime for the same reason as the other fakes: a literal
        # key header in this file would be flagged by the scanner these tests
        # exercise, and would train everyone to ignore the scanner.
        header = "-----BEGIN RSA " + "PRIVATE KEY-----"
        hits = check_secrets.scan_text(f"{header}\nMIIE...")
        self.assertTrue(any("private key" in label for label, _ in hits))

    def test_it_does_not_flag_the_documented_placeholder(self):
        self.assertEqual(check_secrets.scan_text("srv-XXXXXXXX?key=YYYYYYYY"), [])

    def test_it_does_not_flag_ordinary_prose(self):
        self.assertEqual(check_secrets.scan_text("The hook URL is a bearer credential."), [])

    def test_a_hit_is_reported_redacted(self):
        """The scanner's own output must not become the leak."""
        hits = check_secrets.scan_text(fake_github_token())
        self.assertTrue(hits)
        for _, sample in hits:
            self.assertNotIn(fake_github_token(), sample)

    def test_it_flags_a_forbidden_filename(self):
        problems = check_secrets.check_paths(["backend/.secrets/deploy.enc"])
        self.assertTrue(any("encrypted secret store" in p for p in problems))

    def test_it_flags_a_passphrase_file(self):
        problems = check_secrets.check_paths(["config/secret.key"])
        self.assertTrue(any("passphrase" in p for p in problems))

    def test_it_flags_a_committed_env_file(self):
        problems = check_secrets.check_paths([".env"])
        self.assertTrue(any(".env" in p for p in problems))

    def test_it_passes_a_clean_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean = Path(tmp) / "notes.md"
            clean.write_text("Nothing secret here.", encoding="utf-8")
            self.assertEqual(check_secrets.check_paths([str(clean)]), [])

    def test_it_finds_a_secret_in_a_real_git_history(self):
        """Run against a real repository, because that is what it must read.

        A scanner tested only on strings it is handed proves nothing about
        whether it enumerates git objects correctly --- and the case that
        matters is a secret that was committed and then removed, which only a
        history scan can see.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

            def git(*args):
                subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)

            git("init", "-q")
            (repo / "leak.txt").write_text(f"token={fake_github_token()}\n", encoding="utf-8")
            git("add", "leak.txt")
            git("commit", "-q", "-m", "oops")
            # Remove it in a second commit: the file is gone from the tree, but
            # the blob is still reachable, which is exactly the case an audit
            # exists to catch.
            (repo / "leak.txt").unlink()
            git("add", "-A")
            git("commit", "-q", "-m", "remove it")

            cwd = os.getcwd()
            os.chdir(repo)
            try:
                problems = check_secrets.scan_git_history()
            finally:
                os.chdir(cwd)
            self.assertTrue(problems, "the history scan missed a committed credential")
            self.assertTrue(any("leak.txt" in p for p in problems))
            # And the finding itself is redacted.
            self.assertFalse(any(fake_github_token() in p for p in problems))

    def test_the_real_repository_history_is_clean(self):
        """The audit result for this project, asserted rather than assumed."""
        cwd = os.getcwd()
        os.chdir(SCRIPTS.parents[1])
        try:
            problems = check_secrets.scan_git_history()
        finally:
            os.chdir(cwd)
        self.assertEqual(problems, [], f"a credential is present in git history: {problems}")


class DeployScriptSecretWiringTests(SimpleTestCase):
    """The deploy script reads the store, falls back, and never prints the hook."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "deploy.enc"
        self.key = self.root / "elsewhere" / "secret.key"
        self.key.parent.mkdir()
        self.key.write_text("passphrase", encoding="utf-8")
        self.key.chmod(0o600)
        render_deploy._SECRETS.clear()
        self.addCleanup(render_deploy._SECRETS.clear)

    def _args(self, **overrides):
        import argparse

        base = {"hook_url": "", "store": str(self.store)}
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_it_reads_the_hook_from_the_encrypted_store(self):
        hook = fake_render_hook()
        secret_store.write_store(self.store, {"secrets": {"RENDER_DEPLOY_HOOK_URL": hook}}, "passphrase")
        with _env(RAKHO_SECRET_PASSPHRASE="passphrase", RENDER_DEPLOY_HOOK_URL=None):
            self.assertEqual(render_deploy._resolve_hook(self._args()), hook)

    def test_it_falls_back_to_the_env_var_when_no_store_exists(self):
        hook = fake_render_hook()
        with _env(RAKHO_SECRET_PASSPHRASE="passphrase", RENDER_DEPLOY_HOOK_URL=hook):
            self.assertEqual(render_deploy._resolve_hook(self._args()), hook)

    def test_a_broken_store_is_not_silently_bypassed(self):
        """Falling through to the env var would hide a wrong passphrase."""
        secret_store.write_store(self.store, {"secrets": {"RENDER_DEPLOY_HOOK_URL": fake_render_hook()}}, "right")
        with _env(RAKHO_SECRET_PASSPHRASE="wrong", RENDER_DEPLOY_HOOK_URL=fake_render_hook()):
            with _captured() as (out, _):
                result = render_deploy._resolve_hook(self._args())
        self.assertIsNone(result)
        self.assertIn("could not be read", out.getvalue())

    def test_the_hook_never_appears_in_stdout_or_stderr(self):
        """The promise: resolving the hook logs its *source*, never its value.

        This exercises ``_resolve_hook`` directly rather than ``main``, because
        ``--check-only`` returns before the hook is ever resolved --- so a test
        that ran ``main`` would pass without the redaction path being reached at
        all, which is the classic way a redaction test proves nothing. The hook
        is a real-shaped Render URL, and no POST is made here.
        """
        hook = fake_render_hook()
        secret_store.write_store(self.store, {"secrets": {"RENDER_DEPLOY_HOOK_URL": hook}}, "passphrase")
        with _env(RAKHO_SECRET_PASSPHRASE="passphrase", RENDER_DEPLOY_HOOK_URL=None):
            with _captured() as (out, err):
                resolved = render_deploy._resolve_hook(self._args())
        self.assertEqual(resolved, hook)
        combined = out.getvalue() + err.getvalue()
        self.assertNotIn(hook, combined)
        self.assertNotIn("api.render.com", combined)
        self.assertIn("encrypted store", combined)

    def test_check_only_prints_nothing_secret(self):
        """``--check-only`` must not resolve or print the hook at all."""
        hook = fake_render_hook()
        secret_store.write_store(self.store, {"secrets": {"RENDER_DEPLOY_HOOK_URL": hook}}, "passphrase")
        with _env(RAKHO_SECRET_PASSPHRASE="passphrase", RENDER_DEPLOY_HOOK_URL=None):
            with _captured() as (out, err):
                code = render_deploy.main(["--base", "http://127.0.0.1:1", "--store", str(self.store), "--check-only"])
        self.assertEqual(code, 0)
        combined = out.getvalue() + err.getvalue()
        self.assertNotIn(hook, combined)
        self.assertNotIn("api.render.com", combined)

    def test_a_verdict_file_never_contains_the_hook(self):
        hook = fake_render_hook()
        secret_store.write_store(self.store, {"secrets": {"RENDER_DEPLOY_HOOK_URL": hook}}, "passphrase")
        verdict = self.root / "verdict.md"
        with _env(RAKHO_SECRET_PASSPHRASE="passphrase", RENDER_DEPLOY_HOOK_URL=None):
            with _captured():
                render_deploy.main(["--base", "http://127.0.0.1:1", "--store", str(self.store), "--check-only", "--write-markdown", str(verdict)])
        text = verdict.read_text(encoding="utf-8")
        self.assertNotIn(hook, text)
        self.assertNotIn("api.render.com", text)

    def test_the_store_path_can_be_overridden_by_the_environment(self):
        with _env(RAKHO_SECRET_STORE=str(self.store)):
            self.assertEqual(render_deploy._store_path(self._args(store="")), self.store)


# ── Test values for the extended store ────────────────────────────────────────
# Clearly labelled as test values, never real credentials. A real database URL
# or Sentry DSN is never invented here; the mechanism is exercised with these,
# and the operator stores the real ones with the documented command.
TEST_DATABASE_URL = "postgres://test-database-url-value@localhost:5432/testdb"
TEST_SENTRY_DSN = "https://test-sentry-dsn-value@example.invalid/1"


class ExtendedSecretStoreTests(SimpleTestCase):
    """``database_url`` and ``sentry_dsn`` in the same store, same crypto."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "deploy.enc"
        self.key = self.root / "elsewhere" / "secret.key"
        self.key.parent.mkdir()
        self.key.write_text("operator-passphrase", encoding="utf-8")
        self.key.chmod(0o600)

    def _run(self, *args, **env):
        base = {"RAKHO_SECRET_PASSPHRASE_FILE": str(self.key)}
        base.update(env)
        with _env(**base), _captured() as (out, err):
            code = secret_store.main([*args, "--store", str(self.store)])
        return code, out.getvalue(), err.getvalue()

    def test_both_secrets_round_trip_under_their_canonical_names(self):
        self._run("set", "--name", secret_store.SECRET_DATABASE_URL, "--from-env", "SRC", SRC=TEST_DATABASE_URL)
        self._run("set", "--name", secret_store.SECRET_SENTRY_DSN, "--from-env", "SRC", SRC=TEST_SENTRY_DSN)
        self.assertEqual(
            secret_store.load_secret(secret_store.SECRET_DATABASE_URL, store_path=self.store, passphrase="operator-passphrase"),
            TEST_DATABASE_URL,
        )
        self.assertEqual(
            secret_store.load_secret(secret_store.SECRET_SENTRY_DSN, store_path=self.store, passphrase="operator-passphrase"),
            TEST_SENTRY_DSN,
        )

    def test_neither_value_is_plaintext_in_the_file(self):
        self._run("set", "--name", secret_store.SECRET_DATABASE_URL, "--from-env", "SRC", SRC=TEST_DATABASE_URL)
        self._run("set", "--name", secret_store.SECRET_SENTRY_DSN, "--from-env", "SRC", SRC=TEST_SENTRY_DSN)
        blob = self.store.read_text(encoding="utf-8")
        self.assertNotIn(TEST_DATABASE_URL, blob)
        self.assertNotIn(TEST_SENTRY_DSN, blob)
        self.assertNotIn("test-database-url-value", blob)
        self.assertNotIn("test-sentry-dsn-value", blob)

    def test_list_shows_both_names_but_no_values(self):
        self._run("set", "--name", secret_store.SECRET_DATABASE_URL, "--from-env", "SRC", SRC=TEST_DATABASE_URL)
        self._run("set", "--name", secret_store.SECRET_SENTRY_DSN, "--from-env", "SRC", SRC=TEST_SENTRY_DSN)
        code, out, _ = self._run("list")
        self.assertEqual(code, 0)
        self.assertIn(secret_store.SECRET_DATABASE_URL, out)
        self.assertIn(secret_store.SECRET_SENTRY_DSN, out)
        self.assertNotIn(TEST_DATABASE_URL, out)
        self.assertNotIn(TEST_SENTRY_DSN, out)

    def test_rotation_preserves_both_secrets(self):
        self._run("set", "--name", secret_store.SECRET_DATABASE_URL, "--from-env", "SRC", SRC=TEST_DATABASE_URL)
        self._run("set", "--name", secret_store.SECRET_SENTRY_DSN, "--from-env", "SRC", SRC=TEST_SENTRY_DSN)
        code, _, _ = self._run("rotate", RAKHO_SECRET_NEW_PASSPHRASE="the-new-passphrase")
        self.assertEqual(code, 0)
        self.assertEqual(
            secret_store.load_secret(secret_store.SECRET_DATABASE_URL, store_path=self.store, passphrase="the-new-passphrase"),
            TEST_DATABASE_URL,
        )
        self.assertEqual(
            secret_store.load_secret(secret_store.SECRET_SENTRY_DSN, store_path=self.store, passphrase="the-new-passphrase"),
            TEST_SENTRY_DSN,
        )

    def test_a_legacy_name_is_still_read(self):
        """A store written before the canonical names existed still opens."""
        secret_store.write_store(self.store, {"secrets": {"DATABASE_URL": TEST_DATABASE_URL}}, "operator-passphrase")
        self.assertEqual(
            secret_store.load_secret_with_aliases(secret_store.SECRET_DATABASE_URL, store_path=self.store, passphrase="operator-passphrase"),
            TEST_DATABASE_URL,
        )

    def test_the_canonical_name_wins_over_a_legacy_one(self):
        secret_store.write_store(
            self.store,
            {"secrets": {secret_store.SECRET_DATABASE_URL: TEST_DATABASE_URL, "DATABASE_URL": "postgres://legacy-value/db"}},
            "operator-passphrase",
        )
        self.assertEqual(
            secret_store.load_secret_with_aliases(secret_store.SECRET_DATABASE_URL, store_path=self.store, passphrase="operator-passphrase"),
            TEST_DATABASE_URL,
        )

    def test_an_absent_store_returns_none_so_the_env_fallback_works(self):
        self.assertIsNone(secret_store.load_secret_with_aliases(secret_store.SECRET_SENTRY_DSN, store_path=self.store))


class SettingsResolverTests(SimpleTestCase):
    """``config.secrets.resolve_secret``: store first, environment fallback."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "deploy.enc"
        self.key = self.root / "elsewhere" / "secret.key"
        self.key.parent.mkdir()
        self.key.write_text("resolver-passphrase", encoding="utf-8")
        self.key.chmod(0o600)

        from config import secrets as config_secrets

        self.config_secrets = config_secrets

    def _env_for_store(self, **extra):
        base = {
            "RAKHO_SECRET_STORE": str(self.store),
            "RAKHO_SECRET_PASSPHRASE_FILE": str(self.key),
            "RAKHO_SECRET_PASSPHRASE": None,
        }
        base.update(extra)
        return base

    def test_the_store_is_preferred_over_the_environment(self):
        secret_store.write_store(self.store, {"secrets": {secret_store.SECRET_DATABASE_URL: TEST_DATABASE_URL}}, "resolver-passphrase")
        with _env(**self._env_for_store(DATABASE_URL="postgres://from-the-environment/db")):
            self.assertEqual(self.config_secrets.resolve_secret(secret_store.SECRET_DATABASE_URL, "DATABASE_URL"), TEST_DATABASE_URL)

    def test_it_falls_back_to_the_environment_when_no_store_exists(self):
        with _env(**self._env_for_store(DATABASE_URL="postgres://from-the-environment/db")):
            self.assertEqual(self.config_secrets.resolve_secret(secret_store.SECRET_DATABASE_URL, "DATABASE_URL"), "postgres://from-the-environment/db")

    def test_it_returns_the_default_when_neither_is_present(self):
        with _env(**self._env_for_store(SENTRY_DSN=None)):
            self.assertEqual(self.config_secrets.resolve_secret(secret_store.SECRET_SENTRY_DSN, "SENTRY_DSN", "the-default"), "the-default")

    def test_a_broken_store_warns_but_still_uses_the_environment(self):
        """A store that will not open must not take the service down."""
        secret_store.write_store(self.store, {"secrets": {secret_store.SECRET_SENTRY_DSN: TEST_SENTRY_DSN}}, "the-right-passphrase")
        with _env(**self._env_for_store(RAKHO_SECRET_PASSPHRASE="the-wrong-passphrase", SENTRY_DSN="https://from-the-environment@example.invalid/1")):
            with self.assertLogs("config.secrets", level="WARNING") as logs:
                value = self.config_secrets.resolve_secret(secret_store.SECRET_SENTRY_DSN, "SENTRY_DSN")
        self.assertEqual(value, "https://from-the-environment@example.invalid/1")
        self.assertTrue(any("could not be read" in line for line in logs.output))
        # The warning must not leak the value it failed to read.
        self.assertFalse(any(TEST_SENTRY_DSN in line for line in logs.output))

    def test_the_sentry_dsn_is_resolved_through_the_store(self):
        secret_store.write_store(self.store, {"secrets": {secret_store.SECRET_SENTRY_DSN: TEST_SENTRY_DSN}}, "resolver-passphrase")
        with _env(**self._env_for_store(SENTRY_DSN=None)):
            self.assertEqual(self.config_secrets.resolve_secret(secret_store.SECRET_SENTRY_DSN, "SENTRY_DSN"), TEST_SENTRY_DSN)
