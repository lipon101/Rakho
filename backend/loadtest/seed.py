"""Seed tenants and stock for the load test (Phase 6).

Creates N organisations, one branch each, a realistic amount of stock, and a
branch API key per tenant, then writes ``loadtest/seed.json`` in the shape
``locustfile.py`` reads.

Run it against a *disposable* database. It creates real tenants with real keys;
pointed at production it would quietly add a hundred pharmacies to a paying
customer's installation. The command therefore refuses to run when
``DJANGO_SETTINGS_MODULE`` names the production module unless ``--force`` is
given, which is the same posture ``setup_rls_role`` takes for the same reason.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import timedelta
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _setup_django():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    django.setup()


DEFAULT_TENANTS = 10
MEDICINES_PER_TENANT = 40
BATCHES_PER_MEDICINE = 2
#: A shop's stock is not uniform: most lines are healthy and a few are close to
#: expiry, which is the distribution the expiry query is designed to find.
NEAR_EXPIRY_SHARE = 0.15
#: The catalogue search is a **paid** feature, enforced server-side. Seeding a
#: couple of Pro chains and the rest free reproduces the real mixture, so the
#: load test measures the catalogue on the tenants that may use it --- and the
#: Pro refusal on the tenants that may not.
PRO_TENANTS = 3


def seed(tenants: int, host: str) -> dict:
    """Create the tenants and return the seed document."""
    from django.utils import timezone

    from inventory.models import Batch, Medicine, Organization, Pharmacy, PharmacyApiKey, Subscription

    today = timezone.localdate()
    seeded = []

    for index in range(tenants):
        # The first PRO_TENANTS chains are Pro; the rest are free. A chain with
        # no subscription row at all resolves to free, which is the state a new
        # install is in.
        is_pro = index < PRO_TENANTS
        org = Organization.objects.create(
            name=f"Loadtest Chain {index:03d}",
            slug=f"loadtest-chain-{index:03d}",
            currency="BDT",
            timezone="Asia/Dhaka",
            locale="bn",
            plan=Organization.Plan.ENTERPRISE if is_pro else Organization.Plan.BRANCH,
            branch_allowance=3,
        )
        branch = Pharmacy.objects.create(
            name=f"Loadtest Branch {index:03d}",
            organization=org,
            branch_code=f"LT{index:03d}",
            currency="BDT",
            timezone="Asia/Dhaka",
        )
        _key, raw_key = PharmacyApiKey.create_key(branch, label="loadtest")

        if is_pro:
            # A dated Pro entitlement, the way a manual bKash payment is recorded.
            Subscription.objects.create(
                pharmacy=branch,
                plan=Subscription.Plan.PRO,
                source=Subscription.Source.MANUAL,
                valid_until=today + timedelta(days=365),
            )

        medicine_ids, batch_ids = [], []
        for m in range(MEDICINES_PER_TENANT):
            medicine = Medicine.objects.create(
                pharmacy=branch,
                brand_name=f"Loadtest Brand {index:03d}-{m:03d}",
                generic_name=f"Generic {m % 12:02d}",
                strength=f"{random.choice([125, 250, 500, 650])}mg",  # noqa: S311
                dosage_form=random.choice(["Tablet", "Syrup", "Capsule", "Injection"]),  # noqa: S311
                manufacturer_name=f"Loadtest Pharma {m % 7}",
                default_selling_price=random.randint(20, 400),  # noqa: S311
                low_stock_threshold=20,
            )
            medicine_ids.append(str(medicine.id))
            for b in range(BATCHES_PER_MEDICINE):
                # Half the batches expire inside the alert window, half well
                # beyond it: a stock where everything is expiring would make the
                # expiry report trivially fast, and one where nothing is would
                # never exercise its filter.
                if random.random() < NEAR_EXPIRY_SHARE:  # noqa: S311
                    expiry = today + timedelta(days=random.randint(5, 30))  # noqa: S311
                else:
                    expiry = today + timedelta(days=random.randint(180, 900))  # noqa: S311

                received = random.randint(50, 600)  # noqa: S311
                batch = Batch.objects.create(
                    pharmacy=branch,
                    medicine=medicine,
                    batch_number=f"B{index:03d}{m:03d}{b}",
                    expiry_date=expiry,
                    unit_cost=random.randint(10, 300),  # noqa: S311
                    selling_price=random.randint(20, 400),  # noqa: S311
                    quantity_received=received,
                    # ``available`` is drawn from ``received`` rather than
                    # independently: the model carries a CHECK constraint that
                    # available can never exceed received, and an independent
                    # draw violates it roughly half the time.
                    quantity_available=random.randint(1, received),  # noqa: S311
                    supplier_name=f"Loadtest Supplier {b}",
                )
                batch_ids.append(str(batch.id))

        seeded.append(
            {
                "organization_id": str(org.id),
                "slug": org.slug,
                "branch_id": str(branch.id),
                "api_key": raw_key,
                "pro": is_pro,
                "medicine_ids": medicine_ids,
                "batch_ids": batch_ids,
            }
        )

    return {"host": host, "tenants": seeded, "console": {}}


def main():
    parser = argparse.ArgumentParser(description="Seed tenants for the Rakho load test.")
    parser.add_argument("--host", default="http://127.0.0.1:8000", help="The host the load test will target.")
    parser.add_argument("--tenants", type=int, default=DEFAULT_TENANTS)
    parser.add_argument("--out", default="loadtest/seed.json", help="Where to write the seed document.")
    parser.add_argument("--force", action="store_true", help="Allow running against production settings.")
    options = parser.parse_args()

    if "production" in os.environ.get("DJANGO_SETTINGS_MODULE", "") and not options.force:
        raise SystemExit("Refusing to seed against production settings. Pass --force if you are certain.")

    _setup_django()
    document = seed(options.tenants, options.host)

    # The file holds live branch keys, so it is written 0600 and is listed in
    # .gitignore --- a load-test key is still a key.
    path = Path(options.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)
    print(f"Seeded {len(document['tenants'])} tenants with {MEDICINES_PER_TENANT} medicines each -> {path}")


if __name__ == "__main__":
    main()
