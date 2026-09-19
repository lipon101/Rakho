"""Input validation: markup is refused outright, never silently mangled.

The signup and payment endpoints previously ran free text through `clean_text`,
which stripped tags. That made `<script>alert(1)</script>` *safe* but still
stored it as `alert(1)` — a value the sender never typed, saved without any
signal that an injection attempt had happened. These tests pin the stricter
policy: markup is rejected with a 400 and nothing is written.

The pharmacy settings endpoint was the real gap: it did a bare
`setattr(pharmacy, field, request.data[field])`, so markup went straight into
the database and an over-long currency reached Postgres as a DataError (500).
"""
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.landing import landing_page
from inventory.models import Pharmacy, PharmacyApiKey

MARKUP = "<script>alert(1)</script>"


class SignupInputValidationTests(TestCase):
    """The unauthenticated signup form is the highest-risk write path."""

    URL = "/api/v1/signup/"
    VALID = {"owner_name": "Kuddus", "pharmacy_name": "Kuddus Pharmacy"}

    def setUp(self):
        # DRF throttle counters live in the cache, which outlives a test.
        cache.clear()

    def _post(self, **overrides):
        payload = dict(self.VALID)
        payload.update(overrides)
        return APIClient().post(self.URL, payload, format="json")

    def test_markup_in_pharmacy_name_is_rejected(self):
        for payload in (MARKUP, "<b>Bold</b>", "A > B"):
            with self.subTest(payload=payload):
                response = self._post(pharmacy_name=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("must not contain HTML", response.data["error"])

    def test_markup_in_owner_name_is_rejected(self):
        response = self._post(owner_name="<img src=x onerror=alert(1)>")
        self.assertEqual(response.status_code, 400)

    def test_rejected_input_stores_nothing(self):
        """Stripping used to save `alert(1)`. Now no tenant is created at all."""
        response = self._post(pharmacy_name=MARKUP)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Pharmacy.objects.count(), 0)

    def test_markup_in_whatsapp_is_rejected(self):
        response = self._post(whatsapp="<script>alert(1)</script>")
        self.assertEqual(response.status_code, 400)

    def test_control_characters_are_rejected(self):
        response = self._post(owner_name="Kuddus\nDROP")
        self.assertEqual(response.status_code, 400)

    def test_overlong_name_is_rejected_rather_than_truncated(self):
        response = self._post(pharmacy_name="ক" * 181)
        self.assertEqual(response.status_code, 400)
        self.assertIn("at most 180", response.data["error"])

    def test_ordinary_names_still_accepted(self):
        """Guard against over-rejecting real values."""
        for owner, shop in (
            ("কুদ্দুস মিয়া", "কুদ্দুস ফার্মেসি"),
            ("Rahman", "Rahman & Sons Pharmacy"),
            ("Nipa", "Nipa Medical Hall (Branch 2)"),
        ):
            with self.subTest(shop=shop):
                cache.clear()
                response = self._post(owner_name=owner, pharmacy_name=shop)
                self.assertEqual(response.status_code, 201, response.data)
                self.assertTrue(response.data["api_key"].startswith("phm_"))


class PharmacySettingsValidationTests(TestCase):
    """The authenticated settings endpoint had no validation at all."""

    URL = "/api/v1/inventory/pharmacy/"

    def setUp(self):
        cache.clear()
        self.pharmacy = Pharmacy.objects.create(name="Bhai Bhai Pharmacy")
        _, key = PharmacyApiKey.create_key(self.pharmacy)
        self.client = APIClient(HTTP_X_PHARMACY_KEY=key)

    def test_markup_is_rejected_in_name_and_address(self):
        for field in ("name", "address"):
            with self.subTest(field=field):
                response = self.client.patch(
                    self.URL, {field: MARKUP}, format="json")
                self.assertEqual(response.status_code, 400)
        self.pharmacy.refresh_from_db()
        self.assertEqual(self.pharmacy.name, "Bhai Bhai Pharmacy")
        self.assertEqual(self.pharmacy.address, "")

    def test_overlong_currency_is_rejected_instead_of_erroring(self):
        """varchar(3): this used to reach Postgres and fail the request."""
        response = self.client.patch(
            self.URL, {"currency": "BDTT"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_currency_is_normalised_to_uppercase(self):
        response = self.client.patch(
            self.URL, {"currency": "bdt"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.pharmacy.refresh_from_db()
        self.assertEqual(self.pharmacy.currency, "BDT")

    def test_overlong_address_is_rejected(self):
        response = self.client.patch(
            self.URL, {"address": "x" * 256}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_address_may_still_be_cleared(self):
        self.pharmacy.address = "Road 1, Dhaka"
        self.pharmacy.save()
        response = self.client.patch(self.URL, {"address": ""}, format="json")
        self.assertEqual(response.status_code, 200)
        self.pharmacy.refresh_from_db()
        self.assertEqual(self.pharmacy.address, "")

    def test_explicit_json_nulls_are_ignored_not_rejected(self):
        """A client that serialises every DTO field sends null for unset ones;
        that means "no change", not "invalid value"."""
        response = self.client.patch(
            self.URL,
            {"name": None, "currency": None, "address": None, "phone": None},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.pharmacy.refresh_from_db()
        self.assertEqual(self.pharmacy.name, "Bhai Bhai Pharmacy")
        self.assertEqual(self.pharmacy.currency, "BDT")

    def test_unrelated_fields_are_ignored(self):
        response = self.client.patch(
            self.URL, {"timezone": "UTC", "low_stock_default": 99}, format="json")
        self.assertEqual(response.status_code, 200)
        self.pharmacy.refresh_from_db()
        self.assertEqual(self.pharmacy.timezone, "Asia/Dhaka")


class LandingPageTests(TestCase):
    def test_landing_page_offers_eight_feature_cards(self):
        # The grid is 4 columns wide at the 1080px container, so eight cards
        # fill exactly two rows with no ragged remainder.
        self.assertEqual(landing_page().count('class="card"'), 8)

    def test_form_inputs_carry_the_server_side_limits(self):
        html = landing_page()
        for attribute in ('maxlength="120"', 'maxlength="180"', 'maxlength="32"'):
            with self.subTest(attribute=attribute):
                self.assertIn(attribute, html)

    def test_landing_page_never_writes_markup_from_data(self):
        """The API key is written with textContent; keep it that way."""
        self.assertNotIn("innerHTML", landing_page())
        self.assertNotIn("insertAdjacentHTML", landing_page())
        self.assertNotIn("document.write", landing_page())
