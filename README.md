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
    ├── inventory/
    │   ├── models.py              # Pharmacy, PharmacyApiKey, CatalogMedicine, Medicine, Batch, Sale(+Line/Allocation), StockMovement
    │   ├── serializers.py         # DRF serializers
    │   ├── services.py            # receive_purchase, create_fefo_sale, write_off_batch (atomic, row-locked)
    │   ├── auth.py                # API-key authentication
    │   ├── views.py               # All API views (public, setup-guarded, tenant-scoped, SPA)
    │   ├── urls.py                # /api/v1/ routes
    │   ├── management/commands/   # create_pharmacy, import_bangladesh_catalog
    │   ├── migrations/            # 0001 initial, 0002 pharmacy address/phone (+index renames)
    │   └── tests/test_api.py      # 11 API tests (FEFO, atomicity, wastage, alerts, setup guard, …)
    └── static/app/                # Built SPA bundle served at /app/
```

## Testing

```bash
cd backend
python manage.py test inventory        # 11 tests — FEFO allocation, expired-stock rejection,
                                       # atomic sales, wastage audit, dashboard/alerts,
                                       # pharmacy settings, catalog count, setup-token guard
```

---

**Status:** live · backend v1.0.0 · DB schema at migration `0002`
**Note:** free-tier Postgres expires ~30 days after creation — see [Database](#database--current-record-counts) for the renewal drill.
