"""Tests for the Sprint 0.1 foundations: the JSON error envelope, the request
id middleware and the CORS hardening.

These pin the contract the Android client depends on. Before the envelope, an
error could arrive as ``{"detail": ...}``, ``{"error": "..."}`` or
``{"error": {"code": ...}}`` depending on where it was raised; a client had to
guess. The tests below assert one shape for every exception path, and that the
one path that already shipped the structured shape (the Pro refusal) is not
double-wrapped.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from inventory.exceptions import code_for_status, error_payload
from inventory.models import Pharmacy, PharmacyApiKey


class ErrorEnvelopeTests(TestCase):
    """Every exception path answers in the same envelope."""

    def setUp(self):
        self.pharmacy = Pharmacy.objects.create(name="Envelope Pharmacy")
        _, key = PharmacyApiKey.create_key(self.pharmacy)
        self.key = key

    def test_unauthenticated_request_is_enveloped(self):
        response = APIClient().get("/api/v1/inventory/medicines/")
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertIn("error", body)
        self.assertIsInstance(body["error"], dict)
        # DRF's own default_code is more specific than the status mapping, so
        # the handler prefers it: a missing key is "not_authenticated", not the
        # generic "permission_denied".
        self.assertEqual(body["error"]["code"], "not_authenticated")
        self.assertIn("detail", body["error"])
        self.assertEqual(body["status"], 403)

    def test_invalid_key_is_enveloped_as_authentication_failed(self):
        client = APIClient(HTTP_X_PHARMACY_KEY="phm_not-a-real-key")
        response = client.get("/api/v1/inventory/medicines/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "authentication_failed")

    def test_unknown_route_is_enveloped_as_not_found(self):
        client = APIClient(HTTP_X_PHARMACY_KEY=self.key)
        response = client.get("/api/v1/definitely-not-a-route/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_wrong_method_is_enveloped(self):
        client = APIClient(HTTP_X_PHARMACY_KEY=self.key)
        response = client.delete("/api/v1/inventory/dashboard/")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"]["code"], "method_not_allowed")

    def test_validation_error_carries_fields(self):
        client = APIClient(HTTP_X_PHARMACY_KEY=self.key)
        response = client.post("/api/v1/inventory/sales/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["code"], "validation_error")
        # Field-level detail is preserved under "fields" so a client can point
        # at the offending input rather than showing one generic message.
        self.assertIn("fields", body["error"])

    def test_pro_refusal_is_not_double_wrapped(self):
        """The one pre-existing structured error must survive untouched."""
        client = APIClient(HTTP_X_PHARMACY_KEY=self.key)
        response = client.get("/api/v1/catalog/medicines/?q=napa")
        self.assertEqual(response.status_code, 402)
        body = response.json()
        self.assertEqual(body["error"]["code"], "pro_required")
        # Not nested inside another envelope.
        self.assertNotIn("code", body["error"].get("error", {}))

    def test_view_level_string_error_keeps_its_shape(self):
        """The legacy ``{"error": "<string>"}`` shape is pinned by its own tests."""
        response = APIClient().post(
            "/api/v1/signup/",
            {"owner_name": "<script>alert(1)</script>", "pharmacy_name": "X"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIsInstance(response.json()["error"], str)


class ErrorPayloadHelperTests(TestCase):
    """The small helpers the envelope is built from."""

    def test_code_for_status_maps_known_codes(self):
        self.assertEqual(code_for_status(400), "validation_error")
        self.assertEqual(code_for_status(403), "permission_denied")
        self.assertEqual(code_for_status(404), "not_found")
        self.assertEqual(code_for_status(429), "throttled")

    def test_code_for_status_falls_back(self):
        self.assertEqual(code_for_status(418), "error")

    def test_error_payload_omits_empty_fields(self):
        self.assertNotIn("fields", error_payload("not_found", "Nope."))
        self.assertIn("fields", error_payload("validation_error", "Bad.", fields={"a": ["b"]}))


class RequestIdMiddlewareTests(TestCase):
    """Every response carries a request id, and a safe inbound one is honoured."""

    def test_response_carries_a_generated_request_id(self):
        response = APIClient().get("/api/v1/health/")
        self.assertEqual(response.status_code, 200)
        request_id = response.headers.get("X-Request-Id")
        self.assertTrue(request_id)
        self.assertGreaterEqual(len(request_id), 8)

    def test_safe_inbound_request_id_is_echoed(self):
        response = APIClient().get("/api/v1/health/", HTTP_X_REQUEST_ID="abc12345-xyz")
        self.assertEqual(response.headers.get("X-Request-Id"), "abc12345-xyz")

    def test_unsafe_inbound_request_id_is_replaced(self):
        """A hostile value must not reach the logs or the response verbatim."""
        hostile = "bad id with spaces and <script>"
        response = APIClient().get("/api/v1/health/", HTTP_X_REQUEST_ID=hostile)
        echoed = response.headers.get("X-Request-Id")
        self.assertNotEqual(echoed, hostile)
        self.assertNotIn("<", echoed)
        self.assertNotIn(" ", echoed)

    def test_too_short_inbound_request_id_is_replaced(self):
        response = APIClient().get("/api/v1/health/", HTTP_X_REQUEST_ID="short")
        self.assertNotEqual(response.headers.get("X-Request-Id"), "short")


class CorsHardeningTests(TestCase):
    """CORS is scoped to the API and refuses a production wildcard."""

    def test_cors_headers_are_absent_on_non_api_routes(self):
        response = APIClient().get("/", HTTP_ORIGIN="http://localhost:5173")
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_allowed_origin_is_echoed_on_api_routes(self):
        response = APIClient().get("/api/v1/health/", HTTP_ORIGIN="http://localhost:5173")
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "http://localhost:5173")

    def test_credentials_are_not_allowed(self):
        """API-key auth is header-based, so credentialed CORS stays off."""
        response = APIClient().get("/api/v1/health/", HTTP_ORIGIN="http://localhost:5173")
        self.assertNotEqual(response.headers.get("Access-Control-Allow-Credentials"), "true")

    def test_wildcard_origin_is_refused_in_production(self):
        """The guard is real: importing settings with a wildcard + DEBUG=false
        must raise, not merely warn. Run in a subprocess so the module is
        imported fresh with the hostile environment in place."""
        import os
        import subprocess
        import sys
        from pathlib import Path

        backend_dir = Path(__file__).resolve().parents[2]
        env = {
            **os.environ,
            "DJANGO_SECRET_KEY": "test-only-key-000000000000000000",
            "DEBUG": "false",
            "CORS_ALLOW_ALL_ORIGINS": "true",
        }
        result = subprocess.run(
            [sys.executable, "-c", "import config.settings"],
            cwd=backend_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CORS_ALLOW_ALL_ORIGINS", result.stderr)
