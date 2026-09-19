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
from datetime import datetime, time
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from inventory.landing import bengali_digits, landing_page, pro_price_bdt
from inventory.models import CatalogMedicine, Pharmacy, SignupRequest


def _markup(html):
    """The rendered page with its inline <style>/<script> removed.

    The console ships its CSS inline, and the stylesheet names the same classes
    the markup uses — ``.rk-chart-dot`` appears three times in the <style> block
    — so a raw substring or class count on the whole document counts the CSS as
    markup. That is how an assertion like "no chart is rendered" passes while a
    chart is very much rendered.
    """
    body = re.sub(r"<style\b.*?</style>", "", html, flags=re.S)
    return re.sub(r"<script\b.*?</script>", "", body, flags=re.S)


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

    def test_the_right_column_is_only_the_activity_log(self):
        """It ran three panels: attention, history, shortcuts. Now it runs one.

        The attention items restated numbers that are already on the page — a
        payment to verify is the amber card *and* the header badge — so the
        panel read as the console arguing with itself.
        """
        markup = _markup(self._html())
        self.assertIn("Recent activity", markup)
        self.assertNotIn("Needs attention", markup)
        self.assertNotIn("Shortcuts", markup)
        # The stock empty-history text must not leak back in either.
        self.assertNotIn("None available", markup)

    def test_activity_badge_names_the_action_rather_than_hiding_it(self):
        """"Deleted: Kussdus Pharma" is what a log entry should read as.

        The verb used to be a visually-hidden span, so the visible row was a
        bare object name and a reader could not tell an add from a delete.
        """
        LogEntry.objects.log_action(
            user_id=self.owner.pk,
            content_type_id=ContentType.objects.get_for_model(Pharmacy).pk,
            object_id="1", object_repr="Kussdus Pharma",
            action_flag=DELETION)
        html = self._html()
        self.assertIn("rk-log-verb delete", html)
        self.assertIn("Kussdus Pharma", html)

    def test_activity_subjects_are_escaped_not_rendered(self):
        """A shop named like a tag must read as text, never execute.

        object_repr is whatever a shop called itself, so it is attacker-shaped
        input rendered in a staff-only page. Django escapes ``{{ }}`` by
        default; this pins that nobody later reaches for ``|safe`` to "fix" the
        angle brackets someone mistook for a rendering bug.
        """
        LogEntry.objects.log_action(
            user_id=self.owner.pk,
            content_type_id=ContentType.objects.get_for_model(Pharmacy).pk,
            object_id="1", object_repr="<script>alert(2)</script>",
            action_flag=DELETION)
        html = self._html()
        self.assertNotIn("<script>alert(2)</script>", html)
        self.assertIn("&lt;script&gt;alert(2)&lt;/script&gt;", html)

    def test_every_stat_card_links_to_the_list_it_counts(self):
        """The cards are the navigation, so a dead card is a dead end.

        Replacing the "Quick actions" panel with links on the cards removed a
        whole duplicated column; a card that stopped being a link would leave
        that number unreachable instead.
        """
        html = self._html()
        self.assertEqual(html.count('<a class="rk-card'), 6)
        for target in ("inventory/pharmacy/", "inventory/subscription/",
                       "inventory/signuprequest/", "inventory/pharmacyapikey/"):
            with self.subTest(target=target):
                self.assertIn(target, html)

    def test_the_console_has_no_model_browser(self):
        """"Manage data" listed all thirteen tables with an "Add" pill each.

        That wall is what made a one-person console unreadable, and it must not
        creep back in. Note there is no ``/add/`` link on this page at all now:
        the numbers are links to *lists*, and the lists have their own Add
        buttons for the models that should have them.
        """
        markup = _markup(self._html())
        self.assertNotIn("Manage data", markup)
        self.assertNotIn("rk-model", markup)
        self.assertNotIn("Quick actions", markup)
        self.assertNotIn("/add/", markup)


