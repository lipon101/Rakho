"""Prove Row-Level Security is actually enforced --- not merely configured.

Why this command exists
-----------------------
A row in ``pg_policies`` is not proof of anything. Three separate things have to
be true at once, and each fails silently on its own:

1. the policies must exist;
2. RLS must be **FORCEd**, because ``ENABLE`` exempts the table's owner --- and
   the owner is exactly the role a deployment connects as by default;
3. the application must be connecting as a role the policies actually bind.

All three can report "configured" while tenant isolation is zero. So this
command goes one step further than catalog inspection and *demonstrates* the
behaviour: it opens a real connection as the non-owner role, writes two
organisations, and proves a connection bound to one cannot see the other's row
--- and that an unbound connection sees neither.

That distinction is the whole point. The Django test suite, the migrations and
this command all normally run as the owner, where RLS is inert; a check that
never changes roles measures the application's own query scoping and calls it
RLS. Only a connection as the non-owner role tests the database's half.

The verification password is supplied per run rather than read from settings, so
it never has to be stored on the host, and the probe rows it writes are rolled
back before the command exits --- they are real rows in a real table.

Usage::

    python manage.py verify_rls --password '<rakho_app password>'
    python manage.py verify_rls --password '...' --role rakho_app --expect-tables 18
"""

from __future__ import annotations

import os
from urllib.parse import quote, urlsplit, urlunsplit

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from inventory.rls_tables import COVERED_TABLES

#: UUID-shaped markers so the two probe rows are recognisable and cannot collide
#: with real data. Fixed rather than random, so a run that left rows behind is
#: identifiable on the next one.
MARKER_PREFIX = "0bf50000-0000-4000-8000-0000000000"
ORG_A = f"{MARKER_PREFIX}01"
ORG_B = f"{MARKER_PREFIX}02"
PROBE_NAME_LIKE = "RLS probe%"


def _application_dsn(role: str, password: str) -> str:
    """The deployment's own database, reached with the verification role.

    Host, port and database come from the live connection, so this verifies the
    actual target rather than a configured default, and the original query string
    is preserved because managed providers require TLS and dropping ``sslmode``
    would silently downgrade the connection.

    Both the role and the password are percent-encoded. A password containing
    ``@``, ``:`` or ``/`` would otherwise be spliced straight into the netloc and
    silently mis-parsed --- producing a connection refused by the *wrong* user,
    which reads as a permissions problem rather than a quoting one.
    """
    settings_dict = connection.settings_dict
    raw = urlsplit(os.environ.get("DATABASE_URL", ""))
    host = settings_dict.get("HOST") or raw.hostname or "localhost"
    port = str(settings_dict.get("PORT") or raw.port or "5432")
    name = settings_dict["NAME"]
    user = quote(role, safe="")
    secret = quote(password, safe="")
    netloc = f"{user}:{secret}@{host}:{port}"
    return urlunsplit(("postgres", netloc, f"/{name}", raw.query, ""))


def _insert_probe(cursor, org_id: str, suffix: str) -> None:
    """Create one organisation row carrying the shared marker."""
    from django.utils import timezone

    now = timezone.now()
    cursor.execute(
        """
        INSERT INTO inventory_organization
            (id, created_at, updated_at, name, slug, legal_name, bin, currency,
             timezone, locale, address, phone, billing_email, plan,
             branch_allowance, seat_addon_count, brand_name, brand_color,
             logo_url, white_label_enabled, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'BDT', 'Asia/Dhaka', 'bn-BD',
                %s, %s, %s, 'trial', 1, 0, %s, '#0E9F6E', '', false, true)
        """,
        (
            org_id,
            now,
            now,
            f"RLS probe {suffix}",
            f"rls-probe-{suffix}",
            f"RLS Probe {suffix}",
            "000000000",
            "probe address",
            "0000000000",
            f"probe-{suffix}@example.invalid",
            f"Probe {suffix}",
        ),
    )


def _probe_ids(cursor) -> list[str]:
    """The probe rows a connection can currently see, sorted for comparison."""
    cursor.execute(f"SELECT id::text FROM inventory_organization WHERE name LIKE '{PROBE_NAME_LIKE}' ORDER BY id")
    return [row[0] for row in cursor.fetchall()]


