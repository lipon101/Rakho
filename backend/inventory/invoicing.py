"""Invoicing: turning a quote into a document.

The distinction this module exists to make is between a *quote* and an
*invoice*. A quote answers "what would this cost today" and is correct to
recompute on every request; an invoice answers "what did this cost for October"
and must never change again. So an invoice copies the numbers and the tax
identity out of the quote at the moment it is issued and keeps its own record
from then on --- closing a branch in November must not alter the October
document the accountant already filed.

Three behaviours are deliberate and each is pinned by a test:

* **Draft, then issue.** The monthly job creates drafts. Nothing that reaches a
  customer is generated unattended.
* **Idempotent per period.** Re-running the job amends the draft it created
  rather than producing a second invoice for the same month, which is what the
  unique constraint on the model also enforces at the database level.
* **Arithmetic in integers.** Subtotal plus VAT equals the total exactly, in
  whole taka, because that is the one line a finance team always checks.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import audit, org_billing
from .models import AuditLog, Invoice, InvoiceLine, Organization

logger = logging.getLogger("inventory.invoicing")

#: How long a customer has to pay. Thirty days is the norm for a B2B software
#: invoice in Bangladesh and matches the monthly billing period.
PAYMENT_TERMS_DAYS = 30

#: The seller's own tax identity, printed on every invoice. Environment-driven
#: because it differs between a hosted deployment and an on-premise reseller
#: install, and it must be the reseller's BIN in the second case, not ours.
DEFAULT_SELLER_NAME = "Rakho"
DEFAULT_SELLER_BIN = ""


def _seller_identity():
    return (
        getattr(settings, "INVOICE_SELLER_NAME", DEFAULT_SELLER_NAME),
        getattr(settings, "INVOICE_SELLER_BIN", DEFAULT_SELLER_BIN),
    )


def next_invoice_number(when: date) -> str:
    """A sequential, human-quotable number: ``RKH-2026-10-0007``.

    Sequential within the month rather than a UUID, because the number is
    spoken aloud on a support call and typed into a bank reference. The loop
    exists because two invoice runs racing on the first of the month would
    otherwise both compute the same next number; the unique constraint is the
    real guard and this simply retries past it.
    """
    prefix = f"RKH-{when.year}-{when.month:02d}-"
    last = Invoice.objects.filter(number__startswith=prefix).order_by("-number").values_list("number", flat=True).first()
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{sequence:04d}"


def _lines_from_quote(invoice, quote):
    """Materialise a quote's lines onto a draft invoice.

    Rebuilt from scratch on every draft so that re-running the job for a period
    whose branch count changed produces the corrected invoice, not a duplicate
    set of rows. Deleting first also keeps the invoice's total honest: the model
    recomputes it from whatever rows remain.
    """
    invoice.lines.all().delete()

    included = [line for line in quote.branches if line.included]
    billable = [line for line in quote.branches if not line.included]

    if included:
        InvoiceLine.objects.create(
            invoice=invoice,
            kind=InvoiceLine.Kind.BASE,
            description=f"Base plan — {len(included)} branch(es) included",
            quantity=len(included),
            unit_amount=0,
            amount=0,
        )

    branch_price = org_billing._rate("BRANCH_PRICE_BDT", org_billing.BRANCH_PRICE)
    for line in billable:
        InvoiceLine.objects.create(
            invoice=invoice,
            kind=InvoiceLine.Kind.BRANCH,
            description=f"Additional branch — {line.name}",
            quantity=1,
            unit_amount=branch_price,
            amount=line.amount,
            pharmacy_id=line.pharmacy_id,
        )

    seat_line = quote.seats
    if seat_line.billable_seats:
        seat_price = org_billing._rate("SEAT_PRICE_BDT", org_billing.SEAT_PRICE)
        InvoiceLine.objects.create(
            invoice=invoice,
            kind=InvoiceLine.Kind.SEAT,
            description=f"Additional seats ({seat_line.active_seats} active, {seat_line.included_seats} included)",
            quantity=seat_line.billable_seats,
            unit_amount=seat_price,
            amount=seat_line.amount,
        )


def draft_invoice(organization, *, period_start: date, period_end: date, request=None) -> Invoice:
    """Create or refresh the draft invoice for one organisation and period.

    Wrapped in one transaction with the line replacement, so a failure half way
    through rebuilding a re-run cannot leave an invoice whose stored total no
    longer matches its own lines.
    """
    with transaction.atomic():
        # select_for_update on the organisation serialises two concurrent runs
        # for the same tenant; without it both could read "no invoice yet" and
        # race into the unique constraint.
        Organization.objects.select_for_update().get(pk=organization.pk)

        existing = (
            Invoice.objects.filter(
                organization=organization,
                period_start=period_start,
                period_end=period_end,
            )
            .exclude(status=Invoice.Status.VOID)
            .first()
        )

        if existing is not None and existing.status != Invoice.Status.DRAFT:
            # An issued invoice is immutable. Re-running the job must not rewrite
            # a document the customer already holds; a correction is an explicit
            # void-and-reissue, not a silent edit.
            logger.info("invoice %s already issued for %s; leaving it alone", existing.number, organization.slug)
            return existing

        quote = org_billing.quote(organization)

        invoice = existing or Invoice(
            organization=organization,
            number=next_invoice_number(period_end),
            period_start=period_start,
            period_end=period_end,
        )
        _seller_name, seller_bin = _seller_identity()
        invoice.currency = organization.currency
        invoice.plan = organization.plan
        invoice.seller_name = _seller_name
        invoice.seller_bin = seller_bin
        invoice.buyer_name = organization.legal_name or organization.display_name
        invoice.buyer_bin = organization.bin
        invoice.buyer_address = organization.address
        invoice.vat_percent = quote.vat_percent
        invoice.notes = " · ".join(quote.notes)[:500]
        try:
            invoice.save()
        except IntegrityError:
            # Another run won the race between our check and our insert.
            logger.warning("invoice number collision for %s; using the existing draft", organization.slug)
            return Invoice.objects.filter(organization=organization, period_start=period_start, period_end=period_end).exclude(status=Invoice.Status.VOID).first()

        _lines_from_quote(invoice, quote)
        invoice.recalculate()
        invoice.save(update_fields=["subtotal", "vat_amount", "total", "updated_at"])

    audit.record(
        request,
        AuditLog.Action.CREATE,
        organization=organization,
        target=invoice,
        changes={"total": {"from": None, "to": invoice.total}},
        note=f"draft invoice {invoice.number}",
    )
    return invoice


def issue_invoice(invoice, *, today: date | None = None, request=None) -> Invoice:
    """Promote a draft to an issued invoice, freezing its terms.

    Refuses an invoice with nothing on it. Sending a customer a zero-taka
    invoice invites a support conversation about a bill they do not owe, and
    the honest answer --- "your plan is free this month" --- is better said by
    not sending one.
    """
    if invoice.status != Invoice.Status.DRAFT:
        raise ValueError(f"Only a draft can be issued; this invoice is {invoice.status}.")
    if invoice.total <= 0:
        raise ValueError("Refusing to issue a zero-total invoice.")

    today = today or timezone.localdate()
    invoice.status = Invoice.Status.ISSUED
    invoice.issued_on = today
    invoice.due_on = today + timedelta(days=PAYMENT_TERMS_DAYS)
    invoice.save(update_fields=["status", "issued_on", "due_on", "updated_at"])

    audit.record(
        request,
        AuditLog.Action.UPDATE,
        organization=invoice.organization,
        target=invoice,
        changes={"status": {"from": Invoice.Status.DRAFT, "to": invoice.status}, "issued_on": {"from": None, "to": today.isoformat()}},
        note=f"issued invoice {invoice.number}",
    )
    return invoice


def record_payment(invoice, *, paid_on: date | None = None, reference: str = "", request=None) -> Invoice:
    """Mark an issued invoice paid.

    Manual, and deliberately so: Bangladeshi B2B software is still largely paid
    by bank transfer against a reference, so the honest model is "an operator
    confirmed the money arrived", not a payment-gateway callback that does not
    exist for this segment.
    """
    if invoice.status not in (Invoice.Status.ISSUED, Invoice.Status.PAID):
        raise ValueError(f"A {invoice.status} invoice cannot be paid.")

    invoice.status = Invoice.Status.PAID
    invoice.paid_on = paid_on or timezone.localdate()
    changes = {"status": {"from": Invoice.Status.ISSUED, "to": invoice.status}, "paid_on": {"from": None, "to": invoice.paid_on.isoformat()}}
    if reference:
        invoice.notes = (f"{invoice.notes} · payment ref {reference}").strip(" ·")[:500]
    invoice.save(update_fields=["status", "paid_on", "notes", "updated_at"])

    audit.record(
        request,
        AuditLog.Action.PAYMENT_RECORDED,
        organization=invoice.organization,
        target=invoice,
        changes=changes,
        note=f"payment for {invoice.number}",
    )
    return invoice


def void_invoice(invoice, *, reason: str = "", request=None) -> Invoice:
    """Void an invoice without deleting it.

    A void row keeps the number allocated and the history visible --- deleting
    would free the number for reuse, and a finance team that finds two different
    documents bearing ``RKH-2026-10-0007`` stops trusting the sequence.
    """
    if invoice.status == Invoice.Status.VOID:
        return invoice
    if invoice.status == Invoice.Status.PAID:
        raise ValueError("A paid invoice cannot be voided; issue a credit note instead.")

    previous = invoice.status
    invoice.status = Invoice.Status.VOID
    if reason:
        invoice.notes = (f"{invoice.notes} · voided: {reason}").strip(" ·")[:500]
    invoice.save(update_fields=["status", "notes", "updated_at"])

    audit.record(
        request,
        AuditLog.Action.UPDATE,
        organization=invoice.organization,
        target=invoice,
        changes={"status": {"from": previous, "to": invoice.status}},
        note=f"voided invoice {invoice.number}: {reason}",
    )
    return invoice


def serialize_invoice(invoice, *, include_lines: bool = True) -> dict:
    """The invoice as the API and the printed document both need it."""
    payload = {
        "id": str(invoice.pk),
        "number": invoice.number,
        "status": invoice.status,
        "organization_id": str(invoice.organization_id),
        "period": {"start": invoice.period_start.isoformat(), "end": invoice.period_end.isoformat()},
        "issued_on": invoice.issued_on.isoformat() if invoice.issued_on else None,
        "due_on": invoice.due_on.isoformat() if invoice.due_on else None,
        "paid_on": invoice.paid_on.isoformat() if invoice.paid_on else None,
        "currency": invoice.currency,
        "seller": {"name": invoice.seller_name, "bin": invoice.seller_bin},
        "buyer": {"name": invoice.buyer_name, "bin": invoice.buyer_bin, "address": invoice.buyer_address},
        "subtotal": invoice.subtotal,
        "vat_percent": invoice.vat_percent,
        "vat_amount": invoice.vat_amount,
        "total": invoice.total,
        "plan": invoice.plan,
        "notes": invoice.notes,
        "created_at": invoice.created_at.isoformat(),
    }
    if include_lines:
        payload["lines"] = [
            {
                "kind": line.kind,
                "description": line.description,
                "quantity": line.quantity,
                "unit_amount": line.unit_amount,
                "amount": line.amount,
                "pharmacy_id": str(line.pharmacy_id) if line.pharmacy_id else None,
            }
            for line in invoice.lines.all()
        ]
    return payload


def invoice_totals(organization) -> dict:
    """Totals for the console's billing panel.

    Counts only non-void invoices, and reports ``overdue`` separately from
    ``outstanding``: a customer with an invoice due next week and one who is
    three weeks late are different conversations and the numbers should not
    merge them.
    """
    today = timezone.localdate()
    live = Invoice.objects.filter(organization=organization).exclude(status=Invoice.Status.VOID)
    outstanding = live.filter(status=Invoice.Status.ISSUED)
    return {
        "currency": organization.currency,
        "invoices": live.count(),
        "draft": live.filter(status=Invoice.Status.DRAFT).count(),
        "outstanding": outstanding.count(),
        "overdue": outstanding.filter(due_on__lt=today).count(),
        "outstanding_total": sum(outstanding.values_list("total", flat=True)),
        "overdue_total": sum(outstanding.filter(due_on__lt=today).values_list("total", flat=True)),
        "paid_total": sum(live.filter(status=Invoice.Status.PAID).values_list("total", flat=True)),
    }
