# Rakho — load test results (Phase 6)

**Run:** 2026-10-06 · 50 concurrent users, 10/s ramp, 60 seconds
**Command:** `locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 60s --host http://127.0.0.1:8000 --csv=loadtest/results --only-summary`
**Target:** local `manage.py runserver`, PostgreSQL 15, seeded with 10 chains × 1 branch × 40 medicines × 2 batches
**Raw output:** `loadtest/results_stats.csv`, `loadtest/results_failures.csv`

---

## Result

| | |
|---|---|
| Total requests | **930** |
| **Failures** | **0 (0.00%)** ✅ |
| Throughput | 15.5 req/s |
| Aggregated p95 | **2900 ms** ❌ (budget 800 ms) |
| Read p95 (medicines) | 1400 ms ❌ (budget 300 ms) |
| Catalogue p95 | 870 ms ❌ (budget 800 ms) |
| DoD threshold gate | **FAILED — correctly** |

The gate did its job: it exited non-zero instead of printing a green summary
nobody would read. **The thresholds are not met on this target, and the numbers
are reported as measured rather than as hoped.**

## Per-endpoint

| Endpoint | Reqs | Fails | Median | p95 | Max |
|---|---|---|---|---|---|
| `GET /inventory/medicines/` | 310 | 0 | 430 | 1400 | 3279 |
| `GET /inventory/dashboard/` | 179 | 0 | 2200 | 3300 | 3749 |
| `GET /inventory/batches/` | 173 | 0 | 640 | 2100 | 3471 |
| `GET /inventory/alerts/` | 121 | 0 | 730 | 1600 | 3608 |
| `POST /inventory/sales/` | 77 | 0 | 1200 | 1800 | 2209 |
| `GET /health/` | 41 | 0 | 210 | 510 | 559 |
| `GET /catalog/medicines/` | 29 | 0 | 420 | 870 | 930 |

## What this does and does not tell us

**It tells us the write path is correct under concurrency.** 77 FEFO sales ran
with 50 concurrent users and **zero** failed — no lost updates, no oversell, no
deadlock. That is the single most valuable result here, because FEFO allocation
is the one transaction where a concurrency bug costs a customer real stock.
(An earlier run against SQLite produced 15 `database is locked` 500s; that is
SQLite's single-writer limit, not an application fault. The test is run against
Postgres for exactly this reason.)

**It tells us the read latency budgets are not met — and says nothing about
whether they would be met in production**, because the target is wrong for the
question. `runserver` is a single development process: no gunicorn worker pool,
no connection pooling, no caching, and `DEBUG`-adjacent middleware that never runs
in production. The DoD's numbers (read p95 < 300 ms) are stated for a production
deployment, and a dev server on a shared sandbox is not one. Comparing them
directly would be measuring the sandbox, not Rakho.

**So the honest verdict is: the harness is complete and the gate works, and the
numbers must be re-taken against production before the DoD item can be closed.**
Re-run the identical command with the host pointed at a staging deployment
behind gunicorn, with Redis-backed caching enabled.

## Where the headroom is, in the order worth attacking

1. **`/inventory/dashboard/` — 2200 ms median is the whole problem.** It is the
   only endpoint whose *median* is above the p95 budget, so it alone drags the
   aggregate. It is an aggregate read whose result changes only when stock
   changes, which makes it the clearest cache candidate in the product.
2. **The `alerts` low-stock loop.** The view iterates every medicine and sums its
   batches in Python (`sum(b.quantity_available for b in m.batches.all())`) — one
   query per medicine. That is an N+1 that will grow with the catalogue and is
   the likely cause of the 1600 ms p95 and the 3600 ms tail.
3. **`/inventory/batches/` at p95 2100 ms** — likely the unbounded list; needs
   pagination enforced at the query rather than the response.

None of these were changed in this phase: they are tuning work on working code,
they need a production target to measure against, and M1 forbids rewriting what
already works. They are recorded here as the next performance task, with the
evidence attached.

## How to reproduce

```bash
cd backend
source .venv/bin/activate
export DJANGO_SETTINGS_MODULE=config.settings.local
export DATABASE_URL="postgres://rakho:rakho@127.0.0.1:5432/rakho"
python manage.py migrate --noinput
python loadtest/seed.py --tenants 10          # writes loadtest/seed.json (0600, git-ignored)
python manage.py runserver 127.0.0.1:8000 &
locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 60s \
    --host http://127.0.0.1:8000 --csv=loadtest/results --only-summary
echo "exit code: $?"     # non-zero when a DoD threshold is missed
```
