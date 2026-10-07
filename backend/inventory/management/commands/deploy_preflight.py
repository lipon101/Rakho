"""Refuse a production deploy that is missing a required setting, before it ships.

Why this exists
---------------
``config/settings/production.py`` raises :class:`ImproperlyConfigured` at import
time when the deployment is unsafe or unbuildable --- which is the right design,
because a service that boots wrong-but-running is worse than one that fails
loudly. But on a host that keeps the last successful deploy serving when a new
one fails, the symptom is not an error at all: the site simply *stays on the old
version* while the deploy hook returns success. That is exactly what happened to
this project --- the live host kept answering 200 on ``/health/`` while
``/version/`` 404'd, and nothing in the repository said why.

So this command turns that silent failure into a diagnosis. It checks the
settings contract first (so every missing variable is listed at once, rather than
one per failed deploy), then imports the real production settings module as the
authoritative verdict.

Wire it into the deploy pipeline ahead of the app, and a misconfigured release
fails in seconds naming the variable to set, instead of quietly not happening.

Usage::

    python manage.py deploy_preflight
    python manage.py deploy_preflight --json
"""

from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError

#: The development default in ``base.py``. Shipping it to production would make
#: every signed cookie and session forgeable, so it is refused by name.
INSECURE_SECRET_KEYS = {
    "",
    "unsafe-development-only-key-change-me",
    "local-development-key-not-for-deployment",
}

MIN_SECRET_KEY_LENGTH = 32


def _checks() -> list[tuple[bool, str, str]]:
    """Return ``(ok, name, detail)`` for every setting production requires.

    Each entry names the variable to set rather than describing the fault, because
    the person reading this is looking at a failed deploy at the worst possible
    moment and needs the fix, not the theory.
    """
    results: list[tuple[bool, str, str]] = []

    secret = os.environ.get("DJANGO_SECRET_KEY", "")
    if secret in INSECURE_SECRET_KEYS:
        results.append((False, "DJANGO_SECRET_KEY", "not set (or still the development default)"))
    elif len(secret) < MIN_SECRET_KEY_LENGTH:
        results.append((False, "DJANGO_SECRET_KEY", f"only {len(secret)} characters; at least {MIN_SECRET_KEY_LENGTH} are required"))
    else:
        results.append((True, "DJANGO_SECRET_KEY", "set to a deployment value"))

    render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    allowed = [host for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host.strip()]
    if allowed and allowed != ["localhost", "127.0.0.1"]:
        results.append((True, "ALLOWED_HOSTS", "explicit host list"))
    elif render_hostname:
        results.append((True, "ALLOWED_HOSTS", f"derived from RENDER_EXTERNAL_HOSTNAME ({render_hostname})"))
    else:
        results.append((False, "ALLOWED_HOSTS", "unset or left at the localhost default, and RENDER_EXTERNAL_HOSTNAME is absent"))

    redis_url = os.environ.get("REDIS_URL", "").strip()
    if redis_url:
        results.append((True, "REDIS_URL", "set (shared cache, DRF throttles and the Celery broker)"))
    else:
        # Not optional: without a shared cache the DRF throttles are per-worker,
        # so a "10/hour" limit silently becomes "10/hour *per worker*", and the
        # Celery broker has nothing to talk to.
        results.append((False, "REDIS_URL", "not set; the shared cache, the DRF throttles and the Celery broker all need it"))

    database_url = os.environ.get("DATABASE_URL", "").strip()
    results.append(
        (
            bool(database_url),
            "DATABASE_URL",
            "set" if database_url else "not set; production has no local database to fall back to",
        )
    )

    if os.environ.get("CORS_ALLOW_ALL_ORIGINS", "").strip().lower() in {"1", "true", "yes"}:
        results.append((False, "CORS_ALLOW_ALL_ORIGINS", "is true, which production refuses; set CORS_ALLOWED_ORIGINS instead"))
    else:
        results.append((True, "CORS_ALLOW_ALL_ORIGINS", "not enabled"))

    return results


class Command(BaseCommand):
    help = "Verify the production settings a deploy needs, before it goes live."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit the result as JSON, for a pipeline to consume.")

    def handle(self, *args, **options):
        results = _checks()
        failures = [(name, detail) for ok, name, detail in results if not ok]

        # The authoritative verdict: import the real production module. The
        # checks above are for a *readable* report; this is the one that cannot
        # drift from the settings the app will actually run.
        import_error = ""
        try:
            from config.settings import production  # noqa: F401

            imported = True
        except Exception as exc:  # noqa: BLE001 - the whole point is to report it
            imported = False
            import_error = f"{type(exc).__name__}: {exc}"

        if options["json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "ready": imported and not failures,
                        "settings_imported": imported,
                        "import_error": import_error,
                        "failures": [{"variable": name, "detail": detail} for name, detail in failures],
                    },
                    indent=2,
                )
            )
        else:
            for ok, name, detail in results:
                mark = "ok  " if ok else "FAIL"
                style = self.style.SUCCESS if ok else self.style.ERROR
                self.stdout.write(style(f"  [{mark}] {name}: {detail}"))
            self.stdout.write("")
            if imported:
                self.stdout.write(self.style.SUCCESS("settings imported cleanly under production configuration."))
            else:
                self.stdout.write(self.style.ERROR(f"production settings refused to load: {import_error}"))

        if failures or not imported:
            if not options["json"]:
                self.stdout.write("")
                self.stdout.write("Set the missing variables in the host's environment (Render: dashboard -> service ->")
                self.stdout.write("Environment) and redeploy. See backend/docs/deployment-checklist.md.")
            raise CommandError(f"deploy preflight failed: {len(failures)} missing setting(s)" + ("" if imported else ", and the production settings module did not import"))

        if not options["json"]:
            self.stdout.write(self.style.SUCCESS("preflight passed: this deployment is ready to serve."))
