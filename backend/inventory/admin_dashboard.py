"""Live admin dashboard stats.

Every number is computed fresh from the database on each page load — nothing is
cached or hardcoded, so the owner always sees the true current state.

Only four things are reported, because only four things are the owner's to act
on: the shops, their API keys, their subscriptions and the payments waiting to
be verified. Per-pharmacy inventory is the app's business, not the console's.
"""

import math

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from .pricing import pro_price_bdt

from .models import (
    CatalogMedicine, Pharmacy, PharmacyApiKey, SignupRequest, Subscription,
)

# The signup chart's window. Two weeks is long enough to show a direction and
# short enough that a quiet week still reads as a shape rather than as noise.
TREND_DAYS = 14

# Axis ceilings the chart is allowed to use. An axis scaled to the exact peak
# ("max: 3") reads as noise; rounding up to a clean even number gives tick
# labels a human would actually write. Even, so the halfway line is a whole
# number too — "1.5 signups" on an axis is nonsense.
_NICE_STEPS = (2, 4, 6, 8, 10, 12, 16, 20, 24, 30, 40, 50, 60, 80, 100, 150, 200)


def _last_n_days(n):
    today = timezone.localdate()
    return [today - timezone.timedelta(days=i) for i in range(n - 1, -1, -1)]


def _axis_ceiling(peak):
    """The smallest clean, even axis maximum that still fits `peak`."""
    for step in _NICE_STEPS:
        if peak <= step:
            return step
    return int(math.ceil(peak / 50.0) * 50)


def _signup_chart(signups, now):
    """Geometry for the 14-day signup chart, computed where the data is.

    The template gets finished coordinates rather than numbers to do arithmetic
    on. Django templates cannot loop with a running index or divide, and the
    filtering/annotation work has to happen in Python anyway, so splitting the
    maths across the two would be the only way to get this wrong.

    Coordinates are per-cent of the plot box, so the SVG can be stretched to any
    width without the caller knowing the pixel size. y=0 is the top of the box
    (the axis ceiling) and y=100 is the baseline.
    """
    days = _last_n_days(TREND_DAYS)
    # TruncDate converts to the project timezone (Asia/Dhaka) before bucketing.
    # date(created_at) bucketed in UTC against a locally-labelled axis, so a
    # signup placed late in the Dhaka evening was counted on the previous day.
    per_day = (
        signups.filter(created_at__gte=now - timezone.timedelta(days=TREND_DAYS - 1))
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(n=Count("id"))
    )
    counts_by_day = {str(row["day"]): row["n"] for row in per_day}
    values = [counts_by_day.get(day.isoformat(), 0) for day in days]

    peak = max(values)
    ceiling = _axis_ceiling(peak)
    total = sum(values)
    last_index = len(days) - 1
    # Inset the first and last points so their dots are not sliced in half by the
    # edges of the plot.
    inset = 1.6

    def x_at(index):
        return round(inset + index * (100.0 - 2 * inset) / last_index, 2)

    points = [
        {
            "x": x_at(index),
            "y": round(100.0 - (value / ceiling) * 100.0, 2),
            "value": value,
            "label": day.strftime("%d %b"),
            # Fourteen dates will not fit under any width this panel gets. Show
            # the ends (so the window is unambiguous) plus every third day, and
            # drop any label that would collide with the final one.
            "show_label": (
                index == 0
                or index == last_index
                or (index % 3 == 0 and last_index - index >= 2)
            ),
        }
        for index, (day, value) in enumerate(zip(days, values))
    ]

    line = " ".join(f"{point['x']},{point['y']}" for point in points)
    # The fill runs out to the plot edges so the shaded area reads as a block
    # rather than as a polygon floating inside the panel.
    area = (
        "M0,100 "
        + " ".join(f"L{p['x']},{p['y']}" for p in points)
        + " L100,100 Z"
    )

    if peak:
        busiest = days[values.index(peak)]
        summary = (f"{total} in this period · busiest {busiest.strftime('%d %b')}"
                   f" with {peak}")
    else:
        summary = "no signups in this period"

    return {
        "points": points,
        "line": line,
        "area": area,
        "total": total,
        "peak": peak,
        "summary": summary,
        # y position and label of each gridline, top-down. The labels are the
        # real axis values, so a reader can check the line against the numbers.
        "ticks": [
            {"pct": 0, "label": ceiling},
            {"pct": 50, "label": ceiling // 2},
            {"pct": 100, "label": 0},
        ],
    }


def dashboard_stats():
    """Real, current figures for the owner console landing page."""
    now = timezone.now()
    thirty_days_ago = now - timezone.timedelta(days=30)

    pharmacies = Pharmacy.objects.count()
    pharmacies_total = pharmacies
    api_keys_total = PharmacyApiKey.objects.count()
    api_keys_active = PharmacyApiKey.objects.filter(revoked_at__isnull=True).count()

    signups = SignupRequest.objects.all()
    signups_total = signups.count()
    pending_payment = signups.filter(status=SignupRequest.Status.PAID_REVIEW).count()

    subscriptions = Subscription.objects.all()
    active_paid = subscriptions.filter(
        ~Q(plan=Subscription.Plan.FREE)
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate()))
    active_pro = active_paid.count()
    # Free vs paid split the owner steers from the console.
    free_pharmacies = pharmacies_total - active_pro

    pro_price = pro_price_bdt()
    monthly_revenue = active_pro * pro_price

    catalog_count = CatalogMedicine.objects.count()

    # The "needs attention" list used to live here and render as a panel on the
    # right. It went because most of what it said was already on the page in a
    # louder form — a payment to verify is the amber card *and* the header
    # badge — so a permanent block repeating it was the console arguing with
    # itself. The one signal that lost its home, a shop that cannot sign in,
    # still shows up as Active API keys reading 0 against a non-zero Pharmacies.

    return {
        "catalog_count": catalog_count,
        "pharmacies": pharmacies,
        "api_keys_active": api_keys_active,
        "api_keys_total": api_keys_total,
        "signups_total": signups_total,
        "pending_payment": pending_payment,
        "active_pro": active_pro,
        "free_pharmacies": free_pharmacies,
        "monthly_revenue": f"৳{monthly_revenue:,}",
        "pro_price": f"৳{pro_price}",
        "signups_last_30d": signups.filter(created_at__gte=thirty_days_ago).count(),
        "chart": _signup_chart(signups, now),
        "generated_at": now,
    }