class ConsoleChartTests(TestCase):
    """The signup chart must be readable, and must not invent anything.

    A chart is the easiest thing on a dashboard to get quietly wrong: smooth the
    line, round the axis and it looks better while being less true. These tests
    pin the parts a reader checks the shape against — one point per day, an axis
    you can count against, and a summary naming the real peak.
    """

    def setUp(self):
        self.owner = User.objects.create_superuser(
            "owner", "owner@example.com", "pw")
        self.client = Client()
        self.client.force_login(self.owner)

    def _html(self):
        response = self.client.get("/" + settings.ADMIN_URL)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def _signup_on(self, days_ago):
        signup = SignupRequest.objects.create(
            owner_name="Owner", pharmacy_name="Shop",
            lookup_token=SignupRequest.generate_token())
        SignupRequest.objects.filter(pk=signup.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=days_ago))
        return signup

    def test_plots_one_point_per_day_in_the_window(self):
        self._signup_on(0)
        markup = _markup(self._html())
        points = re.search(
            r'class="rk-chart-line" points="([^"]+)"', markup).group(1)
        self.assertEqual(len(points.split()), 14)
        self.assertEqual(markup.count('class="rk-chart-dot'), 14)
        self.assertEqual(markup.count("title="), 14)

    def test_names_the_real_peak_and_total(self):
        for days_ago in (0, 0, 4):
            self._signup_on(days_ago)
        html = self._html()
        today = timezone.localdate().strftime("%d %b")
        self.assertIn("3 in this period", html)
        self.assertIn(f"busiest {today} with 2", html)

    def test_axis_ceiling_rounds_up_to_a_countable_number(self):
        """A peak of 3 must not produce ticks reading 3 / 1.5 / 0."""
        for _ in range(3):
            self._signup_on(0)
        html = self._html()
        self.assertIn('top:0%">4<', html)
        self.assertIn('top:50%">2<', html)
        self.assertIn('top:100%">0<', html)

    def test_a_fresh_install_gets_an_explanation_not_an_empty_frame(self):
        markup = _markup(self._html())
        self.assertIn("nothing to plot yet", markup)
        self.assertNotIn("rk-chart-line", markup)
        self.assertNotIn("rk-chart-dot", markup)

    def test_the_chart_links_to_the_catalogue_it_cannot_otherwise_reach(self):
        """The dashboard has no model sidebar, so this link is the only way in."""
        self.assertIn(
            f"/{settings.ADMIN_URL}inventory/catalogmedicine/", self._html())

    def test_counts_land_on_the_dhaka_day_not_the_utc_one(self):
        """00:30 in Dhaka is 18:30 *yesterday* in UTC.

        The axis is labelled in local dates, so bucketing the rows in UTC put
        that signup under yesterday's column — a chart that visibly disagrees
        with the signups list it links to, and with the day the shop actually
        signed up.
        """
        just_after_midnight = timezone.make_aware(
            datetime.combine(timezone.localdate(), time(0, 30)),
            timezone.get_current_timezone())
        signup = self._signup_on(0)
        SignupRequest.objects.filter(pk=signup.pk).update(
            created_at=just_after_midnight)

        titles = re.findall(r'title="([^"]+)"', self._html())
        today = timezone.localdate().strftime("%d %b")
        yesterday = (timezone.localdate()
                     - timezone.timedelta(days=1)).strftime("%d %b")
        by_label = {title[:6]: title for title in titles}
        self.assertIn("1 signup", by_label[today])
        self.assertIn("0 signups", by_label[yesterday])


