"""Billing endpoints: the invoices an organisation can see and act on.

The console's billing screen has to answer four questions, and each maps to one
thing here: what have we been billed (``InvoiceListView``), what is on a
particular invoice (``InvoiceDetailView``), what will next month cost
(``BillingOverviewView``), and can I mark this paid (``InvoicePaymentView``).

Everything is admin-only and requires a signed-in person, not a branch API key.
An invoice is a financial document; a device credential must not be able to read
one, let alone settle it. That is enforced by ``HasFreshJWT`` on the base class
rather than per view, so a new endpoint added here inherits the rule.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from rest_framework import status
from rest_framework.response import Response

from . import invoicing, org_billing
from .models import Invoice, OrgMembership
from .org_context import HasFreshJWT
from .org_views import OrgScopedView

logger = logging.getLogger("inventory.billing")


def _period_from_request(request):
    """Resolve the billing period, defaulting to the month just ended.

    "Just ended" rather than "current" because that is the period an invoice is
    for: a customer is billed for a month that is complete, and defaulting to
    the running month would produce a draft that changes every day until it is
    issued.
    """
    start_raw = request.data.get("period_start") or request.query_params.get("period_start")
    end_raw = request.data.get("period_end") or request.query_params.get("period_end")
    if start_raw and end_raw:
        try:
            return date.fromisoformat(str(start_raw)), date.fromisoformat(str(end_raw)), None
        except ValueError:
            return (
                None,
                None,
                Response(
                    {"error": {"code": "invalid_period", "detail": "period_start and period_end must be YYYY-MM-DD.", "fields": {}}},
                    status=status.HTTP_400_BAD_REQUEST,
                ),
            )
    today = date.today()
    last_month_end = today.replace(day=1) - timedelta(days=1)
    return last_month_end.replace(day=1), last_month_end, None


class InvoiceScopedView(OrgScopedView):
    """Billing views: admin only, and always a signed-in human."""

    permission_classes = [*OrgScopedView.permission_classes, HasFreshJWT]
    required_role = OrgMembership.Role.ADMIN

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.require_role(OrgMembership.Role.ADMIN)


class InvoiceListView(InvoiceScopedView):
    """List this organisation's invoices, newest period first.

    Supports ``?status=`` so the console can show "unpaid" without pulling the
    whole history, and ``?year=`` because the single most common request from an
    accountant is "everything for the financial year".
    """

    def get(self, request):
        queryset = Invoice.objects.filter(organization=self.organization).prefetch_related("lines")
        invoice_status = request.query_params.get("status")
        if invoice_status:
            if invoice_status not in dict(Invoice.Status.choices):
                return Response(
                    {"error": {"code": "invalid_status", "detail": f"status must be one of: {', '.join(dict(Invoice.Status.choices))}.", "fields": {}}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(status=invoice_status)
        year = request.query_params.get("year")
        if year:
            try:
                queryset = queryset.filter(period_start__year=int(year))
            except (TypeError, ValueError):
                return Response(
                    {"error": {"code": "invalid_year", "detail": "year must be a four-digit number.", "fields": {}}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(
            {
                "totals": invoicing.invoice_totals(self.organization),
                "invoices": [invoicing.serialize_invoice(invoice, include_lines=True) for invoice in queryset[:200]],
            }
        )

    def post(self, request):
        """Draft an invoice for a period on demand.

        The scheduled job drafts every tenant on the first of the month; this is
        the same operation for one tenant, for the case where a finance team
        wants the current month's document before the run, or needs to re-create
        one that was voided.
        """
        period_start, period_end, error = _period_from_request(request)
        if error:
            return error
        if period_end < period_start:
            return Response(
                {"error": {"code": "invalid_period", "detail": "period_end must not be before period_start.", "fields": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        invoice = invoicing.draft_invoice(self.organization, period_start=period_start, period_end=period_end, request=request)
        http_status = status.HTTP_201_CREATED if invoice.status == Invoice.Status.DRAFT else status.HTTP_200_OK
        return Response(invoicing.serialize_invoice(invoice), status=http_status)


class InvoiceDetailView(InvoiceScopedView):
    """Read one invoice, or void it.

    Voiding is a DELETE because that is what the customer means, but it is
    implemented as a status change: the row and its number survive. See
    ``invoicing.void_invoice`` for why the number must not be recycled.
    """

    def _get_invoice(self, invoice_id):
        # Filtered by organisation, so another tenant's invoice id answers 404
        # rather than 403 --- existence is itself information.
        return Invoice.objects.filter(pk=invoice_id, organization=self.organization).prefetch_related("lines").first()

    def get(self, request, invoice_id):
        invoice = self._get_invoice(invoice_id)
        if invoice is None:
            return Response({"error": {"code": "not_found", "detail": "No such invoice.", "fields": {}}}, status=status.HTTP_404_NOT_FOUND)
        return Response(invoicing.serialize_invoice(invoice))

    def delete(self, request, invoice_id):
        invoice = self._get_invoice(invoice_id)
        if invoice is None:
            return Response({"error": {"code": "not_found", "detail": "No such invoice.", "fields": {}}}, status=status.HTTP_404_NOT_FOUND)
        try:
            invoice = invoicing.void_invoice(invoice, reason=str(request.data.get("reason", ""))[:200], request=request)
        except ValueError as exc:
            return Response({"error": {"code": "cannot_void", "detail": str(exc), "fields": {}}}, status=status.HTTP_409_CONFLICT)
        return Response(invoicing.serialize_invoice(invoice))


class InvoiceIssueView(InvoiceScopedView):
    """Promote a draft to an issued invoice."""

    def post(self, request, invoice_id):
        invoice = Invoice.objects.filter(pk=invoice_id, organization=self.organization).first()
        if invoice is None:
            return Response({"error": {"code": "not_found", "detail": "No such invoice.", "fields": {}}}, status=status.HTTP_404_NOT_FOUND)
        try:
            invoice = invoicing.issue_invoice(invoice, request=request)
        except ValueError as exc:
            return Response({"error": {"code": "cannot_issue", "detail": str(exc), "fields": {}}}, status=status.HTTP_409_CONFLICT)
        return Response(invoicing.serialize_invoice(invoice))


class InvoicePaymentView(InvoiceScopedView):
    """Record that an invoice has been paid."""

    def post(self, request, invoice_id):
        invoice = Invoice.objects.filter(pk=invoice_id, organization=self.organization).first()
        if invoice is None:
            return Response({"error": {"code": "not_found", "detail": "No such invoice.", "fields": {}}}, status=status.HTTP_404_NOT_FOUND)
        try:
            invoice = invoicing.record_payment(invoice, reference=str(request.data.get("reference", ""))[:64], request=request)
        except ValueError as exc:
            return Response({"error": {"code": "cannot_pay", "detail": str(exc), "fields": {}}}, status=status.HTTP_409_CONFLICT)
        return Response(invoicing.serialize_invoice(invoice))


class BillingOverviewView(InvoiceScopedView):
    """The billing panel in one call: what is owed, and what is next.

    Returning the current quote alongside the invoice totals is deliberate. The
    question the customer actually has is "why is next month bigger", and being
    able to show the live branch and seat breakdown next to last month's invoice
    answers it before they have to ask.
    """

    def get(self, request):
        organization = self.organization
        quote = org_billing.quote(organization)
        return Response(
            {
                "organization": {
                    "name": organization.display_name,
                    "legal_name": organization.legal_name,
                    "bin": organization.bin,
                    "plan": organization.plan,
                    "currency": organization.currency,
                    "branch_allowance": organization.branch_allowance,
                    "seat_addon_count": organization.seat_addon_count,
                },
                "invoices": invoicing.invoice_totals(organization),
                "next_quote": {
                    "branches": [{"pharmacy_id": line.pharmacy_id, "name": line.name, "included": line.included, "amount": line.amount} for line in quote.branches],
                    "seats": {
                        "included": quote.seats.included_seats,
                        "active": quote.seats.active_seats,
                        "billable": quote.seats.billable_seats,
                        "amount": quote.seats.amount,
                    },
                    "subtotal": quote.subtotal,
                    "vat_percent": quote.vat_percent,
                    "vat_amount": quote.vat_amount,
                    "total": quote.total,
                    "notes": quote.notes,
                },
                "seat_utilisation": org_billing.seat_utilisation(organization),
            }
        )
