"""Truth tests for the public facts on the landing page and the console.

Two classes of bug motivated these.

The Pro price was typed into the landing page (in Bengali digits, in three
places) and into the console's revenue figure, while the checkout page billed
``PRO_PRICE_BDT``, so changing that setting left the marketing page advertising
a price nobody was charged. The app is now free, so the public surfaces quote no
price at all and only the dormant admin figure follows the setting — both states
are pinned here, because either could silently drift back.

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
from django.utils import timezone

from inventory.admin_dashboard import dashboard_stats
from inventory.landing import landing_page
from inventory.models import (
    Pharmacy,
    PharmacyApiKey,
    SignupRequest,
    Subscription,
)
from inventory.pay import pay_page

BRAND_DIR = Path(settings.BASE_DIR) / "static" / "brand"


def _png_size(path):
    """Read width/height straight out of the PNG header."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _structured_data(html, node_type):
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
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
        image = re.search(r'<meta property="og:image" content="([^"]+)"', html).group(1)
        self.assertTrue(image.startswith("https://"), image)
        self.assertTrue(image.endswith("/static/brand/og.png"), image)

        declared_w = re.search(r'<meta property="og:image:width" content="(\d+)"', html).group(1)
        declared_h = re.search(r'<meta property="og:image:height" content="(\d+)"', html).group(1)
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
        redirect = __import__("config.urls", fromlist=["favicon"]).favicon(response)
        self.assertEqual(redirect.status_code, 302)
        location = redirect["Location"]
        self.assertTrue(location.startswith("/static/brand/favicon-32"), location)
        self.assertTrue(location.endswith(".png"), location)


class FreeSurfaceTruthTests(TestCase):
    """No public page may quote a price, and the checkout may not ask for money.

    The Pro price used to be typed into the landing page in three places while
    the checkout billed ``PRO_PRICE_BDT``, so a settings change left the
    marketing page advertising a price nobody was charged. The app then became
    free outright, which retires the whole question: the honest state is that a
    visitor sees no price and no upgrade anywhere, whatever the dormant setting
    says, and the admin's legacy revenue figure is the only place it survives.
    """

    def test_landing_page_offers_nothing_to_buy(self):
        """No price, and no pricing *vocabulary* either.

        The first pass deleted the Pro card and the ৳299 but left the section
        heading reading দাম ("price") over a free plan --- a page that titles a
        free section "price" still teaches the visitor that a bill is coming, so
        the words are banned as well as the number.
        """
        html = landing_page()
        for pricing in ("Pro", "৳২৯৯", "দাম", "মূল্য", "প্রতি মাস", "মাসিক", "Price", "pricing"):
            with self.subTest(pricing=pricing):
                self.assertNotIn(pricing, html)
        self.assertNotIn("/pay/", html)
        self.assertIn("৳০", html)  # the one price the page is allowed to show

    def test_dormant_price_setting_cannot_reach_a_visitor(self):
        """PRO_PRICE_BDT is admin plumbing now; it must not leak to the public."""
        baseline = landing_page()
        with override_settings(PRO_PRICE_BDT="349"):
            self.assertEqual(landing_page(), baseline)

    def test_public_modules_no_longer_quote_the_price_helper(self):
        """The drift that made two prices disagree cannot silently return.

        ``admin_dashboard`` still reads the canonical helper for a legacy paid
        subscription, which is why the helper itself stays.
        """
        from inventory import admin_dashboard, landing, pay
        from inventory.pricing import pro_price_bdt as canonical

        self.assertFalse(hasattr(landing, "pro_price_bdt"))
        self.assertFalse(hasattr(pay, "pro_price_bdt"))
        self.assertIs(admin_dashboard.pro_price_bdt, canonical)

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

    def test_unusable_price_setting_falls_back_for_the_admin_instead_of_crashing(self):
        """A typo in an env var must not take the console down."""
        for bad in ("", "  ", "not-a-price", None, 0, "-5"):
            with self.subTest(value=bad):
                with override_settings(PRO_PRICE_BDT=bad):
                    stats = dashboard_stats()
                self.assertEqual(stats["pro_price"], "৳299")

    def test_checkout_page_asks_for_no_money(self):
        """Not a price, not a form, not even the old plan's name.

        The page explains that it used to take payments --- and the first draft
        did it by naming the retired plan, which is the one word a shopkeeper
        scrolling past will read. So the copy says "this used to take money" and
        stops there.
        """
        page = pay_page("some-token")
        for paid in ("<form", "<input", "TrxID", "ভেরিফাই করুন", "৳২৯৯", "Send Money", "Pro", "৳", "প্রতি মাস"):
            with self.subTest(fragment=paid):
                self.assertNotIn(paid, page)
        self.assertIn("সম্পূর্ণ ফ্রি", page)

    def test_checkout_page_never_echoes_the_token(self):
        """The token is attacker-controlled and has no use here, so it is not
        rendered at all --- which beats escaping a value that should not appear."""
        page = pay_page("</script><script>alert(1)</script>")
        self.assertEqual(page.count("<script"), 0)
        self.assertNotIn("alert(1)", page)

    def test_payment_number_is_no_longer_shown_to_a_visitor(self):
        """The MFS number was for collecting money; a free app must not print it."""
        with override_settings(PAYMENT_NUMBER="<b>99998888", SUPPORT_WHATSAPP=""):
            page = pay_page("t")
        self.assertNotIn("99998888", page)
        self.assertNotIn("<b>99998888", page)
        self.assertNotIn("&lt;b&gt;99998888", page)


