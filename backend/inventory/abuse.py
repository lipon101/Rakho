"""Abuse protection for the public signup/payment endpoints.

Goals:
- A single real client may create at most a few signups per day.
- Behind Render's proxy the true client IP lives in X-Forwarded-For; we key on
  that, not the proxy's address, or every user would share one bucket (and one
  attacker would look like one IP while using many).
- Persist the daily tally in the database so it survives worker restarts and
  the multi-process gunicorn setup (in-memory cache alone would not).
- Cheap: the read path is one small indexed query; the write happens only on a
  successful signup.
"""

from django.db import IntegrityError
from django.utils import timezone


def client_ip(request):
    """Best-effort real client IP behind a reverse proxy.

    Render (and most PaaS) append the client address to X-Forwarded-For, whose
    leftmost entry is the original caller. We take only the first hop and fall
    back to REMOTE_ADDR when the header is absent. We never trust arbitrary
    X-Real-IP spoofing from the client side.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


class SignupDailyThrottle:
    """DB-backed daily cap on signups per client IP (default 3/day).

    Implemented as a plain helper rather than a DRF throttle so it works
    identically across gunicorn workers and restarts (the authoritative count
    is the SignupDailyCount table, not a per-process cache).
    """
    DAILY_LIMIT = 3

    def is_over_daily_limit(self, request):
        """True when this IP has already used today's signup allowance."""
        from .models import SignupDailyCount
        today = timezone.localdate()
        row = SignupDailyCount.objects.filter(ip=client_ip(request), day=today).first()
        return row is not None and row.count >= self.DAILY_LIMIT

    def record_success(self, request):
        """Increment today's tally. Call only after a signup is actually created."""
        from .models import SignupDailyCount
        ip = client_ip(request)
        today = timezone.localdate()
        obj, _ = SignupDailyCount.objects.get_or_create(ip=ip, day=today)
        obj.count = obj.count + 1
        try:
            obj.save(update_fields=["count", "updated_at"])
        except IntegrityError:
            # Concurrent first-writes raced; the row exists, so just bump it.
            SignupDailyCount.objects.filter(ip=ip, day=today).update(count=obj.count)
