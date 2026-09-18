# Rakho — Pharmacy Inventory & Expiry Manager

Backend for **Rakho**, a pharmacy inventory, POS and expiry-management service
built for pharmacies in Bangladesh. This public repository contains only the
**server** that powers it:

- Django REST API — medicines, batches, purchases, sales, FEFO stock rotation,
  expiry alerts, dashboard
- Bangladesh national medicine catalog search (~14,000 products)
- Google Play purchase verification for subscriptions
- Public privacy policy & terms pages

**Live service:** https://rakho-api.onrender.com
**Web app:** https://rakho-api.onrender.com/app/
**API docs:** https://rakho-api.onrender.com/api/docs/
**Health:** https://rakho-api.onrender.com/api/v1/health/

## Repository layout

```
backend/           Django project (config + inventory app + built web assets)
render.yaml        Render blueprint (service + database)
.github/workflows  Deploy hook on push
```

The mobile app, web-app source and product docs are maintained privately.

## Run locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Deploy (Render)

The service deploys automatically from `main` via the Render blueprint
(`render.yaml`): one web service (gunicorn) and one PostgreSQL database.
Migrations run in the build command.

## Security notes

- Pharmacy API keys are stored **hashed**; clients send them as
  `X-Pharmacy-Key`.
- All traffic is rate-limited (anonymous, catalog and per-pharmacy scopes).
- Setup endpoints (`/api/v1/setup/*`) require the `X-Setup-Token` header when
  `SETUP_TOKEN` is configured.
- Report vulnerabilities to **support@rakho.app**.

## License

Proprietary — all rights reserved. You may not copy or redistribute the
service code without permission.
