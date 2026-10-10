"""The national catalogue is open to every pharmacy — the old paywall is gone.

DEPRECATED history, recorded so the next reader does not "restore" a gate that
was removed on purpose: the catalogue endpoint was first ``AllowAny`` (anyone
could page the 14,000+ product national dataset), then gated behind a paid plan
that answered 402 ``pro_required``. Rakho is free for everyone now, so these
tests pin the new contract instead:

1. Search — open to any pharmacy with a valid key, whether it has no
   subscription row at all, a free row, or a lapsed one. All three are the
   same experience.
2. Medicine creation — linking a ``catalog_medicine`` id copies that row's
   brand/generic/strength onto the new medicine *and returns them* for every
   pharmacy, not just paid ones.
3. The key itself is still the only gate: anonymous callers and revoked keys
   are refused, so "free for everyone" does not mean "public to everyone".
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inventory.models import (
    CatalogMedicine,
    Medicine,
    Pharmacy,
    PharmacyApiKey,
    Subscription,
)

CATALOG_URL = "/api/v1/catalog/medicines/"
MEDICINES_URL = "/api/v1/inventory/medicines/"


class CatalogueAccessTests(TestCase):
    def setUp(self):
        self.pharmacy = Pharmacy.objects.create(name="Karim Pharmacy")
        _, self.key = PharmacyApiKey.create_key(self.pharmacy)
        self.catalogue = CatalogMedicine.objects.create(
            brand_name="Napa",
            generic_name="Paracetamol",
            strength="500 mg",
            manufacturer_name="Beximco",
            source_brand_id=101,
        )
        self.client = APIClient(HTTP_X_PHARMACY_KEY=self.key)

    # ── search ────────────────────────────────────────────────────────────

    def test_anonymous_search_is_refused(self):
        """Free for users, not for strangers: the key is still required."""
        response = APIClient().get(CATALOG_URL, {"q": "napa"})
        self.assertIn(response.status_code, (401, 403))

    def test_search_works_with_no_subscription_row_at_all(self):
        """A brand-new pharmacy has no Subscription row and still searches."""
        self.assertFalse(Subscription.objects.filter(pharmacy=self.pharmacy).exists())
        response = self.client.get(CATALOG_URL, {"q": "napa"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["brand_name"], "Napa")

    def test_a_free_row_is_no_different_from_no_row(self):
        Subscription.objects.create(pharmacy=self.pharmacy, plan=Subscription.Plan.FREE)
        response = self.client.get(CATALOG_URL, {"q": "napa"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    def test_a_lapsed_subscription_gets_the_same_full_access(self):
        """Old expired subscription → exactly the same experience as new."""
        Subscription.objects.create(
            pharmacy=self.pharmacy,
            plan=Subscription.Plan.PRO,
            valid_until=timezone.localdate() - timedelta(days=1),
        )
        response = self.client.get(CATALOG_URL, {"q": "napa"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    def test_revoked_key_cannot_reach_the_catalogue(self):
        PharmacyApiKey.objects.filter(pharmacy=self.pharmacy).update(revoked_at=timezone.now())
        response = APIClient(HTTP_X_PHARMACY_KEY=self.key).get(CATALOG_URL)
        self.assertIn(response.status_code, (401, 403))

    # ── medicine creation ─────────────────────────────────────────────────

    def test_catalogue_rows_link_and_are_copied_without_any_subscription(self):
        """The 402 that used to refuse this payload is gone with the paywall."""
        response = self.client.post(
            MEDICINES_URL,
            {"catalog_medicine": self.catalogue.id, "brand_name": "Napa", "default_selling_price": "12.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["generic_name"], "Paracetamol")
        self.assertEqual(response.json()["manufacturer_name"], "Beximco")
        self.assertTrue(Medicine.objects.filter(pharmacy=self.pharmacy).exists())

    def test_a_medicine_can_still_be_added_manually(self):
        response = self.client.post(
            MEDICINES_URL,
            {"brand_name": "Napa", "strength": "500 mg", "default_selling_price": "12.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["brand_name"], "Napa")
