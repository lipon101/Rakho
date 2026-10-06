"""Phase 5 (M6): proof that the database itself enforces tenancy.

The application already scopes every query through ``OrgContext``, and the
existing organisation tests prove that. What they cannot prove is the second
lock: that a query which *forgets* to scope still returns nothing. That is a
property of the database, so it is tested against the database --- as the
non-owner role the deployment is meant to use, with the tenant bound the way the
middleware binds it.

The test is skipped unless the database is PostgreSQL, because the policies are
a PostgreSQL feature. On SQLite --- a developer's laptop, or a CI job that has
not provisioned Postgres --- the module reports as skipped rather than failing,
which is honest: there is nothing to assert.

It connects with a raw psycopg connection rather than through Django's ORM on
purpose. The ORM would apply the application's own scoping and the test would
then pass even if the policies were missing entirely --- it would be measuring
the first lock while claiming to measure the second. A raw connection has no
scoping of its own, so anything it cannot see is the policy's doing.
"""

from __future__ import annotations

import os
import unittest
import uuid

from django.db import connection
from django.test import TransactionTestCase

from inventory.models import Organization, Pharmacy

#: The non-owner role ``setup_rls_role`` creates. The test uses it because the
#: table owner is exempt from the policies under ``ENABLE`` (and only bound
#: under ``FORCE``), so testing as the owner would prove nothing.
APP_ROLE = os.environ.get("RLS_TEST_ROLE", "rakho_app")
APP_PASSWORD = os.environ.get("RLS_TEST_PASSWORD", "app-secret-123")


def _app_connection():
    """A raw connection as the non-owner role, or ``None`` if unavailable.

    Returns ``None`` rather than raising when the role does not exist, so a
    developer who has not run ``setup_rls_role`` gets a skip with a reason
    instead of a red suite.
    """
    try:
        import psycopg
    except ImportError:  # pragma: no cover - psycopg is a hard dependency
        return None

    settings = connection.settings_dict
    try:
        return psycopg.connect(
            host=settings.get("HOST") or "localhost",
            port=settings.get("PORT") or 5432,
            dbname=settings["NAME"],
            user=APP_ROLE,
            password=APP_PASSWORD,
            autocommit=False,
        )
    except Exception:
        return None


