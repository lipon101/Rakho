"""Tests for the Sprint 0.1 foundations: the JSON error envelope, the request
id middleware and the CORS hardening.

These pin the contract the Android client depends on. Before the envelope, an
error could arrive as ``{"detail": ...}``, ``{"error": "..."}`` or
``{"error": {"code": ...}}`` depending on where it was raised; a client had to
guess. The tests below assert one shape for every exception path, and that a
view that already ships the structured shape is not double-wrapped (the Pro
refusal used to be the live example of that; it left with the paywall, so the
invariant is now asserted against the handler itself).
"""

from django.test import TestCase
from rest_framework.exceptions import APIException
from rest_framework.test import APIClient

from inventory.exceptions import api_exception_handler, code_for_status, error_payload
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

    def test_structured_error_is_not_double_wrapped(self):
        """A payload that already is the envelope must survive untouched.

        Views that hand-build ``{"error": {"code": ...}}`` (the invitation
        endpoints do, for instance) go through the same handler as every other
        exception; re-wrapping would nest the envelope inside itself and break
        every client that reads ``error.code``.
        """

        class AlreadyEnveloped(APIException):
            default_detail = error_payload("seat_limit_reached", "Seats are full.")
            status_code = 402

        response = api_exception_handler(AlreadyEnveloped(), {})
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.data["error"]["code"], "seat_limit_reached")
        # Not nested inside another envelope.
        self.assertNotIn("error", response.data["error"])
        # The status still travels inside the body too.
        self.assertEqual(response.data["status"], 402)

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
        """The guard is real: importing the production settings with a wildcard
        and DEBUG=false must raise, not merely warn. Run in a subprocess so the
        module is imported fresh with the hostile environment in place.

        ``config.settings.production`` is imported by name rather than relying
        on the package-level resolver, so the test keeps asserting the guard
        itself instead of the resolver's choice of module.
        """
        import os
        import subprocess
        import sys
        from pathlib import Path

        backend_dir = Path(__file__).resolve().parents[2]
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DJANGO_SECRET_KEY": "test-only-key-000000000000000000",
            "DEBUG": "false",
            "CORS_ALLOW_ALL_ORIGINS": "true",
        }
        result = subprocess.run(
            [sys.executable, "-c", "import django; django.setup()"],
            cwd=backend_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CORS_ALLOW_ALL_ORIGINS", result.stderr)

    def test_package_resolver_falls_back_to_production(self):
        """Naming ``config.settings`` itself must resolve to the hardened module.

        Something that names the package rather than an environment module (a
        cron entry, an older Deploy Button) used to get whichever values the
        single settings module happened to compute. It now has to get
        production --- a permissive fallback would be the more dangerous
        mistake, since it only shows up on the internet.
        """
        import os
        import subprocess
        import sys
        from pathlib import Path

        backend_dir = Path(__file__).resolve().parents[2]
        env = {
            **os.environ,
            # The literal package name, not the blank case: manage.py, wsgi.py
            # and config/celery.py all fill the variable in when nothing else
            # has, so naming the package is the only way to reach the resolver.
            "DJANGO_SETTINGS_MODULE": "config.settings",
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
