# Rakho — Pharmacy Inventory & Expiry Manager

**Rakho** (রাখো — *keep*) is an inventory and expiry-management platform for
pharmacies, sold as a mobile-first product with an enterprise tier for chains.
A branch's staff run the shop from an Android app; the owner runs the business
and the team from a web console and a JSON API.

It is built for Bangladesh first — a real national medicine catalogue, bKash
and Nagad payment flows, Bengali as the default interface language — and
structured so that a pharmacy anywhere else can adopt it without anything
feeling local-only: every price is in a configurable currency, every timestamp
in a configurable timezone, and the API's contract is language-neutral English
JSON.

---

## What problem it solves

A pharmacy loses money in three places that a paper register cannot see:

1. **Expiry.** Stock that expires on the shelf is pure loss, and it is invisible
   until someone physically checks every box. Rakho holds stock per batch with
   an expiry date and reports what is expiring, block by block.
2. **Dispensing the wrong batch.** Selling newer stock first leaves the older
   stock to expire. Rakho's point of sale allocates stock **FEFO** (first-expired,
   first-out) automatically, inside a transaction, and refuses a sale the stock
   cannot cover rather than letting the numbers drift.
3. **No idea what is actually happening.** A busy branch cannot say what sold
   today, what is running low, or which branch is underperforming. Rakho answers
   all three from one dashboard.

---

## Repository layout

```
rakho/
├─ backend/                  Django 5.2 + DRF API, admin console, landing page
│  ├─ config/                project configuration
│  │  ├─ settings/           base / local / production (+ package resolver)
│  │  ├─ middleware.py       request id, language default
│  │  ├─ logging.py          JSON formatter, request-id & PII filters
│  │  └─ urls.py             landing, legal pages, console, /api/v1
│  ├─ inventory/             the whole domain: models, views, services, tasks
│  │  ├─ models.py           Pharmacy, Medicine, Batch, Sale, Subscription, …
│  │  ├─ services.py         FEFO allocation, purchase receiving, billing
│  │  ├─ views.py            every API view
│  │  ├─ tasks.py            Celery jobs (digests, exports, invitations)
│  │  ├─ tests/              the test suite
│  │  └─ management/         import_bangladesh_catalog, create_pharmacy, …
│  ├─ requirements.txt       pinned runtime dependencies
│  └─ pyproject.toml         ruff + black configuration
├─ android/                  Kotlin + Jetpack Compose app (Play Store)
│  └─ app/src/main/java/com/lipon/rakho/
│     ├─ core/               domain logic (FEFO, money, dates) — testable, no UI
│     ├─ data/               API client, DTOs, repositories, local cache
│     ├─ feature/            one package per screen (screen + view model)
│     └─ ui/                 theme, shared components, charts, navigation
├─ .github/workflows/        CI (backend tests + lint) and Android build
├─ render.yaml               the deployment definition
└─ LAUNCH.md                 the go-to-market checklist
```

---

## How the pieces fit

```
  Android app (Kotlin/Compose)          Web console (Django admin)
        │  X-Pharmacy-Key                      │  JWT (email + password)
        │                                      │
        └──────────────┬───────────────────────┘
                       ▼
              Django 5.2 + DRF  ──────────  Celery worker + beat
              /api/v1/... (versioned)              │
                       │                          │
                       ▼                          ▼
                 PostgreSQL                    Redis
        (tenants, inventory, billing)   (cache, broker, throttles)
```

* **PostgreSQL** holds everything. Row-level scoping by pharmacy/organisation is
  enforced in the query layer, and Row-Level Security is available as a second
  line of defence on the database itself.
* **Redis** does three jobs with one service: Django's cache, the Celery broker
  and the DRF throttle store. The last one is why it is mandatory in production —
  an in-process cache gives every gunicorn worker its own rate-limit counter.
* **Celery** runs everything that must not block a request: expiry digests,
  low-stock alerts, invitation email and report exports.
* **The Android app** is the shop-floor client. It talks to the same API as the
  console, caches reads locally, and queues writes so a dropped connection does
  not lose a sale.

---

## Getting started

