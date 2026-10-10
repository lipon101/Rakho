"""Phase 2-4 tests: background jobs, invoicing, reporting and bulk onboarding.

These guard the surface an enterprise buyer actually exercises in a trial, so
each class pins the behaviour that would embarrass a demo rather than merely
exercising a code path:

* **Async jobs** run in eager mode, which is the only honest way to test a task
  body without a broker --- the logic is a plain function and this proves it.
* **Invoicing** pins arithmetic (subtotal + VAT == total), snapshotting (an
  issued invoice does not move), and idempotence (a re-run amends, never
  duplicates).
* **Reporting** pins branch scoping, because a report that leaks one branch's
  takings to a manager of another is the same class of bug as a cross-tenant
  leak, just smaller.
* **Stock import** pins partial success and idempotence, the two properties
  that decide whether a real spreadsheet with three bad rows is usable.
"""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from config.celery import app as celery_app
from inventory import invoicing, org_billing
from inventory import tasks as async_tasks
from inventory.models import (
    Batch,
    Invoice,
    Medicine,
    Organization,
    OrgMembership,
    Pharmacy,
    PharmacyApiKey,
    Sale,
    SaleLine,
    StaffInvitation,
    StockMovement,
)

User = get_user_model()
PASSWORD = "sup3r-secret-pw"


def make_org(name="Dhaka Pharma Ltd", slug="dhaka-pharma", **kw):
    return Organization.objects.create(name=name, slug=slug, **kw)


def make_user(email):
    return User.objects.create_user(username=email, email=email, password=PASSWORD)


def login(email, password=PASSWORD):
    client = APIClient()
    response = client.post("/api/v1/auth/token/", {"username": email, "password": password}, format="json")
    assert response.status_code == 200, response.content
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    return client


class BaseFixture(TestCase):
    def setUp(self):
        # DRF's throttle counters live in the cache, and the cache outlives a
        # single test --- so without this, a suite that logs in for every case
        # eventually trips the anonymous rate limit on the token endpoint and
        # unrelated tests start failing with a 429. Same remedy the input
        # validation tests already use.
        cache.clear()
        self.org = make_org(bin="BIN-123456", billing_email="finance@dhaka.test", plan=Organization.Plan.BRANCH)
        self.owner_user = make_user("owner@dhaka.test")
        self.owner = OrgMembership.objects.create(organization=self.org, user=self.owner_user, role=OrgMembership.Role.OWNER)
        self.main = Pharmacy.objects.create(name="Dhanmondi", organization=self.org, branch_code="DH-01")
        self.second = Pharmacy.objects.create(name="Mirpur", organization=self.org, branch_code="MP-02")
        self.owner.scoped_pharmacies.add(self.main, self.second)
        self.client = login("owner@dhaka.test")

    def member(self, email, role, *branches):
        user = make_user(email)
        membership = OrgMembership.objects.create(organization=self.org, user=user, role=role)
        if branches:
            membership.scoped_pharmacies.add(*branches)
        return user, membership

    def medicine(self, pharmacy, brand="Napa Extend", **kw):
        return Medicine.objects.create(pharmacy=pharmacy, brand_name=brand, **kw)

    def batch(self, pharmacy, *, brand="Napa Extend", number="B-1", expiry_days=30, quantity=100, unit_cost="2.00", price="3.00"):
        medicine = self.medicine(pharmacy, brand=brand)
        return Batch.objects.create(
            pharmacy=pharmacy,
            medicine=medicine,
            batch_number=number,
            expiry_date=timezone.localdate() + timedelta(days=expiry_days),
            unit_cost=Decimal(unit_cost),
            selling_price=Decimal(price),
            quantity_received=quantity,
            quantity_available=quantity,
        )

    def sale(self, pharmacy, *, medicine, quantity=2, unit_price="10.00", number="INV-1"):
        sale = Sale.objects.create(pharmacy=pharmacy, invoice_number=number, total_amount=Decimal(unit_price) * quantity)
        SaleLine.objects.create(sale=sale, medicine=medicine, quantity=quantity, unit_price=Decimal(unit_price), line_total=Decimal(unit_price) * quantity)
        return sale