class ConsoleWorkQueueTests(TestCase):
    """Work waiting on the owner must be impossible to miss.

    There used to be a "needs attention" panel for this. It is gone, because
    most of what it said restated the page in a louder form — a payment to
    verify was the amber card *and* the header badge *and* a panel entry — and a
    panel that repeats the numbers beside it trains the owner to stop reading
    it. What matters is that the signal survives without the panel, so these
    tests follow the ways a payment can be noticed rather than the panel that
    used to announce it.
    """

    def setUp(self):
        self.owner = User.objects.create_superuser("owner", "owner@example.com", "pw")
        self.client = Client()
        self.client.force_login(self.owner)

    def _html(self):
        response = self.client.get("/" + settings.ADMIN_URL)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def _pending_payments(self, count):
        # lookup_token is unique with no default, so two rows both get '' and the
        # second insert trips the constraint. Give each one a real token.
        for index in range(count):
            SignupRequest.objects.create(
                owner_name=f"Owner {index}",
                pharmacy_name=f"Shop {index}",
                status=SignupRequest.Status.PAID_REVIEW,
                lookup_token=SignupRequest.generate_token(),
            )

    def test_pending_payment_raises_the_header_badge(self):
        self._pending_payments(1)
        html = self._html()
        # Match the attribute, not the bare class name: the page's own <style>
        # block contains ".rk-badge{", which made a substring check pass even
        # with nothing rendered.
        self.assertIn('class="rk-badge"', html)
        self.assertIn("status__exact=paid_review", html)

    def test_badge_count_matches_the_payments_card(self):
        """Two surfaces show this number; if they disagree, one is lying."""
        self._pending_payments(3)
        html = self._html()
        badge = re.search(r'class="rk-badge">(\d+)<', html)
        card = re.search(r'Payments to verify</span></div>\s*<div class="rk-value">(\d+)<', html)
        self.assertIsNotNone(badge, "no header badge rendered")
        self.assertIsNotNone(card, "no payments card rendered")
        self.assertEqual(badge.group(1), card.group(1))
        self.assertEqual(badge.group(1), "3")

    def test_no_payment_means_no_badge(self):
        """A badge reading 0 all day is decoration, not a signal."""
        self.assertNotIn('class="rk-badge"', self._html())

    def test_a_shop_that_cannot_sign_in_shows_as_zero_active_keys(self):
        """The one signal the panel carried that nothing else did.

        A shop exists but nothing can authenticate as it. The panel said so in
        words; the cards say so as Active API keys reading 0 against a
        non-zero Pharmacies, which is the same fact in the place a reader is
        already looking.
        """
        pharmacy = Pharmacy.objects.create(name="Karim Pharmacy")
        PharmacyApiKey.create_key(pharmacy)
        PharmacyApiKey.objects.filter(pharmacy=pharmacy).update(revoked_at=timezone.now())
        html = self._html()
        self.assertIn("of 1 issued", html)
        self.assertRegex(html, r'Active API keys</span></div>\s*<div class="rk-value">0<')


class SiteUrlTests(TestCase):
    """Canonical tags and the sitemap must agree on the real origin."""

    def test_landing_and_sitemap_follow_the_configured_origin(self):
        with override_settings(SITE_URL="https://rakho.example.com"):
            html = landing_page()
            sitemap = __import__("config.urls", fromlist=["sitemap_xml"]).sitemap_xml(RequestFactory().get("/sitemap.xml")).content.decode()
            robots = __import__("config.urls", fromlist=["robots_txt"]).robots_txt(RequestFactory().get("/robots.txt")).content.decode()

        self.assertIn('<link rel="canonical" href="https://rakho.example.com/">', html)
        self.assertNotIn("rakho-api.onrender.com", html)
        self.assertIn("<loc>https://rakho.example.com/</loc>", sitemap)
        self.assertIn("https://rakho.example.com/sitemap.xml", robots)