class ConsoleCatalogueTests(TestCase):
    """The national catalogue is dataset-owned, so the console must not edit it.

    The console used to list "Add catalog medicine" and a change form built from
    the raw dataset columns (source brand id, slug, package container…). A row
    typed by hand there is a record the next import cannot reconcile, and it
    silently forks the owner's copy from the one every install searches. The
    console therefore browses the catalogue read-only and re-imports it instead.
    """

    def setUp(self):
        self.owner = User.objects.create_superuser(
            "owner", "owner@example.com", "pw")
        self.client = Client()
        self.client.force_login(self.owner)
        self.changelist = f"/{settings.ADMIN_URL}inventory/catalogmedicine/"
        self.import_url = self.changelist + "import/"

    @staticmethod
    def _prose(html):
        """Rendered text, so source line wrapping cannot break an assertion."""
        return re.sub(r"\s+", " ", html)

    def test_no_hand_entry_form_is_reachable(self):
        response = self.client.get(self.changelist + "add/")
        self.assertEqual(response.status_code, 403)

    def test_dashboard_offers_no_add_link_for_the_catalogue(self):
        html = self.client.get("/" + settings.ADMIN_URL).content.decode()
        self.assertNotIn("inventory/catalogmedicine/add/", html)

    def test_changelist_explains_where_the_rows_come_from(self):
        prose = self._prose(self.client.get(self.changelist).content.decode())
        self.assertIn("Imported data", prose)
        self.assertIn("Assorted Medicine Dataset of Bangladesh", prose)

    def test_changelist_offers_a_re_import_button(self):
        """The button has to be *rendered*, not merely registered.

        Django only draws the changelist action dropdown when the user may
        change the model, so an `actions` entry on this read-only admin was
        reachable by POST but invisible — a refresh nobody could click.
        """
        html = self.client.get(self.changelist).content.decode()
        self.assertIn(self.import_url, html)
        self.assertIn("Re-import from dataset", html)
        self.assertIn('method="post"', html)

    def test_a_record_can_still_be_read(self):
        """Read-only must not mean unreadable: the owner still inspects rows.

        A page the owner cannot open would be reported as another broken page,
        so the detail view stays, minus any way to save it.
        """
        medicine = CatalogMedicine.objects.create(
            brand_name="Napa", source_brand_id=101)
        html = self.client.get(
            f"{self.changelist}{medicine.pk}/change/").content.decode()
        self.assertIn("Napa", html)
        self.assertNotIn('name="_save"', html)

    def test_changelist_rows_link_to_the_record(self):
        medicine = CatalogMedicine.objects.create(
            brand_name="Napa", source_brand_id=101)
        html = self.client.get(self.changelist).content.decode()
        self.assertIn(f"{self.changelist}{medicine.pk}/change/", html)

    def test_a_record_cannot_be_edited(self):
        medicine = CatalogMedicine.objects.create(
            brand_name="Napa", source_brand_id=101)
        response = self.client.post(
            f"{self.changelist}{medicine.pk}/change/",
            {"brand_name": "Renamed", "source_brand_id": 101})
        self.assertEqual(response.status_code, 403)
        medicine.refresh_from_db()
        self.assertEqual(medicine.brand_name, "Napa")

    def test_re_import_upserts_without_clearing_live_rows(self):
        CatalogMedicine.objects.create(brand_name="Seclo", source_brand_id=7)
        with mock.patch("inventory.admin.call_command") as command:
            response = self.client.post(self.import_url)
        self.assertRedirects(response, self.changelist)
        command.assert_called_once_with(
            "import_bangladesh_catalog", "--download", verbosity=0)
        # The live row survives a refresh — the import upserts, never truncates.
        self.assertTrue(CatalogMedicine.objects.filter(source_brand_id=7).exists())

    def test_the_import_cannot_be_triggered_by_a_plain_link(self):
        """A GET must not run a table-wide import.

        This URL is a normal part of the console, so a prefetcher, a crawler or
        an <img src> could otherwise kick off a full re-import.
        """
        with mock.patch("inventory.admin.call_command") as command:
            response = self.client.get(self.import_url)
        self.assertEqual(response.status_code, 405)
        command.assert_not_called()

    def test_a_failed_import_reports_instead_of_wiping_the_catalogue(self):
        from django.core.management import CommandError

        CatalogMedicine.objects.create(brand_name="Seclo", source_brand_id=7)
        with mock.patch("inventory.admin.call_command",
                        side_effect=CommandError("offline")):
            response = self.client.post(self.import_url, follow=True)
        self.assertEqual(CatalogMedicine.objects.count(), 1)
        self.assertIn("Import failed", response.content.decode())

    def test_the_import_is_refused_to_anonymous_visitors(self):
        self.client.logout()
        response = self.client.post(self.import_url)
        self.assertNotEqual(response.status_code, 200)
        self.assertIn(response.status_code, (302, 403))


