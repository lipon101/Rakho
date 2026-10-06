"""Reporting and analytics for the organisation console.

Everything here answers a question a chain owner actually asks --- "which
branch is sitting on money that expires", "what did we sell last month",
"who is not moving stock" --- and every figure is computed from the same
stock and sale rows the rest of the app writes, so a report can never disagree
with the screen a manager just used to record a sale.

Two conventions are applied throughout, because getting either wrong makes a
number quietly misleading:

* **Expired stock is still stock.** An expired batch is counted in its own
  bucket rather than dropped, because the money was spent and the loss has to
  appear somewhere. Hiding it would make the expiry report flattering and the
  write-off report unexplained.
* **A day boundary is the organisation's day.** Dates are resolved in the
  tenant's own timezone, so a Dhaka pharmacy's "today" is not the server's.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from .models import Batch, Medicine, SaleLine, StockMovement

MONEY = DecimalField(max_digits=14, decimal_places=2)

#: Expiry buckets, in days ahead. Ordered, and the last one is open-ended so a
#: batch expiring in three years still lands somewhere instead of falling out
#: of the report entirely.
EXPIRY_BUCKETS = ((0, 30, "0–30 days"), (31, 60, "31–60 days"), (61, 90, "61–90 days"), (91, None, "90+ days"))


@dataclass
class DateWindow:
    """A half-open date range ``[start, end)`` in the tenant's timezone."""

    start: object
    end: object
    timezone_name: str = "UTC"

    @classmethod
    def last_days(cls, days: int, *, organization=None):
        """The last ``days`` complete days, ending today.

        "Last 30 days" is read as 30 days *including today*, which is what a
        person means when they say it --- not a 30-day block that ended
        yesterday and leaves today's sales invisible.
        """
        tz = _organization_tz(organization)
        today = timezone.localdate(timezone=tz)
        return cls(start=today - timedelta(days=days - 1), end=today + timedelta(days=1), timezone_name=str(tz))

    @classmethod
    def from_dates(cls, start, end, *, organization=None):
        """An explicit range, inclusive of both ends.

        The end date is exclusive internally, so a caller asking for the 1st to
        the 31st does not silently lose the 31st --- the single most common
        off-by-one in every reporting UI ever written.
        """
        tz = _organization_tz(organization)
        return cls(start=start, end=end + timedelta(days=1), timezone_name=str(tz))

    def q(self, field: str) -> Q:
        return Q(**{f"{field}__gte": self.start, f"{field}__lt": self.end})

    def label(self) -> str:
        return f"{self.start.isoformat()} – {(self.end - timedelta(days=1)).isoformat()}"


def _organization_tz(organization):
    if organization is None:
        return timezone.get_current_timezone()
    import zoneinfo

    try:
        return zoneinfo.ZoneInfo(organization.timezone or "Asia/Dhaka")
    except Exception:  # noqa: BLE001 - a bad stored zone must not break a report
        return zoneinfo.ZoneInfo("Asia/Dhaka")


def _trunc_tz(tz):
    """The value ``TruncDate(tzinfo=...)`` actually needs.

    A tz-aware ``TruncDate`` wants a real ``tzinfo`` object and raises
    ``AttributeError: 'str' object has no attribute 'tzname'`` if handed a
    string. ``DateWindow.timezone_name`` is a string because it goes straight
    into JSON, so the object is rebuilt here rather than threaded through the
    window --- one conversion, next to the only function that needs it.
    """
    import zoneinfo

    if not isinstance(tz, str):
        return tz
    try:
        return zoneinfo.ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        return zoneinfo.ZoneInfo("Asia/Dhaka")


def branch_scope_queryset(organization, scoped_ids=None):
    """Branches a report covers.

    ``scoped_ids`` carries a member's branch restriction through to the report,
    so a manager pinned to one branch sees that branch's numbers rather than a
    chain-wide total they are not allowed to know.
    """
    queryset = organization.pharmacies.filter(is_active=True)
    if scoped_ids is not None:
        queryset = queryset.filter(pk__in=list(scoped_ids))
    return queryset


