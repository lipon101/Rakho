from pathlib import Path
import os
import sys
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
    "DIRS": [BASE_DIR / "templates"],
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
# Managed Postgres providers (Neon, Supabase, Render) require TLS. When the
# DATABASE_URL points at one, enforce sslmode=require so the driver negotiates
# a secure connection instead of being refused. Local sqlite is unaffected.
if DATABASES["default"].get("ENGINE") == "django.db.backends.postgresql":
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].setdefault("sslmode", "require")
AUTH_PASSWORD_VALIDATORS = [
    # A weak admin password is the single biggest risk on a public deployment;
    # enforce real strength for the owner console.
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Admin console location ──
# The admin lives at a non-obvious path instead of /admin/. Set ADMIN_URL on
# Render to a random string (e.g. "console-x7q9") so even this default is not
# the real address; the public repo only ever shows the default.
ADMIN_URL = os.environ.get("ADMIN_URL", "lostsec").strip("/") + "/"

# ── Production security hardening ──
# Active when DEBUG=false AND we are not running the test suite. Render sets
# DEBUG=false in production, so these are live there; tests and local dev keep
# plain http so nothing is redirected away.
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
if not DEBUG and not TESTING:
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
        "signup_daily": "3/day",
        "payment": "30/hour",
    },
}

# ── Storefront (landing page + manual MFS payments) ──
# The bKash/Nagad number customers send money to, and the Pro price shown on
# the landing page. Override via env on Render; never commit real secrets.
PAYMENT_NUMBER = os.environ.get("PAYMENT_NUMBER", "+8801580857515")
PAYMENT_METHODS = os.environ.get("PAYMENT_METHODS", "bKash / Nagad")
PRO_PRICE_BDT = os.environ.get("PRO_PRICE_BDT", "299")

# The app's Google Play listing. Customers run the shop from the Android app,
# so this is the other half of the funnel beside the signup form — but the
# listing does not exist until it is published. Left empty, the landing page
# renders no install section, no nav link and no downloadUrl rather than a
# button that leads to a 404; set it once and all three appear together.
PLAY_STORE_URL = os.environ.get("PLAY_STORE_URL", "")

# Canonical public origin, used for the canonical link, Open Graph URLs,
# structured-data @ids, robots.txt and the sitemap. Render sets
# RENDER_EXTERNAL_HOSTNAME, so the default already tracks the real host and
# moving to a custom domain only means setting SITE_URL once — instead of
# leaving a stale onrender.com address in the page's canonical tag.
SITE_URL = os.environ.get(
    "SITE_URL",
    "https://" + os.environ.get("RENDER_EXTERNAL_HOSTNAME", "rakho-api.onrender.com"),
).rstrip("/")

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
