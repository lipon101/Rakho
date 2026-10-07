# Deploy mechanism, RLS rollout, and the staging verification

Recorded 2026-10-06. Every number in this file was produced by a command run in
this session against the artefacts named here; nothing is estimated.

## The problem this closes

Pushing to `main` did not deploy anything.

`render.yaml` ships no auto-deploy key, so Render's auto-deploy is off for the
`rakho-api` service and a push only changes the repository. The live host at
`https://rakho-api.onrender.com/` was sitting on a build from **before the whole
project**: the root answered 200 while every route added since Phase 0 404'd.

That is the failure mode worth naming, because nothing looks broken:

| Probe | Live result | Meaning |
|---|---|---|
| `GET /api/v1/health/` | 200, ~8ms | The service is up and healthy |
| `GET /api/v1/ping/` | 204, ~0.15s | The keep-alive endpoint works (D9) |
| `GET /api/v1/ready/` | **404** | Phase 0's readiness probe is absent |
| `GET /api/v1/version/` | **404** | No build identity at all |
| `GET /api/v1/metrics/` | **404** | Phase 6 observability is absent |
| `GET /api/v1/org/` | **404** | Phase 1 tenancy is absent |
| `GET /api/v1/reports/` | **404** | Phase 4 reporting is absent |

A green dashboard is a claim about a *build*, never about the *process serving
traffic*. The two can disagree for a week without anyone noticing.

## The mechanism

### `GET /api/v1/version/` — the running process's own identity

Reports `commit`, `branch`, `environment`, `rls_enabled`, `version`, read from
`RENDER_GIT_COMMIT` / `RENDER_GIT_BRANCH` / `RLS_ENABLED` at boot.

Two deliberate choices:

- **Public.** The commit sha is already in the public GitHub repository, so
  hiding it buys nothing — and a deploy check that needs a secret is a check that
  gets skipped at exactly the moment it is needed.
- **Read from the environment, not baked in.** A value baked at image-build time
  is captured once and then sails through every later deploy unchanged,
  reporting the old commit forever while looking authoritative. An unset commit
  is reported as empty: `unknown` is honest, and a fabricated sha would make the
  deploy check itself lie.

### `scripts/render_deploy.py` — trigger, then prove

The POST is the easy half. The hook returns 200 the moment Render *accepts* a
build request, which says nothing about whether the build succeeds or which
commit it contains — so the script polls `/api/v1/version/` until the live
process reports the commit that was pushed, and exits non-zero if it never does.

Behaviour that matters:

- The hook URL is read from `RENDER_DEPLOY_HOOK_URL` and never hardcoded, never
  passed on the command line (shell history, `ps`) and never committed. Missing →
  exit 2 with the exact setup instructions, and **no** fabricated URL.
- `401`/`403`/`404` from the hook are treated as non-transient: a wrong or
  revoked credential is not retried, because retrying cannot help and hammering
  a service looks like an attack.
- A short sha matches the full 40-character sha, because an operator types
  `git rev-parse --short` while Render reports all 40 characters, and a check
  that fails on that technicality is a check that gets worked around.
- "Host asleep", "old build still serving" and "new build is wrong" are reported
  as three different things.

### `scripts/mock_deploy_hook.py` — the offline stand-in

Present because the real hook is a credential that was not available here, and an
untested deploy script fails for the first time during a real release.

### `.github/workflows/deploy.yml` — CI now verifies the deploy

Runs the script after a push to `main`, so a commit that never reaches the
running service fails the job instead of only failing when Render refuses a POST.
Reports a skip (exit 0) when the secret is absent, so a missing credential never
blocks a merge.

## Local verification (real, this session)

Four scenarios, run against a loopback server holding a known build sha. The
`VersionView` was served by a real gunicorn process with
`RENDER_GIT_COMMIT=1111111aaaaabbbbbcccccdddddeeeeefffff0000`.

| Scenario | Outcome |
|---|---|
| `--check-only` | exit 0, reports the live build, sends no POST |
| hook triggered + commit matches | exit 0, **VERIFIED**, 1 POST |
| hook triggered but commit never matches | exit 1, "still serving the old commit" |
| `RENDER_DEPLOY_HOOK_URL` unset | exit 2, instructions printed, **0 POSTs** |