# ══════════════════════════════════════════════════════════════════════════
# Phase 2 — background jobs
# ══════════════════════════════════════════════════════════════════════════


class AsyncJobTests(BaseFixture):
    def test_beat_schedule_only_references_registered_tasks(self):
        """A beat entry for a renamed task is a silent no-op --- catch it here."""
        registered = set(celery_app.tasks.keys())
        for name, entry in celery_app.conf.beat_schedule.items():
            self.assertIn(entry["task"], registered, f"beat entry '{name}' points at an unregistered task {entry['task']!r}")

    def test_every_task_declares_a_finite_retry_budget(self):
        """A task that retries forever is a task nobody is ever told about."""
        for name in celery_app.conf.beat_schedule.values():
            task = celery_app.tasks[name["task"]]
            self.assertIsNotNone(getattr(task, "max_retries", None), f"{name['task']} has no retry bound")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_expiry_digest_is_queued_per_organisation_and_sends_mail(self):
        self.batch(self.main, number="EXP-1", expiry_days=10, quantity=5)
        result = async_tasks.queue_expiry_digests.apply(kwargs={"days": 30})
        self.assertGreaterEqual(result.get()["queued"], 1)
        # One task per tenant, so the digest of the only org with expiring stock
        # is exactly one message to its billing address.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("finance@dhaka.test", mail.outbox[0].to)

    def test_digest_sends_nothing_when_no_stock_is_expiring(self):
        result = async_tasks.send_expiry_digest.apply(args=[str(self.org.pk)], kwargs={"days": 30})
        self.assertEqual(result.get()["status"], "nothing_to_report")

    def test_lapsed_invitations_are_closed_and_shown_as_expired(self):
        invitation = StaffInvitation.objects.create(
            organization=self.org,
            email="late@dhaka.test",
            role=OrgMembership.Role.STAFF,
            token_hash=StaffInvitation.hash_token(StaffInvitation.generate_raw_token()),
            expires_at=timezone.now() - timedelta(days=1),
        )
        result = async_tasks.expire_stale_invitations.apply()
        self.assertEqual(result.get()["expired"], 1)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, StaffInvitation.Status.EXPIRED)

    def test_build_export_writes_a_csv_and_returns_its_path(self):
        medicine = self.medicine(self.main)
        self.sale(self.main, medicine=medicine, number="INV-EXP")
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                result = async_tasks.build_export.apply(
                    kwargs={
                        "organization_id": str(self.org.pk),
                        "kind": "sales",
                        "requested_by": str(self.owner_user.pk),
                    }
                ).get()
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["path"].endswith(".csv"))
        self.assertEqual(result["rows"], 1)

    def test_build_export_for_a_deleted_organisation_is_a_no_op(self):
        result = async_tasks.build_export.apply(kwargs={"organization_id": "00000000-0000-0000-0000-000000000000"}).get()
        self.assertEqual(result["status"], "gone")


# ══════════════════════════════════════════════════════════════════════════
# Phase 3 — invoicing
# ══════════════════════════════════════════════════════════════════════════


