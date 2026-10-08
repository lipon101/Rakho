"""Base settings shared by every environment.

This module holds everything that is true regardless of where Rakho runs: the
apps, the middleware, the DRF contract, the logging shape and the feature
flags. The two environment modules on top of it add only what differs ---
``local`` turns on DEBUG and SQLite, ``production`` turns on TLS hardening and
a shared Redis cache.

The split exists because the previous single module decided those differences
with ``if`` statements on ``DEBUG``. That worked, but it meant a production
misconfiguration could only be discovered by reading a conditional that had
already evaluated; now the environment is chosen once, by name, and each
module states its own posture outright.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

import dj_database_url
from corsheaders.defaults import default_headers

from config.secrets import resolve_secret

# ``config/settings/base.py`` -> ``config/settings`` -> ``config`` -> ``backend``.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "unsafe-development-only-key-change-me")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [host for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host]
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# ── Am I running the test suite? ─────────────────────────────────────────────
# Detected once, here, because several settings below legitimately differ under
# test (static files storage, eager Celery). The three signals cover
# ``manage.py test``, an explicit env var, and pytest-django --- whose argv
# does not contain "test" at all.
TESTING = (len(sys.argv) > 1 and sys.argv[1] == "test") or os.environ.get("DJANGO_TESTING", "").lower() == "true" or "pytest" in sys.modules

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "django_celery_beat",
    "storages",
    "inventory",
    "drf_spectacular",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # Request id first, so every log line and every error envelope below it
    # can be tied back to one request.
    "config.middleware.RequestIdMiddleware",
    # Prometheus instrumentation (Phase 6). Placed high so it times everything
    # below it, and low enough that the request id is already bound when an
    # error is recorded.
    "config.middleware.MetricsMiddleware",
    # Row-Level Security (M6). A pass-through unless RLS_ENABLED is set, in
    # which case it opens the transaction that ``SET LOCAL app.current_org``
    # needs in order to be scoped to this request and discarded at its end.
    "inventory.rls.RLSContextMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # LocaleMiddleware sits directly after SessionMiddleware, as Django
    # requires, so a caller's explicit language choice (cookie or session) is
    # honoured on every page.
    "django.middleware.locale.LocaleMiddleware",
    # Below LocaleMiddleware, so it can apply Rakho's own default (Bengali for
    # the human-facing UI) only when the caller has expressed no preference.
    # It never touches /api/, whose contract is English JSON for every client.
    "config.middleware.DefaultLanguageMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Exposes the resolved language + available languages to every
                # template, so a language switch needs no per-view context.
                "django.template.context_processors.i18n",
            ]
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        # The encrypted store is preferred over the environment variable: the
        # environment is readable by anything that can see /proc and is inherited
        # by every child process, whereas the store keeps the URL encrypted on
        # disk. When no store is present this is exactly the old behaviour.
        default=resolve_secret("database_url", "DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
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
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Admin console location ──
# The admin lives at a non-obvious path instead of /admin/. Set ADMIN_URL on
# Render to a random string (e.g. "console-x7q9") so even this default is not
# the real address; the public repo only ever shows the default.
ADMIN_URL = os.environ.get("ADMIN_URL", "lostsec").strip("/") + "/"

# ── Caching ─────────────────────────────────────────────────────────────────
# Default to per-process memory so nothing breaks when Redis is absent. A
# production deployment with several gunicorn workers MUST override this with
# Redis; ``production.py`` does exactly that, and the reason matters: DRF's
# throttles are stored in this cache, and LocMemCache gives every worker its
# own counter, so a rate limit of "10/hour" silently becomes "10/hour per
# worker".
REDIS_URL = os.environ.get("REDIS_URL", "")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "rakho-default",
    }
}

# ── Internationalisation ────────────────────────────────────────────────────
# Bangladesh-first: Bengali is the default language of the human-facing UI
# (landing page, console, legal pages), English is the fallback. The JSON API
# deliberately stays English --- its messages are a machine-checked contract,
# and the Android client branches on the ``code`` field regardless.
#
# LANGUAGE_CODE stays "en" so Django's and DRF's own built-in messages keep the
# exact wording they had before localisation existed; the Bengali default is
# applied per-request by DefaultLanguageMiddleware for non-API paths.
LANGUAGE_CODE = "en"
LANGUAGES = [
    ("bn", "বাংলা"),
    ("en", "English"),
]
SITE_DEFAULT_LANGUAGE = os.environ.get("SITE_DEFAULT_LANGUAGE", "bn")
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True
TIME_ZONE = "Asia/Dhaka"
USE_TZ = True

# ── Static files ────────────────────────────────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# The manifest storage hashes every file and refuses to serve one that is not
# in its manifest. That is right in production (where collectstatic runs during
# the build) but wrong under test: the admin's own CSS is not collected, so
# every page that renders an admin template raised
# "Missing staticfiles manifest entry" and 52 tests errored before reaching
# their assertions. Tests use the plain storage, which resolves any path.
if TESTING:
    STORAGES = {
        # The file-storage backend is left at Django's default under test, but
        # it must be named here: a STORAGES dict replaces the whole mapping, and
        # omitting "default" made ``default_storage`` raise KeyError the first
        # time a test exercised an async export.
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "inventory.exceptions.api_exception_handler",
    # Staff-facing endpoints (the org dashboard) authenticate with a JWT; the
    # pharmacy app keeps using its API key. Both classes are enabled here so a
    # single view can accept either caller and decide with its own permission
    # class; the pharmacy views narrow this back to the API key alone.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "inventory.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    # Abuse protection: the catalog search is unauthenticated and hits a
    # 14k-row table, so anonymous traffic is rate limited per IP. Keyed
    # pharmacy traffic gets a generous but finite ceiling. Throttling is
    # backed by the default cache; production points that at Redis so the
    # counter is shared across workers instead of per-process.
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
        # Staff login is the one endpoint worth brute-forcing; keep it slow.
        "login": "20/hour",
        "org": "3000/hour",
        "export": "60/hour",
    },
}

# ── JWT (staff web dashboard) ───────────────────────────────────────────────
# Short access token, rotating refresh token. Claims carry the active org and
# role so a permission check never has to hit the membership table on the hot
# path.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_OBTAIN_SERIALIZER": "inventory.serializers.OrgTokenObtainPairSerializer",
}

# ── Celery (background jobs) ────────────────────────────────────────────────
CELERY_BROKER_URL = REDIS_URL or "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = REDIS_URL or "redis://localhost:6379/1"
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60
# Under test, tasks run inline so a test asserts the *effect* of an expiry
# digest without needing a live broker in CI.
CELERY_TASK_ALWAYS_EAGER = TESTING
CELERY_TASK_EAGER_PROPAGATES = TESTING
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# ── Object storage (org logos, generated exports) ───────────────────────────
# Empty by default: uploads then fall back to the local filesystem, which is
# right for local dev and wrong for a multi-instance deployment (the file
# lands on one container and is invisible to the others). Production sets
# MEDIA_S3_BUCKET and the signed-URL flow takes over.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_S3_BUCKET = os.environ.get("MEDIA_S3_BUCKET", "")
MEDIA_S3_REGION = os.environ.get("MEDIA_S3_REGION", "auto")
MEDIA_S3_ENDPOINT = os.environ.get("MEDIA_S3_ENDPOINT", "")
MEDIA_S3_ACCESS_KEY = os.environ.get("MEDIA_S3_ACCESS_KEY", "")
MEDIA_S3_SECRET_KEY = os.environ.get("MEDIA_S3_SECRET_KEY", "")
EXPORT_URL_TTL_SECONDS = int(os.environ.get("EXPORT_URL_TTL_SECONDS", "86400"))

# ── Privacy layer (optional profile, consent, aggregates) ─────────────────────
# The privacy-policy version a consent is recorded against. The app fetches it
# from GET /api/v1/profile/, shows it beside the Bangla consent screen, and every
# consent toggle stores whatever was current at the moment of the toggle — so
# "they said yes to policy v1.0 in October" still holds after v1.1 ships. Bump it
# whenever the policy text changes.
PRIVACY_POLICY_VERSION = os.environ.get("PRIVACY_POLICY_VERSION", "1.0")

# Key for the reversible profile fields (today: the drug licence number). Falls
# back to SECRET_KEY so encryption needs no extra configuration, but SECRET_KEY
# rotates for unrelated reasons and each rotation would orphan the ciphertext
# already stored — so production should set this explicitly and keep it stable.
# Read via the encrypted-secrets path, so the key itself never sits in an env
# file. See inventory/field_crypto.py.
PROFILE_ENCRYPTION_KEY = resolve_secret("profile_encryption_key", "PROFILE_ENCRYPTION_KEY")

# ── B2B billing (M5: base per branch + per-seat add-on) ─────────────────────
# Prices are integers in the organisation's currency (BDT by default) so the
# invoice arithmetic stays exact; a float here would show up as 199.99999999
# on a customer's VAT invoice.
BRANCH_PRICE_BDT = int(os.environ.get("BRANCH_PRICE_BDT", "1499"))
SEAT_PRICE_BDT = int(os.environ.get("SEAT_PRICE_BDT", "199"))
INCLUDED_SEATS_PER_BRANCH = int(os.environ.get("INCLUDED_SEATS_PER_BRANCH", "3"))
VAT_PERCENT = os.environ.get("VAT_PERCENT", "15")
# Organisation self-serve trial length. A trial that ends without warning is
# the most common source of one-star reviews, so the length lives here and is
# surfaced to the client rather than being implied.
ORG_TRIAL_DAYS = int(os.environ.get("ORG_TRIAL_DAYS", "14"))

# ── Storefront (landing page + manual MFS payments) ─────────────────────────
# The bKash/Nagad number customers send money to, and the Pro price shown on
# the landing page. Override via env on Render; never commit real secrets.
PAYMENT_NUMBER = os.environ.get("PAYMENT_NUMBER", "+8801580857515")
PAYMENT_METHODS = os.environ.get("PAYMENT_METHODS", "bKash / Nagad")
PRO_PRICE_BDT = os.environ.get("PRO_PRICE_BDT", "299")

# The app's Google Play link. Customers run the shop from the Android app, so
# this is the other half of the funnel beside the signup form --- but a listing
# does not exist until it is published. The install band renders either way;
# what this switches is which action it offers. Set it and visitors get a Play
# button (plus a schema downloadUrl); leave it empty and they get the free API
# key instead of a button that would 404. A closed-test link
# (https://play.google.com/apps/testing/com.lipon.rakho) is accepted too, since
# that is how testers install an app that is not public yet.
PLAY_STORE_URL = os.environ.get("PLAY_STORE_URL", "")

# Canonical public origin, used for the canonical link, Open Graph URLs,
# structured-data @ids, robots.txt and the sitemap. Render sets
# RENDER_EXTERNAL_HOSTNAME, so the default already tracks the real host and
# moving to a custom domain only means setting SITE_URL once --- instead of
# leaving a stale onrender.com address in the page's canonical tag.
SITE_URL = os.environ.get(
    "SITE_URL",
    "https://" + os.environ.get("RENDER_EXTERNAL_HOSTNAME", "rakho-api.onrender.com"),
).rstrip("/")

# ── Sentry error monitoring (free tier) ─────────────────────────────────────
# Set SENTRY_DSN on Render to enable. No-op when unset so local dev stays clean.
# Read through the resolver so the DSN can live in the encrypted store instead of
# the environment; the environment variable still works unchanged.
SENTRY_DSN = resolve_secret("sentry_dsn", "SENTRY_DSN")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        # Only errors --- no PII, no performance spans --- on the free tier.
        traces_sample_rate=0.0,
        send_default_pii=False,
        # The release id makes it possible to tell a deploy's errors from the
        # previous build's, which is the first question any incident asks.
        release=os.environ.get("SENTRY_RELEASE", ""),
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production" if not DEBUG else "development"),
    )

# ── Structured logging ──────────────────────────────────────────────────────
# One JSON line per event so Render's log stream (and any future aggregator)
# can filter by level and logger without regex-parsing prose. The request id
# is attached by RequestIdMiddleware, which lets a single user complaint be
# traced across every line it produced.
# ── Build identity ────────────────────────────────────────────────────────────
# Which commit is this process running? A deploy that "succeeded" in the
# dashboard is a claim about the build, not about the running process --- the
# service can be up, healthy and still serving the previous release. Render
# exports the deploy's commit as RENDER_GIT_COMMIT, so the fact is available at
# boot and is reported by /api/v1/version/ for the deploy script to confirm.
#
# Read from the environment rather than baked in at build time: a baked value is
# captured when the image is built and then sails through every later deploy
# unchanged --- reporting the old commit forever while looking authoritative.
# Empty is reported as empty, because "unknown" is honest and a fabricated
# answer would make the deploy check itself lie.
GIT_COMMIT = os.environ.get("RENDER_GIT_COMMIT", "").strip()
GIT_BRANCH = os.environ.get("RENDER_GIT_BRANCH", "").strip()
# Rollout marker for the RLS runbook, reported by /version/ so an operator can
# see from the outside whether the RLS role switch has been applied.
RLS_ENABLED = os.environ.get("RLS_ENABLED", "false").lower() == "true"

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "config.logging.JsonFormatter",
        },
        "plain": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "filters": {
        "request_id": {"()": "config.logging.RequestIdFilter"},
        "redact": {"()": "config.logging.PIIRedactionFilter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if not DEBUG else "plain",
            "filters": ["request_id", "redact"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        # Django's own request logger is noisy at INFO; keep it at WARNING.
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        # The API's own logger: every unhandled exception and every refusal
        # worth auditing lands here.
        "inventory": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "inventory.api": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "inventory.audit": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# ── CORS (mobile & web clients) ─────────────────────────────────────────────
# Hardened: the API is consumed by the Android app (which sends no Origin and
# is unaffected by CORS) and by the web console. A wildcard origin on a
# production deployment would let any site on the internet read a pharmacy's
# inventory with a leaked key, so it is refused outright rather than merely
# defaulted off. The refusal itself lives in ``production.py``, where the
# environment is known.
CORS_ALLOW_ALL_ORIGINS = os.environ.get("CORS_ALLOW_ALL_ORIGINS", "false").lower() == "true"
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
# CORS headers are only meaningful for the API; the landing page, the checkout
# page and the admin console are same-origin and need none. Scoping the
# middleware to /api/ keeps the headers off every other response.
CORS_URLS_REGEX = r"^/api/.*$"
# API-key auth travels in a header, never a cookie, so credentialed CORS is
# unnecessary --- and leaving it off means a browser will not attach cookies to
# a cross-origin API call even if one is ever set.
CORS_ALLOW_CREDENTIALS = False
CORS_ALLOW_METHODS = ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"]
CORS_ALLOW_HEADERS = [*default_headers, "x-pharmacy-key", "x-setup-token", "accept-language"]

# Guards the public /api/v1/setup/* endpoints when non-empty.
SETUP_TOKEN = os.environ.get("SETUP_TOKEN", "")

# ── Google Play Billing (server-side purchase verification) ─────────────────
# A service account with access to the Play Console, either as inline JSON or
# as a path to the JSON key file. When empty, the billing endpoints answer 503
# and every pharmacy stays on the free plan instead of trusting the client.
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "")
GOOGLE_PLAY_PACKAGE_NAME = os.environ.get("GOOGLE_PLAY_PACKAGE_NAME", "com.lipon.rakho")

# ── Multi-tenancy / RLS (M6) ────────────────────────────────────────────────
# Row-Level Security is applied by a dedicated migration and only takes effect
# on PostgreSQL. The switch exists so an operator can fall back to the
# code-level scoping alone (which is always active) without editing migrations.
RLS_ENABLED = os.environ.get("RLS_ENABLED", "false").lower() == "true"
# ``FORCE`` extends the policies to the table owner as well. It is only safe
# once the application connects as the non-owner role that ``setup_rls_role``
# creates --- forcing while the application is still the owner would lock it out
# of its own tables. Off by default for exactly that reason.
RLS_FORCE = os.environ.get("RLS_FORCE", "false").lower() == "true"

# ── OpenAPI / Swagger ───────────────────────────────────────────────────────
REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"
SPECTACULAR_SETTINGS = {
    "TITLE": "Rakho Pharmacy Inventory API",
    "DESCRIPTION": (
        "REST API for pharmacy inventory management \u2014 medicines, batches, "
        "purchases, sales, FEFO stock rotation, expiry alerts \u2014 plus the "
        "organisation, team, billing and reporting endpoints an enterprise "
        "multi-branch deployment needs."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "CONTACT": {"name": "Rakho API Support"},
    # Path-based versioning (M7): /api/v1 stays stable, /api/v2 is additive.
    "SCHEMA_PATH_PREFIX": "/api/v",
}