Plus 17 automated tests (`inventory/tests/test_deploy_mechanism.py`), including
short-sha matching, the refusal to retry a bad hook, an unreachable host reading
as "cannot say", and an end-to-end loopback run of the real trigger-and-poll.

## What the user must paste, and where

This cannot be automated and is not guessable: the Deploy Hook URL is issued per
service.

1. Render dashboard → the `rakho-api` service → **Settings → Deploy Hook** → copy
   the URL (shape: `https://api.render.com/deploy/srv-XXXXXXXX?key=YYYYYYYY`).
2. Either export it for one shell:

   ```bash
   export RENDER_DEPLOY_HOOK_URL='<paste here>'
   ```

   or, to deploy on every push, save it as a repository secret —
   **Settings → Secrets and variables → Actions → New repository secret**,
   name `RENDER_DEPLOY_HOOK_URL`.
3. Then:

   ```bash
   python backend/scripts/render_deploy.py --expect-commit "$(git rev-parse HEAD)"
   ```

## Load test — the production-shaped local target

The dependable staging target: the app's own production-shaped settings
(`config.settings.loadtest`), gunicorn with a real worker pool, PostgreSQL 15,
Redis. Same scenario and same command shape as the previous Phase 6 run.

```bash
locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 60s \
    --host http://127.0.0.1:8001 --csv=loadtest/results --only-summary
```

| Metric | Measured | DoD budget | Verdict |
|---|---|---|---|
| Requests | 1,567 | — | — |
| Failure rate | **0.00%** | < 0.5% | met |
| Median | 15ms | — | — |
| Overall p95 | **54ms** | < 800ms | met |
| Read p95 | **34ms** | < 300ms | met |
| Catalogue p95 | **33ms** | (Pro tier) | met |
| FEFO concurrent sale | p95 96ms | — | met |

Domain invariants, read straight from the database rather than inferred from
HTTP status codes:

```
sales_recorded=114   salelines=114   (one line per sale — no double-booking)
batches=800
negative_stock=0     oversold=0      (no oversell under 50 concurrent users)
deadlocks=0          http_5xx=0
```

## Load test — the real staging host

Safe by construction: `seed.py` creates real organisations with real API keys, so
pointing it at staging would have added ten fake pharmacies to the installation.
`loadtest/public_locustfile.py` therefore measures only the credential-free
public surface (liveness, readiness, API root, keep-alive, 404 envelope) — no
writes, no tenant rows read.

The host was warmed first (three requests, ~0.15s each) and the warm-up is
excluded from the statistics; there was no cold start in this run, because the
keep-alive from D9 had kept it awake.

| Metric | Measured | DoD budget | Verdict |
|---|---|---|---|
| Requests | 1,741 | — | — |
| Failure rate | **0.000%** | < 0.5% | **met** |
| Median | 390ms | — | — |
| p95 | **850ms** | read p95 < 300ms | **exceeded** |
| Build under test | **stale** — `/version/` 404 | — | see below |

Read honestly: three endpoints were still absent on this build (`/ready/`,
`/version/`, the JSON error envelope), so the run predates the deploy. The ~390ms
median against ~15ms locally is the shared free instance — one small container
with no worker pool of its own, serving ~29 req/s from a single load generator —
not a regression in the code and not a capacity figure. **The 300ms read budget
is not met on the free tier**; that is a property of where the app is hosted
today, and the paid instance that D9 defers is what changes it.

## RLS production rollout

The ordered, gated sequence lives in the runbook:
`webpages/rakho-rls-runbook/index.html`. The short form:

1. `python manage.py setup_rls_role --dry-run` — inspect, change nothing.
2. `python manage.py setup_rls_role` — create the non-owner `rakho_app` role;
   policies exist but do not apply to the owner, so the running app is unaffected.
3. Move the application onto `rakho_app` — **this is the step where RLS starts
   protecting**, and the point of no return.
4. `RLS_ENABLED=true` — makes `/version/` report `rls_enabled: true`.
5. Verify: inside `rakho_app`, a query scoped to one organisation must return
   **zero** rows for another. Zero rows, not an error — that is what a policy
   does, and it is why the check has to look for emptiness.
6. Rollback: move the application back to the owner role. Policies stay in place
   and inert; no migration is reversed and no data is touched.
