# Changelog

All notable changes to Rakho. Format follows Keep a Changelog; versions follow
the deployment SHA, because that is what the runbook and the rollback plan ask
an operator to write down.

---

## [Phase 7] — 2026-10-10

The Android app becomes Firebase-only, the invitation join page stops pointing
at a 404, and the website stops selling a plan that no longer exists.

### Changed

- **The mobile app's data plane is now Cloud Firestore**, not the Django REST
  API. Every shop owns `pharmacies/{uid}/…` keyed by its Firebase Auth uid;
  `X-Pharmacy-Key`, the API-key onboarding, the SQLite cache and the
  pending-operations queue are gone from the app. Setup, the data model and the
  owner-only security rules are documented in
  [`android/docs/firebase-setup.md`](android/docs/firebase-setup.md).
- **Offline safety moved from a hand-rolled queue to Firestore's persistence
  layer**: writes are batched with `FieldValue.increment` and replayed exactly
  once, so a credit sale and its baki entry land together and a replay cannot
  double-deduct stock. Phone OTP stayed switched off deliberately — enabling it
  requires the paid Blaze plan, and the app is built to never hit a paywall.
- **Design system finished in the app**: dark mode is now a user preference
  (system / light / dark) with scheme-aware status inks, the Expiry Strip and
  status chips reach POS cart lines, dues rows and dashboard alerts, a
  first-run three-step card replaces empty charts for a new shop, and every
  screen string — auth errors included — resolves through resources in English
  and Bangla.
- **Baki becomes actionable**: a cloud customer book (`customers`), a one-tap
  WhatsApp reminder per debtor, names suggested at the counter, and a daily
  overdue-baki notification on its own channel. Nothing here costs money: the
  message is composed on the device and handed to WhatsApp by intent.

- **The web surfaces stopped selling a Pro tier the app no longer has.** The
  landing page advertised ৳299/month for cloud sync, catalogue search, backup and
  CSV export — all of which the Firebase build gives every account free — and its
  signup form handed out an API key the app has no field to enter any more. The
  page now carries one free plan, a single `৳0` offer in the structured data, and
  an install call to action (Play when `PLAY_STORE_URL` is set, the support
  contact otherwise). `/pay/<token>/` answers old links with a "nothing to pay"
  notice and asks for nothing; the token is no longer rendered at all, which
  removes the reflected-XSS surface it used to sit inside. `PRO_PRICE_BDT`,
  `PAYMENT_NUMBER` and the subscription records stay, as dormant admin history.
- **Privacy policy and terms rewritten for what the app actually does.** The
  policy claimed "no third-party analytics SDKs" while the app ships Firebase
  Analytics and Crashlytics, and both documents promised Google Play billing,
  auto-renewing Pro/Business plans, refunds and API-key auth. They now describe
  Firebase Auth, owner-only Firestore, instant self-service deletion, the baki
  book's customer names and numbers, and a free product with no refund policy to
  read.
- Added `SUPPORT_EMAIL` / `SUPPORT_WHATSAPP` settings, because the landing page
  now has no form and a contact is its only remaining action.

### Fixed

- **`inventory/join_page.py` was missing**, so `config/urls.py` failed to import
  and `manage.py check` — and therefore CI — could not run at all; every
  invitation email pointed at a dead `/console/join` link. The page now renders
  the invitation, registers the account and spends the token server-side, and
  embeds the URL-supplied token through the same script-context escaping the
  pay page uses, so a crafted token cannot close the script block.
- **`ruff` B904 in `inventory/views.py`** — the recount `ValidationError`
  swallowed the parse failure it was reacting to; and `black` formatting on
  `views.py` / `serializers.py`, which the CI format gate would have refused.

---

## [Phase 6] — 2026-10-06

Observability, load testing, backup verification, supply-chain hygiene and
deployment readiness. Nothing existing was rewritten or removed.

### Added

