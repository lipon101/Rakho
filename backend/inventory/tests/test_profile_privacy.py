"""Tests for the optional profile + consent endpoint.

Three promises are pinned here, because each is easy to break silently:

1. **Default-deny / skip-safe.** An account that never answered anything gets
   a fully working, all-false payload, and merely reading the endpoint creates
   no rows.
2. **The licence number never lands in plaintext.** Asserted against the raw
   column, not against the API response.
3. **Validation is all-or-nothing.** A patch with one bad field must leave the
   profile exactly as it was, so a half-typed question can never half-apply.
"""

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.field_crypto import FieldDecryptError, decrypt_field, encrypt_field
from inventory.models import (
    Medicine,
    Pharmacy,
    PharmacyApiKey,
    UserConsent,
    UserPreference,
    UserProfile,
)

PROFILE_URL = "/api/v1/profile/"


class FieldCryptoTests(TestCase):
    """The cipher itself, independent of any endpoint."""

    def test_round_trip_preserves_the_value(self):
        token = encrypt_field("license_no", "DL-1234/2026")
        self.assertTrue(token.startswith("v1:"))
        self.assertEqual(decrypt_field("license_no", token), "DL-1234/2026")

    def test_empty_value_stays_empty(self):
        # A skipped question writes no ciphertext at all.
        self.assertEqual(encrypt_field("license_no", ""), "")

    def test_plaintext_never_appears_in_the_ciphertext(self):
        token = encrypt_field("license_no", "NID-SECRET-99")
        self.assertNotIn("NID-SECRET-99", token)

    def test_tampering_is_rejected(self):
        token = encrypt_field("license_no", "DL-1")
        # Flip a character in the middle of the base64 payload.
        flipped = token[:10] + ("A" if token[10] != "A" else "B") + token[11:]
        with self.assertRaises(FieldDecryptError):
            decrypt_field("license_no", flipped)

    def test_a_ciphertext_cannot_be_reused_in_another_field(self):
        # Purpose binding (AAD): a licence ciphertext copied into a different
        # encrypted column must not authenticate there.
        token = encrypt_field("license_no", "DL-1234/2026")
        with self.assertRaises(FieldDecryptError):
            decrypt_field("some_other_field", token)

    def test_unprefixed_value_is_refused(self):
        with self.assertRaises(FieldDecryptError):
            decrypt_field("license_no", "plaintext-in-the-column")


