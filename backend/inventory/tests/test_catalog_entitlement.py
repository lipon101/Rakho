"""The national catalogue is the paid asset, so the server must protect it.

The catalogue endpoint was ``AllowAny``: no API key, no subscription. Anyone
could page the whole 14,000+ product dataset out of it, or rebuild it into a
competing app, without ever paying. Both routes that expose catalogue data are
gated now, and these tests pin the reasons:

1. Search — the endpoint free installs call on every keystroke.
2. Medicine creation — supplying a ``catalog_medicine`` id copies that row's
   brand/generic/strength onto the new medicine *and returns them*, so with
   search closed it still leaked the dataset one sequential id at a time.

Free accounts are not meant to lose anything else: manual entry has to keep
working, and a lapsed Pro plan has to behave like free rather than like an
error.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inventory.models import (
    CatalogMedicine, Medicine, Pharmacy, PharmacyApiKey, Subscription,
)

CATALOG_URL = "/api/v1/catalog/medicines/"
MEDICINES_URL = "/api/v1/inventory/medicines/"


class CatalogueAccessTests(TestCase):
    def setUp(self):
        self.pharmacy = Pharmacy.objects.create(name="Karim Pharmacy")
        _, self.key = PharmacyApiKey.create_key(self.pharmacy)
        self.catalogue = CatalogMedicine.objects.create(
            brand_name="Napa", generic_name="Paracetamol", strength="500 mg",
            manufacturer_name="Beximco", source_brand_id=101,
        )
        self.client = APIClient(HTTP_X_PHARMACY_KEY=self.key)

    def _make_pro(self, plan=Subscription.Plan.PRO, valid_until=None):
        Subscription.objects.create(
            pharmacy=self.pharmacy, plan=plan,
            valid_until=valid_until or timezone.localdate() + timedelta(days=30),
        )

    # ── search ────────────────────────────────────────────────────────────

    def test_anonymous_search_is_refused(self):
        response = APIClient().get(CATALOG_URL, {"q": "napa"})
        self.assertIn(response.status_code, (401, 403))

    def test_free_plan_search_is_refused_and_leaks_nothing(self):
        response = self.client.get(CATALOG_URL, {"q": "napa"})
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()["error"]["code"], "pro_required")
        # The refusal must not carry the data it is refusing to serve.
        self.assertNotIn("Napa", response.content.decode())
        self.assertNotIn("Paracetamol", response.content.decode())

    def test_pro_plan_search_is_served(self):
        self._make_pro()
        response = self.client.get(CATALOG_URL, {"q": "napa"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["brand_name"], "Napa")

    def test_any_non_free_plan_counts_as_paid(self):
        """Only free/pro exist now; this guards the paid gate, not a tier list."""
        self._make_pro(plan="pro")
        self.assertEqual(self.client.get(CATALOG_URL, {"q": "napa"}).status_code, 200)

    def test_lapsed_pro_plan_is_treated_as_free(self):
        """A lapsed subscription must not keep the paid features switched on."""
        Subscription.objects.create(
            pharmacy=self.pharmacy, plan=Subscription.Plan.PRO,
            valid_until=timezone.localdate() - timedelta(days=1),
        )
        self.assertEqual(self.client.get(CATALOG_URL, {"q": "napa"}).status_code, 402)

    def test_revoked_key_cannot_reach_the_catalogue(self):
        PharmacyApiKey.objects.filter(pharmacy=self.pharmacy).update(
            revoked_at=timezone.now())
        self._make_pro()
        response = APIClient(HTTP_X_PHARMACY_KEY=self.key).get(CATALOG_URL)
        self.assertIn(response.status_code, (401, 403))

    # ── medicine creation ─────────────────────────────────────────────────

    def test_free_plan_cannot_read_the_catalogue_through_medicine_creation(self):
        # A valid payload: the free plan sends the brand name itself and gets the
        # remaining fields copied out of the catalogue row it points at.
        response = self.client.post(
            MEDICINES_URL,
            {"catalog_medicine": self.catalogue.id, "brand_name": "Napa",
             "default_selling_price": "12.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()["error"]["code"], "pro_required")
        self.assertNotIn("Paracetamol", response.content.decode())
        self.assertNotIn("Beximco", response.content.decode())
        self.assertFalse(Medicine.objects.filter(pharmacy=self.pharmacy).exists())

    def test_free_plan_can_still_add_a_medicine_manually(self):
        response = self.client.post(
            MEDICINES_URL,
            {"brand_name": "Napa", "strength": "500 mg",
             "default_selling_price": "12.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["brand_name"], "Napa")

    def test_pro_plan_can_link_a_medicine_to_the_catalogue(self):
        self._make_pro()
        response = self.client.post(
            MEDICINES_URL,
            {"catalog_medicine": self.catalogue.id, "brand_name": "Napa",
             "default_selling_price": "12.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["generic_name"], "Paracetamol")
        self.assertEqual(response.json()["manufacturer_name"], "Beximco")