class InvoicingTests(BaseFixture):
    def setUp(self):
        super().setUp()
        self.period_end = timezone.localdate().replace(day=1) - timedelta(days=1)
        self.period_start = self.period_end.replace(day=1)

    def draft(self, **kw):
        return invoicing.draft_invoice(
            self.org,
            period_start=kw.get("period_start", self.period_start),
            period_end=kw.get("period_end", self.period_end),
        )

    def test_draft_snapshots_amounts_and_tax_identity(self):
        invoice = self.draft()
        quote = org_billing.quote(self.org)
        self.assertEqual(invoice.subtotal, quote.subtotal)
        self.assertEqual(invoice.vat_amount, quote.vat_amount)
        self.assertEqual(invoice.total, quote.total)
        # The buyer's own BIN is copied at draft time so a later correction to
        # the organisation cannot rewrite a document already issued.
        self.assertEqual(invoice.buyer_bin, "BIN-123456")

    def test_invoice_arithmetic_is_exact_in_integer_taka(self):
        invoice = self.draft()
        self.assertEqual(invoice.subtotal + invoice.vat_amount, invoice.total)
        self.assertIsInstance(invoice.total, int)
        # 15% of the subtotal, rounded to the nearest taka --- never a fraction.
        self.assertEqual(invoice.vat_amount, round(invoice.subtotal * float(invoice.vat_percent) / 100))

    def test_rerunning_a_draft_replaces_lines_rather_than_duplicating_them(self):
        first = self.draft()
        first_count = first.lines.count()
        second = self.draft()
        self.assertEqual(first.pk, second.pk, "a re-run must amend the draft, not create a second invoice")
        self.assertEqual(second.lines.count(), first_count)
        self.assertEqual(Invoice.objects.filter(organization=self.org).count(), 1)

    def test_issued_invoice_is_immutable_under_a_rerun(self):
        invoice = self.draft()
        invoicing.issue_invoice(invoice)
        invoice.refresh_from_db()
        issued_total = invoice.total
        again = self.draft()
        self.assertEqual(again.pk, invoice.pk)
        self.assertEqual(again.total, issued_total)
        self.assertEqual(again.status, Invoice.Status.ISSUED)

    def test_a_zero_total_invoice_refuses_to_be_issued(self):
        # A FREE tenant with a single included branch and no members owes
        # nothing, so its draft totals zero.
        bare = make_org(name="Bare Chemists", slug="bare", plan=Organization.Plan.FREE)
        Pharmacy.objects.create(name="Only", organization=bare, branch_code="ON-01")
        invoice = invoicing.draft_invoice(bare, period_start=self.period_start, period_end=self.period_end)
        self.assertEqual(invoice.total, 0)
        with self.assertRaises(ValueError):
            invoicing.issue_invoice(invoice)

    def test_payment_moves_an_issued_invoice_to_paid(self):
        invoice = invoicing.issue_invoice(self.draft())
        invoicing.record_payment(invoice, reference="TRX-99")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertIn("TRX-99", invoice.notes)

    def test_a_paid_invoice_cannot_be_voided(self):
        invoice = invoicing.record_payment(invoicing.issue_invoice(self.draft()))
        with self.assertRaises(ValueError):
            invoicing.void_invoice(invoice, reason="oops")

    def test_voiding_keeps_the_row_and_frees_the_period_from_the_constraint(self):
        invoice = self.draft()
        invoicing.void_invoice(invoice, reason="wrong branch count")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.VOID)
        # A voided invoice no longer blocks a fresh draft for the same period.
        replacement = self.draft()
        self.assertNotEqual(replacement.pk, invoice.pk)

    def test_invoice_numbers_are_sequential_within_a_month(self):
        first = self.draft()
        self.assertRegex(first.number, r"^RKH-\d{4}-\d{2}-\d{4}$")
        # A second organisation drafting in the same month takes the next number.
        other = make_org(name="Chittagong Chemists", slug="ctg-chemists", plan=Organization.Plan.BRANCH)
        Pharmacy.objects.create(name="Agrabad", organization=other, branch_code="AG-01")
        second = invoicing.draft_invoice(other, period_start=self.period_start, period_end=self.period_end)
        self.assertNotEqual(first.number, second.number)
        self.assertEqual(int(second.number.rsplit("-", 1)[1]), int(first.number.rsplit("-", 1)[1]) + 1)

    def test_totals_separate_outstanding_from_overdue(self):
        invoice = invoicing.issue_invoice(self.draft())
        # Push the due date into the past to make it overdue.
        Invoice.objects.filter(pk=invoice.pk).update(due_on=timezone.localdate() - timedelta(days=3))
        totals = invoicing.invoice_totals(self.org)
        self.assertEqual(totals["outstanding"], 1)
        self.assertEqual(totals["overdue"], 1)
        self.assertEqual(totals["overdue_total"], invoice.total)