@unittest.skipUnless(connection.vendor == "postgresql", "RLS is a PostgreSQL feature")
class RowLevelSecurityTests(TransactionTestCase):
    """Two tenants, one non-owner connection, and the policies in between.

    ``TransactionTestCase`` rather than ``TestCase``, and that choice is load
    bearing. ``TestCase`` wraps each test in a transaction it rolls back, which
    is faster but means the seeded rows are never committed --- and the whole
    point of this module is to read them from a *second* connection, which
    cannot see uncommitted data. Under ``TestCase`` the positive assertions
    would fail for a reason that has nothing to do with RLS, and the negative
    ones would pass for the same wrong reason. Committing the fixtures is what
    makes the test measure the policy.
    """

    #: The tables this module writes to, so the flush between tests is bounded
    #: and the suite does not pay to truncate the whole schema.
    available_apps = ["inventory"]

    @classmethod
    def setUpClass(cls):
        """Grant the non-owner role access to the *test* database.

        The role is created against the real database by ``setup_rls_role``, but
        Django builds a fresh test database for every run, so the grants have to
        be repeated here or the role would connect and then be refused on the
        first table.

        The grants run on a separate **autocommit** connection, and that detail
        is the whole reason this method is not three lines. ``GRANT`` is
        transactional in PostgreSQL, and Django wraps each test in a transaction
        it rolls back at the end --- so a grant issued on the test connection
        would be undone before the first assertion ran, and the failure would
        look like a missing privilege rather than a rolled-back one.
        """
        super().setUpClass()
        if connection.vendor != "postgresql":
            return
        if not APP_ROLE.replace("_", "").isalnum():
            return
        try:
            import psycopg

            settings = connection.settings_dict
            with psycopg.connect(
                host=settings.get("HOST") or "localhost",
                port=settings.get("PORT") or 5432,
                dbname=settings["NAME"],
                user=settings.get("USER") or "postgres",
                password=settings.get("PASSWORD") or "",
                autocommit=True,
            ) as owner:
                with owner.cursor() as cursor:
                    cursor.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
                    cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
                    cursor.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
        except Exception:
            # The role does not exist in this environment; ``setUp`` will skip
            # with a reason rather than the whole class erroring.
            pass

    def setUp(self):
        # Seeded per test rather than in ``setUpTestData``: that hook belongs to
        # ``TestCase`` and is not run for a ``TransactionTestCase``, so the rows
        # have to be created here. They are committed by the test framework
        # before the assertions run, which is what lets the second connection
        # see them.
        self.org_a = Organization.objects.create(name="Org A", slug=f"org-a-{uuid.uuid4().hex[:8]}")
        self.org_b = Organization.objects.create(name="Org B", slug=f"org-b-{uuid.uuid4().hex[:8]}")
        self.branch_a = Pharmacy.objects.create(name="A Branch", organization=self.org_a, branch_code="A1")
        self.branch_b = Pharmacy.objects.create(name="B Branch", organization=self.org_b, branch_code="B1")

        self.conn = _app_connection()
        if self.conn is None:
            self.skipTest(f"role '{APP_ROLE}' is not available; run `manage.py setup_rls_role` first")

    def tearDown(self):
        if getattr(self, "conn", None) is not None:
            self.conn.close()

    def _visible_branch_names(self, org_id):
        """Names of the branches visible to a session bound to ``org_id``.

        ``SET LOCAL`` is used inside an explicit transaction, exactly as the
        middleware does it, so the test exercises the same mechanism the request
        path relies on rather than a convenient approximation of it.
        """
        with self.conn.cursor() as cursor:
            cursor.execute("BEGIN")
            if org_id is not None:
                cursor.execute("SELECT set_config('app.current_org', %s, true)", [str(org_id)])
            cursor.execute("SELECT name FROM inventory_pharmacy ORDER BY name")
            names = [row[0] for row in cursor.fetchall()]
            cursor.execute("COMMIT")
        return names

    def test_no_tenant_bound_sees_nothing(self):
        """The default posture is deny: an unbound connection sees no tenant rows.

        This is the case that matters most. A connection with no organisation
        bound is what a bug --- a missing context, a background task that forgot
        to scope --- actually looks like, and the correct answer is an empty
        result, not every tenant's data.
        """
        self.assertEqual(self._visible_branch_names(None), [])

    def test_org_a_sees_only_its_own_branch(self):
        self.assertEqual(self._visible_branch_names(self.org_a.id), ["A Branch"])

    def test_org_b_sees_only_its_own_branch(self):
        self.assertEqual(self._visible_branch_names(self.org_b.id), ["B Branch"])

    def test_org_a_cannot_read_org_b_row_by_id(self):
        """Naming another tenant's row explicitly does not reach it.

        The previous test proves the *list* is filtered; this one proves the
        filter is not merely a default ordering. A caller who knows --- or
        guesses --- another tenant's primary key still gets nothing, which is
        the difference between a scoped query and a scoped query that can be
        bypassed by an id.
        """
        with self.conn.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute("SELECT set_config('app.current_org', %s, true)", [str(self.org_a.id)])
            cursor.execute("SELECT count(*) FROM inventory_pharmacy WHERE id = %s", [str(self.branch_b.id)])
            count = cursor.fetchone()[0]
            cursor.execute("COMMIT")
        self.assertEqual(count, 0)

    def test_org_a_cannot_write_a_row_for_org_b(self):
        """The policy's ``WITH CHECK`` refuses a cross-tenant insert.

        Reading is only half the rule. Without the check clause a caller could
        not *see* another tenant's rows but could still create one, which is a
        data-integrity failure that would surface much later as a branch that
        belongs to nobody.
        """
        import psycopg

        with self.conn.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute("SELECT set_config('app.current_org', %s, true)", [str(self.org_a.id)])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(
                    "INSERT INTO inventory_pharmacy (id, name, currency, timezone, low_stock_default, address, phone, organization_id, branch_code, is_active, created_at, updated_at) "
                    "VALUES (%s, 'Smuggled', 'BDT', 'Asia/Dhaka', 10, '', '', %s, 'X1', true, now(), now())",
                    [str(uuid.uuid4()), str(self.org_b.id)],
                )
            cursor.execute("ROLLBACK")

    def test_policies_are_enabled_on_the_tenant_tables(self):
        """Every covered table actually has RLS switched on.

        A migration that silently did nothing --- because it ran on the wrong
        vendor, or a table name was misspelled --- would leave the suite green
        while the deployment was unprotected. This asserts the switch itself.
        """
        from inventory.rls_tables import COVERED_TABLES

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relname FROM pg_class WHERE relkind = 'r' AND relrowsecurity AND relname = ANY(%s)",
                [COVERED_TABLES],
            )
            enabled = {row[0] for row in cursor.fetchall()}
        self.assertEqual(enabled, set(COVERED_TABLES))
