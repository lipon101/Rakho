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
    """Real client IP behind Render's reverse proxy.

    Render appends the true client address to X-Forwarded-For, so the
    RIGHTMOST entry is the only one the trusted proxy added — every entry to
    its left is client-controlled and trivially spoofed. Keying on the
    leftmost value would let an attacker rotate fake IPs and defeat the daily
    signup cap entirely. Falls back to REMOTE_ADDR when the header is absent.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
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
