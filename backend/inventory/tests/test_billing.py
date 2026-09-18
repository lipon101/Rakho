import json
from datetime import timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from inventory.models import Pharmacy, PharmacyApiKey, PlayPurchaseEvent, Subscription
from inventory.services import (
    PlayNotConfigured,
    PlayVerificationFailed,
    PlayVerifier,
    apply_play_purchase,
    current_subscription,
)


class BillingApiTests(APITestCase):
    """The server owns entitlements: the app can never grant itself Pro."""

    def setUp(self):
        self.pharmacy = Pharmacy.objects.create(name="Halal Pharmacy")
        self.raw_key = "phm_testkey_0000000000000000"
        PharmacyApiKey.objects.create(
            pharmacy=self.pharmacy,
            label="Primary",
            key_prefix=self.raw_key[:11],
            key_hash=PharmacyApiKey.hash_key(self.raw_key),
        )
        self.auth = {"HTTP_X_PHARMACY_KEY": self.raw_key}

    # ── entitlement ──
    def test_subscription_defaults_to_free(self):
        response = self.client.get(reverse("subscription"), **self.auth)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["plan"], "free")
        self.assertEqual(response.data["source"], "none")
        self.assertFalse(response.data["is_active"])
        self.assertIsNone(response.data["valid_until"])

    def test_subscription_requires_pharmacy_key(self):
        response = self.client.get(reverse("subscription"))
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_active_play_subscription_is_reported(self):
        Subscription.objects.create(
            pharmacy=self.pharmacy,
            plan=Subscription.Plan.PRO,
            source=Subscription.Source.PLAY,
            product_id="rakho_pro_yearly",
            valid_until=timezone.localdate() + timedelta(days=300),
            auto_renewing=True,
        )
        response = self.client.get(reverse("subscription"), **self.auth)
        self.assertEqual(response.data["plan"], "pro")
        self.assertEqual(response.data["source"], "play")
        self.assertTrue(response.data["is_active"])
        self.assertTrue(response.data["auto_renewing"])

    def test_lapsed_subscription_reports_free_but_keeps_the_lapse_date(self):
        lapsed = timezone.localdate() - timedelta(days=3)
        Subscription.objects.create(
            pharmacy=self.pharmacy,
            plan=Subscription.Plan.PRO,
            source=Subscription.Source.PLAY,
            valid_until=lapsed,
        )
        response = self.client.get(reverse("subscription"), **self.auth)
        self.assertEqual(response.data["plan"], "free")
        self.assertFalse(response.data["is_active"])
        self.assertEqual(response.data["valid_until"], lapsed.isoformat())

    # ── play verification ──
    def test_verify_requires_pharmacy_key(self):
        response = self.client.post(
            reverse("play-verify"),
            {"purchase_token": "tok", "product_id": "rakho_pro_monthly"},
            format="json",
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_verify_rejects_unknown_product(self):
        response = self.client.post(
            reverse("play-verify"),
            {"purchase_token": "tok", "product_id": "not_a_rakho_product"},
            format="json",
            **self.auth,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_returns_503_when_play_is_not_configured(self):
        response = self.client.post(
            reverse("play-verify"),
            {"purchase_token": "tok", "product_id": "rakho_pro_monthly"},
            format="json",
            **self.auth,
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def _verified(self, *, expiry_days=365, payment_state=1, auto_renewing=True):
        payload = {
            "expiryTimeMillis": str(
                int((timezone.now() + timedelta(days=expiry_days)).timestamp() * 1000)
            ),
            "paymentState": payment_state,
            "autoRenewing": auto_renewing,
            "orderId": "GPA.1234",
        }
        with mock.patch("inventory.views.get_play_verifier") as factory:
            factory.return_value = PlayVerifier(service=_FakePlayService(payload))
            return self.client.post(
                reverse("play-verify"),
                {
                    "purchase_token": "play-token-1",
                    "product_id": "rakho_pro_monthly",
                    "package_name": "com.lipon.rakho",
                },
                format="json",
                **self.auth,
            ), payload

    def test_verified_purchase_activates_pro_and_is_idempotent(self):
        response, _ = self._verified()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["plan"], "pro")
        self.assertTrue(response.data["is_active"])
        self.assertEqual(response.data["product_id"], "rakho_pro_monthly")

        first_expiry = Subscription.objects.get(pharmacy=self.pharmacy).valid_until

        # Replaying the same purchase token must not create a second entitlement.
        replay, _ = self._verified()
        self.assertEqual(replay.status_code, status.HTTP_200_OK)
        self.assertEqual(Subscription.objects.filter(pharmacy=self.pharmacy).count(), 1)
        self.assertEqual(Subscription.objects.get(pharmacy=self.pharmacy).valid_until, first_expiry)

        events = PlayPurchaseEvent.objects.filter(pharmacy=self.pharmacy)
        self.assertEqual(events.count(), 2)
        self.assertTrue(all(event.succeeded for event in events))

    def test_expired_play_subscription_is_rejected_and_stays_free(self):
        response, _ = self._verified(expiry_days=-1, payment_state=1)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Subscription.objects.filter(pharmacy=self.pharmacy).exists())
        self.assertFalse(
            PlayPurchaseEvent.objects.filter(pharmacy=self.pharmacy, succeeded=True).exists()
        )

    def test_pending_payment_is_not_treated_as_paid(self):
        response, _ = self._verified(payment_state=0)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Subscription.objects.filter(pharmacy=self.pharmacy).exists())

    def test_free_trial_payment_state_is_accepted(self):
        response, _ = self._verified(payment_state=2, expiry_days=14)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["plan"], "pro")

    def test_google_failure_is_reported_as_bad_request(self):
        with mock.patch("inventory.views.get_play_verifier") as factory:
            factory.return_value = _FailingVerifier()
            response = self.client.post(
                reverse("play-verify"),
                {"purchase_token": "tok", "product_id": "rakho_pro_monthly"},
                format="json",
                **self.auth,
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class PlayVerifierUnitTests(APITestCase):
    def test_unconfigured_verifier_refuses_to_verify(self):
        verifier = PlayVerifier(credentials_info=None, package_name="")
        self.assertFalse(verifier.configured)
        with self.assertRaises(PlayNotConfigured):
            verifier.verify("token", "rakho_pro_monthly", "com.lipon.rakho")

    def test_apply_purchase_requires_a_configured_verifier(self):
        pharmacy = Pharmacy.objects.create(name="Unconfigured Pharmacy")
        with self.assertRaises(PlayNotConfigured):
            apply_play_purchase(
                pharmacy=pharmacy,
                purchase_token="tok",
                product_id="rakho_pro_monthly",
                package_name="com.lipon.rakho",
                verifier=PlayVerifier(credentials_info=None, package_name=""),
            )

    def test_current_subscription_returns_unsaved_free_default(self):
        pharmacy = Pharmacy.objects.create(name="Fresh Pharmacy")
        subscription = current_subscription(pharmacy)
        self.assertEqual(subscription.plan, Subscription.Plan.FREE)
        self.assertFalse(subscription.is_active)


class PolicyPageTests(APITestCase):
    """Play Console requires both URLs to answer publicly."""

    def test_privacy_policy_is_public_html(self):
        response = self.client.get("/privacy/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        body = response.content.decode()
        self.assertIn("Privacy Policy", body)
        self.assertIn("support@rakho.app", body)

    def test_terms_are_public_html(self):
        response = self.client.get("/terms/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Terms of Service", body)
        self.assertIn("Google Play", body)


class _FakePlayService:
    """Minimal stand-in for the androidpublisher client used in tests."""

    def __init__(self, payload):
        self.payload = payload

    def purchases(self):
        return self

    def subscriptions(self):
        return self

    def get(self, **kwargs):
        return self

    def execute(self):
        return self.payload


class _FailingVerifier:
    configured = True

    def verify(self, purchase_token, product_id, package_name=None):
        raise PlayVerificationFailed("google rejected the token")
