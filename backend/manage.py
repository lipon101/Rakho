#!/usr/bin/env python3
import importlib
import os
import sys


def _pick_settings():
    """Which settings module this process should use.

    An explicit ``DJANGO_SETTINGS_MODULE`` always wins. Otherwise the choice is
    made from the environment rather than from a default, because the two
    plausible mistakes are not equally bad: running the hardened configuration
    on a laptop fails loudly and instantly, while running the development one
    on the internet exposes every tenant. Render sets ``RENDER=true``, so a
    deployment gets ``production`` without anyone having to remember a flag.

    ``test`` is called out separately. The production module deliberately
    refuses to import without a real secret key, a real ``ALLOWED_HOSTS`` and a
    ``REDIS_URL``, none of which a contributor's laptop or a CI runner has ---
    so a test run that inherited production settings would fail at import
    rather than at an assertion, and the failure would say nothing about the
    code under test.
    """
    explicit = os.environ.get("DJANGO_SETTINGS_MODULE")
    if explicit:
        return explicit
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        return "config.settings.local"
    if os.environ.get("RENDER") or os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
        return "config.settings.production"
    return "config.settings.local"


def _explain_broken_production_settings() -> None:
    """Print ``deploy_preflight``'s report for a production import that refused.

    Django's management machinery loads the settings module before it can
    locate the requested command (``get_commands()`` reads
    ``settings.INSTALLED_APPS``), so a production refusal --- a missing
    ``REDIS_URL``, say --- escapes as a raw traceback and the one command that
    exists to diagnose a failed deploy never runs. This is that command's
    report, run directly with the machinery bypassed: every missing variable
    named at once, plus the import refusal, instead of the single guard that
    fired first.
    """
    from django.core.management.base import CommandError

    from inventory.management.commands.deploy_preflight import Command

    try:
        Command().handle(json="--json" in sys.argv)
    except CommandError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", _pick_settings())
    from django.core.exceptions import ImproperlyConfigured
    from django.core.management import execute_from_command_line

    # Production guard: a plain `migrate` on a partially-initialized managed
    # Postgres crashes with `relation "..." already exists`. Render's dashboard
    # build command has historically used plain `manage.py migrate`; rather
    # than depend on the dashboard being updated, make migrate self-heal here.
    # Explicit operator flags and `manage.py test` are passed through
    # untouched: they express intent the recovery runner must not override.
    argv1 = sys.argv[1] if len(sys.argv) > 1 else ""
    passthrough_flags = {"--fake", "--fake-initial", "--plan", "--prune"}
    is_test = any(a == "test" or a.endswith(".tests") for a in sys.argv)
    if argv1 == "migrate" and not is_test and not any(a in passthrough_flags for a in sys.argv):
        sys.argv[1] = "stepwise_migrate"

    try:
        execute_from_command_line(sys.argv)
    except ImproperlyConfigured:
        # Django's machinery re-raises a settings-import refusal as a raw
        # traceback (fetch_command reads INSTALLED_APPS to locate the command),
        # before deploy_preflight --- the command built for exactly this moment
        # --- can run. Translate it into that command's report, but only when
        # the production module is what failed to import: a command raising
        # ImproperlyConfigured for its own reasons, or a code bug inside the
        # settings module, keeps its real traceback.
        settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
        if settings_module == "config.settings.production":
            try:
                importlib.import_module(settings_module)
            except ImproperlyConfigured:
                _explain_broken_production_settings()
        raise
