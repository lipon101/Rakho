"""Truth tests for the public facts on the landing page and the console.

Two classes of bug motivated these.

The Pro price was typed into the landing page (in Bengali digits, in three
places) and into the console's revenue figure, while the checkout page billed
``PRO_PRICE_BDT``. That setting is environment-driven, so changing it would
leave the marketing page advertising a price nobody was charged. These tests
change the setting and assert every surface follows it.

The repository also shipped no image assets, so a link shared to Facebook,
Messenger or WhatsApp rendered as a bare grey card and the browser tab showed
a blank icon. These tests assert the images exist, that the tags point at them,
and that the declared Open Graph dimensions match the real file.
"""
import json
import re
import struct
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from inventory.admin_dashboard import dashboard_stats
from inventory.landing import bengali_digits, landing_page
from inventory.pay import pay_page
from inventory.models import (
    CatalogMedicine, Pharmacy, PharmacyApiKey, SignupRequest, Subscription,
)

BRAND_DIR = Path(settings.BASE_DIR) / "static" / "brand"


def _png_size(path):
    """Read width/height straight out of the PNG header."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _structured_data(html, node_type):
    match = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    nodes = json.loads(match.group(1))["@graph"]
    return next(n for n in nodes if n["@type"] == node_type)


class BrandAssetTests(TestCase):
    """The favicon, app icon and share card must exist and be wired up."""

    def test_generated_images_are_present_and_the_right_shape(self):
        expected = {
            "favicon-32.png": (32, 32),
            "apple-touch-icon.png": (180, 180),
            "og.png": (1200, 630),
        }
        for name, size in expected.items():
            with self.subTest(name=name):
                path = BRAND_DIR / name
                self.assertTrue(path.exists(), f"{name} is missing")
                self.assertEqual(_png_size(path), size)

    def test_landing_page_declares_the_icon_and_share_card(self):
        html = landing_page()
        self.assertIn('rel="icon"', html)
        self.assertIn("/static/brand/favicon-32.png", html)
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn("/static/brand/apple-touch-icon.png", html)
        self.assertIn('property="og:image"', html)
        self.assertIn('name="twitter:image"', html)
        # A summary card with an image is only a rich card if the platform is
        # told so; "summary" gives a thumbnail, "summary_large_image" a banner.
        self.assertIn('content="summary_large_image"', html)

    def test_share_card_is_absolute_and_matches_the_real_image(self):
        """A relative og:image is ignored, and wrong dimensions get cropped."""
        html = landing_page()
        image = re.search(
            r'<meta property="og:image" content="([^"]+)"', html).group(1)
        self.assertTrue(image.startswith("https://"), image)
        self.assertTrue(image.endswith("/static/brand/og.png"), image)

        declared_w = re.search(
            r'<meta property="og:image:width" content="(\d+)"', html).group(1)
        declared_h = re.search(
            r'<meta property="og:image:height" content="(\d+)"', html).group(1)
        actual_w, actual_h = _png_size(BRAND_DIR / "og.png")
        self.assertEqual((int(declared_w), int(declared_h)), (actual_w, actual_h))

    def test_console_links_the_favicon(self):
        owner = User.objects.create_superuser("owner", "o@example.com", "pw")
        client = Client()
        client.force_login(owner)
        html = client.get("/" + settings.ADMIN_URL).content.decode()
        # Matched without the extension: with a manifest storage the href is
        # cache-busted to a hashed filename.
        self.assertIn("brand/favicon-32", html)

    def test_favicon_route_serves_a_real_file(self):
        """/favicon.ico is requested on every origin, icon tag or not."""
        response = RequestFactory().get("/favicon.ico")
        redirect = __import__("config.urls", fromlist=["favicon"]).favicon(
            response)
        self.assertEqual(redirect.status_code, 302)
        location = redirect["Location"]
        self.assertTrue(location.startswith("/static/brand/favicon-32"), location)
        self.assertTrue(location.endswith(".png"), location)


class PriceSingleSourceTests(TestCase):
    """Every price a visitor or the owner sees must follow PRO_PRICE_BDT."""

    def test_landing_page_follows_the_configured_price(self):
        with override_settings(PRO_PRICE_BDT="349"):
            html = landing_page()
        self.assertIn("৳৩৪৯", html)          # the pricing card and the FAQ
        self.assertNotIn("৳২৯৯", html)       # no stale hardcoded price left
        offer = next(
            o for o in _structured_data(html, "SoftwareApplication")["offers"]
            if o["name"] == "Pro"
        )
        self.assertEqual(offer["price"], 349)

    def test_structured_data_price_matches_the_visible_card(self):
        with override_settings(PRO_PRICE_BDT="349"):
            html = landing_page()
        card = re.search(r'class="price">৳([০-৯]+)</div>', html).groups()
        # The plan cards render Free then Pro.
        self.assertEqual(card[0], "০")
        pro_card = re.findall(r'<div class="price">৳([০-৯]+)</div>', html)[1]
        self.assertEqual(pro_card, "৩৪৯")

    def test_console_revenue_follows_the_configured_price(self):
        pharmacy = Pharmacy.objects.create(name="Test Pharmacy")
        Subscription.objects.create(
            pharmacy=pharmacy,
            plan=Subscription.Plan.PRO,
            valid_until=timezone.localdate() + timedelta(days=30),
        )
        with override_settings(PRO_PRICE_BDT="349"):
            stats = dashboard_stats()
        self.assertEqual(stats["active_pro"], 1)
        self.assertEqual(stats["pro_price"], "৳349")
        self.assertEqual(stats["monthly_revenue"], "৳349")

    def test_every_surface_shares_one_price_helper(self):
        """Two copies of this logic is exactly how the price drifted.

        Paying for a duplicated helper is cheap insurance: if someone pastes a
        second implementation into any of these modules, this fails.
        """
        from inventory import admin_dashboard, landing, pay
        from inventory.pricing import pro_price_bdt as canonical

        self.assertIs(landing.pro_price_bdt, canonical)
        self.assertIs(admin_dashboard.pro_price_bdt, canonical)
        self.assertIs(pay.pro_price_bdt, canonical)

    def test_checkout_charges_the_same_price_the_page_advertises(self):
        for configured in ("349", 349, "499"):
            with self.subTest(value=configured):
                with override_settings(PRO_PRICE_BDT=configured):
                    page = pay_page("token")
                    landing = landing_page()
                self.assertIn(str(configured), page)
                self.assertIn(
                    f"৳{bengali_digits(int(configured))}", landing)

    def test_unusable_price_setting_falls_back_instead_of_crashing(self):
        """A typo in an env var must not take the landing page down."""
        for bad in ("", "  ", "not-a-price", None, 0, "-5"):
            with self.subTest(value=bad):
                with override_settings(PRO_PRICE_BDT=bad):
                    html = landing_page()
                    stats = dashboard_stats()
                self.assertIn("৳২৯৯", html)
                self.assertEqual(stats["pro_price"], "৳299")


class ConsoleAttentionTests(TestCase):
    """Work waiting on the owner must be impossible to miss."""

    def setUp(self):
        self.owner = User.objects.create_superuser(
            "owner", "owner@example.com", "pw")
        self.client = Client()
        self.client.force_login(self.owner)

    def _html(self):
        response = self.client.get("/" + settings.ADMIN_URL)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_pending_signup_is_surfaced_and_linked(self):
        """A lead used to sit unanswered with the console reporting all-clear."""
        SignupRequest.objects.create(
            owner_name="Karim", pharmacy_name="Karim Pharmacy",
            status=SignupRequest.Status.PENDING,
        )
        html = self._html()
        self.assertIn("awaiting a first response", html)
        self.assertIn("status__exact=pending", html)

    def test_payment_waiting_for_verification_is_surfaced(self):
        SignupRequest.objects.create(
            owner_name="Rahim", pharmacy_name="Rahim Pharmacy",
            status=SignupRequest.Status.PAID_REVIEW,
        )
        html = self._html()
        self.assertIn("waiting to be verified", html)
        self.assertIn("status__exact=paid_review", html)

    def test_attention_count_matches_the_items_listed(self):
        """The headline number must equal the number of items shown.

        A count that drifts from the list is worse than no count: it either
        invents work or hides it.
        """
        SignupRequest.objects.create(
            owner_name="Karim", pharmacy_name="Karim Pharmacy",
            status=SignupRequest.Status.PENDING,
        )
        html = self._html()
        listed = html.count('class="rk-attn-item')
        headline = re.search(r"<strong>(\d+) items?</strong>", html)
        self.assertIsNotNone(headline, "no attention headline rendered")
        self.assertGreater(listed, 0)
        self.assertEqual(int(headline.group(1)), listed)

    def test_no_customers_is_not_reported_as_a_lockout(self):
        """Zero API keys is normal before the first customer, not a fault.

        Treating it as an alarm told the owner something was broken while every
        number was simply zero — which trains them to ignore the panel.
        """
        html = self._html()
        self.assertNotIn("none of them can sign in", html)
        self.assertNotIn("locked out", html)

    def test_shops_with_no_active_key_are_reported_as_a_lockout(self):
        """A shop that exists but cannot authenticate is a real lockout."""
        pharmacy = Pharmacy.objects.create(name="Karim Pharmacy")
        _, raw_key = PharmacyApiKey.create_key(pharmacy)
        PharmacyApiKey.objects.filter(pharmacy=pharmacy).update(
            revoked_at=timezone.now())
        html = self._html()
        self.assertIn("none of them can sign in", html)

    def test_all_clear_state_reports_nothing_to_chase(self):
        CatalogMedicine.objects.create(brand_name="Napa")
        pharmacy = Pharmacy.objects.create(name="Test Pharmacy")
        PharmacyApiKey.objects.create(
            pharmacy=pharmacy, key_prefix="phm_test12", key_hash="a" * 64)
        html = self._html()
        self.assertIn("Nothing needs attention", html)
        self.assertNotIn("ck-attn-item", html)


class SiteUrlTests(TestCase):
    """Canonical tags and the sitemap must agree on the real origin."""

    def test_landing_and_sitemap_follow_the_configured_origin(self):
        with override_settings(SITE_URL="https://rakho.example.com"):
            html = landing_page()
            sitemap = __import__(
                "config.urls", fromlist=["sitemap_xml"]
            ).sitemap_xml(RequestFactory().get("/sitemap.xml")).content.decode()
            robots = __import__(
                "config.urls", fromlist=["robots_txt"]
            ).robots_txt(RequestFactory().get("/robots.txt")).content.decode()

        self.assertIn(
            '<link rel="canonical" href="https://rakho.example.com/">', html)
        self.assertNotIn("rakho-api.onrender.com", html)
        self.assertIn("<loc>https://rakho.example.com/</loc>", sitemap)
        self.assertIn("https://rakho.example.com/sitemap.xml", robots)