- **Prometheus metrics** (`inventory/metrics.py`) — `rakho_http_requests_total`,
  `rakho_http_request_duration_seconds`, `rakho_http_requests_in_flight`,
  `rakho_celery_tasks_total`, `rakho_celery_task_duration_seconds`,
  `rakho_celery_queue_depth` and `rakho_dependency_up`. Multiprocess-safe when
  `PROMETHEUS_MULTIPROC_DIR` is set, which matters because gunicorn runs more
  than one worker and a per-process registry reports one worker's share with no
  sign that anything is missing.
- **`MetricsMiddleware`** (`config/middleware.py`) — times every request and
  labels it by **route template**, never by path. A uuid in a label is one time
  series per invoice, and a Prometheus whose series count grows with the customer
  base is a Prometheus that falls over on a good day.
- **`/api/v1/metrics/`** — closed by default. With no `METRICS_TOKEN` configured
  it returns **404** rather than defaulting open, so a forgotten environment
  variable removes the endpoint instead of exposing the route table.
- **`/api/v1/ops/sentry/`** and **`manage.py verify_sentry`** — reports whether
  error reporting is configured *and* sends a flushed test event, because
  `SENTRY_DSN` being set proves nothing about delivery.
- **Readiness now checks workers** (`_check_workers`) — the probe was blind to a
  dead Celery worker: the API answered 200 while every digest and invoice draft
  piled up. Advisory by default, strict when `CELERY_REQUIRE_WORKER=true`
  (requiring a worker reply on a web-only instance would take healthy web
  instances out of rotation).
- **Celery signal handlers** (`inventory/celery_signals.py`) — task outcomes and
  per-attempt durations, connected from `AppConfig.ready` so the web process, the
  worker and the test runner all publish them.
- **Load test** (`loadtest/locustfile.py`, `loadtest/seed.py`) — realistic
  multi-tenant scenario with a declared mix, and a **DoD gate that fails the run**
  when the thresholds are missed. A load test that cannot fail is one nobody reads.
- **`manage.py backup_db`** — `pg_dump` plus a manifest recording per-table row
  counts and a sha256, so a backup can be *checked* rather than trusted. Refuses
  to run on SQLite; refuses in production settings without `--force`.
- **`manage.py restore_drill`** — restores into a scratch database and compares
  restored row counts against the manifest. Refuses to restore into the live
  database, and exits non-zero on a mismatch so it can be a CI gate.
- **SBOM generator** (`scripts/generate_sbom.py`) — CycloneDX 1.5, written
  against installed distribution metadata rather than a third-party scanner,
  because installing a scanner to inventory the supply chain is itself a
  supply-chain dependency. 127 components.
- **Dependabot** (`.github/dependabot.yml`) — grouped weekly PRs; the maintainers
  who close fifteen unread PRs on a Tuesday morning are the ones this avoids.
- **Deploy smoke test** (`scripts/deploy_smoke.sh`) — 12 checks against the
  running artefact, including that the JSON error envelope is still emitted and
  that `X-Request-Id` is returned.
- **Documentation** — `docs/runbook.md`, `docs/deployment-checklist.md`,
  `docs/migration-rollback-plan.md`, `docs/load-test-results.md`.

### Changed

- **Dependency security upgrades** from `pip-audit`: Django 5.2.9 → **5.2.17**,
  DRF 3.16.1 → **3.17.2**, simplejwt 5.5.0 → **5.5.1**, pytest 8.4.1 → **9.0.3**,
  and PyJWT pinned explicitly at **2.15.0** (it arrives via simplejwt, and an
  indirect dependency absent from `requirements.txt` is one nobody upgrades).
  `pip-audit` now reports **no known vulnerabilities**.
- **CI** — the test step now runs under coverage with an **85% gate** and a
  SBOM job publishes the artifact for every build. The gate sits at the DoD's
  own 85% and the measured figure is 85%; that margin is thin on purpose and
  honestly reported, so the next uncovered branch fails the build rather than
  sliding past it.