class InstallLinkTests(TestCase):
    """The app is always on the page; the download is only there when it works.

    The Android app is the product — the web page only sells it — so the page
    must name it whether or not a listing exists: a landing page that says
    nothing about the app reads as if there were no app. What must never
    happen is a download button pointing at a draft, a mistyped package id or
    a lookalike host, because that is a 404 on the one tap meant to install the
    product. So the band renders in both states and ``PLAY_STORE_URL`` decides
    only whether its action is the Play button plus the schema ``downloadUrl``,
    or the contact that can deliver the app by hand.
    """

    LISTING = "https://play.google.com/store/apps/details?id=com.lipon.rakho"
    CLOSED_TEST = "https://play.google.com/apps/testing/com.lipon.rakho"

    def test_the_app_is_named_before_the_listing_is_published(self):
        """The badge is shown, but it is not a link and it says so."""
        html = landing_page()
        band = html.split('class="install"')[1]
        self.assertIn("অ্যান্ড্রয়েড অ্যাপ", band)
        self.assertIn('class="play-badge soon"', band)
        self.assertIn("শীঘ্রই আসছে", band)
        # Drawn, never linked: nothing in the band can 404.
        self.assertNotRegex(band, r"<a[^>]+play-badge")
        self.assertNotIn("play.google.com", html)
        self.assertNotIn("downloadUrl", _structured_data(html, "SoftwareApplication"))
        # The action that does work today is still one tap away, and the nav
        # link has a real section to land on because the band always renders.
        self.assertIn('href="#get"', band)
        self.assertIn('href="#app"', html)
        # Pre-launch the real action is the contact that can hand someone the
        # app, not a form that hands out an API key the Firebase build has no
        # field for. The closing section must therefore exist and carry no form.
        self.assertIn('id="get"', html)
        self.assertNotIn('id="signupForm"', html)

    def test_the_action_and_the_schema_follow_one_setting(self):
        with override_settings(PLAY_STORE_URL=self.LISTING):
            html = landing_page()
        # The badge itself is the button, and the coming-soon label is gone.
        self.assertIn(f'class="play-badge" href="{self.LISTING}"', html)
        self.assertNotIn("শীঘ্রই আসছে", html)
        self.assertIn('href="#app"', html)
        self.assertEqual(_structured_data(html, "SoftwareApplication")["downloadUrl"], self.LISTING)

    def test_a_closed_or_internal_test_link_is_a_real_install_path(self):
        """An unreleased app has no public listing, only a tester link.

        Refusing these shapes would leave the one audience that can install the
        app today — actual testers — without a button, which is how a working
        install path gets mistaken for a missing one.
        """
        for link in (
            self.CLOSED_TEST,
            "https://play.google.com/apps/internaltest/4700000000000000000",
        ):
            with self.subTest(link=link):
                with override_settings(PLAY_STORE_URL=link):
                    html = landing_page()
                self.assertIn(f'href="{link}"', html)
                self.assertEqual(_structured_data(html, "SoftwareApplication")["downloadUrl"], link)

    def test_the_install_link_leaves_the_page_safely(self):
        """A new tab without noopener hands the opened page a window.opener."""
        with override_settings(PLAY_STORE_URL=self.LISTING):
            html = landing_page()
        band = html.split('class="install"')[1]
        self.assertIn('target="_blank"', band)
        self.assertIn('rel="noopener"', band)

    def test_an_unusable_setting_is_ignored_rather_than_shipped(self):
        """A typo must fail closed: it falls back to the key, not to a 404."""
        for value in (
            "",
            "   ",
            "play.google.com/store/apps/details?id=x",
            "http://play.google.com/store/apps/details?id=x",
            "https://example.com/app",
            "javascript:alert(1)",
            "https://play.google.com.evil.com/store/apps/x",
        ):
            with self.subTest(value=value):
                with override_settings(PLAY_STORE_URL=value):
                    html = landing_page()
                self.assertNotRegex(html, r"<a[^>]+play-badge")
                self.assertIn('class="play-badge soon"', html)
                self.assertNotIn("downloadUrl", _structured_data(html, "SoftwareApplication"))
                # The band is still there, offering the key instead.
                band = html.split('class="install"')[1]
                self.assertIn('href="#get"', band)
                if value.strip():
                    self.assertNotIn(value, html)

    def test_the_listing_url_cannot_break_out_of_its_attribute(self):
        """The value is configuration, but it is rendered, never trusted.

        Escaping is what keeps a quote in the setting from closing the href and
        leaving an event handler behind; the JSON-LD must survive it too, or
        one stray character disables every rich result on the page.
        """
        hostile = 'https://play.google.com/store/apps/details?id=x"onload="alert(1)'
        with override_settings(PLAY_STORE_URL=hostile):
            html = landing_page()
        self.assertNotIn('onload="alert(1)"', html)
        self.assertIn("&quot;", html)
        self.assertEqual(_structured_data(html, "SoftwareApplication")["downloadUrl"], hostile)

    def test_no_placeholder_survives_rendering(self):
        """An un-replaced marker is a visible page bug, both ways round."""
        for configured in ("", self.LISTING):
            with self.subTest(listing=configured):
                with override_settings(PLAY_STORE_URL=configured):
                    self.assertNotIn("__", landing_page())
