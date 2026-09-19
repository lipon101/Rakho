"""Live admin dashboard stats.

Every number is computed fresh from the database on each page load — nothing is
cached or hardcoded, so the owner always sees the true current state.
"""

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from .pricing import pro_price_bdt

from .models import (
    Batch, CatalogMedicine, Medicine, Pharmacy, PharmacyApiKey, PlayPurchaseEvent,
    Sale, SaleAllocation, SaleLine, SignupRequest, StockMovement, Subscription,
)


def model_counts():
    """One-row-per-model counts for the dashboard's "Manage data" cards."""
    return {
        "Pharmacy": Pharmacy.objects.count(),
        "PharmacyApiKey": PharmacyApiKey.objects.count(),
        "CatalogMedicine": CatalogMedicine.objects.count(),
        "Medicine": Medicine.objects.count(),
        "Batch": Batch.objects.count(),
        "Sale": Sale.objects.count(),
        "SaleLine": SaleLine.objects.count(),
        "SaleAllocation": SaleAllocation.objects.count(),
        "StockMovement": StockMovement.objects.count(),
        "PlayPurchaseEvent": PlayPurchaseEvent.objects.count(),
        "SignupRequest": SignupRequest.objects.count(),
        "Subscription": Subscription.objects.count(),
    }


def _last_n_days(n):
    today = timezone.localdate()
    return [today - timezone.timedelta(days=i) for i in range(n - 1, -1, -1)]


def dashboard_stats():
    """Real, current figures for the owner console landing page."""
    now = timezone.now()
    thirty_days_ago = now - timezone.timedelta(days=30)

    pharmacies = Pharmacy.objects.count()
    api_keys_total = PharmacyApiKey.objects.count()
    api_keys_active = PharmacyApiKey.objects.filter(revoked_at__isnull=True).count()

    signups = SignupRequest.objects.all()
    signups_total = signups.count()
    pending_payment = signups.filter(status=SignupRequest.Status.PAID_REVIEW).count()
    pending_review = signups.filter(status=SignupRequest.Status.PENDING).count()

    subscriptions = Subscription.objects.all()
    active_pro = subscriptions.filter(
        ~Q(plan=Subscription.Plan.FREE)
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate())).count()

    pro_price = pro_price_bdt()
    monthly_revenue = active_pro * pro_price

    catalog_count = CatalogMedicine.objects.count()

    # New signups per day, last 14 days, for the trend chart.
    # TruncDate converts to the project timezone (Asia/Dhaka) before bucketing.
    # The previous date(created_at) bucketed in UTC while the axis was labelled
    # with local dates, so a signup placed late in the Dhaka evening was counted
    # on the previous day. It also replaces the deprecated QuerySet.extra().
    days = _last_n_days(14)
    per_day = (
        signups.filter(created_at__gte=now - timezone.timedelta(days=13))
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(n=Count("id"))
    )
    counts_by_day = {str(row["day"]): row["n"] for row in per_day}
    trend = [counts_by_day.get(d.isoformat(), 0) for d in days]
    peak = max(trend) if trend else 0
    signups_14d = sum(trend)
    if peak:
        busiest = days[trend.index(peak)]
        trend_summary = (f"{signups_14d} in total, busiest {busiest.strftime('%d %b')} "
                         f"with {peak}")
    else:
        trend_summary = "no signups in this period"
    trend_bars = [
        {
            "label": d.strftime("%d %b"),
            "value": v,
            # Bar height as a percentage of the tallest day, so the chart always
            # fits the panel regardless of the numbers.
            "height": round((v / peak) * 100) if peak else 0,
        }
        for d, v in zip(days, trend)
    ]

    # Data-driven "needs attention" list. Only genuinely actionable problems
    # are listed, so an empty list honestly means there is nothing to chase.
    # The empty-catalogue item exists because name-search silently returns
    # nothing in that state, which is invisible from the outside.
    attention = []
    if pending_payment:
        attention.append({
            "tone": "amber",
            "text": (
                f"{pending_payment} payment"
                f"{'' if pending_payment == 1 else 's'} waiting to be verified"
            ),
            "action": "Review payments",
            "url": reverse("admin:inventory_signuprequest_changelist")
                   + "?status__exact=paid_review",
        })
    # Someone asked for a key and is still waiting. This was already counted
    # but never shown anywhere, so a lead could sit unanswered with the console
    # reporting everything as fine.
    if pending_review:
        attention.append({
            "tone": "amber",
            "text": (
                f"{pending_review} signup request"
                f"{'' if pending_review == 1 else 's'} awaiting a first response"
            ),
            "action": "Open requests",
            "url": reverse("admin:inventory_signuprequest_changelist")
                   + "?status__exact=pending",
        })
    if catalog_count == 0:
        attention.append({
            "tone": "rose",
            "text": "The medicine catalogue is empty, so catalogue name-search "
                    "returns nothing to the app.",
            "action": "Import catalogue",
            "url": reverse("admin:inventory_catalogmedicine_changelist"),
        })
    # A lockout means shops exist that nothing can sign in as. Having no keys at
    # all is the normal state of a service with no customers yet, so alarming on
    # that told the owner something was broken when nothing was.
    if pharmacies and api_keys_active == 0:
        attention.append({
            "tone": "rose",
            "text": (
                f"{pharmacies} registered shop"
                f"{'' if pharmacies == 1 else 's'} but no active API key — "
                "none of them can sign in."
            ),
            "action": "API keys",
            "url": reverse("admin:inventory_pharmacyapikey_changelist"),
        })

    return {
        "attention": attention,
        "catalog_count": catalog_count,
        "pharmacies": pharmacies,
        "api_keys_active": api_keys_active,
        "api_keys_total": api_keys_total,
        "signups_total": signups_total,
        "pending_payment": pending_payment,
        "pending_review": pending_review,
        "active_pro": active_pro,
        "monthly_revenue": f"৳{monthly_revenue:,}",
        "pro_price": f"৳{pro_price}",
        "trend_bars": trend_bars,
        "trend_summary": trend_summary,
        "signups_14d": signups_14d,
        "signups_last_30d": signups.filter(created_at__gte=thirty_days_ago).count(),
        "generated_at": now,
    }