- **`render.yaml`** — the web service now starts through
  `scripts/gunicorn_entrypoint.sh`, which clears `PROMETHEUS_MULTIPROC_DIR`
  before the workers start (stale files there are replayed as live metrics, so a
  p95 would never reset across a deploy). Added `METRICS_TOKEN`,
  `RLS_ENABLED=false` and `CELERY_REQUIRE_WORKER=true` on the worker services.
- **`.gitignore`** — `backend/docs/` re-included (a runbook that exists on one
  laptop is not documentation); `loadtest/seed.json` excluded, because it holds
  live branch API keys.

### Fixed

- **`inventory/apps.py`** — `ready()` was missing; the metrics token was never
  mirrored onto settings and the Celery signals were never connected, so the task
  counters would have read zero in every process.
- **`config/middleware.py`** — `time` was not imported; the metrics middleware
  would have raised `NameError` on its first request.
- **`loadtest/seed.py`** — `quantity_available` was drawn independently of
  `quantity_received`, violating the model's CHECK constraint roughly half the
  time. Found by running the seeder, not by reading it.
- **Load-test contract bugs**, both found by the first real run: the sale body
  needs `invoice_number` (the endpoint refuses without it), the catalogue search
  reads `?q=` not `?search=`, and it is Pro-only — the script now skips it for free
  tenants rather than counting a correct refusal as a failure.

### Verified

- **407 tests pass** (was 365; +42 in this phase).
- **85% coverage** of `inventory` + `config`, which is the DoD's own bar — at
  parity, not above it, so the CI gate has no margin and fails the next
  uncovered branch on purpose.
- `ruff` clean, `black` clean, `makemigrations --check` clean,
  `check --deploy --fail-level ERROR` exits 0.
- **Restore drill VERIFIED** — 36/36 tables, all 1,753 rows.
- **Deploy smoke test 12/12 PASS** against a live server.
- **Load test 930 requests, 0 failures** — 77 concurrent FEFO sales with no
  oversell and no deadlock. The latency thresholds were **not** met on the dev
  server, and this changelog does not claim otherwise; see
  `docs/load-test-results.md` for why the target was wrong for the question and
  where the headroom actually is.

---

## [Phase 5] — RLS, invoice PDFs

### Added

- Row-Level Security across **18 tenant-scoped tables**, with policies reaching
  the organisation directly, via `pharmacy_id`, and via parent rows. Verified by
  six tests that connect as the non-owner role over raw psycopg — the Django ORM
  would have measured the *first* lock (view-level scoping) and reported it as
  the second.
- `setup_rls_role` — creates the non-owner `rakho_app` role and applies `FORCE`.
- Bengali/English invoice and quotation PDFs with an embedded Hind Siliguri font.

### Fixed

- The invoice font originally chosen (**Noto Sans Bengali**) carries **no Latin
  glyphs**, so every Latin word in a Bengali invoice — the brand name, the
  customer's legal name, "Base plan" — rendered as **nothing at all**. Not a box,
  not a fallback: blank. The page still looked complete. Caught by rendering a
  real invoice and reading it, not by a test; the PDF tests now assert Latin text
  survives, so the next font change breaks a test here rather than a customer's
  tax document.

---

## [Phase 0–4] — Foundation through reporting

- **Sprint 0.1** — the CI gate that actually runs the suite; the uniform JSON
  error envelope; the JSON 404 for unknown API paths; CORS hardening; structured
  logging with `X-Request-Id`; the Android app (88 files, 10,502 LOC) restored to
  the public repo. Found and fixed 52 tests erroring on
  `Missing staticfiles manifest entry` before reaching their assertions.
- **Phases 1–4** — `Organization → Pharmacy → Stock` tenancy; RBAC, audit logging
  and seat management; branch-based pricing and seat add-ons; VAT invoicing
  (drafts only — a machine must not send an invoice); organisation-level reporting
  and CSV onboarding; the Celery background pipeline.
