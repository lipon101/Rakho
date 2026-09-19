"""Idempotent production migrate for Render builds.

Why this exists: on a managed Postgres (Neon/Render) a previous deploy attempt
can leave the database partially initialized — built-in tables (contenttypes,
auth, sessions) exist but their django_migrations rows were never recorded, so a
plain `migrate` crashes with `relation "django_content_type" already exists`.
A production build must never crash on that.

Strategy:
1. `migrate` normally (the common case; everything recorded).
2. On failure, run the stepwise recovery (management command `stepwise_migrate`):
   each pending migration is attempted on its own; one that fails only because
   its tables/indexes/constraints already exist is recorded as applied and the
   rest are applied for real. Data migrations are never faked, so a genuine
   mismatch still fails loudly instead of being masked.

Migrations are authored and reviewed in the repo; we never run makemigrations
on the server, so production state is reproducible from version control.
"""

import os
import sys

import django

# Kept for backwards compatibility: recovery no longer fakes whole apps, but
# the tuple documents the built-in apps that collide on partial init.
BASELINE_APPS = ("contenttypes", "auth", "sessions")


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    from django.core.management import call_command

    try:
        call_command("migrate", interactive=False, verbosity=1)
        print("MIGRATE_OK")
        return 0
    except Exception as exc:  # noqa: BLE001 - recovery must be bulletproof
        print(
            f"Plain migrate failed ({type(exc).__name__}: {exc}); "
            f"running stepwise recovery.",
            file=sys.stderr,
        )

    # Recovery path: apply each pending migration individually, faking only
    # the ones whose schema already exists. Non-recoverable failures still
    # crash the build loudly (so a real problem is never silently masked).
    call_command("stepwise_migrate", verbosity=1)
    print("MIGRATE_OK_RECOVERED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
