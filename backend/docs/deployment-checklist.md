# Rakho — production deployment checklist

Run this list top to bottom for every production deployment. Every item is
either an environment variable, a command, or an assertion that can be checked
by someone who did not write the change. Anything that cannot be checked that
way does not belong on this list.

Last reviewed: 2026-10-06.

---

## 1. Before you start

- [ ] The commit you are deploying is on `main` and CI is **green** on it. CI runs
      the full pytest suite, `ruff`, `black --check`, `makemigrations --check` and
      `manage.py check --deploy`. Do not deploy a commit that skipped any of them.
- [ ] You know the **rollback target**: the currently deployed commit SHA. Write it
      down. Every step below is reversible only relative to that SHA.
- [ ] You have a **database backup from within the last hour** (`manage.py backup_db`
      — see the runbook). A migration without a fresh backup is an experiment on
      customer data.

## 2. Environment variables

The application boots without most of these, which is exactly why they are
listed: a missing one does not crash, it silently disables a guarantee.

| Variable | Required | Why it matters if missing |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | yes | Must name `config.settings.production`. Anything else silently weakens the deployment. |
| `SECRET_KEY` | yes | Startup fails without it — the one thing that is allowed to crash. |
| `DATABASE_URL` | yes | Startup fails. |
| `ALLOWED_HOSTS` | yes | Startup fails in production. |
| `CORS_ALLOWED_ORIGINS` | yes for a web console | An empty list means the browser console cannot call the API. A `*` is **refused** in production by design. |
| `REDIS_URL` | yes | Startup fails in production by design: it backs the shared cache, the DRF throttles (per-process counters would multiply every rate limit by the worker count) and the Celery broker. `render.yaml` sources it from the `rakho-redis` service --- if the dashboard environment lost the variable, copy that connection string back in (Render: rakho-redis -> Connection Details, then rakho-api -> Environment -> Deploy). |
| `SENTRY_DSN` | strongly recommended | Error reporting is off. `/api/v1/ready/` does **not** fail for it (an optional dependency must not take an instance out of rotation), so verify it explicitly with `manage.py verify_sentry`. |
| `METRICS_TOKEN` | for scraping | `/api/v1/metrics/` and `/api/v1/ops/sentry/` return **404**. This is deliberate: an unset token removes the endpoints instead of exposing them. |
| `PROMETHEUS_MULTIPROC_DIR` | when >1 worker | Without it each gunicorn worker keeps its own registry and a scrape reports one worker's share of the traffic with no indication that anything is missing. Must be a writable directory, and it must be cleared on restart (the multiprocess collector refuses to start on stale files). |
| `CELERY_REQUIRE_WORKER` | on the worker service | Set `true` on a service that runs workers, so the readiness probe fails when they die. Leave unset on web-only services, where requiring a worker reply would take healthy web instances out of rotation. |
| `RLS_ENABLED` | after Phase 5 rollout | Row-Level Security is off. See the RLS production runbook. |
| `RAKHO_S3_*` / media settings | if exports are enabled | Large exports fail. Small ones fall back to local storage. |

Check them all in one go:

```bash
manage.py check --deploy --fail-level ERROR   # exits non-zero on a real problem
manage.py verify_sentry                       # actually sends and flushes a test event
```

## 3. Deploy

- [ ] Run migrations **before** the new code starts serving:
      `manage.py migrate --noinput`
      Migrations are written to be backward compatible for one release (additive
      columns, no destructive renames), so the old code keeps working during the
      window — see `migration-rollback-plan.md`.
- [ ] `manage.py collectstatic --noinput` when static assets changed.
- [ ] The medicine catalogue is populated — the build runs it automatically as
      `manage.py import_bangladesh_catalog --download --if-empty`; a populated
      table is a 2-second no-op and only an empty one downloads the Kaggle
      archive. A deploy that skips this ships an empty search box to paying
      pharmacies; if the build log says `skipping the import`, the data is there.
- [ ] Restart the web process.
- [ ] Restart **the Celery worker**, and the beat scheduler if it is separate. A
      worker running old code against new task signatures is the failure this
      step prevents, and it is invisible until a task runs.

## 4. Verify (all of these, not a selection)

```bash
# Liveness — should be 200 and fast
curl -fsS https://<host>/api/v1/health/          # {"status": "ok"}

# Readiness — dependencies, including worker state
curl -fsS https://<host>/api/v1/ready/

# Metrics are live and closed to strangers
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/api/v1/metrics/          # 403 (or 404 if no token)
curl -fsS 'https://<host>/api/v1/metrics/?token=$METRICS_TOKEN' | head -20       # 200
```

- [ ] `/health/` returns 200.
- [ ] `/ready/` returns 200, and `checks.workers` says something other than
      `"no worker replied"` when workers were expected.
- [ ] `/metrics/` shows `rakho_http_requests_total` **increasing** as you hit the
      site — a registry that renders but never moves means the middleware is not
      installed.
- [ ] `rakho_celery_queue_depth` is near zero on a quiet system. A number that
      only grows is a dead consumer.
- [ ] One real request in the access log carries an `X-Request-Id`, and the same
      id appears on the matching log lines. Without that, log correlation is
      broken and incident triage costs an order of magnitude more time.
- [ ] Sentry received the test event (open the project, check the environment).
- [ ] A single end-to-end smoke test on the live host: sign in, list medicines,
      record one sale. This is the only check that exercises the FEFO path.

## 5. After

- [ ] Watch error rate and p95 for 30 minutes. The thresholds are the DoD's: error
      rate under 0.5%, read p95 under 300 ms, write p95 under 800 ms.
- [ ] Confirm the nightly digest job is queued (`queue_expiry_digests`). It is the
      job whose failure a customer notices a day later, in their inbox.
- [ ] Update the changelog with the deployed SHA.

## 6. Rollback

If verification fails, roll back the **application** first — it is instant and
does not touch data:

```bash
# Re-deploy the previous commit SHA recorded in step 1, then restart web + worker.
```

Migrations are not rolled back in a hurry; they are designed so the previous
release still works against the migrated schema. Only if a migration itself is
the problem do you follow `migration-rollback-plan.md`, which is slower and
requires the backup from step 1.