class ConsoleSurfaceTests(TestCase):
    """The console is five entries, and that is the whole specification.

    Nine more models used to be registered — medicines, batches, sales and the
    ledgers behind them — every one of them written by the Android app through
    the API. Two things went wrong with that. The console became a wall of
    thirteen tables to scroll, and half of them offered an "Add" form for rows
    no person should ever create: a hand-typed sale line contradicts its own
    batch allocations, and a hand-typed stock movement has no batch behind it.

    So the assertion here is a closed set, in both directions. Adding a model
    back is a decision, not an accident.
    """

    CONSOLE = ("pharmacy", "pharmacyapikey", "subscription", "signuprequest",
               "catalogmedicine")
    APP_OWNED = ("medicine", "batch", "sale", "saleline", "saleallocation",
                 "stockmovement", "playpurchaseevent", "signupdailycount")

    def setUp(self):
        self.owner = User.objects.create_superuser(
            "owner", "owner@example.com", "pw")
        self.client = Client()
        self.client.force_login(self.owner)

    def _url(self, model):
        return f"/{settings.ADMIN_URL}inventory/{model}/"

    def test_the_console_lists_exactly_these_models(self):
        html = self.client.get("/" + settings.ADMIN_URL).content.decode()
        for model in self.CONSOLE:
            with self.subTest(model=model):
                self.assertIn(f"inventory/{model}/", html)
        for model in self.APP_OWNED:
            with self.subTest(model=model):
                self.assertNotIn(f"inventory/{model}/", html)

    def test_records_the_app_owns_are_not_in_the_console_at_all(self):
        for model in self.APP_OWNED:
            with self.subTest(model=model):
                self.assertEqual(self.client.get(self._url(model)).status_code, 404)

    def test_the_owners_own_levers_stay_reachable(self):
        """Minimal must not mean the console lost the things it is for."""
        for model in ("pharmacy", "subscription", "signuprequest",
                      "pharmacyapikey"):
            with self.subTest(model=model):
                self.assertEqual(  # the list
                    self.client.get(self._url(model)).status_code, 200)
                self.assertEqual(  # and its add form
                    self.client.get(self._url(model) + "add/").status_code, 200)

    def test_no_page_in_the_console_offers_to_add_app_owned_data(self):
        pages = ["/" + settings.ADMIN_URL] + [self._url(m) for m in self.CONSOLE]
        for url in pages:
            html = self.client.get(url).content.decode()
            for model in self.APP_OWNED:
                with self.subTest(url=url, model=model):
                    self.assertNotIn(f"inventory/{model}/add/", html)


class NoTemplateMarkerLeakTests(TestCase):
    """A comment that does not render as a comment is a visible page bug.

    Django's ``{# ... #}`` comment is single-line only; a wrapped one spills its
    own prose onto the page. One did exactly that at the top of the owner
    console, and nothing caught it because no test ever looked at rendered admin
    chrome for stray markup.
    """

    def test_no_project_template_wraps_a_hash_comment(self):
        template_dir = Path(settings.BASE_DIR) / "templates"
        for path in template_dir.rglob("*.html"):
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1):
                if "{#" in line:
                    with self.subTest(template=path.name, line=number):
                        self.assertIn("#}", line.split("{#", 1)[1])

    def test_the_landing_page_ships_no_stray_control_characters(self):
        """A CSS escape written with one backslash too few becomes a control byte.

        The FAQ's open marker asked CSS for an en dash in a Python string, so
        Python consumed the escape first and the browser received a control
        character followed by a bare "3": opening a question swapped its "+"
        for a literal 3. Nothing failed — the page just looked broken — so pin
        the whole document rather than that one rule.
        """
        html = landing_page()
        self.assertNotRegex(html, r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
                            )
        self.assertIn('content:"\\2013"', html)

    def test_rendered_console_pages_contain_no_template_markers(self):
        owner = User.objects.create_superuser("owner", "owner@example.com", "pw")
        client = Client()
        client.force_login(owner)
        pages = (
            "/" + settings.ADMIN_URL,
            f"/{settings.ADMIN_URL}inventory/catalogmedicine/",
            f"/{settings.ADMIN_URL}inventory/signuprequest/",
        )
        for url in pages:
            html = client.get(url).content.decode()
            with self.subTest(url=url):
                self.assertNotIn("{#", html)
                self.assertNotIn("{%", html)
                self.assertNotIn("{{ ", html)


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