def sales_summary(organization, window: DateWindow, *, scoped_ids=None) -> dict:
    """Revenue and units over a window, split by branch and by day.

    ``SaleLine`` is summed rather than ``Sale.total``, because the per-branch
    split has to come from the line's own branch and a stored total would have
    to be re-attributed. Both figures are returned so a caller can reconcile.
    """
    branches = {str(branch.pk): branch for branch in branch_scope_queryset(organization, scoped_ids)}
    lines = (
        SaleLine.objects.filter(
            window.q("sale__sold_at"),
            sale__pharmacy__organization=organization,
            sale__pharmacy_id__in=branches.keys(),
        )
        .values("sale__pharmacy_id")
        .annotate(revenue=Coalesce(Sum(F("unit_price") * F("quantity")), Value(Decimal("0.00")), output_field=MONEY), units=Sum("quantity"))
    )

    by_branch = []
    total_revenue = Decimal("0.00")
    total_units = 0
    seen = set()
    for row in lines:
        key = str(row["sale__pharmacy_id"])
        branch = branches.get(key)
        if branch is None:
            continue
        seen.add(key)
        by_branch.append(
            {
                "branch_id": key,
                "branch": branch.name,
                "branch_code": branch.branch_code,
                "revenue": str(row["revenue"] or 0),
                "units": int(row["units"] or 0),
            }
        )
        total_revenue += row["revenue"] or Decimal("0.00")
        total_units += int(row["units"] or 0)

    # A branch with no sales must still appear, with a zero. A report that
    # silently omits a branch is read as "no data" rather than "no sales", and
    # the manager who needs to notice a quiet branch is exactly the one who
    # would be misled.
    for key, branch in branches.items():
        if key not in seen:
            by_branch.append(
                {
                    "branch_id": key,
                    "branch": branch.name,
                    "branch_code": branch.branch_code,
                    "revenue": "0.00",
                    "units": 0,
                }
            )
    by_branch.sort(key=lambda row: Decimal(row["revenue"]), reverse=True)

    daily = (
        SaleLine.objects.filter(window.q("sale__sold_at"), sale__pharmacy__organization=organization, sale__pharmacy_id__in=branches.keys())
        .annotate(day=TruncDate("sale__sold_at", tzinfo=_trunc_tz(window.timezone_name)))
        .values("day")
        .annotate(revenue=Coalesce(Sum(F("unit_price") * F("quantity")), Value(Decimal("0.00")), output_field=MONEY), units=Sum("quantity"))
        .order_by("day")
    )

    return {
        "window": {"start": window.start.isoformat(), "end": (window.end - timedelta(days=1)).isoformat()},
        "timezone": window.timezone_name,
        "totals": {"revenue": str(total_revenue), "units": total_units, "branches_reporting": len(branches)},
        "by_branch": by_branch,
        "daily": [{"day": row["day"].isoformat(), "revenue": str(row["revenue"] or 0), "units": int(row["units"] or 0)} for row in daily],
    }


def expiry_summary(organization, *, days: int = 90, scoped_ids=None) -> dict:
    """What expires when, split into buckets, and what it is worth.

    Value is ``quantity_available × unit_cost`` --- what the stock *cost*,
    since that is the money at risk. Valuing it at the selling price would
    report a loss the pharmacy never actually suffered.
    """
    today = timezone.localdate(timezone=_organization_tz(organization))
    horizon = today + timedelta(days=days)
    branches = {str(branch.pk): branch for branch in branch_scope_queryset(organization, scoped_ids)}
    queryset = (
        Batch.objects.filter(
            pharmacy__organization=organization,
            pharmacy_id__in=branches.keys(),
            quantity_available__gt=0,
            expiry_date__lte=horizon,
        )
        .select_related("medicine", "pharmacy")
        .order_by("expiry_date")
    )

    buckets = {label: {"label": label, "batches": 0, "units": 0, "value": Decimal("0.00")} for _, _, label in EXPIRY_BUCKETS}
    expired = {"label": "Already expired", "batches": 0, "units": 0, "value": Decimal("0.00")}
    rows = []
    for batch in queryset:
        days_left = (batch.expiry_date - today).days
        value = (batch.unit_cost or Decimal("0.00")) * batch.quantity_available
        key = next((label for low, high, label in EXPIRY_BUCKETS if days_left >= low and (high is None or days_left <= high)), None)
        target = expired if days_left < 0 else buckets[key]
        target["batches"] += 1
        target["units"] += batch.quantity_available
        target["value"] += value
        rows.append(
            {
                "batch_id": str(batch.pk),
                "medicine": batch.medicine.brand_name,
                "batch_number": batch.batch_number,
                "branch": batch.pharmacy.name,
                "expiry_date": batch.expiry_date.isoformat(),
                "days_left": days_left,
                "units": batch.quantity_available,
                "value": str(value),
            }
        )

    def as_dict(bucket):
        return {**bucket, "value": str(bucket["value"])}

    soon_cutoff = today + timedelta(days=30)
    return {
        "as_of": today.isoformat(),
        "horizon_days": days,
        "totals": {
            "batches": len(rows),
            "units": sum(row["units"] for row in rows),
            "value": str(sum((Decimal(row["value"]) for row in rows), Decimal("0.00"))),
            "soon": sum(1 for row in rows if 0 <= row["days_left"] <= 30),
            "expired": expired["batches"],
        },
        "buckets": [as_dict(buckets[label]) for _, _, label in EXPIRY_BUCKETS] + [as_dict(expired)],
        "branches": sorted({row["branch"] for row in rows}),
        "batches": rows[:500],
        "attention_by": soon_cutoff.isoformat(),
    }


