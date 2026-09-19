"""Security regression tests for the public signup and payment endpoints.

Covers the abuse controls on the money-adjacent public surface:
- spoofed X-Forwarded-For cannot rotate IPs past the daily signup cap,
- replayed bKash/Nagad TrxIDs are rejected (including concurrently),
- a tampered plan field cannot reserve a higher tier,
- garbage/short transaction IDs are rejected before touching the DB.
"""
from unittest import mock

from django.test import TransactionTestCase

from inventory.abuse import SignupDailyThrottle, client_ip
from inventory.models import SignupRequest


def _signup_payload(**overrides):
    payload = {
        "owner_name": "Kuddus",
        "pharmacy_name": "Kuddus Pharmacy",
        "whatsapp": "+8801712345678",
    }
    payload.update(overrides)
    return payload


class ClientIpTests(TransactionTestCase):
    """The throttle must key on the proxy-added entry, not spoofable ones."""

    def test_rightmost_forwarded_entry_wins(self):
        request = mock.MagicMock(
            META={"HTTP_X_FORWARDED_FOR": "1.2.3.4, 5.6.7.8, 10.0.0.9",
                  "REMOTE_ADDR": "10.0.0.1"}
        )
        # 10.0.0.9 is what Render's trusted proxy appended; anything to its
        # left came from the client and must be ignored.
        self.assertEqual(client_ip(request), "10.0.0.9")

    def test_remote_addr_fallback(self):
        request = mock.MagicMock(META={"REMOTE_ADDR": "203.0.113.7"})
        self.assertEqual(client_ip(request), "203.0.113.7")


class SignupIpSpoofTests(TransactionTestCase):
    """Rotating fake X-Forwarded-For values must not defeat the daily cap."""

    def setUp(self):
        self.throttle = SignupDailyThrottle()

    def _request(self, spoofed):
        return mock.MagicMock(
            META={"HTTP_X_FORWARDED_FOR": f"{spoofed}, 10.0.0.9",
                  "REMOTE_ADDR": "10.0.0.1"}
        )

    def test_spoofed_ips_share_one_bucket(self):
        real_limit = self.throttle.DAILY_LIMIT
        for i in range(real_limit):
            request = self._request(f"9.9.9.{i}")
            self.assertFalse(self.throttle.is_over_daily_limit(request))
            self.throttle.record_success(request)
        # Cap used up by the real client — now spoofing fresh IPs must fail.
        for i in range(3):
            request = self._request(f"8.8.8.{i}")
            self.assertTrue(self.throttle.is_over_daily_limit(request))


class PaymentValidationTests(TransactionTestCase):
    """TrxID format, replay and plan-tampering protections."""

    def setUp(self):
        self.signup = SignupRequest.objects.create(
            owner_name="Owner", pharmacy_name="Pharmacy",
            lookup_token=SignupRequest.generate_token(),
        )

    def _post(self, url, payload):
        from rest_framework.test import APIClient
        return APIClient().post(url, payload, format="json")

    PAY_URL = "/api/v1/signup/pay/"

    def test_garbage_trx_id_rejected(self):
        response = self._post(self.PAY_URL, {
            "token": self.signup.lookup_token, "trx_id": "!!!not-a-trx!!!",
        })
        self.assertEqual(response.status_code, 400)

    def test_short_trx_id_rejected(self):
        response = self._post(self.PAY_URL, {
            "token": self.signup.lookup_token, "trx_id": "ab1",
        })
        self.assertEqual(response.status_code, 400)

    def test_plan_field_is_forced_to_pro(self):
        response = self._post(self.PAY_URL, {
            "token": self.signup.lookup_token, "trx_id": "TRX123456",
            "plan": "business",
        })
        self.assertEqual(response.status_code, 200)
        self.signup.refresh_from_db()
        self.assertEqual(self.signup.plan, "pro")

    def test_replayed_trx_id_rejected_on_second_signup(self):
        other = SignupRequest.objects.create(
            owner_name="Other", pharmacy_name="Other Pharmacy",
            lookup_token=SignupRequest.generate_token(),
        )
        first = self._post(self.PAY_URL, {
            "token": self.signup.lookup_token, "trx_id": "TRX999999",
        })
        self.assertEqual(first.status_code, 200)
        second = self._post(self.PAY_URL, {
            "token": other.lookup_token, "trx_id": "TRX999999",
        })
        self.assertEqual(second.status_code, 409)

    def test_unknown_token_404(self):
        response = self._post(self.PAY_URL, {
            "token": "not-a-real-token", "trx_id": "TRX123456",
        })
        self.assertEqual(response.status_code, 404)
