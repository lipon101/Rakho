"""Idempotent production migrate for Render builds.

Why this exists: on a managed Postgres (Neon/Render) a previous deploy attempt
can leave the database partially initialized, and a plain `migrate` then fails
with `relation "django_content_type" already exists`. A production build must
never crash on that.

Strategy, in order:
1. `migrate` normally (the common case; all migrations recorded).
2. If it fails because built-in tables already exist, run
   `migrate --fake-initial` so Django treats existing tables as already applied,
   records them in django_migrations, then applies anything genuinely new.

Never uses `makemigrations` on the server — migrations are authored and reviewed
in the repo, so production state is always reproducible from version control.
"""

import os
import sys

import django


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
        # e.g. a table from a prior partial attempt already exists. The exact
        # exception class differs between Postgres (ProgrammingError) and other
        # backends (OperationalError); catch both so the build never crashes.
        print(f"Plain migrate hit an existing-relation error: {exc}", file=sys.stderr)
        print("Retrying with --fake-initial so existing tables are recorded, not recreated.")
        call_command("migrate", interactive=False, fake_initial=True, verbosity=1)
        print("MIGRATE_OK_FAKE_INITIAL")
        return 0


if __name__ == "__main__":
    sys.exit(main())
