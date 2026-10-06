"""Organisation services: creating tenants, inviting people, managing seats.

Every function here is a unit of business work that touches more than one row,
so every one is atomic. The alternative --- letting the view do it --- produces
the failure this module exists to prevent: an invitation that was emailed but
not recorded, or a membership that was created after the seat limit had already
been exceeded, because the check and the write were two separate round trips.

The seat limit is the single most important thing in this file. It is checked
immediately before the write that would exceed it, inside the same transaction,
against a counted value --- not against a cached number and not before the
transaction opens.
"""

import logging
import secrets

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from . import audit
from .models import AuditLog, Organization, OrgMembership, Pharmacy, StaffInvitation
from .org_billing import active_seat_count, included_seats

logger = logging.getLogger("inventory")


class SeatLimitReached(Exception):
    """Raised when an action would occupy a seat the plan does not cover.

    A distinct exception rather than a permission error, because the fix is
    commercial (buy a seat) rather than administrative (ask an admin). The view
    turns it into a 402-shaped response the console can act on.
    """

    def __init__(self, used, included):
        self.used = used
        self.included = included
        super().__init__(f"All {included} seats in the plan are in use ({used} active).")


class DuplicateInvitation(Exception):
    """A live invitation already exists for this address."""


class AlreadyMember(Exception):
    """The address already belongs to an active member of this organisation.

    Distinct from ``DuplicateInvitation`` because the two need different words:
    a duplicate invitation is something to wait for, whereas an existing member
    needs no invitation at all --- and telling an owner to "buy a seat" for
    someone who already has one is worse than a generic refusal.
    """

    def __init__(self, email):
        super().__init__(f"{email} is already a member of this organisation.")


def unique_slug(name, model=Organization, field="slug"):
    """A slug that is unique, derived from ``name``.

    Deterministic rather than random: a customer's invoice reference should read
    like their company, not like a UUID, and ``-2`` is easier to explain than a
    hash when two companies share a name.
    """
    base = slugify(name)[:100] or "org"
    candidate = base
    counter = 2
    while model.objects.filter(**{field: candidate}).exists():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


@transaction.atomic
def create_organization(
    *,
    name,
    owner_user=None,
    legal_name="",
    bin="",
    currency="BDT",
    timezone_name="Asia/Dhaka",
    locale="bn",
    trial_days=None,
    request=None,
):
    """Create a tenant, optionally with its first branch and owner.

    The trial is started here rather than lazily on first sign-in, so the
    countdown a customer sees is the countdown the billing engine will use.
    """
    from django.conf import settings

    days = settings.ORG_TRIAL_DAYS if trial_days is None else trial_days
    organization = Organization.objects.create(
        name=name,
        slug=unique_slug(name),
        legal_name=legal_name or name,
        bin=bin,
        currency=currency,
        timezone=timezone_name,
        locale=locale,
        plan=Organization.Plan.TRIAL,
        trial_ends_on=(timezone.localdate() + timezone.timedelta(days=days)) if days else None,
    )
    if owner_user is not None:
        OrgMembership.objects.create(
            user=owner_user,
            organization=organization,
            role=OrgMembership.Role.OWNER,
            joined_at=timezone.now(),
        )
    audit.record(
        request,
        AuditLog.Action.CREATE,
        organization=organization,
        target=organization,
        changes={"name": {"from": None, "to": name}},
        note=f"trial {days} days",
    )
    return organization


