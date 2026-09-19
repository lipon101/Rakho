"""Presentation tests for the public landing page and the owner console.

The landing page used to advertise "১৪,০০০+ ওষুধের তালিকা" (14,000+ medicines)
with a catalogue search, while the production catalogue was empty — so the page
promised a feature that silently returned nothing. These tests pin the
invariant that the page states the *real* catalogue size, or none at all.

The console tests pin the layout fixes: the stat grid used `auto-fit`, which
resolved to five columns in the real container and orphaned the sixth card on a
row of its own.
"""
import json
import re
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase

from inventory.landing import bengali_digits, landing_page, pro_price_bdt
from inventory.models import CatalogMedicine


def _structured_data(html):
    """The parsed JSON-LD block. Raises if the block is missing or malformed."""
    match = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    if match is None:
        raise AssertionError("no JSON-LD block found")
    return json.loads(match.group(1))


def _node(data, node_type):
    return next(n for n in data["@graph"] if n["@type"] == node_type)


class LandingSeoTests(TestCase):
    def setUp(self):
        self.html = landing_page()

    def test_carries_canonical_and_social_metadata(self):
        for tag in ('rel="canonical"', "og:url", "og:site_name", "og:locale",
                    "twitter:card", 'name="robots"', "hreflang"):
            with self.subTest(tag=tag):
                self.assertIn(tag, self.html)

    def test_structured_data_is_valid_json(self):
        data = _structured_data(self.html)
        types = {node["@type"] for node in data["@graph"]}
        self.assertEqual(
            types, {"Organization", "SoftwareApplication", "FAQPage"})

    def test_faq_schema_matches_the_visible_faq(self):
        """Google requires marked-up questions to be present on the page."""
        schema = _node(_structured_data(self.html), "FAQPage")["mainEntity"]
        self.assertEqual(len(schema), self.html.count('<details class="qa">'))
        for question in schema:
            with self.subTest(question=question["name"]):
                self.assertIn(question["name"], self.html)

    def test_offers_match_the_prices_shown_on_the_page(self):
        offers = {o["name"]: o for o in
                  _node(_structured_data(self.html),
                        "SoftwareApplication")["offers"]}
        price = pro_price_bdt()
        self.assertEqual(offers["Pro"]["price"], price)
        self.assertEqual(offers["Pro"]["priceCurrency"], "BDT")
        self.assertEqual(offers["ফ্রি"]["price"], 0)
        # The page itself shows the same Pro price, never a hardcoded one.
        self.assertIn(f"৳{bengali_digits(price)}", self.html)


class LandingCatalogueTruthTests(TestCase):
    """The catalogue number must come from the database, never be invented."""

    def test_no_count_is_claimed_when_the_catalogue_is_empty(self):
        self.assertEqual(CatalogMedicine.objects.count(), 0)
        html = landing_page()
        self.assertNotIn("১৪,০০০+", html)
        self.assertIn("নিজের ওষুধ নিজে যোগ করুন", html)

    def test_real_count_is_stated_when_the_catalogue_has_rows(self):
        CatalogMedicine.objects.create(brand_name="Napa")
        CatalogMedicine.objects.create(brand_name="Seclo")
        html = landing_page()
        self.assertIn("2</strong>টি ওষুধ", html)
        self.assertNotIn("১৪,০০০+", html)

    def test_catalogue_card_is_marked_pro_because_the_server_gates_it(self):
        """The card must not read as if catalogue search came with the free tier.

        The endpoint itself is Pro-only, so a free visitor who read the card as
        free would hit a locked feature on their first search.
        """
        CatalogMedicine.objects.create(brand_name="Napa")
        html = landing_page()
        card = html.split('class="card"')[5]
        self.assertIn("pro-tag", card)
        self.assertIn("Pro", card)

    def test_no_pro_tag_when_there_is_no_catalogue_to_sell(self):
        """With an empty catalogue the card describes manual entry, not Pro."""
        html = landing_page()
        catalogue_card = html.split('class="card"')[5]
        self.assertIn("নিজের ওষুধ নিজে যোগ করুন", catalogue_card)
        self.assertNotIn("pro-tag", catalogue_card)

    def test_catalogue_failure_never_breaks_the_page(self):
        with mock.patch("inventory.models.CatalogMedicine.objects") as manager:
            manager.count.side_effect = Exception("database is down")
            html = landing_page()
        self.assertIn("ওষুধের তালিকা", html)
        self.assertNotIn("১৪,০০০+", html)

    def test_still_offers_eight_feature_cards(self):
        self.assertEqual(landing_page().count('class="card"'), 8)

    def test_form_fields_carry_screen_reader_labels(self):
        html = landing_page()
        for field in ("owner", "pharmacy", "whatsapp"):
            with self.subTest(field=field):
                self.assertIn(f'for="{field}"', html)

    def test_form_reports_errors_inline_not_via_alert(self):
        js = landing_page().split("<script>", 1)[1]
        self.assertNotIn("alert(", js)
        self.assertIn("formError", js)


class ConsoleDashboardTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser(
            "owner", "owner@example.com", "pw")
        self.client = Client()
        self.client.force_login(self.owner)
        self.url = "/" + settings.ADMIN_URL

    def _html(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_renders_six_stat_cards(self):
        self.assertEqual(self._html().count('class="rk-card'), 6)

    def test_stat_grid_uses_fixed_columns_rather_than_auto_fit(self):
        """auto-fit gave five columns in the real container, orphaning one."""
        html = self._html()
        self.assertIn("repeat(3, minmax(0, 1fr))", html)
        self.assertNotIn("grid-template-columns:repeat(auto-fit, minmax(180px", html)

    def test_empty_catalogue_is_surfaced_as_attention(self):
        self.assertIn("catalogue is empty", self._html())

    def test_attention_clears_once_the_catalogue_has_rows(self):
        CatalogMedicine.objects.create(brand_name="Napa")
        self.assertNotIn("catalogue is empty", self._html())

    def test_chart_shows_an_empty_state_when_there_are_no_signups(self):
        self.assertIn("rk-chart-empty", self._html())

    def test_sidebar_offers_shortcuts_and_hides_empty_history(self):
        html = self._html()
        self.assertIn("Shortcuts", html)
        self.assertIn("Public landing page", html)
        # With no admin history the stock "None available" box must not render.
        self.assertNotIn("None available", html)

    def test_model_cards_do_not_truncate_names(self):
        """Long labels were cut to "Play purchase ev..." by an ellipsis."""
        html = self._html()
        self.assertNotIn("text-overflow:ellipsis;white-space:nowrap", html)


class RobotsAndSitemapTests(TestCase):
    def test_robots_blocks_the_console_api_and_private_pay_pages(self):
        body = __import__("config.urls", fromlist=["robots_txt"]).robots_txt(
            RequestFactory().get("/robots.txt")).content.decode()
        self.assertIn(f"Disallow: /{settings.ADMIN_URL}", body)
        self.assertIn("Disallow: /api/", body)
        self.assertIn("Disallow: /pay/", body)
        self.assertIn("Disallow: /app/", body)
        self.assertIn("Sitemap:", body)

    def test_sitemap_lists_only_public_pages(self):
        body = __import__("config.urls", fromlist=["sitemap_xml"]).sitemap_xml(
            RequestFactory().get("/sitemap.xml")).content.decode()
        self.assertIn(f"{settings.SITE_URL}/</loc>", body)
        self.assertNotIn("/pay/", body)
        self.assertNotIn(f"/{settings.ADMIN_URL}", body)

    def test_sitemap_stops_promoting_the_web_app(self):
        """Customers use the Android app; the web is for landing, pay and keys.

        The SPA still answers at /app/, but inviting search engines to index it
        put a second, competing page in front of the page that sells.
        """
        body = __import__("config.urls", fromlist=["sitemap_xml"]).sitemap_xml(
            RequestFactory().get("/sitemap.xml")).content.decode()
        self.assertNotIn("/app/", body)
        self.assertIn(f"{settings.SITE_URL}/terms/", body)