```bash
git clone https://github.com/lipon101/Rakho.git
cd Rakho/backend

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # every value has a working default
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Then:

* the landing page is at <http://localhost:8000/>
* the owner console is at <http://localhost:8000/lostsec/> (change `ADMIN_URL`)
* the API browser is at <http://localhost:8000/api/docs/>
* liveness is at `/api/v1/health/`, readiness at `/api/v1/ready/`

No Redis is required to develop or to run the test suite: the cache falls back
to per-process memory and Celery tasks run inline.

### Loading the medicine catalogue

The searchable catalogue is built from the public *Assorted Medicine Dataset of
Bangladesh* (~21,700 products) and imported once per deployment:

```bash
python manage.py import_bangladesh_catalog --download
```

The import is idempotent — running it again refreshes rather than duplicates —
and it never deletes a row a pharmacy has already linked to.

### Running the Android app

```bash
cd android
./gradlew :app:assembleDebug          # or installDebug with a device attached
./gradlew :app:testDebugUnitTest      # unit tests
```

The app points at the hosted API by default; override `API_BASE_URL` in
`android/gradle.properties` to talk to a local server.

---

## Testing and quality gates

```bash
cd backend
python manage.py test                 # the full suite
ruff check .                          # lint
black --check .                       # formatting
python manage.py check --deploy       # production-system checks
python manage.py makemigrations --check --dry-run   # no model drift
```

CI runs all five on every push and pull request; a red lint or a missing
migration fails the build before a deploy can fire. The Android job builds and
unit-tests the app, and produces a signed bundle only when the signing secrets
are present — a missing secret never blocks development.

---

## Deployment

`render.yaml` defines the services: a web service (gunicorn), a Celery worker,
a Celery beat scheduler and a managed Redis instance. Set these in the Render
dashboard:

| Variable | Why it is required |
| --- | --- |
| `DJANGO_SECRET_KEY` | 32+ chars. The production settings refuse to import without it. |
| `ALLOWED_HOSTS` | The real hostname. Also refused if left at localhost. |
| `REDIS_URL` | Backs the shared cache, the throttles and the broker. |
| `DATABASE_URL` | Managed Postgres; TLS is enforced automatically. |
| `SITE_URL` | Canonical origin for the sitemap and Open Graph URLs. |

`DEBUG` is not a variable you set: the environment module decides. Production is
selected by `RENDER=true` (which Render sets itself), and it refuses to start on
a wildcard CORS origin, a missing host list or a placeholder secret — a
misconfiguration fails the deploy instead of going unnoticed on the internet.

Optional integrations: `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON` (server-side purchase
verification), `MEDIA_S3_BUCKET` and friends (exports and org logos), `SENTRY_DSN`
(error reporting), `EMAIL_*` (invitations and digests).

---

## API

All endpoints live under `/api/v1/`; the prefix is the version, and new
capabilities are added additively so a published version never changes shape
under a client. Interactive documentation is at `/api/docs/`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health/`, `/ready/`, `/ping/` | liveness, readiness, keep-alive |
| `GET` | `/catalog/medicines/?q=` | national catalogue search (paid tier) |
| `POST` | `/signup/` | self-serve registration, returns an API key |
| `POST` | `/signup/pay/` | record a bKash/Nagad transaction id |
| `POST` | `/inventory/medicines/` | create a medicine |
| `POST` | `/inventory/purchases/` | receive stock (creates batches) |
| `POST` | `/inventory/sales/` | record a sale — allocates stock FEFO |
| `GET` | `/inventory/alerts/` | expired, expiring and low stock |
| `GET` | `/inventory/dashboard/` | today's figures for one branch |
| `GET` | `/billing/subscription/` | current entitlement |

Authentication is `X-Pharmacy-Key` for the app and a JWT bearer token for the
console. Every error answers in one envelope, so a client branches on a stable
code rather than parsing prose:

```json
{"error": {"code": "validation_error", "detail": "Validation failed.", "fields": {}}, "status": 400}
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: trunk-based on `main`, a
conventional commit message, tests and lint green before you push, and no secret
ever committed.

## Licence

Proprietary. © Rakho. All rights reserved.
