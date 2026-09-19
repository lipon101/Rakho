#!/usr/bin/env python3
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
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
    if (argv1 == "migrate"
            and not is_test
            and not any(a in passthrough_flags for a in sys.argv)):
        sys.argv[1] = "stepwise_migrate"

    execute_from_command_line(sys.argv)
