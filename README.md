# Rakho — Pharma Inventory & Expiry Manager

**Rakho** is a pharmacy inventory, POS, and expiry-management system built for pharmacies in Bangladesh. It ships as a Django REST API backend with an embedded React SPA, deployed live at:

👉 **App:** https://rakho-api.onrender.com/app/
👉 **API docs (Swagger):** https://rakho-api.onrender.com/api/docs/
👉 **API root:** https://rakho-api.onrender.com/api/v1/
👉 **Health check:** https://rakho-api.onrender.com/api/v1/health/

---

## Table of Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Android app (Google Play)](#android-app-google-play)
- [Subscriptions & payments](#subscriptions--payments)
- [Tech stack](#tech-stack)
- [Database & current record counts](#database--current-record-counts)
- [API reference](#api-reference)
- [Multi-tenancy & security model](#multi-tenancy--security-model)
- [Local development](#local-development)
- [First-run setup (create pharmacy + import catalog)](#first-run-setup-create-pharmacy--import-catalog)
- [Deployment (Render)](#deployment-render)
- [Making the repo private later](#making-the-repo-private-later)
- [Project structure](#project-structure)
- [Testing](#testing)

---

## What it does

- **Point of sale (POS)** — search medicines, build a cart, and complete a sale. Stock is deducted automatically using **FEFO** (First-Expired-First-Out): the batches expiring soonest are always sold first, and expired stock can never be allocated.
- **Batch-level inventory** — every delivery is received as a batch (number, expiry date, unit cost, selling price, supplier). Re-receiving an existing batch number tops it up.
- **Expiry management** — live alerts for expired and soon-expiring (≤90 days) batches, with the monetary value at risk, and one-click write-off (wastage) that zeroes the batch and records an audit movement.
- **Low-stock alerts** — per-medicine thresholds; a medicine is flagged when the sum of its batch stock falls to/below its threshold.
- **Bangladesh medicine catalog** — a read-mostly national catalog (brand, generic, strength, dosage form, manufacturer, package info) imported from public source data. The Add Medicine screen searches it and pre-fills everything.
- **Audit trail** — every stock change (purchase, sale, wastage, adjustment) is recorded as a `StockMovement`.
- **Dashboard** — today's revenue, stock units/value, alert counts.
- **Offline-tolerant frontend** — the SPA keeps a local zustand store (persisted to `localStorage`); mutations try the API first and fall back to local-only with a confirm dialog.

---

## Architecture

```
┌───────────────────────────── Render web service: rakho-api ─────────────────────────────┐
│                                                                                          │
│   React SPA (Vite build, committed to backend/static/app/)                               │
│        ▲                                                                                 │
│        │  same origin — no CORS needed in production                                     │
│   Django + DRF  ── Whitenoise (static) ── gunicorn                                       │
│        │                                                                                 │
│        ├── API-key auth per pharmacy tenant (X-Pharmacy-Key header)                      │
│        └── PostgreSQL (Render) via dj-database-url                                       │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

- The **frontend is a single-page app** (`src/`) built with Vite (`base: '/static/app/'`) and served by Django at `/app/` (including SPA asset routes via `/app/<path:route>`).
- The **backend is a Django project** (`backend/`) with one app, `inventory`, exposing the REST API under `/api/v1/`.
- Frontend ↔ backend communication is a thin typed client (`src/app/api.ts`) sending the `X-Pharmacy-Key` header on every tenant request.

## Android app (Google Play)

A complete native Android app lives in `android/` — Kotlin and Jetpack Compose, built as an offline-first companion to the same API.

| | |
|---|---|
| Language / UI | Kotlin 2.4, Jetpack Compose (Material 3), Navigation Compose |
| Build | AGP 9.4 with built-in Kotlin, Gradle 9.7 (wrapper committed), JDK 17 |
| SDK levels | `compileSdk 37`, `targetSdk 36` (Android 16 — the level Play requires for new apps), `minSdk 26` |
| Billing | Google Play Billing **9.1**, verified server-side |
| Package | `com.lipon.rakho` |
| Languages | English + বাংলা (`values-bn`), per-app language on Android 13+ |

### What the app does

- **Sell (POS)** — search or scan, cart with FEFO batch allocation, discounts, cash/bKash/Nagad/card/**baki (credit)**, change due, and an offline queue that replays safely.
- **Stock & expiry radar** — every medicine with its batches, colour-coded expiry (`Expired`, `Expires today`, `days left`), low-stock flags, and write-off with a confirmation.
- **Receive stock** — supplier, batch number, **date-picker expiry** (never typed), quantity, cost and selling price, with validation that selling price is never below cost.
- **Add medicine** — relevance-ranked search of the ~14,000-medicine Bangladesh catalogue, or manual entry, with a low-stock threshold.
- **Reports** — today / 7-day / month totals, average bill, top sellers, and CSV export through the share sheet.
- **Dashboard** — today's sales, stock value, low stock, expiring soon, plus a Pro upsell.
- **Settings** — pharmacy profile, language, sync status, reconnect, per-app server URL for self-hosting, expiry-reminder toggle, privacy/terms links, account deletion route.
- **Expiry reminders** — a daily WorkManager job (09:00 Dhaka time) notifies about expiring and low stock.

### Offline-first design

Sales, receipts and stock must be correct in a shop with flaky internet, so the app is local-first:

- Reads are served from a hand-written SQLite cache (`LocalCache`) that re-emits on every change; there is no annotation processor in the build.
- Writes go to the API when possible and are **queued** otherwise, then replayed on the next sync.
- A sale uses a device-generated invoice number that is unique per pharmacy, so a replay is rejected as a duplicate and can never double-book a sale.
- FEFO allocation exists in both the app and the backend and produces identical results (deterministic tie-break by batch number); money is integer paisa everywhere, never floating point.

### Build and test

```bash
cd android
./gradlew :app:testDebugUnitTest     # 26 unit tests (money, FEFO, cart, expiry)
./gradlew :app:lintRelease           # release lint, aborts on error
./gradlew :app:assembleDebug         # debug APK
./gradlew :app:bundleRelease         # Play bundle (.aab)
```

Release signing is read from environment variables, so the keystore is never committed:

```bash
RAKHO_KEYSTORE_PATH=/secure/rakho-upload.jks \
RAKHO_KEYSTORE_PASSWORD=... RAKHO_KEY_ALIAS=rakho RAKHO_KEY_PASSWORD=... \
./gradlew :app:bundleRelease
```

Without them the bundle still builds, unsigned. `.github/workflows/android.yml` runs tests, lint and the bundle on every change, and signs it when the keystore secrets are configured.

### Play Console checklist

| Requirement | Status |
|---|---|
| Target API level 36 (Android 16) for new apps | ✅ `targetSdk 36` |
| Play Billing Library 8.0.0+ | ✅ `9.1.0` |
| App Bundle (`.aab`) | ✅ produced by `bundleRelease` |
| Privacy policy URL | ✅ `/privacy/` (served by this backend) |
| Terms of service | ✅ `/terms/` |
| In-app account deletion route | ✅ Settings → Delete account |
| Data safety: no ads, no trackers, no location/contacts | ✅ no such SDKs; `allowBackup=false`, so records are never copied off-device |
| Subscription disclosure text (auto-renew, cancel in Play) | ✅ shown on the paywall |
| Billing products | create `rakho_pro_monthly`, `rakho_pro_yearly` in Play Console |
| Personal developer accounts | must run a closed test with ≥12 testers for 14 days before production |

---

## Subscriptions & payments

Rakho has one entitlement model, however the pharmacy paid:

| Channel | Used for | Notes |
|---|---|---|
| **Google Play Billing** | in-app subscriptions (Play policy requires it for digital goods) | Bangladeshi buyers can pay with bKash/Nagad/Rocket/carrier billing through their own Play account; Play keeps ~15% |
| **PipraPay (self-hosted)** | web, WhatsApp and B2B/distributor sales | bKash, Nagad, Rocket, upay, bank; ~1.5–2.5% gateway fee. Never linked from inside the Play app, which policy forbids |
| **Manual** | cash or bank transfer recorded by an admin | Django admin → `Subscription` → set plan, source and expiry |

**The server is the only source of truth.** The app posts a Play purchase token to `/api/v1/billing/play/verify/`; the backend verifies it with the Google Play Developer API and only then stores the entitlement. Every attempt is recorded in `PlayPurchaseEvent`, replaying a token is idempotent, and a lapsed or unpaid subscription is reported as `free` (with the lapse date retained).

Enable verification by setting, on the server:

```
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON = <service-account JSON, or a path to it>
GOOGLE_PLAY_PACKAGE_NAME       = com.lipon.rakho
```

With no credentials the endpoint answers `503` and every pharmacy simply stays on the free plan — shipping the app never depends on billing being configured.

---

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, Django 5.2, Django REST Framework, drf-spectacular (OpenAPI) |
| Database | PostgreSQL (Render), SQLite locally by default |
| Auth | SHA-256-hashed per-pharmacy API keys (`PharmacyApiKey`), optional `SETUP_TOKEN` for setup routes |
| Frontend | React 18, TypeScript, Vite 6, Tailwind CSS 4, zustand (+persist), date-fns, lucide-react |
| Static/media | WhiteNoise (compressed manifest storage) |
| Deploy | Render Blueprint (`render.yaml`): web service + free PostgreSQL, auto-migrate on deploy |

---

## Database & current record counts

**Which database:** a Render-managed **PostgreSQL 18** instance named `bangladesh-pharmacy-db` (free plan, Oregon), connected via the `DATABASE_URL` env var. Locally, the project falls back to `backend/db.sqlite3`.

> ⚠️ **Free-tier expiry:** Render free Postgres expires ~30 days after creation. When it does, endpoints return `"database": "unreachable"` / 500s. Fix: create a new database on Render, update `DATABASE_URL`, redeploy — then re-run the [first-run setup](#first-run-setup-create-pharmacy--import-catalog). (Longer-term: move to a provider whose free tier doesn't expire, e.g. Neon.)

**Current live record counts** (as of 2026-09-18, right after the fresh DB was provisioned):

| Table / model | Records | Purpose |
|---|---|---|
| `Pharmacy` | **1** | `Halal Pharmacy` (the live tenant) |
| `CatalogMedicine` | **≈14,000+** *(verify: `GET /api/v1/catalog/medicines/` returns `"count"`)* | National medicine catalog imported from public Kaggle data |
| `Medicine` | **0** | Per-pharmacy sellable catalog — grows as you add medicines |
| `Batch` | **0** | Stock batches — grows as you receive deliveries |
| `Sale` / `SaleLine` / `SaleAllocation` | **0** | Sales ledger — grows as you sell |
| `StockMovement` | **0** | Audit trail of every stock delta |
| `PharmacyApiKey` | **1** | The active key for the pharmacy |

You can always re-check counts yourself:

```bash
curl -s https://rakho-api.onrender.com/api/v1/catalog/medicines/ | head -c 200   # "count" = catalog total
# tenant tables need the key (see API reference below)
```

---

## API reference

Interactive docs: **/api/docs/** (Swagger) · **/api/redoc/** · schema at **/api/schema/**

### Public (no auth)

| Method & path | Purpose |
|---|---|
| `GET /api/v1/health/` | Service + DB status (`{"database": "connected"}`) |
| `GET /api/v1/catalog/medicines/?q=napa` | Search the national catalog (`count` = true total, `results` capped at 100) |
| `POST /api/v1/setup/pharmacy/` | Create a tenant; returns the raw API key **once**. Requires `X-Setup-Token` when `SETUP_TOKEN` is set |
| `POST /api/v1/setup/catalog/` | Trigger catalog import (same token guard) |

### Tenant endpoints (header `X-Pharmacy-Key: phm_...`)

| Method & path | Purpose |
|---|---|
| `GET/POST /api/v1/inventory/medicines/` | List (with `available_quantity` annotation) / create medicine (optionally linked to a catalog entry) |
| `GET/PATCH /api/v1/inventory/medicines/{id}/` | Detail incl. its batches / partial update |
| `GET /api/v1/inventory/batches/` | List batches (`?active=true`, `?medicine={id}`) |
| `GET /api/v1/inventory/batches/{id}/` | Batch detail |
| `POST /api/v1/inventory/batches/{id}/write-off/` | Write off remaining stock (wastage) |
| `GET/POST /api/v1/inventory/purchases/` | List recent purchase movements / receive stock (`{"items": [...]}`) |
| `GET/POST /api/v1/inventory/sales/` | List sales / create a **FEFO sale** |
| `GET /api/v1/inventory/alerts/?days=90` | Expired + expiring + low-stock, with overview counts |
| `GET /api/v1/inventory/dashboard/` | KPI snapshot (stock value, today/week sales, alert counts) |
| `GET /api/v1/inventory/movements/` | Recent stock movements (audit) |
| `GET/PATCH /api/v1/inventory/pharmacy/` | Pharmacy profile (name, currency, address, phone) |
| `GET /api/v1/billing/subscription/` | Current entitlement (plan, source, valid_until, is_active) |
| `POST /api/v1/billing/play/verify/` | Verify a Google Play purchase and store the entitlement |

Error shape (all tenant endpoints): `{"error": {...}, "status": <int>}`.

---

## Multi-tenancy & security model

- Every tenant is a `Pharmacy` row. Its API keys are stored **hashed** (SHA-256); only a prefix is kept for identification. The raw key is shown exactly once at creation.
- `PharmacyApiKeyAuthentication` resolves `X-Pharmacy-Key` → the `Pharmacy` instance; all tenant queries are scoped by it (`PharmacyScopedAPIView`), so cross-tenant access is impossible.
- **Setup routes** (`/setup/pharmacy/`, `/setup/catalog/`) are public but guarded by the optional `SETUP_TOKEN` env var: when set, requests must include `X-Setup-Token: <value>`.
- No secrets live in the repository: `render.yaml` declares `SETUP_TOKEN` with `generateValue: true` and leaves `CORS_ALLOW_ALL_ORIGINS` as a deploy-time value (`sync: false`); `backend/.env.example` is a template only.

---

## Local development

```bash
# Backend
cd backend
python -m venv ../.venv && source ../.venv/bin/activate      # Windows: ../.venv/Scripts/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver                                    # http://127.0.0.1:8000

# Frontend (hot reload dev server; talks to the production API per src/app/api.ts)
# from the repo root:
npm install
npm run dev                                                   # http://localhost:5173

# Frontend production build → served by Django at /app/
npm run build          # outputs to backend/static/app/ (see vite.config.ts)
```

`DATABASE_URL` unset → local SQLite. Copy `backend/.env.example` for the standard env vars (`DJANGO_SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CORS_*`, `SETUP_TOKEN`).

## First-run setup (create pharmacy + import catalog)

```bash
# 1) Create a pharmacy tenant — prints the raw API key ONCE
python manage.py create_pharmacy "Halal Pharmacy"

# 2) Import the Bangladesh catalog (~14k records; downloads a public Kaggle archive)
python manage.py import_bangladesh_catalog --download
#    (or from a local zip: --archive /path/to/archive.zip, plus --clear to reset)
```

On production (remote equivalent):

```bash
curl -X POST -H "X-Setup-Token: $SETUP_TOKEN" -H "Content-Type: application/json" \
     -d '{"name":"Halal Pharmacy"}' https://rakho-api.onrender.com/api/v1/setup/pharmacy/

curl -X POST -H "X-Setup-Token: $SETUP_TOKEN" https://rakho-api.onrender.com/api/v1/setup/catalog/
```

Then paste the returned `phm_...` key into the app: **Settings → Rakho API Key → Connect & Sync**.

## Deployment (Render)

`render.yaml` (Blueprint) defines:

- **Web service `rakho-api`** — Python, `rootDir: backend`, build = `pip install` + `makemigrations --noinput` + `collectstatic` + `migrate`, start = gunicorn, health check = `/api/v1/health/`, auto-deploy on commit to `main`.
- **Database `bangladesh-pharmacy-db`** — its connection string is injected as `DATABASE_URL`.
- **Env vars** — `DJANGO_SECRET_KEY` (generated), `SETUP_TOKEN` (generated), `CORS_ALLOW_ALL_ORIGINS` (deploy-time value), `ALLOWED_HOSTS`, `DEBUG=false`.

Pushing to `main` triggers a deploy automatically; migrations run as part of the build.

## Making the repo private later

Nothing in the code depends on the repository being public:

- No API keys, tokens, or passwords are committed (verified by a repo-wide secret scan; `.env.example` holds empty placeholders only).
- The SPA bundle in `backend/static/app/` is public static assets, not secrets.
- Live services authenticate via env vars (`DJANGO_SECRET_KEY`, `SETUP_TOKEN`, `DATABASE_URL`) which Render stores server-side and which remain valid regardless of repo visibility.

So: **Settings → Danger → Change visibility → Private** is safe anytime. Afterwards, keep deploying with the same Blueprint; if you use a GitHub token for anything, prefer fine-grained tokens limited to this repo.

## Project structure

```
├── index.html                     # SPA entry (dev)
├── vite.config.ts                 # Vite: base /static/app/, @ → src alias, figma asset resolver
├── render.yaml                    # Render Blueprint: web service + Postgres
├── src/
│   ├── main.tsx                   # React bootstrap
│   ├── app/
│   │   ├── App.tsx                # All screens (dashboard, POS, expiry, receive, settings, add-medicine)
│   │   ├── api.ts                 # Typed API client (X-Pharmacy-Key header, response normalizers)
│   │   └── components/            # shadcn/Radix UI kit + figma helper
│   └── styles/                    # Tailwind/theme CSS
└── backend/
    ├── manage.py · requirements.txt · .env.example
    ├── config/                    # settings.py (DRF/CORS/Whitenoise/SETUP_TOKEN), urls.py (landing, /app/, API, docs)
    ├── inventory/│   ├── models.py              # Pharmacy, PharmacyApiKey, CatalogMedicine, Medicine, Batch, Sale(+Line/Allocation), StockMovement, Subscription, PlayPurchaseEvent
│   ├── serializers.py         # DRF serializers (incl. SubscriptionSerializer, PlayVerifySerializer)
│   ├── services.py            # receive_purchase, create_fefo_sale, write_off_batch (atomic, row-locked), PlayVerifier, apply_play_purchase
│   ├── static_pages.py        # Public privacy policy and terms pages
│   ├── auth.py                # API-key authentication
│   ├── views.py               # All API views (public, setup-guarded, tenant-scoped, billing, SPA)
│   ├── urls.py                # /api/v1/ routes
│   ├── management/commands/   # create_pharmacy, import_bangladesh_catalog
│   ├── migrations/            # 0001 initial, 0002 pharmacy address/phone, 0003 subscriptions + Play events
│   └── tests/                 # test_api.py (FEFO, atomicity, wastage, alerts, setup guard) + test_billing.py (subscriptions, Play verification, policy pages)
    └── static/app/                # Built SPA bundle served at /app/
└── android/                       # Native Kotlin/Compose app for Google Play (see above)
    ├── gradle/libs.versions.toml   # Pinned AGP/Kotlin/Compose/Billing versions
    ├── app/src/main/java/bd/rakho/pharmacy/
    │   ├── core/                   # Money (BDT paisa), FEFO planner, cart maths, expiry rules, Dhaka time
    │   ├── data/                   # Retrofit API, SQLite cache, offline queue, repositories, session
    │   ├── feature/                # dashboard, pos, stock, receive, addmedicine, reports, billing, settings
    │   └── work/                   # Daily expiry-reminder worker
    └── app/src/test/               # 26 unit tests for the money/FEFO/expiry logic
```

## Testing

```bash
# Backend — 31 tests
cd backend
python manage.py test inventory        # FEFO allocation, expired-stock rejection, atomic sales,
                                       # wastage audit, dashboard/alerts, pharmacy settings,
                                       # catalog ranking/count, setup-token guard, subscription
                                       # entitlement, Play verification (incl. idempotency),
                                       # policy pages

# Android — 26 tests + release lint
cd android
./gradlew :app:testDebugUnitTest :app:lintRelease
```

---

**Status:** live · backend v1.0.0 · DB schema at migration `0003` · Android app v1.0.0 (Play-ready bundle)
**Note:** free-tier Postgres expires ~30 days after creation — see [Database](#database--current-record-counts) for the renewal drill.