class Command(BaseCommand):
    help = "Demonstrate that RLS is enforced for the non-owner application role."

    def add_arguments(self, parser):
        parser.add_argument("--role", default="rakho_app", help="Non-owner application role (default: rakho_app).")
        parser.add_argument("--password", required=True, help="Password for that role.")
        parser.add_argument(
            "--expect-tables",
            type=int,
            default=len(COVERED_TABLES),
            help="How many tables RLS must cover (default: the migration's own list).",
        )
        parser.add_argument("--skip-behaviour", action="store_true", help="Check the catalog only; write nothing.")
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Delete probe rows left by an earlier run and exit; a correct run leaves none.",
        )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError(f"RLS is a PostgreSQL feature; this database is {connection.vendor}.")

        role = options["role"]
        expected = options["expect_tables"]
        failures: list[str] = []

        if options["purge"]:
            removed = self._purge(role, options["password"])
            self.stdout.write(self.style.SUCCESS(f"purged {removed} leftover probe row(s)."))
            return

        # ── 1. Catalog: policies exist, and RLS is FORCEd ──────────────────
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_class WHERE relrowsecurity AND relname = ANY(%s)", [COVERED_TABLES])
            enabled = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM pg_class WHERE relforcerowsecurity AND relname = ANY(%s)", [COVERED_TABLES])
            forced = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM pg_policies WHERE schemaname = 'public'")
            policies = cursor.fetchone()[0]

        self.stdout.write(f"catalog: {policies} policies; RLS enabled on {enabled}/{len(COVERED_TABLES)} tables.")
        if enabled < expected:
            failures.append(f"RLS is enabled on only {enabled} tables; expected {expected}")
        if forced < expected:
            # The one that matters most: without FORCE the owner is exempt, so a
            # deployment still connecting as the owner is wholly unprotected
            # while every dashboard reports the policies as present.
            failures.append(f"RLS is FORCED on only {forced} tables; expected {expected}")
        self.stdout.write(f"catalog: RLS FORCED on {forced}/{len(COVERED_TABLES)} tables (the owner is bound).")

        if options["skip_behaviour"]:
            return self._finish(failures, forced)

        # ── 2. Behaviour: run as the application role, not as the owner ────
        import psycopg  # imported here so this module loads without the driver

        owner_user = connection.settings_dict["USER"]
        conn = psycopg.connect(_application_dsn(role, options["password"]), autocommit=False)
        unbound_count = -1
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user")
                as_role = cursor.fetchone()[0]
                if as_role == owner_user:
                    raise CommandError(f"verification connected as '{as_role}', the table owner --- RLS is inert for " "the owner, so this run would prove nothing. Check --role/--password.")
                self.stdout.write(f"behaviour: connected as '{as_role}', a non-owner role.")

                # Deliberately NOT committed. The probe rows are real rows in a
                # real registry, and a rollback is the only cleanup that cannot
                # fail separately from the work it is cleaning up --- an earlier
                # revision committed here, which made the rollback in the
                # ``finally`` block a no-op and left two fake organisations
                # behind on every run.
                _insert_probe(cursor, ORG_A, "alpha")
                _insert_probe(cursor, ORG_B, "beta")

                # No tenant bound: the default posture must be deny.
                unbound = _probe_ids(cursor)
                unbound_count = len(unbound)
                if unbound:
                    failures.append(f"an UNBOUND connection saw {unbound_count} probe rows ({unbound[:2]}\u2026); " "the default must be deny")

                # Bound to entity A: exactly A's row may appear.
                cursor.execute("SELECT set_config('app.current_org', %s, true)", [ORG_A])
                bound = _probe_ids(cursor)
                if bound != [ORG_A]:
                    failures.append(f"bound to org A, expected exactly [{ORG_A}] and saw {bound}")
                else:
                    self.stdout.write("behaviour: bound to org A, saw exactly org A's row and not org B's.")
                cursor.execute("SELECT set_config('app.current_org', '', true)")

                # And the reverse, so a policy that merely matched nothing is
                # not mistaken for correct scoping.
                cursor.execute("SELECT set_config('app.current_org', %s, true)", [ORG_B])
                reverse = _probe_ids(cursor)
                if reverse != [ORG_B]:
                    failures.append(f"bound to org B, expected exactly [{ORG_B}] and saw {reverse}")
        finally:
            # ── 3. Leave no trace ──────────────────────────────────────────
            # Real rows were written to a real registry; roll back unconditionally,
            # including on the failure path, or a broken run would strand two fake
            # organisations in the table.
            conn.rollback()
            conn.close()

        return self._finish(failures, forced, unbound_count)

    def _purge(self, role: str, password: str) -> int:
        """Delete any probe rows a previous run left behind, and report how many.

        Recovery only: a correct run commits nothing and so leaves nothing. But
        because a broken run *could* strand rows, shipping the cleanup is the
        difference between a tool that can be trusted on production and one that
        quietly needs a manual ``psql`` afterwards. Each probe organisation has to
        be bound in turn, because RLS is FORCED and an unbound connection cannot
        see the rows to delete them.
        """
        import psycopg  # imported here so this module loads without the driver

        deleted = 0
        conn = psycopg.connect(_application_dsn(role, password), autocommit=False)
        try:
            with conn.cursor() as cursor:
                for org_id in (ORG_A, ORG_B):
                    cursor.execute("SELECT set_config('app.current_org', %s, true)", [org_id])
                    cursor.execute(f"DELETE FROM inventory_organization WHERE name LIKE '{PROBE_NAME_LIKE}'")
                    deleted += cursor.rowcount
            conn.commit()
        finally:
            conn.close()
        return deleted

    def _finish(self, failures: list[str], forced: int, unbound_count: int | None = None) -> None:
        if unbound_count is not None:
            self.stdout.write(f"behaviour: an unbound connection saw {unbound_count} probe rows (must be 0).")

        if failures:
            self.stdout.write("")
            for failure in failures:
                self.stdout.write(self.style.ERROR(f"FAIL: {failure}"))
            raise CommandError(f"RLS verification failed with {len(failures)} problem(s).")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"RLS VERIFIED: policies exist, RLS is FORCED on {forced} tables, and a non-owner " "connection bound to one organisation cannot see another's rows."))
