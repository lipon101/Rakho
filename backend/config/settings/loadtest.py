"""Load-test settings: production's posture, minus the parts that assume TLS.

**Why this module exists at all.** The Phase 6 DoD names latency budgets, and a
budget is only meaningful against a target that resembles the deployment. The
first attempt measured ``manage.py runserver`` --- a single development process
with no worker pool, no connection pooling and no shared cache --- and the
result was reported honestly but said more about the sandbox than about Rakho.

Simply pointing the load test at ``config.settings.production`` does not fix
that either, for one concrete reason: production sets
``SECURE_SSL_REDIRECT = True``, and the load generator speaks plain HTTP to
``127.0.0.1:8000``. Every request would be answered with a 301 before reaching a
view, so the run would measure Django's redirect middleware and nothing else.
Putting a TLS terminator in front of a local load test to work around that adds
a moving part whose own latency would land in the numbers.

So this module takes production's *real* posture --- ``DEBUG`` off, Redis as the
shared cache, the JSON log formatter, the strict CORS and host checks, the
``sslmode=require`` database default --- and disables exactly the three settings
that only make sense when the request arrived over TLS. Those three are named
below and nothing else is relaxed.

**This must never be used to serve real traffic.** It is not in the deploy
configuration, and the redirect it disables is a defence in depth behind the
proxy rather than the only defence. It exists to be a measurement target.
"""

from .production import *  # noqa: F401,F403

# ── The three TLS-only settings ──────────────────────────────────────────────
# The load generator is plain HTTP on loopback; see the module docstring. Each
# of these is a cookie/redirect flag whose only job is to require TLS, which a
# loopback load test does not have. Nothing about authentication, scoping,
# throttling or caching is touched.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# HSTS is a response header that tells browsers to refuse plain HTTP to this
# host for a year. Sending it from a throwaway load-test host would be
# meaningless at best; the setting is turned off so the responses under test are
# not carrying a policy about a hostname that will not exist tomorrow.
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
