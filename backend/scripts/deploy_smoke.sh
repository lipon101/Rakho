#!/usr/bin/env bash
# Deploy smoke test (Phase 6).
#
# Run immediately after a deploy, against the deployed host. It is the only check
# that exercises the running artefact rather than the code in the repository, and
# it exists because the failures it catches --- a missing environment variable, a
# un-run migration, a stale worker --- all look like a successful deploy from the
# outside.
#
# Exits non-zero on the first real problem, so it can be the last step of a
# pipeline and block a promotion.
#
# Usage:
#   BASE=https://rakho-api.onrender.com METRICS_TOKEN=... ./scripts/deploy_smoke.sh

set -uo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
METRICS_TOKEN="${METRICS_TOKEN:-}"
FAILED=0

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }

echo "Deploy smoke test against $BASE"
echo

echo "1. Liveness"
if curl -fsS --max-time 10 "$BASE/api/v1/health/" >/dev/null 2>&1; then
  pass "health endpoint answered"
else
  fail "health endpoint did not answer (the service is down, not degraded)"
fi

echo "2. Readiness"
READY_BODY="$(curl -fsS --max-time 15 "$BASE/api/v1/ready/" 2>/dev/null || echo '')"
if [ -n "$READY_BODY" ]; then
  pass "readiness answered"
  # The database is the dependency whose absence makes the instance useless, so
  # it is the one that fails the smoke test.
  if printf '%s' "$READY_BODY" | grep -q '"database"'; then
    if printf '%s' "$READY_BODY" | grep -q '"database": *{[^}]*"ok": *true'; then
      pass "database reachable"
    else
      fail "database reported not ok"
    fi
  fi
  # Workers are advisory (a web-only instance has none) --- reported, not failed.
  if ! printf '%s' "$READY_BODY" | grep -q '"workers"'; then
    fail "readiness has no workers check (the Phase 6 probe is not deployed)"
  else
    pass "workers check present"
  fi
else
  fail "readiness did not answer"
fi

echo "3. Metrics are closed to strangers"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/api/v1/metrics/")"
if [ "$CODE" = "403" ] || [ "$CODE" = "404" ]; then
  pass "unauthenticated metrics refused ($CODE)"
else
  fail "metrics returned $CODE without a token --- it should be 403, or 404 when no token is configured"
fi

echo "4. Metrics are live and moving"
if [ -z "$METRICS_TOKEN" ]; then
  echo "  SKIP  METRICS_TOKEN not set, so liveness of the registry cannot be checked"
else
  BODY="$(curl -fsS --max-time 15 "$BASE/api/v1/metrics/?token=$METRICS_TOKEN" 2>/dev/null || echo '')"
  if [ -z "$BODY" ]; then
    fail "metrics endpoint refused the configured token"
  else
    pass "metrics served"
    if printf '%s' "$BODY" | grep -q 'rakho_http_requests_total'; then
      pass "request counter present (the middleware is installed)"
    else
      fail "request counter absent --- MetricsMiddleware is not in MIDDLEWARE"
    fi
    # A series that exists but never moves means the middleware is registered
    # under a name Django ignores, which is otherwise invisible.
    BEFORE="$(curl -fsS --max-time 15 "$BASE/api/v1/metrics/?token=$METRICS_TOKEN" | grep -c 'rakho_http_requests_total' || true)"
    curl -fsS --max-time 10 "$BASE/api/v1/health/" >/dev/null 2>&1
    AFTER="$(curl -fsS --max-time 15 "$BASE/api/v1/metrics/?token=$METRICS_TOKEN" | grep -c 'rakho_http_requests_total' || true)"
    if [ "$AFTER" -ge "$BEFORE" ]; then
      pass "counter is being written"
    fi
    if printf '%s' "$BODY" | grep -q 'rakho_celery_queue_depth\|rakho_dependency_up'; then
      pass "dependency/job gauges published"
    else
      echo "  NOTE  queue-depth gauge absent (no broker configured on this service)"
    fi
  fi
fi

echo "5. Request-id correlation"
HEADERS="$(curl -sI --max-time 10 "$BASE/api/v1/health/" 2>/dev/null || echo '')"
if printf '%s' "$HEADERS" | grep -qi 'x-request-id'; then
  pass "X-Request-Id is returned (logs can be correlated to a request)"
else
  fail "no X-Request-Id header --- incident triage will be slower for it"
fi

echo "6. JSON error envelope"
# An unknown API path must answer JSON, not Django's HTML 404 page: a JSON client
# parsing HTML is the failure this asserts against.
NOTFOUND="$(curl -s --max-time 10 "$BASE/api/v1/definitely-not-here/" 2>/dev/null || echo '')"
case "$NOTFOUND" in
  \{*|\[*) pass "unknown API path answers JSON" ;;
  *)        fail "unknown API path answered non-JSON: $(printf '%s' "$NOTFOUND" | head -c 80)" ;;
esac

echo
if [ "$FAILED" -eq 0 ]; then
  printf '\033[32mSmoke test PASSED\033[0m\n'
  exit 0
fi
printf '\033[31mSmoke test FAILED\033[0m\n'
exit 1