def dead_stock(organization, *, days: int = 90, scoped_ids=None) -> dict:
    """Stock that has not moved in ``days``, oldest first.

    Identified from stock movements rather than from the absence of a sale
    line, because a batch that was written off or transferred also counts as
    moved --- and counting it as dead would send a manager to check stock that
    is already gone.
    """
    cutoff = timezone.now() - timedelta(days=days)
    branches = branch_scope_queryset(organization, scoped_ids)
    moved = StockMovement.objects.filter(pharmacy_id__in=branches.values_list("pk", flat=True), created_at__gte=cutoff).values_list("batch_id", flat=True)
    stagnant = (
        Batch.objects.filter(
            pharmacy_id__in=branches.values_list("pk", flat=True),
            quantity_available__gt=0,
            expiry_date__gt=timezone.localdate(timezone=_organization_tz(organization)),
        )
        .exclude(pk__in=moved)
        .select_related("medicine", "pharmacy")
        .order_by("expiry_date")
    )
    rows = [
        {
            "batch_id": str(batch.pk),
            "medicine": batch.medicine.brand_name,
            "branch": batch.pharmacy.name,
            "expiry_date": batch.expiry_date.isoformat(),
            "units": batch.quantity_available,
            "value": str((batch.unit_cost or Decimal("0.00")) * batch.quantity_available),
        }
        for batch in stagnant[:500]
    ]
    return {
        "idle_days": days,
        "batches": rows,
        "totals": {"batches": len(rows), "units": sum(row["units"] for row in rows), "value": str(sum((Decimal(row["value"]) for row in rows), Decimal("0.00")))},
    }


def branch_scorecard(organization, window: DateWindow, *, scoped_ids=None) -> list:
    """One row per branch: what it sold, what it holds, what it is losing.

    This is the report the chain owner opens first, so it is assembled from
    three already-tested queries instead of a bespoke one --- a single
    hand-written aggregate that had to be right for six different columns is
    how a scorecard ends up disagreeing with the detail pages it links to.
    """
    sales = {row["branch_id"]: row for row in sales_summary(organization, window, scoped_ids=scoped_ids)["by_branch"]}
    expiry = expiry_summary(organization, scoped_ids=scoped_ids)
    branches = branch_scope_queryset(organization, scoped_ids)

    at_risk = {}
    for batch in expiry["batches"]:
        at_risk[batch["branch"]] = at_risk.get(batch["branch"], Decimal("0.00")) + Decimal(batch["value"])

    catalogue = Medicine.objects.filter(pharmacy__in=branches, is_active=True).values("pharmacy_id").annotate(medicines=Count("id"))
    catalogue_by_branch = {str(row["pharmacy_id"]): row["medicines"] for row in catalogue}

    scorecard = []
    for branch in branches:
        key = str(branch.pk)
        sold = sales.get(key, {"revenue": "0.00", "units": 0})
        scorecard.append(
            {
                "branch_id": key,
                "branch": branch.name,
                "branch_code": branch.branch_code,
                "revenue": sold["revenue"],
                "units_sold": sold["units"],
                "medicines": catalogue_by_branch.get(key, 0),
                "value_at_risk": str(at_risk.get(branch.name, Decimal("0.00"))),
            }
        )
    scorecard.sort(key=lambda row: Decimal(row["revenue"]), reverse=True)
    return scorecard


def sales_csv(organization, window: DateWindow, *, scoped_ids=None) -> str:
    """Sales as CSV text, one row per line item.

    Built in memory rather than streamed to disk: an organisation's monthly
    export is tens of thousands of rows at most, and a file on disk would have
    to be cleaned up on every failure path. When that stops being true the
    change is local to this function.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["branch", "branch_code", "sold_at", "medicine", "batch_number", "quantity", "unit_price", "line_total", "currency"])
    # A sale line is satisfied from one or more batches (FEFO allocation), so the
    # batch numbers come from the line's allocations rather than from a single
    # column on the line --- there is no such column, and assuming one would make
    # the export raise for every organisation that has ever recorded a sale.
    lines = (
        SaleLine.objects.filter(window.q("sale__sold_at"), sale__pharmacy__organization=organization)
        .select_related("sale", "sale__pharmacy", "medicine")
        .prefetch_related("allocations__batch")
        .order_by("sale__sold_at", "id")
    )
    if scoped_ids is not None:
        lines = lines.filter(sale__pharmacy_id__in=list(scoped_ids))
    currency = organization.currency or "BDT"
    for line in lines:
        batches = sorted({allocation.batch.batch_number for allocation in line.allocations.all() if allocation.batch_id})
        writer.writerow(
            [
                line.sale.pharmacy.name,
                line.sale.pharmacy.branch_code,
                timezone.localtime(line.sale.sold_at).isoformat(),
                line.medicine.brand_name if line.medicine_id else "",
                "/".join(batches),
                line.quantity,
                line.unit_price,
                (line.unit_price or Decimal("0.00")) * line.quantity,
                currency,
            ]
        )
    return buffer.getvalue()


def expiry_csv(organization, *, days: int = 90, scoped_ids=None) -> str:
    """Every batch inside the expiry horizon, soonest first."""
    summary = expiry_summary(organization, days=days, scoped_ids=scoped_ids)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["branch", "medicine", "batch_number", "expiry_date", "days_left", "units", "value_at_cost", "currency"])
    currency = organization.currency or "BDT"
    for row in summary["batches"]:
        writer.writerow([row["branch"], row["medicine"], row["batch_number"], row["expiry_date"], row["days_left"], row["units"], row["value"], currency])
    return buffer.getvalue()
