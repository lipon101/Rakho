"""Live admin dashboard stats.

Every number is computed fresh from the database on each page load — nothing is
cached or hardcoded, so the owner always sees the true current state.
"""

from django.db.models import Count, Q
from django.utils import timezone

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

    pro_price = 299  # BDT/month list price shown on the landing page
    monthly_revenue = active_pro * pro_price

    # New signups per day, last 14 days, for the trend chart.
    days = _last_n_days(14)
    per_day = (
        signups.filter(created_at__gte=now - timezone.timedelta(days=13))
        .extra(select={"day": "date(created_at)"})
        .values("day")
        .annotate(n=Count("id"))
    )
    counts_by_day = {str(row["day"]): row["n"] for row in per_day}
    trend = [counts_by_day.get(d.isoformat(), 0) for d in days]
    peak = max(trend) if trend else 0
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

    return {
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
        "signups_last_30d": signups.filter(created_at__gte=thirty_days_ago).count(),
        "generated_at": now,
    }
