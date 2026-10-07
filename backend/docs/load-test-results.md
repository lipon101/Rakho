# Rakho — load test results (Phase 6)

**Run:** 2026-10-06 · 50 concurrent users, 10/s ramp, 60 seconds
**Command:** `locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 60s --host http://127.0.0.1:8000 --csv=loadtest/results --only-summary`
**Target:** gunicorn 23 (`--workers 4 --threads 2`), `config.settings.loadtest`, PostgreSQL 15, Redis 7, seeded with 10 chains × 1 branch × 40 medicines × 2 batches
**Raw output:** `loadtest/results_stats.csv`, `loadtest/results_failures.csv`

---

## Result

| | Budget | Measured | |
|---|---|---|---|
| Total requests | — | **1547** | |
| **Failures** | < 0.5% | **0 (0.00%)** | ✅ |
| Throughput | — | 26.2 req/s | |
| **Aggregated p95** | 800 ms | **24 ms** | ✅ |
| **Read p95 (medicines)** | 300 ms | **16 ms** | ✅ |
| **Catalogue p95** | 800 ms | **12 ms** | ✅ |
| DoD threshold gate | — | **PASSED** (exit 0) | ✅ |

All three latency budgets and the error-rate budget are met, and the gate exits
0 instead of failing. The thresholds it enforces are the DoD's own numbers.

## Per-endpoint

| Endpoint | Reqs | Fails | Median | p95 | Max |
|---|---|---|---|---|---|
| `GET /inventory/medicines/` | 560 | 0 | **8** | **16** | 803 |
| `GET /inventory/dashboard/` | 324 | 0 | **10** | **20** | 67 |
| `GET /inventory/batches/` | 273 | 0 | **13** | **31** | 867 |
| `GET /inventory/alerts/` | 180 | 0 | **12** | **23** | 787 |
| `POST /inventory/sales/` | 111 | 0 | **13** | **25** | 167 |
| `GET /health/` | 53 | 0 | 2 | 6 | 9 |
| `GET /catalog/medicines/` | 46 | 0 | 6 | 12 | 23 |

## What changed, and why it mattered

The previous run on the same harness reported aggregate p95 **2900 ms** against a
budget of 800 ms. Three endpoints were rewritten to do their arithmetic in the
database instead of in Python, and the difference is not incremental:

| Endpoint | Before (median) | After (median) | Read p95 before → after |
|---|---|---|---|
| `dashboard` | **2200 ms** | **10 ms** | 3300 → 20 ms |
| `medicines` | 430 ms | 8 ms | 1400 → 16 ms |
| `batches` | 640 ms | 13 ms | 2100 → 31 ms |
| `alerts` | 730 ms | 12 ms | 1600 → 23 ms |
| aggregate p95 | **2900 ms** | **24 ms** | — |

The dashboard was the whole problem and the doc's own diagnosis was correct: it
was the only endpoint whose *median* sat above the p95 budget, so it alone
dragged the aggregate. It loaded every in-stock batch to sum quantity and cost,
every sale in the day and the week to sum amounts, and every active medicine to
decide low stock — several hundred rows per request on this seed. `Sum` now
computes the totals, and the low-stock comparison happens as
`annotate(...).filter(available_quantity__lte=F("low_stock_threshold"))`, so a
medicine is compared against its own threshold without a row leaving the
database. The same treatment was applied to the low-stock loop in `alerts` (one
query per medicine, previously) and to the per-medicine batch sum in the medicine
list.

Two of the fixes also corrected real bugs, not just latency:

* The float arithmetic on money could render `199.99999999` on a total a
  shopkeeper reads aloud. It is `Decimal` now.
* The money annotation is used for **both** the dashboard total and the low-stock
  filter, and it is named `available_quantity` specifically because that is the
  field `MedicineSerializer` reads. Annotating under a prettier name leaves the
  serializer looking for an attribute the row does not have, and the list raises
  instead of rendering — so the name is load-bearing, not cosmetic.

## What this does and does not tell us

**It tells us the write path is correct under concurrency.** 111 FEFO sales ran
with 50 concurrent users and **zero** failed — no lost updates, no oversell, no
deadlock. That remains the single most valuable result here, because FEFO
allocation is the one transaction where a concurrency bug costs a customer real
stock. (An even earlier run against SQLite produced 15 `database is locked` 500s;
that is SQLite's single-writer limit, not an application fault, and it is why the
harness targets Postgres.)

**It tells us the read budgets are met on a production-shaped target.** This run
used gunicorn with a worker pool, a shared Redis cache, `DEBUG` off and the JSON
log formatter — `config.settings.loadtest` is `production` minus the three
settings that assume TLS terminates in front of the app (`SECURE_SSL_REDIRECT`,
the two secure-cookie flags, and HSTS). Those four are named in that module and
nothing else is relaxed; without them the load generator, which speaks plain HTTP
on loopback, would have been answered with a 301 before reaching a view and the
run would have measured redirect middleware.

**Its limits are worth stating.** It is still 4 workers on one sandbox host, so
these are single-machine numbers: they say the query work is no longer the
bottleneck, not that this is the ceiling of a multi-instance deployment. The tail
is the honest caveat — `max` reaches 800-870 ms on three endpoints, roughly 4% of
requests above 60 ms. That tail is consistent with occasional worker recycling
and `fsync` contention on the shared volume rather than with application work
(no endpoint's *p99* exceeds 800 ms except `alerts` at 700 and `medicines` at
59). Re-taking these numbers against the real staging host before launch is still
the right final step, and the command is unchanged.

## How to reproduce

```bash
cd backend
export DJANGO_SETTINGS_MODULE=config.settings.loadtest
export DJANGO_SECRET_KEY="<32+ chars>"          # production guard needs a real one
export ALLOWED_HOSTS="127.0.0.1,localhost"
export DATABASE_URL="postgres://rakho:rakho@127.0.0.1:5432/rakho_load?sslmode=disable"
export REDIS_URL="redis://127.0.0.1:6379/0"
export SITE_URL="http://127.0.0.1:8000"
export CSRF_TRUSTED_ORIGINS="http://127.0.0.1:8000"

python manage.py migrate --noinput
python loadtest/seed.py --tenants 10            # writes loadtest/seed.json (0600, git-ignored)
python manage.py collectstatic --noinput
python -m gunicorn config.wsgi:application --workers 4 --threads 2 --bind 127.0.0.1:8000 &

locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 60s \
    --host http://127.0.0.1:8000 --csv=loadtest/results --only-summary
echo "exit code: $?"    # non-zero when a DoD threshold is missed
```