@transaction.atomic
def create_branch(organization, *, name, branch_code="", actor=None, request=None, **fields):
    """Add a branch, enforcing the branch allowance at the point of write.

    A branch beyond the allowance is allowed but billed, so the check here is a
    note rather than a refusal --- the opposite of the seat rule, and
    deliberately so: a chain opening a shop must not be blocked by a billing
    setting at 9pm, and the extra branch is money the platform is happy to earn.
    """
    # The uniqueness rule is a database constraint, because two admins can
    # submit the same branch code in the same second and only the database sees
    # both. Catching the violation here turns a 500 into the 400 a form can
    # render: the constraint is the authority, and this only translates it.
    try:
        with transaction.atomic():
            branch = Pharmacy.objects.create(organization=organization, name=name, branch_code=branch_code, **fields)
    except IntegrityError as exc:
        if "branch_code" in str(exc):
            raise DjangoValidationError(f"Branch code '{branch_code}' is already used in this organisation.") from exc
        raise

    # A branch without a device credential cannot be used: the Android app
    # authenticates with an API key, and an admin who creates a branch in the
    # console has no other way to obtain one. Minting it here means "create a
    # branch" is a complete action rather than one that leaves a follow-up only
    # an operator can perform. The raw key is returned to the caller exactly
    # once, like every other key in this codebase.
    raw_key = None
    try:
        from .models import PharmacyApiKey

        _, raw_key = PharmacyApiKey.create_key(branch, f"Branch {name}"[:60])
    except Exception:  # noqa: BLE001 - a key failure must not lose the branch
        logger.exception("could not mint an API key for new branch %s", branch.pk)

    over_allowance = organization.pharmacies.filter(is_active=True).count() > organization.branch_allowance
    audit.record(
        request,
        AuditLog.Action.CREATE,
        organization=organization,
        pharmacy=branch,
        target=branch,
        changes={"name": {"from": None, "to": name}, "branch_code": {"from": None, "to": branch_code}},
        note="beyond plan allowance, billable" if over_allowance else "within plan allowance",
    )
    return branch, raw_key


@transaction.atomic
def provision_organization_for_signup(*, pharmacy, owner_name="", contact_phone="", request=None):
    """Give a brand-new self-serve signup its tenant, in one step.

    Called from the public signup endpoint, so it runs on a completely
    unauthenticated request and must therefore be *idempotent*: a form re-posted
    after a timeout, or a retried mobile request, would otherwise create a
    second organisation and a second branch for the same shop --- and the owner
    would have two tenants, one of which they can never find.

    The shop is made the organisation's first branch rather than being left
    detached, so multi-tenancy is on from the very first request. A one-shop
    customer notices nothing: a one-branch organisation behaves exactly like a
    standalone pharmacy, and the branch list simply has one row in it.

    No user account is created here. The signup flow hands back an API key for
    the Android app; a console login is a separate, later step, and inventing a
    password on the customer's behalf would be worse than asking them for one.
    """
    # Already provisioned: return the existing tenant unchanged.
    if pharmacy.organization_id is not None:
        organization = pharmacy.organization
        membership = OrgMembership.objects.filter(organization=organization, role=OrgMembership.Role.OWNER).select_related("user").first()
        return organization, membership

    display_name = owner_name.strip() or pharmacy.name
    organization = Organization.objects.create(
        name=pharmacy.name,
        slug=unique_slug(pharmacy.name),
        legal_name=pharmacy.name,
        phone=contact_phone or pharmacy.phone or "",
        address=pharmacy.address or "",
        currency=pharmacy.currency or "BDT",
        timezone=pharmacy.timezone or "Asia/Dhaka",
        locale="bn",
        plan=Organization.Plan.FREE,
        # One branch's worth of allowance, which is exactly what this customer
        # has. A second shop is a paid upgrade, and the pricing engine already
        # describes that without a special case.
        branch_allowance=1,
    )
    pharmacy.organization = organization
    pharmacy.branch_code = pharmacy.branch_code or "MAIN"
    pharmacy.save(update_fields=["organization", "branch_code", "updated_at"])

    audit.record(
        request,
        AuditLog.Action.CREATE,
        organization=organization,
        pharmacy=pharmacy,
        target=organization,
        changes={"name": {"from": None, "to": pharmacy.name}, "owner": {"from": None, "to": display_name}},
        note="self-serve signup",
    )
    return organization, None


def seats_available(organization):
    """How many seats remain unoccupied, or a negative number when over."""
    return included_seats(organization) - active_seat_count(organization)


