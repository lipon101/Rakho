"""Create the non-owner database role that RLS actually constrains.

``ENABLE ROW LEVEL SECURITY`` exempts the table's owner, which is the right
default --- it means turning RLS on cannot break a deployment whose application
connects as the owner. But it also means that until the application connects as
*someone else*, the policies are inert. This command performs that move:

1. create a ``rakho_app`` role with ``LOGIN`` and no ``SUPERUSER``/``BYPASSRLS``;
2. grant it the privileges it needs on the schema and its tables;
3. ``FORCE ROW LEVEL SECURITY`` on every covered table, so the owner is bound
   too --- safe now, because the application is about to stop being the owner.

It is idempotent: running it twice changes nothing and reports so. It prints the
``DATABASE_URL`` the application should use afterwards, because the one step it
cannot do for you is change the deployment's environment.

Usage::

    python manage.py setup_rls_role --password 'a-long-random-secret'
    python manage.py setup_rls_role --password '...' --role rakho_app --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from inventory.rls_tables import COVERED_TABLES

DEFAULT_ROLE = "rakho_app"


class Command(BaseCommand):
    help = "Create the non-owner application role and FORCE RLS on the tenant tables."

    def add_arguments(self, parser):
        parser.add_argument("--role", default=DEFAULT_ROLE, help=f"Role name to create (default: {DEFAULT_ROLE}).")
        parser.add_argument("--password", required=True, help="Password for the new role. Required: a role with no password cannot log in.")
        parser.add_argument("--dry-run", action="store_true", help="Print the statements without executing them.")

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("RLS is a PostgreSQL feature; this database is " f"{connection.vendor}.")

        role = options["role"]
        password = options["password"]
        dry_run = options["dry_run"]

        # The role name is interpolated into DDL, which cannot take a bound
        # parameter. It is therefore validated rather than trusted: a name with
        # a quote or a space in it is refused outright.
        if not role.replace("_", "").isalnum():
            raise CommandError("Role name must be alphanumeric or underscore only.")

        statements = [
            # CREATE ROLE has no IF NOT EXISTS, so existence is checked first.
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN CREATE ROLE {role} LOGIN PASSWORD %s; END IF; END $$;",
            f"GRANT CONNECT ON DATABASE {connection.settings_dict['NAME']} TO {role};",
            f"GRANT USAGE ON SCHEMA public TO {role};",
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role};",
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role};",
            # Future tables created by a later migration must be reachable too,
            # or the next deploy would fail with a permission error on a table
            # nobody remembered to grant.
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role};",
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role};",
        ]
        for table in COVERED_TABLES:
            statements.append(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

        if dry_run:
            self.stdout.write("-- dry run: the following would be executed")
            for statement in statements:
                self.stdout.write(statement.replace("%s", "'<password>'"))
            return

        with connection.cursor() as cursor:
            for statement in statements:
                if "%s" in statement:
                    cursor.execute(statement, [password])
                else:
                    cursor.execute(statement)

        host = connection.settings_dict.get("HOST") or "localhost"
        port = connection.settings_dict.get("PORT") or "5432"
        name = connection.settings_dict["NAME"]
        self.stdout.write(self.style.SUCCESS(f"Role '{role}' is ready and RLS is FORCED on {len(COVERED_TABLES)} tables."))
        self.stdout.write("")
        self.stdout.write("Point the application at the new role by setting DATABASE_URL to:")
        self.stdout.write(f"  postgres://{role}:<password>@{host}:{port}/{name}")
        self.stdout.write("")
        self.stdout.write("Then set RLS_ENABLED=true. Until both are done the policies stay inert, " "which is the safe order: the role exists before anything depends on it.")
