from pathlib import Path
import os
import dj_database_url
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "unsafe-development-only-key-change-me")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [host for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host]
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "inventory",
    "drf_spectacular",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {"staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "inventory.exceptions.api_exception_handler",
    # Abuse protection: the catalog search is unauthenticated and hits a
    # 14k-row table, so anonymous traffic is rate limited per IP. Keyed
    # pharmacy traffic gets a generous but finite ceiling. Throttling is
    # backed by the default cache; on single-instance deploys LocMemCache
    # is sufficient.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/hour",
        "catalog": "240/hour",
        "health": "60/hour",
        "pharmacy": "6000/hour",
        # Public self-serve endpoints get a tight per-IP ceiling so an attacker
        # cannot mint unlimited tenants/keys or brute-force TrxID values.
        "signup": "10/hour",
        "payment": "30/hour",
    },
}

# ── Storefront (landing page + manual MFS payments) ──
# The bKash/Nagad number customers send money to, and the Pro price shown on
# the landing page. Override via env on Render; never commit real secrets.
PAYMENT_NUMBER = os.environ.get("PAYMENT_NUMBER", "+8801580857515")
PAYMENT_METHODS = os.environ.get("PAYMENT_METHODS", "bKash / Nagad")
PRO_PRICE_BDT = os.environ.get("PRO_PRICE_BDT", "299")

# ── Sentry error monitoring (free tier) ──
# Set SENTRY_DSN on Render to enable. No-op when unset so local dev stays clean.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        # Only errors — no PII, no performance spans — on the free tier.
        traces_sample_rate=0.0,
        send_default_pii=False,
    )

# ── CORS (mobile & web clients) ──
CORS_ALLOW_ALL_ORIGINS = os.environ.get("CORS_ALLOW_ALL_ORIGINS", "false").lower() == "true"
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
CORS_ALLOW_HEADERS = [*default_headers, "x-pharmacy-key", "x-setup-token"]

# Guards the public /api/v1/setup/* endpoints when non-empty.
SETUP_TOKEN = os.environ.get("SETUP_TOKEN", "")

# ── Google Play Billing (server-side purchase verification) ──
# A service account with access to the Play Console, either as inline JSON or
# as a path to the JSON key file. When empty, the billing endpoints answer 503
# and every pharmacy stays on the free plan instead of trusting the client.
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "")
GOOGLE_PLAY_PACKAGE_NAME = os.environ.get("GOOGLE_PLAY_PACKAGE_NAME", "com.lipon.rakho")

# ── OpenAPI / Swagger ──
REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"
SPECTACULAR_SETTINGS = {
    "TITLE": "Pharmacy Inventory API",
    "DESCRIPTION": "REST API for pharmacy inventory management — medicines, batches, purchases, sales, FEFO stock rotation, and expiry alerts.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "CONTACT": {"name": "API Support"},
}