@transaction.atomic
def invite_staff(organization, *, email, role, invited_by=None, default_pharmacy=None, expires_in_days=14, request=None):
    """Create an invitation, if a seat is free for it.

    The seat is reserved at invitation time, not at acceptance. That ordering is
    deliberate: an owner who has invited a sixth person should learn that it
    costs money *before* the message is sent, not when the person clicks the
    link and the invitation fails in their hands.
    """
    email = email.strip().lower()

    # Checked before the seat, and in this order on purpose. Inviting someone who
    # is already on the team is a no-op the caller should be told about, not a
    # purchase: if the seat check ran first, a full plan would answer "buy a
    # seat" for a person who needs no seat at all, which sends the owner to the
    # billing page for nothing.
    if OrgMembership.objects.filter(
        organization=organization,
        user__email__iexact=email,
        is_active=True,
    ).exists():
        raise AlreadyMember(email)

    if active_seat_count(organization) + pending_invitation_count(organization) >= included_seats(organization):
        audit.record(
            request,
            AuditLog.Action.SEAT_LIMIT_REACHED,
            organization=organization,
            target=("StaffInvitation", email),
            note=f"attempted to invite {email} with no seat free",
        )
        raise SeatLimitReached(active_seat_count(organization), included_seats(organization))

    raw_token = StaffInvitation.generate_raw_token()
    try:
        invitation = StaffInvitation.objects.create(
            organization=organization,
            email=email,
            role=role,
            token_hash=StaffInvitation.hash_token(raw_token),
            invited_by=invited_by,
            default_pharmacy=default_pharmacy,
            expires_at=timezone.now() + timezone.timedelta(days=expires_in_days),
        )
    except IntegrityError as exc:
        # The unique constraint on (organization, email, pending) is the backstop
        # for two admins inviting the same person at the same instant.
        raise DuplicateInvitation(email) from exc

    audit.record(
        request,
        AuditLog.Action.INVITE,
        organization=organization,
        target=invitation,
        changes={"email": {"from": None, "to": email}, "role": {"from": None, "to": role}},
    )
    return invitation, raw_token


def pending_invitation_count(organization):
    """Live invitations, expired ones excluded.

    An expired invitation must not hold a seat: otherwise an owner who invited
    someone who never replied would be unable to invite anyone else without
    manually revoking, which they have no way to discover they need to do.
    """
    return StaffInvitation.objects.filter(
        organization=organization,
        status=StaffInvitation.Status.PENDING,
        expires_at__gt=timezone.now(),
    ).count()


@transaction.atomic
def accept_invitation(raw_token, *, user, request=None, accept=True):
    """Turn an invitation into a membership, once --- or decline it.

    Two checks are re-run here rather than trusted from invitation time. The
    seat limit, because acceptance can happen days after the invitation was
    issued and another admin may have filled the plan in between --- a 402 is
    the honest answer there, since the invitation is valid but the plan is
    full. And the email address, because an invitation is addressed to a
    *person*: a forwarded link must not let whoever holds it join the tenant,
    which is the whole reason the invitation names an address rather than
    being a bearer token alone.
    """
    token_hash = StaffInvitation.hash_token(raw_token)
    invitation = StaffInvitation.objects.select_for_update().select_related("organization").filter(token_hash=token_hash).first()
    if invitation is None:
        raise LookupError("This invitation link is not valid.")
    if invitation.status != StaffInvitation.Status.PENDING:
        raise ValueError(f"This invitation has already been {invitation.get_status_display().lower()}.")
    if invitation.is_expired:
        invitation.status = StaffInvitation.Status.EXPIRED
        invitation.save(update_fields=["status", "updated_at"])
        raise ValueError("This invitation has expired. Ask an administrator to send a new one.")

    # The address is compared case-insensitively and after stripping, matching
    # how it was stored, so "Karim@Shop.test " is the same person.
    if (user.email or "").strip().lower() != invitation.email.strip().lower():
        raise PermissionError(f"This invitation was sent to {invitation.email}. Sign in as that address to accept it.")

    organization = invitation.organization

    if not accept:
        # Declining frees the reserved seat straight away. Waiting for the
        # expiry would leave an owner unable to invite a replacement for a
        # fortnight, with nothing in the UI explaining why.
        invitation.status = StaffInvitation.Status.REVOKED
        invitation.save(update_fields=["status", "updated_at"])
        audit.record(
            request,
            AuditLog.Action.UPDATE,
            organization=organization,
            target=invitation,
            note="invitation declined by the invitee",
        )
        return None

    existing = OrgMembership.objects.filter(organization=organization, user=user).first()
    if existing is not None:
        # Idempotent by design: a person who clicks the link twice, or who was
        # already a member, gets the role they were invited with rather than a
        # duplicate row or an error.
        existing.is_active = True
        existing.role = invitation.role
        existing.save(update_fields=["is_active", "role", "updated_at"])
        membership = existing
    else:
        if active_seat_count(organization) >= included_seats(organization):
            raise SeatLimitReached(active_seat_count(organization), included_seats(organization))
        membership = OrgMembership.objects.create(
            user=user,
            organization=organization,
            role=invitation.role,
            default_pharmacy=invitation.default_pharmacy,
            joined_at=timezone.now(),
        )

    invitation.status = StaffInvitation.Status.ACCEPTED
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["status", "accepted_at", "accepted_by", "updated_at"])

    audit.record(
        request,
        AuditLog.Action.INVITE_ACCEPTED,
        organization=organization,
        target=invitation,
        changes={"role": {"from": None, "to": invitation.role}, "user": {"from": None, "to": str(user.pk)}},
    )
    return membership


