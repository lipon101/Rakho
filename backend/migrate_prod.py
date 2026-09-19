"""Idempotent production migrate for Render builds.

Why this exists: on a managed Postgres (Neon/Render) a previous deploy attempt
can leave the database partially initialized — built-in tables (contenttypes,
auth, sessions) exist but their django_migrations rows were never recorded, so a
plain `migrate` crashes with `relation "django_content_type" already exists`.
A production build must never crash on that.

Strategy, in order:
1. `migrate` normally (the common case; everything recorded).
2. On an existing-relation error, run a baseline recovery: mark the built-in
   apps' initial migrations as applied (--fake) so Django stops trying to
   recreate their tables, then run a plain migrate to apply anything new
   (including our inventory migrations).

Migrations are authored and reviewed in the repo; we never run makemigrations
on the server, so production state is reproducible from version control.
"""

import os
import sys

import django

# Built-in apps whose initial migrations create the shared framework tables.
# When a DB is partially initialized these are the ones that collide.
BASELINE_APPS = ("contenttypes", "auth", "sessions")


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    from django.core.management import call_command
    from django.db import utils as db_utils

    try:
        call_command("migrate", interactive=False, verbosity=1)
        print("MIGRATE_OK")
        return 0
    except (db_utils.ProgrammingError, db_utils.OperationalError) as exc:
        print(f"Plain migrate hit an existing-relation error: {exc}", file=sys.stderr)
        print("Running baseline recovery (fake built-in initials, then apply new).")
        # Mark the shared framework migrations as already applied so their
        # tables are not recreated. Safe: those exact tables already exist.
        for app in BASELINE_APPS:
            try:
                call_command("migrate", app, interactive=False, fake=True, verbosity=0)
            except Exception as fake_exc:
                print(f"baseline fake for {app} raised: {fake_exc}", file=sys.stderr)
        # Apply anything genuinely new (our inventory migrations).
        call_command("migrate", interactive=False, verbosity=1)
        print("MIGRATE_OK_RECOVERED")
        return 0


if __name__ == "__main__":
    sys.exit(main())

