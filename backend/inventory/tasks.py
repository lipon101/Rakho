"""Background jobs: the work that must not happen inside a request.

Four rules shape this module, and each one came from a specific way a task
queue goes wrong:

* **One task per tenant, not one for all tenants.** A nightly digest that
  loops over every organisation is a single point of failure: one tenant with
  a broken address aborts the run and nobody gets a digest. Each tenant gets
  its own task, with its own retry budget.
* **Idempotent by construction.** ``acks_late`` and automatic retries mean a
  task can run twice; every task here either checks whether its effect already
  exists or writes a result that is stable under repetition.
* **No unbounded retries.** ``max_retries`` is small and finite. A task that
  keeps failing should end up in the dead-letter path where somebody sees it,
  not retry until the morning.
* **The body is a plain function call.** The task wrapper resolves ids and
  delegates to a service, so the logic can be tested without a broker ---
  which is exactly how the suite exercises it, in eager mode.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from . import notifications, org_billing, org_services, reports
from .models import Organization, StaffInvitation

logger = logging.getLogger("inventory.tasks")

#: A retry after a transient SMTP or network failure. Small and finite on
#: purpose: three attempts spans roughly five minutes, which covers a blip
#: without holding a worker slot for an hour.
RETRY_BACKOFF = 60
MAX_RETRIES = 3


@shared_task(bind=True, max_retries=MAX_RETRIES, acks_late=True)
def send_invitation_email(self, invitation_id: str):
    """Deliver one invitation.

    The raw token is *not* stored, so it is passed in the message rather than
    re-read from the row. That is why the task takes the token as an argument:
    a queued email that could not be recovered from the database is the price
    of never persisting a credential that admits somebody into a tenant.
    """
    try:
        invitation = StaffInvitation.objects.select_related("organization", "invited_by").get(pk=invitation_id)
    except StaffInvitation.DoesNotExist:
        # Revoked between enqueue and execution. Nothing to send, and nothing
        # to retry: the outcome the caller wanted has already happened.
        logger.info("invitation %s no longer exists; skipping email", invitation_id)
        return {"status": "gone"}

    raw_token = self.request.kwargs.get("raw_token") or getattr(self.request, "raw_token", None)
    if not raw_token:
        return {"status": "no_token"}
    if invitation.status != StaffInvitation.Status.PENDING:
        return {"status": "not_pending", "invitation_status": invitation.status}

    result = notifications.invitation_email(invitation, raw_token)
    if not result.ok:
        invitation.last_send_error = "; ".join(f"{f['recipient']}: {f['reason']}" for f in result.failures)[:500]
        invitation.save(update_fields=["last_send_error", "updated_at"])
        raise self.retry(countdown=RETRY_BACKOFF * (self.request.retries + 1))
    if invitation.last_send_error:
        invitation.last_send_error = ""
        invitation.save(update_fields=["last_send_error", "updated_at"])
    return result.as_dict()


@shared_task(bind=True, max_retries=MAX_RETRIES, acks_late=True)
def send_expiry_digest(self, organization_id: str, days: int = 30):
    """The nightly expiry summary for one organisation.

    A tenant with nothing expiring is skipped rather than emailed: a daily
    message that says "nothing to report" is how a genuinely urgent alert gets
    filtered into a folder nobody opens.
    """
    try:
        organization = Organization.objects.get(pk=organization_id, is_active=True)
    except Organization.DoesNotExist:
        return {"status": "gone"}

    summary = reports.expiry_summary(organization, days=days)
    if summary["totals"]["batches"] == 0:
        return {"status": "nothing_to_report", "organization": organization.slug}

    result = notifications.expiry_digest_email(organization, summary)
    if not result.ok:
        raise self.retry(countdown=RETRY_BACKOFF * (self.request.retries + 1))
    return {**result.as_dict(), "organization": organization.slug}


@shared_task
def queue_expiry_digests(days: int = 30):
    """Fan the nightly digest out into one task per organisation.

    ``queue_expiry_digests`` sends no mail itself, so a tenant that fails does
    not affect the others and the whole fan-out is one cheap query.
    """
    organization_ids = list(Organization.objects.filter(is_active=True).exclude(billing_email="").values_list("id", flat=True))
    for organization_id in organization_ids:
        send_expiry_digest.delay(str(organization_id), days)
    return {"queued": len(organization_ids)}


@shared_task(bind=True, max_retries=MAX_RETRIES, acks_late=True)
def expire_stale_invitations(self):
    """Close invitations that lapsed without being answered.

    Needed because a lapsed invitation holds a seat. Without this job an owner
    who invited somebody who never replied would be told the plan is full with
    no visible reason --- the pending row is invisible in the team list, which
    shows members.
    """
    now = timezone.now()
    stale = StaffInvitation.objects.filter(status=StaffInvitation.Status.PENDING, expires_at__lt=now)
    count = stale.update(status=StaffInvitation.Status.EXPIRED, updated_at=now)
    return {"expired": count}


@shared_task(bind=True, max_retries=MAX_RETRIES, acks_late=True)
def sync_organization_billing(self):
    """Re-derive every tenant's seat add-on floor and flag over-allowance.

    A nightly reconciliation rather than a live computation, because both
    numbers depend on how many branches and members exist *now* --- and a
    mid-month snapshot would make an invoice disagree with the console the
    owner is looking at when they call to complain.
    """
    checked = 0
    over = []
    for organization in Organization.objects.filter(is_active=True).iterator(chunk_size=200):
        quote = org_billing.quote(organization)
        if quote["over_allowance"]:
            over.append(organization.slug)
        checked += 1
    return {"checked": checked, "over_allowance": over}


@shared_task(bind=True, max_retries=MAX_RETRIES, acks_late=True)
def reconcile_abandoned_signups(self, hours: int = 48):
    """Note self-serve signups that never activated anything.

    This is a *sales* signal, not a cleanup job: a shop that took an API key
    and recorded no stock within two days is a shop worth calling, and the
    only way to see them is to look. Deliberately does not delete anything ---
    the pharmacy keeps working exactly as it did.
    """
    from datetime import timedelta

    from .models import Pharmacy

    cutoff = timezone.now() - timedelta(hours=hours)
    quiet = Pharmacy.objects.filter(created_at__lt=cutoff, is_active=True).filter(Q(medicines__isnull=True) & Q(batches__isnull=True)).distinct().values_list("name", flat=True)[:100]
    names = list(quiet)
    if names:
        logger.info("signups with no stock yet: %s", ", ".join(names[:10]))
    return {"quiet_signups": len(names), "names": names}


@shared_task(bind=True, max_retries=MAX_RETRIES, acks_late=True)
def build_export(self, *, organization_id: str, kind: str = "sales", requested_by: str = "", days: int = 30):
    """Render a large export away from the request and park it in storage.

    The synchronous export endpoint caps its row count, so this is where the
    request that exceeds the cap lands. It writes the same CSV the synchronous
    path would have written and returns its storage path, which keeps the two
    paths from drifting into different formats --- a customer who exports this
    month via the API and last month via this job must get the same columns.
    """
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    try:
        organization = Organization.objects.get(pk=organization_id)
    except Organization.DoesNotExist:
        return {"status": "gone"}

    window = reports.DateWindow.last_days(days, organization=organization)
    if kind == "expiry":
        text = reports.expiry_csv(organization)
        filename = f"expiry-{timezone.localdate().isoformat()}.csv"
    else:
        text = reports.sales_csv(organization, window)
        filename = f"sales-{window.start.isoformat()}-to-{(window.end - timezone.timedelta(days=1)).isoformat()}.csv"

    # Encoded with a BOM so Excel on Windows opens the Bengali product names
    # correctly, matching the synchronous download byte for byte.
    path = default_storage.save(f"exports/{organization.slug}/{filename}", ContentFile(text.encode("utf-8-sig")))
    logger.info("export ready organization=%s kind=%s path=%s requested_by=%s", organization.slug, kind, path, requested_by)
    return {"status": "ready", "path": path, "rows": max(text.count("\n") - 1, 0), "kind": kind, "organization": organization.slug}


@shared_task(bind=True, max_retries=MAX_RETRIES, acks_late=True)
def generate_monthly_invoices(self, *, period_start: str | None = None, period_end: str | None = None):
    """Draft one invoice per active organisation for the period just ended.

    Drafts, never issued: an invoice that emails itself to fifty customers
    without a human looking at the first one is a billing incident waiting for
    a bad month. The job produces the pile, an operator approves it, and only
    then does anything leave the building.
    """
    from datetime import date

    from . import invoicing

    if period_start and period_end:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
    else:
        today = timezone.localdate()
        first_of_this_month = today.replace(day=1)
        end = first_of_this_month - timezone.timedelta(days=1)
        start = end.replace(day=1)

    drafted, skipped = [], []
    for organization in Organization.objects.filter(is_active=True).iterator(chunk_size=200):
        if organization.plan in (Organization.Plan.FREE,):
            # A free tenant is never invoiced. Skipping here rather than in the
            # invoice service keeps the service's contract simple --- it always
            # bills what it is given --- and puts the commercial rule where a
            # reader looks for it.
            skipped.append(organization.slug)
            continue
        invoice = invoicing.draft_invoice(organization, period_start=start, period_end=end)
        drafted.append(invoice.number)
    return {"drafted": len(drafted), "skipped": len(skipped), "period_start": start.isoformat(), "period_end": end.isoformat()}


@shared_task
def cleanup_expired_exports(days: int = 30):
    """Delete export files that have outlived their usefulness.

    An export lands in storage and is never opened again in almost every case,
    so without this the bucket grows by every report anyone ever ran. The
    default window is a month, long enough that a finance team reconciling at
    month end still finds the file it downloaded a fortnight ago.
    """
    from datetime import timedelta

    from django.core.files.storage import default_storage
    from django.utils import timezone as dj_timezone

    cutoff = dj_timezone.now() - timedelta(days=days)
    removed = 0
    prefix = "exports/"
    try:
        directories, _files = default_storage.listdir(prefix)
    except (NotImplementedError, FileNotFoundError):
        # Some storage backends cannot list; nothing to do and nothing broken.
        return {"status": "unsupported"}

    for organization_dir in directories:
        try:
            _, names = default_storage.listdir(f"{prefix}{organization_dir}")
        except (NotImplementedError, FileNotFoundError):
            continue
        for name in names:
            path = f"{prefix}{organization_dir}/{name}"
            try:
                modified = default_storage.get_modified_time(path)
            except (NotImplementedError, OSError):
                continue
            if modified < cutoff:
                default_storage.delete(path)
                removed += 1
    return {"removed": removed, "older_than_days": days}


# ── Test-support helper ─────────────────────────────────────────────────


def deliver_invitation_now(invitation, raw_token, *, request=None):
    """Send an invitation inline, falling back to the queue on failure.

    Called from the request path. Sending inline is the right default for a
    single invitation --- the person is waiting, and an email that arrives in
    four minutes feels broken. The queue is the *fallback*: if inline delivery
    fails (SMTP down, credentials rotated), the invitation still exists and the
    owner still gets the copyable link from the API response, so nothing is
    lost by deferring the retry.
    """
    result = notifications.invitation_email(invitation, raw_token)
    if result.ok:
        return result
    invitation.last_send_error = "; ".join(f"{f['recipient']}: {f['reason']}" for f in result.failures)[:500]
    invitation.save(update_fields=["last_send_error", "updated_at"])
    try:
        send_invitation_email.apply_async(args=[str(invitation.pk)], kwargs={"raw_token": raw_token})
    except Exception:  # noqa: BLE001 - a broker outage must not fail the invite
        logger.exception("could not queue the invitation email for %s", invitation.pk)
    return result


def provision_owner_membership(*, organization, user, request=None):
    """Attach a user to a tenant as its owner, idempotently.

    Used when an organisation gains its first console account after a
    self-serve signup. Kept here rather than in ``org_services`` so the
    signup path and the console path share one implementation.
    """
    from .models import OrgMembership

    membership = OrgMembership.objects.filter(organization=organization, user=user).first()
    if membership is not None:
        return membership
    return org_services.create_owner_membership(organization=organization, user=user, request=request)
