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

import logging
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import TESTING

logger = logging.getLogger(__name__)

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
# misconfiguration this module exists to make impossible.
if CORS_ALLOW_ALL_ORIGINS:  # noqa: F405
    logger.warning("CORS_ALLOW_ALL_ORIGINS=true was specified in production; automatically forcing CORS_ALLOW_ALL_ORIGINS=False for security.")
    CORS_ALLOW_ALL_ORIGINS = False  # noqa: F405

# Checked after the CORS refusal, so that when both are wrong the operator is
# told about the security-critical fault first. A missing host list is not a
# style problem: with DEBUG off Django answers 400 to every request, so the
# deployment is down rather than merely insecure --- and a failure at import is
# a far clearer diagnosis than a wall of 400s in the access log.
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
