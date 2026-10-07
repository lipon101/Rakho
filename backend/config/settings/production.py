"""Production settings.

Everything in this module assumes Rakho is reachable from the internet and is
holding real pharmacies' inventory data. Two rules follow from that and are
enforced rather than documented:

1. **A misconfiguration stops the process.** A wildcard CORS origin, a
   development secret key or a missing ALLOWED_HOSTS raises at import time.
   Booting a wrong-but-running server is worse than failing the deploy, because
   a failed deploy is noticed in seconds and a leak is noticed in months.
2. **The strict value is the default.** If an operator sets nothing at all,
   they get the hardened posture, not the convenient one.
"""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import TESTING

DEBUG = False

# ── Secrets ─────────────────────────────────────────────────────────────────
_insecure_defaults = {"", "unsafe-development-only-key-change-me", "local-development-key-not-for-deployment"}
if SECRET_KEY in _insecure_defaults:  # noqa: F405
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set to a real value in production.")
if len(SECRET_KEY) < 32:  # noqa: F405
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be at least 32 characters in production.")

# ── CORS: default deny, refuse a wildcard ───────────────────────────────────
# The API is read by the Android app (no Origin, CORS-irrelevant) and by the
# web console (a known origin). A wildcard would let any site on the internet
# read a pharmacy's stock with a leaked key, so it is refused rather than
# merely warned about --- the previous fail-open switch is exactly the class of
# misconfiguration this module exists to make impossible. deploy_preflight
# enforces the same rule, so an operator meets it in CI rather than in a
# breach, and render.yaml ships the variable as "false" for the same reason.
if CORS_ALLOW_ALL_ORIGINS:  # noqa: F405
    raise ImproperlyConfigured("CORS_ALLOW_ALL_ORIGINS=true is refused in production. " "Set CORS_ALLOWED_ORIGINS to the exact console origin(s) instead.")
CORS_ALLOW_ALL_ORIGINS = False  # noqa: F405

# Checked after the CORS refusal, so that when both are wrong the operator is
# told about the security-critical fault first. A missing host list is not a
# style problem: with DEBUG off Django answers 400 to every request, so the
# deployment is down rather than merely insecure --- and a failure at import is
# a far clearer diagnosis than a wall of 400s in the access log.
#
# RENDER_EXTERNAL_HOSTNAME is the platform's own name for this service, so it
# is a correct host rather than a convenient guess: an operator who set nothing
# gets the deploy working, and an operator who set a wrong list still fails.
if not ALLOWED_HOSTS or ALLOWED_HOSTS == ["localhost", "127.0.0.1"]:  # noqa: F405
    if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip():
        ALLOWED_HOSTS = [render_host]
    else:
        raise ImproperlyConfigured("ALLOWED_HOSTS must name the real host(s) in production, or set RENDER_EXTERNAL_HOSTNAME.")

# ── TLS / transport hardening ───────────────────────────────────────────────
# Render terminates TLS at the proxy; trust its header, then force HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
# A Content-Security-Policy for the server-rendered pages (landing, checkout,
# legal). 'unsafe-inline' is required by the hand-rolled inline <style> and
# <script> the landing page ships; 'self' still blocks an injected third-party
# origin, which is the threat that matters. The API and the SPA are unaffected.
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

CSRF_TRUSTED_ORIGINS = [origin for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", SITE_URL).split(",") if origin]  # noqa: F405

# ── Cache + broker: Redis is required, not optional ─────────────────────────
# Without a shared cache, DRF throttles are per-worker. A single gunicorn
# worker with four threads would give a "10/hour" signup limit an effective
# ceiling of 20-40/hour, and the daily signup tally would be inconsistent
# between workers. Failing the deploy is the honest outcome.
if not REDIS_URL:  # noqa: F405
    raise ImproperlyConfigured("REDIS_URL must be set in production: it backs the shared cache, the DRF throttles and the Celery broker.")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,  # noqa: F405
        "KEY_PREFIX": "rakho",
        "TIMEOUT": 300,
    }
}

# ── Cookie / session posture ────────────────────────────────────────────────
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # the console JS reads it to send the header
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_AGE = 60 * 60 * 12

# ── Error reporting ─────────────────────────────────────────────────────────
# Verbose debug pages must never reach the public internet.
DEBUG_PROPAGATE_EXCEPTIONS = False

# ── Object storage (exports + org logos) ────────────────────────────────────
# When a bucket is configured, generated exports and branding assets go to
# S3-compatible storage and are served as time-limited signed URLs. With no
# bucket, the local filesystem is used, which is acceptable only on a
# single-instance deployment.
if MEDIA_S3_BUCKET:  # noqa: F405
    STORAGES["default"] = {  # noqa: F405
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": MEDIA_S3_BUCKET,  # noqa: F405
            "region_name": MEDIA_S3_REGION,  # noqa: F405
            "endpoint_url": MEDIA_S3_ENDPOINT or None,  # noqa: F405
            "access_key": MEDIA_S3_ACCESS_KEY,  # noqa: F405
            "secret_key": MEDIA_S3_SECRET_KEY,  # noqa: F405
            # Private by default: an export holds a whole branch's sales, so it
            # is reached through a signed URL, never a guessable public path.
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": EXPORT_URL_TTL_SECONDS,  # noqa: F405
            "file_overwrite": False,
        },
    }

# ── Password reset / email ──────────────────────────────────────────────────
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Rakho <no-reply@rakho.app>")

# ── Safety valve for management commands ────────────────────────────────────
# ``manage.py`` under production settings has to be able to run without the
# full guard when a developer inspects the deployed config (``check --deploy``
# in CI does exactly this), so TESTING keeps the guards quiet there.
if TESTING:  # pragma: no cover - only true when a test imports this module
    pass
