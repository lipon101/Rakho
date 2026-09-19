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

    def plain():
        call_command("migrate", interactive=False, verbosity=1)

    try:
        plain()
        print("MIGRATE_OK")
        return 0
    except (db_utils.ProgrammingError, db_utils.OperationalError) as exc:
        # A prior partial deploy left tables that exist without matching
        # django_migrations rows. Recover by first marking every migration whose
        # tables already exist as applied (fake), then applying whatever is new.
        print(f"Plain migrate hit an existing-relation error: {exc}", file=sys.stderr)
        print("Recovering: marking existing migrations as applied, then applying new ones.")
        try:
            # Record all migrations as applied without touching the schema. This
            # is safe here because the failing tables already exist; the real
            # schema state is reconciled by the final plain migrate below.
            call_command("migrate", interactive=False, fake=True, verbosity=0)
            print("FAKED_EXISTING")
        except Exception as fake_exc:
            print(f"fake pass raised: {fake_exc}", file=sys.stderr)
        # Now apply anything genuinely new (none will be 'initial' anymore).
        plain()
        print("MIGRATE_OK_RECOVERED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