@transaction.atomic
def revoke_invitation(invitation, *, request=None):
    """Revoke a live invitation, freeing the seat it reserved."""
    if invitation.status != StaffInvitation.Status.PENDING:
        raise ValueError("Only a pending invitation can be revoked.")
    invitation.status = StaffInvitation.Status.REVOKED
    invitation.save(update_fields=["status", "updated_at"])
    audit.record(request, AuditLog.Action.UPDATE, organization=invitation.organization, target=invitation, note="invitation revoked")
    return invitation


@transaction.atomic
def change_role(membership, new_role, *, request=None):
    """Change a member's role, refusing to leave a tenant without an owner.

    An organisation with no owner cannot be administered at all --- nobody can
    change billing, invite, or restore a role. Refusing the last demotion is the
    difference between a recoverable mistake and a support escalation with no
    self-service fix.
    """
    if membership.role == OrgMembership.Role.OWNER and new_role != OrgMembership.Role.OWNER:
        other_owners = (
            OrgMembership.objects.filter(
                organization=membership.organization,
                role=OrgMembership.Role.OWNER,
                is_active=True,
            )
            .exclude(pk=membership.pk)
            .count()
        )
        if other_owners == 0:
            raise ValueError("An organisation must keep at least one owner.")

    before = membership.role
    membership.role = new_role
    membership.save(update_fields=["role", "updated_at"])
    audit.record(
        request,
        AuditLog.Action.ROLE_CHANGED,
        organization=membership.organization,
        target=membership,
        changes={"role": {"from": before, "to": new_role}},
    )
    return membership


@transaction.atomic
def deactivate_membership(membership, *, request=None):
    """Remove a person's access, freeing their seat.

    The row is kept rather than deleted: an audit entry names the actor by a
    foreign key, and cascading the membership away would erase the attribution
    of everything that person ever did.

    The last owner cannot be removed. An organisation with no active owner
    cannot be administered at all --- nobody can change billing, invite anyone,
    or restore a role --- so \"remove the last owner\" is not a mistake the
    product can let a customer make and then fix for them. The same guard exists
    on role changes; it is repeated here because a removal is a different code
    path and the earlier one does not cover it.
    """
    if membership.role == OrgMembership.Role.OWNER and membership.is_active:
        other_owners = (
            OrgMembership.objects.filter(
                organization=membership.organization,
                role=OrgMembership.Role.OWNER,
                is_active=True,
            )
            .exclude(pk=membership.pk)
            .count()
        )
        if other_owners == 0:
            raise ValueError("An organisation must keep at least one owner. Promote someone else first.")

    membership.is_active = False
    membership.save(update_fields=["is_active", "updated_at"])
    audit.record(
        request,
        AuditLog.Action.UPDATE,
        organization=membership.organization,
        target=membership,
        changes={"is_active": {"from": True, "to": False}},
        note="membership deactivated",
    )
    return membership


def seed_invitation_token():
    """A short, human-typable token for a channel that cannot carry a link.

    Kept separate from the URL token: a code read aloud over the phone should
    not be the same string that appears in a forwarded email.
    """
    return f"{secrets.randbelow(10**6):06d}"
