"""Tests for the owner's tier and key controls in the console.

The console is where the owner flips a pharmacy between FREE and the paid
tiers, rotates or revokes the key that lets a device in, and sets how long any
of it lasts. Every lever added here is reachable from the list page itself —
one click, no hunting — and each POST endpoint refuses GET so no prefetcher or
crawler can fire it.
"""
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from inventory.models import Pharmacy, PharmacyApiKey, Subscription
from inventory.admin import DURATION_CHOICES, _duration_end, _key_expiry


class TierAndDurationHelpersTests(TestCase):
    def test_duration_end_map(self):
        today = timezone.localdate()
        self.assertEqual(_duration_end("1m"), today + timedelta(days=30))
        self.assertEqual(_duration_end("3m"), today + timedelta(days=91))
        self.assertEqual(_duration_end("6m"), today + timedelta(days=182))
        self.assertEqual(_duration_end("1y"), today + timedelta(days=365))

    def test_lifetime_has_no_end(self):
        self.assertIsNone(_duration_end("lifetime"))

    def test_custom_end_uses_the_given_date(self):
        end = timezone.localdate() + timedelta(days=45)
        self.assertEqual(_duration_end("custom", end.isoformat()), end)

    def test_custom_garbage_falls_back_to_one_month(self):
        self.assertEqual(
            _duration_end("custom", "not-a-date"),
            timezone.localdate() + timedelta(days=30),
        )

    def test_key_expiry_spans(self):
        now = timezone.now()
        self.assertAlmostEqual(
            _key_expiry("6m"), now + timedelta(days=182), delta=timedelta(seconds=5))
        self.assertIsNone(_key_expiry("lifetime"))

    def test_key_expiry_custom_accepts_a_bare_date(self):
        end_date = timezone.localdate() + timedelta(days=10)
        end = _key_expiry("custom", end_date.isoformat())
        self.assertEqual(end.date(), end_date)

    def test_every_duration_choice_resolves(self):
        for value, _name in DURATION_CHOICES:
            with self.subTest(duration=value):
                _duration_end(value, "2027-01-01")
                _key_expiry(value, "2027-01-01")


class AdminFixtureMixin:
    def setUp(self):
        from django.contrib.auth.models import User

        self.owner = User.objects.create_superuser("owner", "owner@example.com", "pw")
        self.client = Client()
        self.client.force_login(self.owner)
        self.pharmacy = Pharmacy.objects.create(name="Test Pharma")
        self.api_key, self.raw_key = PharmacyApiKey.create_key(self.pharmacy)
        self.subscription = Subscription.for_pharmacy(self.pharmacy)