class ProfileEndpointTests(TestCase):
    def setUp(self):
        self.pharmacy = Pharmacy.objects.create(name="Bhai Bhai Pharmacy")
        _, key = PharmacyApiKey.create_key(self.pharmacy)
        self.client = APIClient(HTTP_X_PHARMACY_KEY=key)
        self.anonymous = APIClient()

    def payload(self):
        response = self.client.get(PROFILE_URL)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def patch(self, body):
        return self.client.patch(PROFILE_URL, body, format="json")

    # ── Access ──────────────────────────────────────────────────────────

    def test_profile_requires_the_pharmacy_key(self):
        self.assertEqual(self.anonymous.get(PROFILE_URL).status_code, 403)
        self.assertEqual(self.anonymous.patch(PROFILE_URL, {"owner_name": "X"}, format="json").status_code, 403)

    def test_another_pharmacies_key_sees_only_its_own_profile(self):
        other = Pharmacy.objects.create(name="Other Shop")
        _, other_key = PharmacyApiKey.create_key(other)
        self.patch({"district": "Chattogram"})

        stranger = APIClient(HTTP_X_PHARMACY_KEY=other_key)
        self.assertEqual(stranger.get(PROFILE_URL).data["district"], "")

    # ── Default-deny / skip safety ──────────────────────────────────────

    def test_reading_creates_no_rows_and_reports_all_consent_off(self):
        data = self.payload()
        self.assertEqual(data["owner_name"], "")
        self.assertEqual(data["district"], "")
        self.assertEqual(data["license_no"], "")
        self.assertEqual(data["profile_completeness"], 0)
        self.assertEqual(data["preferred_wholesalers"], [])
        self.assertEqual(set(data["consents"]), {"analytics", "sponsor_offers", "area_insights"})
        self.assertEqual(data["consents"], {"analytics": False, "sponsor_offers": False, "area_insights": False})
        self.assertEqual(data["policy_version"], settings.PRIVACY_POLICY_VERSION)
        self.assertEqual(UserProfile.objects.count(), 0)
        self.assertEqual(UserConsent.objects.count(), 0)
        self.assertEqual(UserPreference.objects.count(), 0)

    def test_the_app_works_with_every_optional_question_skipped(self):
        # The definition of done: an untouched optional layer is a valid
        # account state, not an error.
        self.assertEqual(self.patch({}).status_code, 200)
        self.assertEqual(UserProfile.objects.count(), 0)

    # ── Profile writes ──────────────────────────────────────────────────

    def test_answers_are_stored_and_completeness_rises(self):
        response = self.patch(
            {
                "owner_name": "Rahim Uddin",
                "district": "Chattogram",
                "upazila": "Pahartali",
                "shop_type": "retail",
                "role": "owner",
                "size_range": "100_500",
            }
        )
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        self.assertEqual(data["owner_name"], "Rahim Uddin")
        self.assertEqual(data["district"], "Chattogram")
        self.assertEqual(data["shop_type"], "retail")
        self.assertGreater(data["profile_completeness"], 0)
        # One row per shop, even after repeated patches (OneToOne + get_or_create).
        self.assertEqual(UserProfile.objects.filter(pharmacy=self.pharmacy).count(), 1)

    def test_partial_patch_leaves_other_answers_untouched(self):
        self.patch({"owner_name": "Rahim", "district": "Chattogram"})
        self.patch({"upazila": "Pahartali"})
        data = self.payload()
        self.assertEqual(data["owner_name"], "Rahim")
        self.assertEqual(data["district"], "Chattogram")
        self.assertEqual(data["upazila"], "Pahartali")

    def test_null_means_not_supplied_while_empty_string_clears(self):
        self.patch({"owner_name": "Rahim", "district": "Chattogram"})
        # Null: the Android client serialises its whole DTO, so a null on an
        # unrelated edit must not wipe what is stored.
        self.patch({"owner_name": None, "upazila": "Halishahar"})
        self.assertEqual(self.payload()["owner_name"], "Rahim")
        # Empty string: an explicit "remove this answer" from the profile screen.
        self.patch({"district": ""})
        data = self.payload()
        self.assertEqual(data["district"], "")
        self.assertEqual(data["owner_name"], "Rahim")

    def test_invalid_profile_patch_is_rejected_atomically(self):
        response = self.patch({"district": "<script>x</script>", "shop_type": "kiosk"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("district", response.data["error"])
        # Nothing was written: the bad district did not sneak in beside the
        # equally bad shop type.
        self.assertEqual(UserProfile.objects.count(), 0)

    def test_unknown_field_is_rejected_by_name(self):
        response = self.patch({"gps_coordinates": "23.81,90.41"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("gps_coordinates", response.data["error"])
        self.assertEqual(UserProfile.objects.count(), 0)

    def test_body_must_be_an_object(self):
        self.assertEqual(self.client.patch(PROFILE_URL, ["not", "an", "object"], format="json").status_code, 400)

    # ── Licence number ──────────────────────────────────────────────────

    def test_license_is_encrypted_at_rest_and_returned_to_its_owner(self):
        response = self.patch({"license_no": "DL-1234/2026"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["license_no"], "DL-1234/2026")

        raw = UserProfile.objects.values_list("license_no_encrypted", flat=True).get(pharmacy=self.pharmacy)
        self.assertTrue(raw.startswith("v1:"))
        self.assertNotIn("DL-1234/2026", raw)
        self.assertNotIn("1234", raw)

    def test_license_charset_is_enforced(self):
        response = self.patch({"license_no": "not a license!!!"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("license_no", response.data["error"])

    # ── Preferences ─────────────────────────────────────────────────────

    def test_wholesalers_are_stored_deduped_and_capped(self):
        response = self.patch({"preferred_wholesalers": ["Square", "Square", "Incepta"]})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["preferred_wholesalers"], ["Square", "Incepta"])

        too_many = self.patch({"preferred_wholesalers": [f"Trader {i}" for i in range(11)]})
        self.assertEqual(too_many.status_code, 400)
        # The cap refusal must not have overwritten the stored answer.
        self.assertEqual(self.payload()["preferred_wholesalers"], ["Square", "Incepta"])

        self.patch({"preferred_wholesalers": []})
        self.assertEqual(self.payload()["preferred_wholesalers"], [])
        # Clearing it leaves no row behind: absence is the storage format.
        self.assertEqual(UserPreference.objects.count(), 1)

    # ── Consent ─────────────────────────────────────────────────────────

    def test_consent_toggles_record_status_version_and_timestamp(self):
        response = self.patch({"consents": {"analytics": True}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["consents"]["analytics"])
        self.assertFalse(response.data["consents"]["sponsor_offers"])

        row = UserConsent.objects.get(pharmacy=self.pharmacy, type="analytics")
        self.assertTrue(row.granted)
        self.assertEqual(row.policy_version, settings.PRIVACY_POLICY_VERSION)
        self.assertIsNotNone(row.updated_at)

        # Revoking is a write to the same row, not a second record.
        self.patch({"consents": {"analytics": False}})
        self.assertEqual(UserConsent.objects.filter(pharmacy=self.pharmacy, type="analytics").count(), 1)
        self.assertFalse(UserConsent.objects.get(pharmacy=self.pharmacy, type="analytics").granted)

    def test_consent_requires_a_real_boolean(self):
        self.assertEqual(self.patch({"consents": {"analytics": "yes"}}).status_code, 400)
        self.assertEqual(self.patch({"consents": {"email_marketing": True}}).status_code, 400)
        self.assertEqual(UserConsent.objects.count(), 0)

    def test_profile_answer_does_not_imply_consent(self):
        # Opting into a friendlier profile must never switch analytics on.
        self.patch({"owner_name": "Rahim", "district": "Chattogram"})
        data = self.payload()
        self.assertEqual(data["consents"], {"analytics": False, "sponsor_offers": False, "area_insights": False})

    # ── Deletion ────────────────────────────────────────────────────────

    def test_delete_removes_the_optional_layer_but_not_the_shop(self):
        Medicine.objects.create(
            pharmacy=self.pharmacy,
            brand_name="Napa",
            generic_name="Paracetamol",
            strength="500 mg",
            dosage_form="Tablet",
            default_selling_price=2,
            low_stock_threshold=5,
        )
        self.patch(
            {
                "owner_name": "Rahim",
                "district": "Chattogram",
                "license_no": "DL-1234",
                "preferred_wholesalers": ["Square"],
                "consents": {"analytics": True},
            }
        )

        response = self.client.delete(PROFILE_URL)
        self.assertEqual(response.status_code, 200, response.data)

        self.assertEqual(UserProfile.objects.count(), 0)
        self.assertEqual(UserPreference.objects.count(), 0)
        self.assertEqual(UserConsent.objects.count(), 0)
        # The shop, its stock and its login key survive untouched.
        self.assertTrue(Pharmacy.objects.filter(pk=self.pharmacy.pk).exists())
        self.assertEqual(Medicine.objects.filter(pharmacy=self.pharmacy).count(), 1)
        # And the response shows the caller the blank state it asked for.
        self.assertEqual(response.data["owner_name"], "")
        self.assertEqual(response.data["consents"]["analytics"], False)
