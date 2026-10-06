"""Local development settings.

Everything here exists to make a developer's machine convenient, so nothing in
this module may be used in a deployment. ``DEBUG`` is on, SQLite is the default
database, HTTPS is not forced, and the module refuses to load at all if the
environment asks for ``DEBUG=false`` --- which is the only realistic way to ship
it by mistake.
"""

import os

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, TESTING

DEBUG = True

# A development secret is fine here and only here; production refuses to boot
# without a real one.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-development-key-not-for-deployment")

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]
if host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(host)

# SQLite unless a developer points DATABASE_URL somewhere else (a local
# Postgres, to exercise the RLS migration before pushing).
DATABASES = {
    "default": dj_database_url.config(  # noqa: F405
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=0,
        conn_health_checks=False,
    )
}

# Run Celery tasks inline unless a broker is explicitly configured, so a
# developer can exercise an expiry digest with no Redis running.
if not os.environ.get("REDIS_URL"):
    CELERY_TASK_ALWAYS_EAGER = True  # noqa: F405
    CELERY_TASK_EAGER_PROPAGATES = False  # noqa: F405

# The front-end dev server is on an explicit allowlist rather than behind a
# wildcard. A wildcard would be harmless in itself (this module is never loaded
# in production), but it would also make the local configuration *behave
# differently* from the deployed one in the one respect that is easiest to get
# wrong: a wildcard echoes ``Access-Control-Allow-Origin: *``, an allowlist
# echoes the caller's origin. Code that reads the echoed value would then work
# locally and fail in production. Same behaviour everywhere; only the permitted
# origins differ.
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]

# Static files: the plain storage, so a missing collectstatic never blocks a
# developer from loading the console.
STORAGES = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}  # noqa: F405

# Django's own dev-server defaults are fine; no TLS, no HSTS, no redirect.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Plain-text logs on a terminal: a JSON blob per line is unreadable when you are
# tailing a runserver.
LOGGING["handlers"]["console"]["formatter"] = "plain"  # noqa: F405
LOGGING["root"]["level"] = os.environ.get("LOG_LEVEL", "INFO").upper()  # noqa: F405

# Let the console and the SPA talk to each other without a proxy during
# development.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# The guard reads the environment rather than the ``DEBUG`` assigned a few lines
# above --- that assignment is always True, so testing it would be dead code and
# the check would never fire. What is being caught here is the contradictory
# case: something asked for ``DEBUG=false`` while also naming the development
# module, which means a deployment is running permissive settings by accident.
if os.environ.get("DEBUG", "").lower() == "false" and not TESTING:  # pragma: no cover - a guard, not a branch
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("DEBUG=false was requested but config.settings.local was selected. Use config.settings.production instead.")
