# Bangladesh Pharmacy API

Independent Django REST API for the Bangladesh pharmacy inventory/POS application. It keeps public medicine catalogue data separate from each pharmacy's operational stock.

## Core guarantees

- All money is decimal BDT (never floats).
- Sales allocate **only non-expired batches** in FEFO order: expiry date, received time, then ID.
- A sale is one database transaction. If any line cannot be fulfilled, no stock changes are saved.
- Purchases, sales, and wastage create immutable stock-movement audit records.
- Every tenant endpoint requires `X-Pharmacy-Key`; only the public medicine catalogue and health endpoint are open.

## Local run

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env # load these variables using your shell or dotenv tool
python manage.py migrate
python manage.py import_bangladesh_catalog --download
python manage.py create_pharmacy "Bhai Bhai Pharmacy"
python manage.py runserver
```

## API base

`/api/v1/`

| Method | Path | Purpose |
|---|---|---|
| GET | `health/` | Public health check |
| GET | `catalog/medicines/?q=napa` | Public Bangladesh medicine source catalogue |
| GET/POST | `medicines/` | Pharmacy medicine records |
| PATCH | `medicines/:id/` | Update a pharmacy medicine |
| GET/POST | `purchases/receive/` | Receive one or more batches |
| GET | `batches/?active=true` | Inventory batches |
| POST | `batches/:id/wastage/` | Write off remaining stock |
| GET/POST | `sales/` | FEFO sale history / create sale |
| GET | `alerts/?days=90` | Expired, expiring, and low-stock lists |
| GET | `dashboard/` | BDT operational summary |
| GET | `stock-movements/` | Inventory audit trail |

The POST endpoints accept JSON. Protect all tenant requests with:

```http
X-Pharmacy-Key: phm_...
```

## Render

This repository includes `render.yaml`. In Render: **New → Blueprint**, connect this repository, select the Blueprint, and approve both resources. The web service runs on the free plan; it may cold-start after inactivity. Confirm Render currently offers a free PostgreSQL option in your account/region before accepting the database plan; if that option is unavailable, choose Render's lowest paid PostgreSQL plan or a compatible external Postgres provider and set `DATABASE_URL`.

After the service is green, execute once from the Render Shell:

```bash
python manage.py import_bangladesh_catalog --download
python manage.py create_pharmacy "Your Pharmacy Name"
```

Copy the displayed API key into a password manager. The key is shown once only.

## Verification

```bash
python manage.py test inventory.tests
curl https://YOUR-SERVICE.onrender.com/api/v1/health/
```

## Data sources and attribution

The import command consumes `medicine.csv` from **Assorted Medicine Dataset of Bangladesh** by Ahmed Shahriar Sakib. Its fields match the public source project [`ahmedshahriar/bd-medicine-scraper`](https://github.com/ahmedshahriar/bd-medicine-scraper), which describes a MedEx-derived Bangladesh medicine catalog. Treat this as reference catalog data: verify pricing, availability, registration, and clinical content against authoritative/local sources before dispensing.

The separate `lsiddiqsunny/API-for-Bangladeshi-Medicine` project was reviewed as a reference source only; this API does not copy its crawler output or expose an upstream dependency.
