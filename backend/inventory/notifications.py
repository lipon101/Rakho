"""Outbound email and in-app notifications.

One module for both because they answer the same question --- "who needs to be
told, and how" --- and keeping them together means an expiry digest and the
in-app banner that mirrors it cannot drift apart.

Nothing here raises on a delivery failure. A digest that could not be sent is a
disappointment; a digest that crashed the nightly job it ran inside is an
outage, and the second is strictly worse than the first. Every send therefore
reports what happened instead of throwing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger("inventory.notifications")


@dataclass
class DeliveryResult:
    """What happened to one notification. Returned, never raised."""

    sent: int = 0
    skipped: int = 0
    failures: list = field(default_factory=list)

    def record_failure(self, recipient: str, reason: str) -> None:
        self.failures.append({"recipient": recipient, "reason": reason})

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def attempted(self) -> int:
        return self.sent + len(self.failures)

    def as_dict(self) -> dict:
        return {
            "sent": self.sent,
            "skipped": self.skipped,
            "failed": len(self.failures),
            "failures": self.failures[:20],
        }


def send_email(
    *,
    subject: str,
    template: str,
    context: dict,
    to: list,
    reply_to: list | None = None,
    result: DeliveryResult | None = None,
) -> DeliveryResult:
    """Render and send one message to one or more addresses.

    An address-less recipient is counted as skipped rather than failed. The
    invitation flow can legitimately have no address to reach (an organisation
    created without a billing contact), and reporting that as a failure would
    make a healthy nightly run look broken.
    """
    result = result or DeliveryResult()
    recipients = [address for address in (to or []) if address and "@" in address]
    if not recipients:
        result.skipped += 1
        return result

    body = render_to_string(f"inventory/email/{template}.txt", context)
    subject_line = f"[Rakho] {subject}" if not subject.startswith("[Rakho]") else subject
    message = EmailMultiAlternatives(
        subject=subject_line,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
        reply_to=reply_to or None,
    )
    html = render_to_string(f"inventory/email/{template}.html", context)
    if html.strip():
        message.attach_alternative(html, "text/html")

    try:
        message.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 - a send failure is reported, not raised
        logger.warning("email '%s' to %s failed: %s", template, recipients, exc)
        for address in recipients:
            result.record_failure(address, type(exc).__name__)
        return result

    result.sent += len(recipients)
    return result


def invitation_email(invitation, raw_token: str) -> DeliveryResult:
    """The one message an invitation produces.

    Sent with a plain-text body *and* an HTML alternative, because a shop
    manager on a phone with a slow connection reads the text part and a
    desktop user gets the button. The link appears verbatim in both so it can
    be copied even when a mail client mangles the anchor.
    """
    accept_url = f"{settings.SITE_URL.rstrip('/')}/console/join?token={raw_token}"
    context = {
        "organisation": invitation.organization.name,
        "role": invitation.role,
        "inviter": getattr(invitation.invited_by, "display_name", None) or invitation.organization.name,
        "accept_url": accept_url,
        "expires_at": invitation.expires_at,
        "site_url": settings.SITE_URL,
        "product_name": "Rakho",
    }
    return send_email(
        subject=f"{context['organisation']} invited you to Rakho",
        template="invitation",
        context=context,
        to=[invitation.email],
        reply_to=[settings.DEFAULT_FROM_EMAIL],
    )


def expiry_digest_email(organization, summary, *, recipient=None) -> DeliveryResult:
    """The nightly "what is about to expire" summary.

    ``summary`` is produced by ``reports.expiry_summary``, so the email and the
    screen a manager opens in the morning are computed by the same function.
    Two implementations of "expiring soon" would eventually disagree, and the
    one nobody re-reads --- the email --- would be the one that drifted.
    """
    to = [recipient] if recipient else [organization.billing_email or ""]
    context = {
        "organisation": organization.name,
        "today": timezone.localdate(),
        "buckets": summary["buckets"],
        "totals": summary["totals"],
        "branches": summary["branches"],
        "dashboard_url": f"{settings.SITE_URL.rstrip('/')}/console/expiry",
        "site_url": settings.SITE_URL,
        "product_name": "Rakho",
    }
    return send_email(
        subject=f"{summary['totals']['soon']} batches expiring in the next 30 days",
        template="expiry_digest",
        context=context,
        to=to,
    )