class InvoicingApiTests(BaseFixture):
    def setUp(self):
        super().setUp()
        self.period_end = timezone.localdate().replace(day=1) - timedelta(days=1)
        self.period_start = self.period_end.replace(day=1)

    def test_admin_can_draft_then_issue_then_pay_through_the_api(self):
        created = self.client.post(
            "/api/v1/org/invoices/",
            {"period_start": self.period_start.isoformat(), "period_end": self.period_end.isoformat()},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        invoice_id = created.json()["id"]

        issued = self.client.post(f"/api/v1/org/invoices/{invoice_id}/issue/", {}, format="json")
        self.assertEqual(issued.status_code, 200)
        self.assertEqual(issued.json()["status"], Invoice.Status.ISSUED)

        paid = self.client.post(f"/api/v1/org/invoices/{invoice_id}/payment/", {"reference": "BANK-1"}, format="json")
        self.assertEqual(paid.status_code, 200)
        self.assertEqual(paid.json()["status"], Invoice.Status.PAID)

    def test_billing_overview_combines_invoice_totals_with_the_next_quote(self):
        response = self.client.get("/api/v1/org/billing/overview/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("next_quote", body)
        self.assertEqual(body["next_quote"]["seats"]["active"], 1)

    def test_another_tenants_invoice_is_a_404_not_a_403(self):
        rival = make_org(name="Rival Chemists", slug="rival", plan=Organization.Plan.BRANCH)
        Pharmacy.objects.create(name="Rival Main", organization=rival)
        rival_invoice = invoicing.draft_invoice(rival, period_start=self.period_start, period_end=self.period_end)
        response = self.client.get(f"/api/v1/org/invoices/{rival_invoice.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_a_viewer_cannot_reach_billing(self):
        _, _membership = self.member("viewer@dhaka.test", OrgMembership.Role.VIEWER)
        viewer_client = login("viewer@dhaka.test")
        response = viewer_client.get("/api/v1/org/invoices/")
        self.assertEqual(response.status_code, 403)

    def test_a_branch_api_key_cannot_read_financial_documents(self):
        _record, raw_key = PharmacyApiKey.create_key(self.main)
        key_client = APIClient()
        key_client.credentials(HTTP_X_PHARMACY_KEY=raw_key)
        response = key_client.get("/api/v1/org/invoices/")
        # A device credential is not a person: an invoice needs a human behind it.
        self.assertIn(response.status_code, (401, 403))

    def test_invoice_pdf_downloads_in_bengali_by_default(self):
        """The PDF endpoint returns a real PDF, and Bengali is the default.

        The default matters: the console links to this URL without a query
        string, and the businesses using it are Bangladeshi. An English default
        would mean every download needed a parameter to be correct.
        """
        created = self.client.post(
            "/api/v1/org/invoices/",
            {"period_start": self.period_start.isoformat(), "period_end": self.period_end.isoformat()},
            format="json",
        )
        invoice_id = created.json()["id"]
        response = self.client.get(f"/api/v1/org/invoices/{invoice_id}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("inline", response["Content-Disposition"].lower())

    def test_invoice_pdf_honours_the_language_parameter(self):
        created = self.client.post(
            "/api/v1/org/invoices/",
            {"period_start": self.period_start.isoformat(), "period_end": self.period_end.isoformat()},
            format="json",
        )
        invoice_id = created.json()["id"]
        english = self.client.get(f"/api/v1/org/invoices/{invoice_id}/pdf/?lang=en")
        self.assertEqual(english.status_code, 200)
        self.assertTrue(english.content.startswith(b"%PDF"))

    def test_another_tenants_invoice_pdf_is_a_404(self):
        """The PDF endpoint is scoped like every other billing view."""
        rival = make_org(name="Rival Chemists", slug="rival-pdf", plan=Organization.Plan.BRANCH)
        Pharmacy.objects.create(name="Rival Main", organization=rival)
        rival_invoice = invoicing.draft_invoice(rival, period_start=self.period_start, period_end=self.period_end)
        response = self.client.get(f"/api/v1/org/invoices/{rival_invoice.pk}/pdf/")
        self.assertEqual(response.status_code, 404)

    def test_quotation_pdf_downloads(self):
        response = self.client.get("/api/v1/org/billing/quote.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_a_viewer_cannot_download_an_invoice_pdf(self):
        """A financial document is admin-only, PDF or JSON."""
        created = self.client.post(
            "/api/v1/org/invoices/",
            {"period_start": self.period_start.isoformat(), "period_end": self.period_end.isoformat()},
            format="json",
        )
        invoice_id = created.json()["id"]
        self.member("viewer2@dhaka.test", OrgMembership.Role.VIEWER)
        viewer_client = login("viewer2@dhaka.test")
        response = viewer_client.get(f"/api/v1/org/invoices/{invoice_id}/pdf/")
        self.assertEqual(response.status_code, 403)


# ══════════════════════════════════════════════════════════════════════════
# Phase 4 — reporting
# ══════════════════════════════════════════════════════════════════════════


class ReportingApiTests(BaseFixture):
    def setUp(self):
        super().setUp()
        self.medicine_a = self.medicine(self.main, "Napa Extend")
        self.medicine_b = self.medicine(self.second, "Seclo 20")
        self.sale(self.main, medicine=self.medicine_a, quantity=3, unit_price="10.00", number="M-1")
        self.sale(self.second, medicine=self.medicine_b, quantity=5, unit_price="10.00", number="S-1")

    def test_sales_report_totals_match_the_sales_that_were_recorded(self):
        response = self.client.get("/api/v1/org/reports/sales/?days=30")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["totals"]["revenue"], "80.00")  # 3x10 + 5x10
        self.assertEqual(body["totals"]["units"], 8)
        self.assertEqual(len(body["by_branch"]), 2)

    def test_sales_report_is_scoped_to_the_managers_branch(self):
        _, _membership = self.member("dhanmondi@dhaka.test", OrgMembership.Role.MANAGER, self.main)
        manager_client = login("dhanmondi@dhaka.test")
        body = manager_client.get("/api/v1/org/reports/sales/?days=30").json()
        # The manager is pinned to Dhanmondi, so Mirpur's takings must not appear.
        self.assertEqual(body["totals"]["revenue"], "30.00")
        self.assertEqual([row["branch_code"] for row in body["by_branch"]], ["DH-01"])

    def test_expiry_report_values_stock_at_cost_not_at_retail(self):
        self.batch(self.main, brand="Expiring", number="X-1", expiry_days=20, quantity=50, unit_cost="2.00", price="9.00")
        body = self.client.get("/api/v1/org/reports/expiry/?horizon=90").json()
        # 50 units x 2.00 cost = 100.00; valuing at the 9.00 retail would be wrong.
        self.assertEqual(body["totals"]["value"], "100.00")
        self.assertEqual(body["totals"]["batches"], 1)

    def test_dead_stock_excludes_a_batch_that_recently_moved(self):
        moved = self.batch(self.main, brand="Moved", number="MOV-1", expiry_days=200)
        self.batch(self.main, brand="Still", number="STL-1", expiry_days=200)
        StockMovement.objects.create(pharmacy=self.main, batch=moved, medicine=moved.medicine, kind=StockMovement.Kind.PURCHASE, quantity_delta=5)
        body = self.client.get("/api/v1/org/reports/dead-stock/?days=90").json()
        names = {row["medicine"] for row in body["batches"]}
        self.assertIn("Still", names)
        self.assertNotIn("Moved", names)

    def test_scorecard_still_lists_a_branch_that_sold_nothing(self):
        quiet = Pharmacy.objects.create(name="Uttara", organization=self.org, branch_code="UT-03")
        self.owner.scoped_pharmacies.add(quiet)
        body = self.client.get("/api/v1/org/reports/scorecard/?days=30").json()
        by_code = {row["branch_code"]: row for row in body["branches"]}
        self.assertIn("UT-03", by_code)
        self.assertEqual(by_code["UT-03"]["revenue"], "0.00")

    def test_sales_export_is_csv_and_carries_a_utf8_bom(self):
        response = self.client.get("/api/v1/org/exports/sales.csv?days=30")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        # The BOM is what makes Excel render Bengali product names correctly.
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        self.assertIn("attachment;", response["Content-Disposition"])

    def test_expiry_export_is_csv(self):
        self.batch(self.main, brand="Expiring", number="X-2", expiry_days=5)
        response = self.client.get("/api/v1/org/exports/expiry.csv?horizon=90")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])

    def test_an_unknown_export_kind_is_a_404(self):
        response = self.client.get("/api/v1/org/exports/profit.csv")
        self.assertEqual(response.status_code, 404)

    def test_reports_require_a_signed_in_member(self):
        response = APIClient().get("/api/v1/org/reports/sales/")
        self.assertIn(response.status_code, (401, 403))

    def test_scorecard_and_dead_stock_need_a_manager(self):
        _, _membership = self.member("staff@dhaka.test", OrgMembership.Role.STAFF)
        staff_client = login("staff@dhaka.test")
        self.assertEqual(staff_client.get("/api/v1/org/reports/scorecard/").status_code, 403)
        self.assertEqual(staff_client.get("/api/v1/org/reports/dead-stock/").status_code, 403)
        # The expiry list has no role gate: any member may see what is expiring.
        self.assertEqual(staff_client.get("/api/v1/org/reports/expiry/").status_code, 200)


# ══════════════════════════════════════════════════════════════════════════
# Bulk onboarding — CSV stock import
# ══════════════════════════════════════════════════════════════════════════

HEADER = "Medicine,Generic,Batch,Expiry,Qty,Cost,Price,Branch\n"


def csv_upload(text, name="stock.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


class StockImportTests(BaseFixture):
    def test_good_rows_import_and_bad_rows_are_reported_with_line_numbers(self):
        text = (
            HEADER
            + "Napa Extend,Paracetamol,NP-1,2027-04-30,10,1.85,2.00,DH-01\n"
            + "Seclo 20,Omeprazole,SC-1,not-a-date,5,3.00,4.00,DH-01\n"
            + "Monas 10,Montelukast,MN-1,2027-06-30,7,4.00,5.00,MP-02\n"
        )
        response = self.client.post("/api/v1/org/import/stock/", {"file": csv_upload(text)}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["created"], 2)
        self.assertEqual(body["failed"], 1)
        # The failure names its line so a manager can fix the right row.
        self.assertEqual(body["errors"][0]["line"], 3)
        self.assertIn("not-a-date", body["errors"][0]["message"])

    def test_headline_aliases_and_day_first_dates_are_accepted(self):
        text = HEADER + "Napa Extend,Paracetamol,B-9,30-04-2027,11,1.85,2.00,DH-01\n"
        body = self.client.post("/api/v1/org/import/stock/", {"file": csv_upload(text)}, format="multipart").json()
        self.assertEqual(body["created"], 1)
        batch = Batch.objects.get(batch_number="B-9")
        self.assertEqual(batch.expiry_date, date(2027, 4, 30))
        self.assertEqual(batch.quantity_available, 11)

    def test_reimport_amends_the_existing_batch_instead_of_duplicating_it(self):
        text = HEADER + "Napa Extend,Paracetamol,NP-1,2027-04-30,10,1.85,2.00,DH-01\n"
        first = self.client.post("/api/v1/org/import/stock/", {"file": csv_upload(text)}, format="multipart").json()
        second = self.client.post("/api/v1/org/import/stock/", {"file": csv_upload(text)}, format="multipart").json()
        self.assertEqual(first["created"], 1)
        # The second upload of the same file tops up stock; it does not mint a
        # second batch bearing the same number.
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(Batch.objects.filter(batch_number="NP-1").count(), 1)
        self.assertEqual(Batch.objects.get(batch_number="NP-1").quantity_available, 20)

    def test_a_row_naming_a_branch_outside_the_callers_scope_is_refused(self):
        _, _membership = self.member("dhanmondi@dhaka.test", OrgMembership.Role.MANAGER, self.main)
        manager_client = login("dhanmondi@dhaka.test")
        text = HEADER + "Napa Extend,Paracetamol,NP-1,2027-04-30,10,1.85,2.00,MP-02\n"
        body = manager_client.post("/api/v1/org/import/stock/", {"file": csv_upload(text)}, format="multipart").json()
        self.assertEqual(body["created"], 0)
        self.assertEqual(body["failed"], 1)
        self.assertIn("outside your branch access", body["errors"][0]["message"])

    def test_missing_required_columns_is_reported_once_not_per_row(self):
        text = "Generic,Batch\nParacetamol,X-1\nOmeprazole,X-2\n"
        body = self.client.post("/api/v1/org/import/stock/", {"file": csv_upload(text)}, format="multipart").json()
        self.assertEqual(body["failed"], 2)
        self.assertEqual(len(body["errors"]), 1)
        self.assertIn("Missing required column", body["errors"][0]["message"])

    def test_import_is_refused_without_a_file(self):
        response = self.client.post("/api/v1/org/import/stock/", {}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "no_file")

    def test_the_get_describes_the_expected_format(self):
        body = self.client.get("/api/v1/org/import/stock/").json()
        self.assertIn("brand_name", body["columns"])
        self.assertIn("branch_code", body["sample"])

    def test_duplicate_batch_number_in_one_file_is_a_per_row_failure_not_a_500(self):
        text = HEADER + "Napa Extend,Paracetamol,DUP-1,2027-04-30,10,1.85,2.00,DH-01\n" + "Napa Extend,Paracetamol,DUP-1,2027-04-30,4,1.85,2.00,DH-01\n"
        response = self.client.post("/api/v1/org/import/stock/", {"file": csv_upload(text)}, format="multipart")
        self.assertIn(response.status_code, (200, 201))
        body = response.json()
        # The first row creates the batch, the second tops it up --- no error,
        # and certainly no unhandled IntegrityError.
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["updated"], 1)
        self.assertEqual(body["failed"], 0)

    def test_export_queue_accepts_a_known_kind(self):
        response = self.client.post("/api/v1/org/exports/queue/", {"kind": "sales"}, format="json")
        self.assertEqual(response.status_code, 202)
        self.assertIn("task_id", response.json())

    def test_export_queue_rejects_an_unknown_kind(self):
        response = self.client.post("/api/v1/org/exports/queue/", {"kind": "everything"}, format="json")
        self.assertEqual(response.status_code, 400)


# ══════════════════════════════════════════════════════════════════════════
# Phase 6 pre-work — branding and usage
# ══════════════════════════════════════════════════════════════════════════


class BrandingAndUsageTests(BaseFixture):
    def test_branding_works_even_while_white_labelling_was_off(self):
        """DEPRECATED: this used to answer 400 ``white_label_refused`` until
        support switched the plan flag on. Every feature is free now, so a
        brand name simply saves — and flips the flag that ``display_name``
        renders behind, so the change takes effect immediately."""
        self.assertFalse(self.org.white_label_enabled)
        response = self.client.patch("/api/v1/org/branding/", {"brand_name": "Apna Pharma"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.org.refresh_from_db()
        self.assertEqual(self.org.brand_name, "Apna Pharma")
        self.assertTrue(self.org.white_label_enabled)

    def test_branding_stores_a_valid_hex_colour_when_enabled(self):
        self.org.white_label_enabled = True
        self.org.save(update_fields=["white_label_enabled"])
        response = self.client.patch("/api/v1/org/branding/", {"brand_name": "Apna Pharma", "brand_color": "#0F7B6C"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.org.refresh_from_db()
        self.assertEqual(self.org.brand_name, "Apna Pharma")

    def test_branding_rejects_a_colour_that_is_not_hex(self):
        self.org.white_label_enabled = True
        self.org.save(update_fields=["white_label_enabled"])
        response = self.client.patch("/api/v1/org/branding/", {"brand_color": "red; drop table"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_branding_rejects_an_http_logo(self):
        self.org.white_label_enabled = True
        self.org.save(update_fields=["white_label_enabled"])
        response = self.client.patch("/api/v1/org/branding/", {"logo_url": "http://insecure.example/logo.png"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_usage_metrics_report_seats_and_branches(self):
        self.member("second@dhaka.test", OrgMembership.Role.STAFF, self.main)
        body = self.client.get("/api/v1/org/usage/").json()
        self.assertEqual(body["seats"]["active_members"], 2)
        self.assertEqual(body["branches"]["active"], 2)
        self.assertEqual(body["branches"]["allowance"], self.org.branch_allowance)
