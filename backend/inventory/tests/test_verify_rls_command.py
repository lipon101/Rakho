"""Tests for the RLS verification command's portable logic.

Scope, stated honestly
----------------------
The command's *behavioural* half --- connecting as the non-owner role and proving
one organisation cannot see another's rows --- cannot be unit-tested here. The
test database is created and owned by a single role and RLS is inert for the
owner, so a test in this file would measure the application's own query scoping
and label the result "RLS". That half is verified by running
``manage.py verify_rls`` against a real PostgreSQL deployment, which is what the
runbook instructs.

What *is* tested here is the part that silently breaks in production: the DSN the
command builds, and the guard against verifying a database that has no RLS. Each
of those failures presents as an authentication error that reads like a
permissions problem, so they are worth pinning down precisely.
"""

from __future__ import annotations

import os
import uuid
from unittest import mock

from django.test import SimpleTestCase

from inventory.management.commands import verify_rls
from inventory.management.commands.verify_rls import MARKER_PREFIX, _application_dsn

#: A production-shaped PostgreSQL settings dict, used as a *patched value* rather
#: than through ``override_settings(DATABASES=...)``: that would not affect
#: ``connection.settings_dict``, which is read from the already-open connection.
#: Patching the attribute is what makes these tests exercise the real resolution
#: path instead of asserting against whatever database the suite happens to use.
PG_SETTINGS_DICT = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "pharmacy",
    "USER": "pharmacy",
    "HOST": "db.internal",
    "PORT": "5432",
}


class _FakeConnection:
    """A stand-in for Django's connection, exposing only what the helper reads.

    Deliberately *not* ``mock.patch.object(connection, "settings_dict", ...)``:
    ``verify_rls.connection`` is Django's global DatabaseWrapper, and patching an
    attribute onto it survives past the test --- it left the real connection
    without a ``settings_dict`` and broke the suite's database teardown. A fake
    object patched in as the module attribute touches nothing shared.
    """

    def __init__(self, settings_dict: dict, vendor: str = "postgresql"):
        self.settings_dict = settings_dict
        self.vendor = vendor


class ApplicationDsnTests(SimpleTestCase):
    """The verification connection string must reach the right database as the
    right identity, or the check verifies something other than the deployment."""

    def _dsn(self, password: str = "s3cret", database_url: str = "", **overrides) -> str:
        settings = dict(PG_SETTINGS_DICT, **overrides)
        with mock.patch.object(verify_rls, "connection", _FakeConnection(settings)):
            with mock.patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
                return _application_dsn("rakho_app", password)

    def test_keeps_sslmode_so_a_managed_host_still_gets_tls(self):
        """Dropping the query string would silently downgrade to plaintext, and a
        managed host refuses that --- which reads as a bad host, not a bad URL."""
        dsn = self._dsn(database_url="postgres://u:p@h:5432/pharmacy?sslmode=require")
        self.assertIn("sslmode=require", dsn)

    def test_uses_the_live_connection_host_port_and_database(self):
        self.assertIn("rakho_app:s3cret@db.internal:5432/pharmacy", self._dsn())

    def test_percent_encodes_a_password_containing_reserved_characters(self):
        """An unescaped '@' or ':' splices into the netloc and mis-parses it."""
        dsn = self._dsn(password="p@ss:word/with#chars")
        self.assertIn("p%40ss%3Aword%2Fwith%23chars", dsn)
        # Exactly one credential delimiter, the one we added.
        self.assertEqual(dsn.count("@"), 1)

    def test_missing_host_falls_back_without_producing_a_broken_url(self):
        dsn = self._dsn(database_url="postgres://u:p@db.remote:5555/pharmacy", HOST="")
        # The DATABASE_URL host is a reasonable fallback; what must never happen
        # is an empty host producing "@:5432", which psycopg reads as a unix socket.
        self.assertIn("db.remote", dsn)
        self.assertNotIn("@:", dsn)


class NonPostgresGuardTests(SimpleTestCase):
    """RLS is a PostgreSQL feature; asking to verify it elsewhere must fail loudly
    rather than reporting success on a database that cannot enforce it."""

    def test_fails_on_a_non_postgresql_backend(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with mock.patch.object(verify_rls, "connection", _FakeConnection(PG_SETTINGS_DICT, vendor="sqlite")):
            with self.assertRaises(CommandError):
                call_command("verify_rls", password="x")


class MarkerTests(SimpleTestCase):
    def test_probe_ids_are_uuid_shaped(self):
        """The markers go into a uuid primary key, so a malformed one would fail
        at insert time with a database error rather than a clear message."""
        uuid.UUID(f"{MARKER_PREFIX}01")
        uuid.UUID(f"{MARKER_PREFIX}02")

    def test_the_probe_name_pattern_cannot_match_real_organisations(self):
        """The purge deletes by this pattern, so it must be specific enough that a
        real organisation could never be swept up by it."""
        self.assertTrue(verify_rls.PROBE_NAME_LIKE.startswith("RLS probe"))
        self.assertNotIn("%", verify_rls.PROBE_NAME_LIKE.replace("%", "", 1))