class PharmacyApiKeyControlsTests(AdminFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.list_url = reverse("admin:inventory_pharmacyapikey_changelist")
        self.rotate_url = reverse(
            "admin:inventory_pharmacyapikey_rotate", args=[self.api_key.pk])
        self.revoke_url = reverse(
            "admin:inventory_pharmacyapikey_revoke", args=[self.api_key.pk])
        self.restore_url = reverse(
            "admin:inventory_pharmacyapikey_restore", args=[self.api_key.pk])

    def test_changelist_shows_tier_and_action_buttons(self):
        html = self.client.get(self.list_url).content.decode()
        self.assertIn("rk-tier", html)
        self.assertIn(">FREE<", html)  # badge, not a blank cell
        self.assertIn("Rotate", html)
        self.assertIn("Revoke", html)

    def test_rotate_get_renders_duration_form(self):
        response = self.client.get(self.rotate_url)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for name in ("1 month", "3 months", "6 months", "1 year",
                     "No expiry (lifetime)", "Custom end date"):
            with self.subTest(choice=name):
                self.assertIn(name, body)

    def test_rotate_issues_a_new_live_key_and_revokes_the_old(self):
        response = self.client.post(self.rotate_url, {"duration": "1m"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.api_key.refresh_from_db()
        self.assertIsNotNone(self.api_key.revoked_at, "old key must be revoked")
        new_key = PharmacyApiKey.objects.filter(revoked_at__isnull=True).get()
        self.assertEqual(new_key.pharmacy, self.pharmacy)
        self.assertAlmostEqual(
            new_key.expires_at, timezone.now() + timedelta(days=30),
            delta=timedelta(seconds=5))
        self.assertIn(self.raw_key[:11], response.content.decode())
        self.assertNotEqual(new_key.key_hash, PharmacyApiKey.hash_key(self.raw_key))

    def test_rotate_lifetime_never_expires(self):
        self.client.post(self.rotate_url, {"duration": "lifetime"})
        new_key = PharmacyApiKey.objects.filter(revoked_at__isnull=True).get()
        self.assertIsNone(new_key.expires_at)

    def test_rotate_with_custom_date(self):
        end = timezone.localdate() + timedelta(days=17)
        self.client.post(self.rotate_url, {"duration": "custom",
                                           "custom_expires_at": end.isoformat()})
        new_key = PharmacyApiKey.objects.filter(revoked_at__isnull=True).get()
        # SQLite/Postgres return UTC; compare on the project's own calendar.
        self.assertEqual(timezone.localtime(new_key.expires_at).date(), end)

    def test_revoke_cuts_access_then_restore_brings_it_back(self):
        self.client.post(self.revoke_url, follow=True)
        self.api_key.refresh_from_db()
        self.assertIsNotNone(self.api_key.revoked_at)
        # The row now offers Restore instead of Revoke.
        html = self.client.get(self.list_url).content.decode()
        self.assertIn("Restore", html)
        self.client.post(self.restore_url, follow=True)
        self.api_key.refresh_from_db()
        self.assertIsNone(self.api_key.revoked_at)

    def test_restore_clears_a_past_expiry(self):
        PharmacyApiKey.objects.filter(pk=self.api_key.pk).update(
            revoked_at=timezone.now(),
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.client.post(self.restore_url)
        self.api_key.refresh_from_db()
        self.assertIsNone(self.api_key.revoked_at)
        self.assertIsNone(self.api_key.expires_at)

    def test_mutating_endpoints_refuse_get(self):
        for url in (self.revoke_url, self.restore_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertIn(response.status_code, (400, 403, 405))

    def test_actions_require_admin(self):
        self.client.logout()
        for url in (self.revoke_url, self.restore_url):
            response = self.client.post(url)
            self.assertIn(response.status_code, (302, 403))

    def test_expired_key_is_not_live(self):
        PharmacyApiKey.objects.filter(pk=self.api_key.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1))
        self.api_key.refresh_from_db()
        self.assertFalse(self.api_key.is_live)

    def test_expired_key_fails_api_authentication(self):
        """Auth honours the expiry the console set, not just revocation."""
        from rest_framework.exceptions import AuthenticationFailed
        from inventory.auth import PharmacyApiKeyAuthentication

        PharmacyApiKey.objects.filter(pk=self.api_key.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1))
        self.api_key.refresh_from_db()
        request = type("R", (), {"headers": {"X-Pharmacy-Key": self.raw_key}})()
        with self.assertRaises(AuthenticationFailed):
            PharmacyApiKeyAuthentication().authenticate(request)

    def test_tier_column_reads_the_real_entitlement(self):
        self.subscription.plan = Subscription.Plan.PRO
        self.subscription.valid_until = timezone.localdate() + timedelta(days=5)
        self.subscription.save()
        html = self.client.get(self.list_url).content.decode()
        self.assertIn("rk-paid\">PAID<", html)

    def test_expired_subscription_shows_free(self):
        self.subscription.plan = Subscription.Plan.PRO
        self.subscription.valid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save()
        html = self.client.get(self.list_url).content.decode()
        self.assertIn(">FREE<", html)


class SubscriptionTierControlsTests(AdminFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.list_url = reverse("admin:inventory_subscription_changelist")
        self.free_url = reverse(
            "admin:inventory_subscription_set_free", args=[self.subscription.pk])
        self.pro_url = reverse(
            "admin:inventory_subscription_set_pro", args=[self.subscription.pk])

    def test_changelist_has_row_controls(self):
        html = self.client.get(self.list_url).content.decode()
        self.assertIn("Set FREE", html)
        self.assertIn("Set PAID", html)

    def test_change_plan_get_renders_duration_choices(self):
        body = self.client.get(self.pro_url).content.decode()
        for name in ("1 month", "3 months", "6 months", "1 year",
                     "No expiry (lifetime)", "Custom end date"):
            with self.subTest(choice=name):
                self.assertIn(name, body)

    def test_set_paid_six_months_keeps_pro_plan(self):
        """Two plans only: PAID always means the Pro plan."""
        self.client.post(self.pro_url, {"duration": "6m"})
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, Subscription.Plan.PRO)
        self.assertEqual(self.subscription.source, Subscription.Source.MANUAL)
        self.assertEqual(
            self.subscription.valid_until,
            timezone.localdate() + timedelta(days=182))
        self.assertTrue(self.subscription.is_active)

    def test_set_paid_ignores_a_client_supplied_tier(self):
        """There is no tier dropdown to abuse; extra fields are ignored."""
        self.client.post(self.pro_url, {"plan": "business", "duration": "1y"})
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, Subscription.Plan.PRO)
        self.assertTrue(self.subscription.is_active)

    def test_custom_end_date(self):
        end = timezone.localdate() + timedelta(days=40)
        self.client.post(self.pro_url, {"plan": "pro", "duration": "custom",
                                        "custom_until": end.isoformat()})
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.valid_until, end)

    def test_lifetime_sets_no_expiry(self):
        self.client.post(self.pro_url, {"plan": "pro", "duration": "lifetime"})
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.valid_until)
        self.assertTrue(self.subscription.is_active)

    def test_to_free_cuts_paid_features(self):
        self.client.post(self.pro_url, {"plan": "pro", "duration": "1m"})
        self.client.post(self.free_url, follow=True)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, Subscription.Plan.FREE)
        self.assertIsNone(self.subscription.valid_until)
        self.assertFalse(self.subscription.is_active)
        self.assertEqual(self.subscription.effective_plan, Subscription.Plan.FREE)

    def test_change_plan_page_offers_durations_not_tiers(self):
        """The form must show time choices, never a tier list."""
        body = self.client.get(self.pro_url).content.decode()
        for name in ("1 month", "6 months", "1 year", "Custom end date"):
            with self.subTest(choice=name):
                self.assertIn(name, body)
        self.assertNotIn("Pro Plus", body)
        self.assertNotIn("Business</label>", body)

    def test_no_auto_renewal_is_implied(self):
        """Manual payments only — the page must say so, plainly."""
        body = self.client.get(self.pro_url).content.decode()
        self.assertIn("nothing auto-renews", body.lower())

    def test_time_left_column_reports_lapse(self):
        """A lapsed paid row says so in words, not just a date."""
        Subscription.objects.filter(pk=self.subscription.pk).update(
            plan=Subscription.Plan.PRO,
            valid_until=timezone.localdate() - timedelta(days=4))
        html = self.client.get(self.list_url).content.decode()
        self.assertIn("lapsed 4 d ago", html)

    def test_changelist_shows_paid_badge(self):
        Subscription.objects.filter(pk=self.subscription.pk).update(
            plan=Subscription.Plan.PRO,
            valid_until=timezone.localdate() + timedelta(days=3))
        html = self.client.get(self.list_url).content.decode()
        self.assertIn("rk-tier rk-paid\">PAID<", html)
        self.assertIn("Set FREE", html)
        self.assertIn("Set PAID", html)

    def test_mutating_endpoints_refuse_get(self):
        for url in (self.free_url, self.pro_url):
            with self.subTest(url=url):
                # The plan form is a real GET page; only set-free must refuse.
                response = self.client.get(url)
                if url == self.free_url:
                    self.assertIn(response.status_code, (400, 403, 405))

    def test_comp_actions_require_admin(self):
        self.client.logout()
        self.assertIn(self.client.post(self.pro_url, {"duration": "1m"}).status_code,
                      (302, 403))

    def test_bulk_set_paid_actions(self):
        for action, days in (("set_paid_1m", 30), ("set_paid_6m", 182),
                             ("set_paid_1y", 365)):
            with self.subTest(action=action):
                Subscription.objects.filter(pk=self.subscription.pk).update(
                    plan=Subscription.Plan.FREE, valid_until=None)
                self.client.post(
                    self.list_url,
                    {"action": action,
                     "_selected_action": str(self.subscription.pk)},
                    follow=True)
                self.subscription.refresh_from_db()
                self.assertEqual(self.subscription.plan, Subscription.Plan.PRO)
                self.assertEqual(
                    self.subscription.valid_until,
                    timezone.localdate() + timedelta(days=days))

    def test_downgrade_to_free_bulk_action(self):
        Subscription.objects.filter(pk=self.subscription.pk).update(
            plan=Subscription.Plan.PRO, valid_until=timezone.localdate() + timedelta(days=3),
            source=Subscription.Source.MANUAL)
        self.client.post(
            self.list_url,
            {"action": "downgrade_free",
             "_selected_action": str(self.subscription.pk)},
            follow=True)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, Subscription.Plan.FREE)

    def test_play_token_survives_a_play_row_downgrade(self):
        """A Play-managed row keeps its token so Play can re-verify it later.

        Downgrading still cuts access immediately — the plan is FREE and
        effective_plan reports free — but the purchase token is evidence of a
        real Play purchase, so it is never wiped by a console action.
        """
        Subscription.objects.filter(pk=self.subscription.pk).update(
            plan=Subscription.Plan.PRO, valid_until=timezone.localdate() + timedelta(days=3),
            source=Subscription.Source.PLAY, purchase_token="tok", product_id="p")
        self.client.post(
            self.list_url,
            {"action": "downgrade_free",
             "_selected_action": str(self.subscription.pk)},
            follow=True)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, Subscription.Plan.FREE)
        self.assertEqual(self.subscription.effective_plan, Subscription.Plan.FREE)
        self.assertEqual(self.subscription.purchase_token, "tok")


class DashboardSplitTests(AdminFixtureMixin, TestCase):
    def test_dashboard_counts_free_and_paid_split(self):
        from inventory.admin_dashboard import dashboard_stats

        self.subscription.plan = Subscription.Plan.PRO
        self.subscription.valid_until = timezone.localdate() + timedelta(days=2)
        self.subscription.save()
        stats = dashboard_stats()
        self.assertEqual(stats["active_pro"], 1)
        self.assertEqual(stats["free_pharmacies"], 0)

        self.subscription.plan = Subscription.Plan.FREE
        self.subscription.save()
        stats = dashboard_stats()
        self.assertEqual(stats["active_pro"], 0)
        self.assertEqual(stats["free_pharmacies"], 1)

    def test_expired_paid_plan_counts_as_free(self):
        from inventory.admin_dashboard import dashboard_stats

        self.subscription.plan = Subscription.Plan.PRO
        self.subscription.valid_until = timezone.localdate() - timedelta(days=1)
        self.subscription.save()
        stats = dashboard_stats()
        self.assertEqual(stats["active_pro"], 0)
        self.assertEqual(stats["free_pharmacies"], 1)
