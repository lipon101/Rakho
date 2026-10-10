"""The organisation API: /api/v1/org/...

This is the enterprise surface. Its whole job is to let a chain run itself ---
branches, people, roles, seats, billing, an audit trail --- without letting any
of that touch another chain. Three structural choices carry that weight:

* **Every view inherits ``OrgScopedView``**, which resolves the tenant from the
  authenticated principal. No view reads an organisation id from the request,
  so there is no field a caller can edit to reach another tenant.
* **Reads are scoped, not filtered.** A list endpoint queries
  ``self.org.visible_pharmacies()`` rather than fetching everything and filtering
  in Python, so a branch restriction travels into the SQL instead of depending on
  a developer remembering a comprehension.
* **Mutations go through ``org_services``.** The seat check and the write that
  would exceed it happen in one transaction; a view never re-implements that.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from . import audit, org_billing, org_services
from .models import AuditLog, OrgMembership, StaffInvitation
from .org_context import HasFreshJWT, IsOrganisationMember, OrgContextMixin
from .org_serializers import (
    AuditEntrySerializer,
    BranchSerializer,
    InvitationAcceptSerializer,
    InvitationCreateSerializer,
    InvitationSerializer,
    MemberRoleUpdateSerializer,
    MemberScopeUpdateSerializer,
    MemberSerializer,
    OrganisationSummarySerializer,
    OrganisationUpdateSerializer,
    QuoteSerializer,
)
from .pagination import StandardPagination

logger = logging.getLogger("inventory.api")


class OrgScopedView(OrgContextMixin, APIView):
    """Base class for every organisation endpoint.

    The permission set is the important part. Authentication alone is not
    authorisation, and an organisation is only known to exist once a membership
    has been resolved --- so the base requires both. That ordering gives an
    anonymous caller a 401 and a signed-in user who belongs to nothing a 403,
    which is what a client needs to tell "sign in" from "you cannot do this".

    A subclass that needs a narrower set (a JWT rather than a device key, say)
    *extends* this list rather than replacing it, so the base check cannot be
    dropped by accident.

    Role gates are applied per action inside the handler, via ``require_role``.
    That is deliberate: a single list endpoint legitimately serves a GET to any
    member and a POST to an admin, and one class-level role would either
    over-restrict the read or under-restrict the write.
    """

    permission_classes = [permissions.IsAuthenticated, IsOrganisationMember]
    pagination_class = StandardPagination

    def paginate(self, queryset, serializer_class, **serializer_kwargs):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        serializer = serializer_class(page, many=True, context=self.get_serializer_context(), **serializer_kwargs)
        return paginator.get_paginated_response(serializer.data)

    def get_serializer_context(self):
        return {"request": self.request, "organization": self.organization}

    def _flag_memberships(self):
        """Expose the caller's own membership to serializers.

        A couple of validators need to know the caller's role --- to stop an
        admin minting an owner, for instance --- and computing it once here
        keeps a single source of truth for that answer.
        """
        self.request.org_membership = self.org.membership


# ── The organisation itself ────────────────────────────────────────────────


class OrganisationView(OrgScopedView):
    """Read and edit the current tenant.

    Only an admin may rename the company or change its VAT number; anyone may
    read it, because every screen in the console needs the currency and the
    timezone to render a date or a price correctly.
    """

    def get(self, request):
        return Response(OrganisationSummarySerializer(self.organization, context=self.get_serializer_context()).data)

    def patch(self, request):
        self.require_role(OrgMembership.Role.ADMIN)
        before = audit.snapshot(self.organization)
        serializer = OrganisationUpdateSerializer(self.organization, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        organization = serializer.save()
        changes = audit.diff(organization, before)
        if changes:
            audit.record(request, AuditLog.Action.UPDATE, pharmacy=None, target=organization, changes=changes)
        return Response(OrganisationSummarySerializer(organization, context=self.get_serializer_context()).data)


# ── Branches ───────────────────────────────────────────────────────────────


class BranchListCreateView(OrgScopedView):
    """List the branches this caller may see, or open a new one."""

    def get(self, request):
        branches = self.scoped_pharmacies().order_by("name", "id")
        if request.query_params.get("active") == "true":
            branches = branches.filter(is_active=True)
        return self.paginate(branches, BranchSerializer)

    def post(self, request):
        self.require_role(OrgMembership.Role.ADMIN)
        serializer = BranchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            branch, raw_key = org_services.create_branch(
                self.organization,
                request=request,
                **serializer.validated_data,
            )
        except DjangoValidationError as exc:
            return Response(
                {"error": {"code": "validation_error", "detail": "; ".join(exc.messages), "fields": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = BranchSerializer(branch, context=self.get_serializer_context()).data
        if raw_key:
            # Returned exactly once, like every credential in this codebase: it
            # is not stored in plaintext, so this response is the only place it
            # will ever exist and the console must show it as a copyable value.
            payload["api_key"] = raw_key
            payload["api_key_note"] = "Save this key now — it will not be shown again."
        return Response(payload, status=status.HTTP_201_CREATED)


class BranchDetailView(OrgScopedView):
    """Read or edit one branch.

    Every lookup filters by the caller's visible set, so a branch belonging to
    another tenant answers 404 --- not 403. A 403 would confirm that the row
    exists, which is itself information the caller must not have.
    """

    def _get_branch(self, branch_id):
        """Look the branch up inside the caller's visible set, never by pk alone."""
        return self.scoped_pharmacies().filter(pk=branch_id).first()

    def get(self, request, branch_id):
        branch = self._get_branch(branch_id)
        if branch is None:
            return self._not_found()
        return Response(BranchSerializer(branch, context=self.get_serializer_context()).data)

    def patch(self, request, branch_id):
        self.require_role(OrgMembership.Role.MANAGER)
        branch = self._get_branch(branch_id)
        if branch is None:
            return self._not_found()
        before = audit.snapshot(branch)
        serializer = BranchSerializer(branch, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        branch = serializer.save()
        changes = audit.diff(branch, before)
        if changes:
            audit.record(request, AuditLog.Action.UPDATE, pharmacy=branch, target=branch, changes=changes)
        return Response(BranchSerializer(branch, context=self.get_serializer_context()).data)

    def delete(self, request, branch_id):
        """Close a branch.

        Deactivated rather than deleted. A branch owns sales, batches and stock
        movements, and deleting it would cascade away the history an accountant
        needs --- so "close" means "stop trading", and the numbers stay.
        """
        self.require_role(OrgMembership.Role.ADMIN)
        branch = self._get_branch(branch_id)
        if branch is None:
            return self._not_found()
        branch.is_active = False
        branch.save(update_fields=["is_active", "updated_at"])
        audit.record(request, AuditLog.Action.UPDATE, pharmacy=branch, target=branch, note="branch deactivated")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _not_found():
        return Response(
            {"error": {"code": "not_found", "detail": "Branch not found.", "fields": {}}},
            status=status.HTTP_404_NOT_FOUND,
        )


# ── Members and seats ──────────────────────────────────────────────────────


class MemberListView(OrgScopedView):
    """The team table, with the seat picture the plan widget renders."""

    def get(self, request):
        members = OrgMembership.objects.filter(organization=self.organization).select_related("user", "default_pharmacy").prefetch_related("scoped_pharmacies").order_by("user__email")
        if request.query_params.get("active") == "true":
            members = members.filter(is_active=True)
        return self.paginate(members, MemberSerializer)


class MemberDetailView(OrgScopedView):
    """Change a member's role or their branch restriction."""

    def _get_member(self, member_id):
        return OrgMembership.objects.filter(organization=self.organization, pk=member_id).select_related("user").first()

    def patch(self, request, member_id):
        self.require_role(OrgMembership.Role.ADMIN)
        member = self._get_member(member_id)
        if member is None:
            return Response(
                {"error": {"code": "not_found", "detail": "Member not found.", "fields": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )
        self._flag_memberships()

        if "role" in request.data:
            serializer = MemberRoleUpdateSerializer(data={"role": request.data["role"]}, context=self.get_serializer_context())
            serializer.is_valid(raise_exception=True)
            try:
                org_services.change_role(member, serializer.validated_data["role"], request=request)
            except ValueError as exc:
                return self._refused(str(exc))

        if "scoped_pharmacy_ids" in request.data:
            serializer = MemberScopeUpdateSerializer(
                data={"scoped_pharmacy_ids": request.data["scoped_pharmacy_ids"]},
                context=self.get_serializer_context(),
            )
            serializer.is_valid(raise_exception=True)
            ids = [str(item) for item in serializer.validated_data["scoped_pharmacy_ids"]]
            member.scoped_pharmacies.set(ids)
            audit.record(
                request,
                AuditLog.Action.UPDATE,
                target=member,
                changes={"scoped_pharmacies": {"from": None, "to": ids}},
                note="branch restriction updated",
            )

        member.refresh_from_db()
        return Response(MemberSerializer(member, context=self.get_serializer_context()).data)

    def delete(self, request, member_id):
        """Remove a member's access, freeing their seat."""
        self.require_role(OrgMembership.Role.ADMIN)
        member = self._get_member(member_id)
        if member is None:
            return Response(
                {"error": {"code": "not_found", "detail": "Member not found.", "fields": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )
        if member.user_id == getattr(request.user, "id", None):
            # Removing your own access is almost always a mistake, and it is the
            # mistake that locks the only admin out of their own console. An
            # owner cannot step down at all while they are the last one, which
            # is the rule the service enforces; saying so here is clearer than
            # letting it surface as a generic refusal.
            if member.role == OrgMembership.Role.OWNER:
                return self._refused("You are the last owner, and an organisation must keep at least one owner. Promote someone else first.")
            return self._refused("You cannot remove your own access. Ask another admin to do it.")
        try:
            org_services.deactivate_membership(member, request=request)
        except ValueError as exc:
            return self._refused(str(exc))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _refused(detail):
        return Response(
            {"error": {"code": "not_allowed", "detail": detail, "fields": {}}},
            status=status.HTTP_409_CONFLICT,
        )


class SeatStatusView(OrgScopedView):
    """How many seats are used, and what another one would cost.

    A dedicated endpoint rather than a field on the organisation summary,
    because the console polls it after every invite or removal and a full tenant
    payload for a three-number answer is wasteful on a metered mobile
    connection.
    """

    def get(self, request):
        utilisation = org_billing.seat_utilisation(self.organization)
        return Response(
            {
                **utilisation,
                "seat_price": org_billing._rate("SEAT_PRICE_BDT", 199),
                "currency": self.organization.currency,
                "note": ("Seats beyond the plan are billed monthly." if utilisation["over"] else "All seats are covered by the plan."),
            }
        )


# ── Invitations ────────────────────────────────────────────────────────────


class InvitationListCreateView(OrgScopedView):
    """List live invitations, or send a new one.

    Requires a signed-in user rather than an API key: an invitation email is
    sent in the organisation's name, and a device credential must not be able to
    speak for the company.
    """

    permission_classes = [*OrgScopedView.permission_classes, HasFreshJWT]

    def get(self, request):
        self.require_role(OrgMembership.Role.ADMIN)
        invitations = StaffInvitation.objects.filter(organization=self.organization).select_related("invited_by__user", "default_pharmacy")
        state = request.query_params.get("status")
        if state:
            invitations = invitations.filter(status=state)
        return self.paginate(invitations, InvitationSerializer)

    def post(self, request):
        self.require_role(OrgMembership.Role.ADMIN)
        self._flag_memberships()
        serializer = InvitationCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        try:
            invitation, raw_token = org_services.invite_staff(
                self.organization,
                invited_by=self.membership,
                request=request,
                **serializer.validated_data,
            )
        except org_services.AlreadyMember as exc:
            # 409, not 402: there is nothing to buy. The address already has a
            # seat, so the console should say so rather than open the billing
            # page for a person who needs no seat.
            return Response(
                {
                    "error": {
                        "code": "already_member",
                        "detail": str(exc),
                        "fields": {"email": ["Already a member of this organisation."]},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )
        except org_services.DuplicateInvitation:
            return Response(
                {
                    "error": {
                        "code": "duplicate_invitation",
                        "detail": "An invitation is already pending for that address.",
                        "fields": {"email": ["Already invited."]},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        payload = InvitationSerializer(invitation, context=self.get_serializer_context()).data
        # The raw token is returned exactly once. It is not stored, so this
        # response is the only place it will ever exist --- the console shows it
        # as a copyable link, and the email carries the same one.
        payload["token"] = raw_token
        payload["accept_path"] = f"/console/join?token={raw_token}"

        # Sent inline, with the queue as the fallback, so the person who was
        # invited hears about it in seconds. A delivery failure is reported in
        # the payload rather than raised: the invitation itself is valid and the
        # owner can still copy the link, so failing the whole request would deny
        # them a working invitation over an SMTP problem.
        from . import tasks as async_tasks

        delivery = async_tasks.deliver_invitation_now(invitation, raw_token, request=request)
        payload["email"] = {"queued": not delivery.ok, "sent_to": invitation.email if delivery.ok else None}
        return Response(payload, status=status.HTTP_201_CREATED)


class InvitationDetailView(OrgScopedView):
    """Revoke a pending invitation."""

    permission_classes = [*OrgScopedView.permission_classes, HasFreshJWT]

    def delete(self, request, invitation_id):
        self.require_role(OrgMembership.Role.ADMIN)
        invitation = StaffInvitation.objects.filter(organization=self.organization, pk=invitation_id).first()
        if invitation is None:
            return Response(
                {"error": {"code": "not_found", "detail": "Invitation not found.", "fields": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            org_services.revoke_invitation(invitation, request=request)
        except ValueError as exc:
            return Response(
                {"error": {"code": "not_allowed", "detail": str(exc), "fields": {}}},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


def _mask_email(address: str) -> str:
    """Show enough of the address to recognise it, not enough to fish with.

    The info endpoint is open (the link holder has no session yet), so the
    full address must not be revealed to whoever holds the token. But the
    recipient does need to recognise *their* address, or they cannot tell
    which mailbox to sign in from when several are possible.
    """
    local, _, domain = address.partition("@")
    if not domain:
        return "•" * len(address)
    visible = local[:2]
    return f"{visible}{'•' * max(len(local) - len(visible), 1)}@{domain}"


def _invitation_by_token(raw_token: str):
    """The live invitation for a raw token, or ``None`` for any failure state.

    Unknown, used, revoked and expired tokens all answer the same way at the
    view layer: a 404 that says the link is not usable, without revealing
    which of those states it is in.
    """
    token_hash = StaffInvitation.hash_token(raw_token)
    invitation = StaffInvitation.objects.select_related("organization", "invited_by__user", "default_pharmacy").filter(token_hash=token_hash).first()
    if invitation is None or not invitation.is_actionable:
        return None
    return invitation


def _invitation_info(invitation) -> dict:
    """The public, read-only context the join page renders."""
    inviter = ""
    if invitation.invited_by is not None:
        inviter_user = invitation.invited_by.user
        inviter = (inviter_user.get_full_name() or inviter_user.email) if inviter_user else ""
    return {
        "organisation": invitation.organization.display_name,
        "role": invitation.role,
        "invited_by": inviter,
        "email_masked": _mask_email(invitation.email),
        "expires_on": invitation.expires_at.strftime("%d %b %Y"),
    }


class InvitationInfoView(APIView):
    """Public context for the join page, keyed by the single-use token.

    The person clicking the link has no session yet, so the page needs the
    invitation's who/where/what before it can render a form. The token is the
    credential, and it is single-use --- but *reading* the invitation must not
    consume it, because the recipient may open the page twice before accepting.
    Only the hash is stored, so an unknown token and a spent one are
    indistinguishable to the caller, which is the safe answer for both.
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "login"  # same tight ceiling the login endpoint gets
    throttle_classes = [ScopedRateThrottle]

    def get(self, request):
        raw_token = (request.query_params.get("token") or "").strip()
        if not raw_token:
            return Response(
                {"error": {"code": "invalid_invitation", "detail": "This invitation link is not valid.", "fields": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )
        invitation = _invitation_by_token(raw_token)
        if invitation is None:
            return Response(
                {"error": {"code": "invalid_invitation", "detail": "This invitation link is not valid. It may have expired or already been used.", "fields": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_invitation_info(invitation))


class InvitationRegisterView(APIView):
    """Create the invited person's account from the join page, then accept.

    The invitation email is the whole identity of the new account: the form
    never asks for an address, so a seat can only ever be claimed by the
    mailbox the invitation was sent to --- the same address check
    ``accept_invitation`` enforces, now applied before the account exists.
    Password rules are the site's own validators (minimum 12 characters,
    common-password and all-numeric refusals), so the join page cannot
    register a credential the console would refuse.
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "login"
    throttle_classes = [ScopedRateThrottle]

    def post(self, request):
        User = get_user_model()
        raw_token = (request.data.get("token") or "").strip()
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""

        invitation = _invitation_by_token(raw_token) if raw_token else None
        if invitation is None:
            return Response(
                {"error": {"code": "invalid_invitation", "detail": "This invitation link is not valid. It may have expired or already been used.", "fields": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )

        fields: dict[str, list[str]] = {}
        if not username:
            fields["username"] = ["Choose a username."]
        elif User.objects.filter(username__iexact=username).exists():
            fields["username"] = ["That username is taken. Choose another."]
        if len(password) < 1:
            fields["password"] = ["Enter a password."]
        if fields:
            return Response({"error": {"code": "validation_error", "detail": "Validation failed.", "fields": fields}}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(password)
        except DjangoValidationError as exc:
            return Response(
                {"error": {"code": "validation_error", "detail": "Validation failed.", "fields": {"password": list(exc.messages)}}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if User.objects.filter(email__iexact=invitation.email).exists():
            # An account already exists for the invited address: the person
            # should sign in, not register a second identity.
            return Response(
                {"error": {"code": "account_exists", "detail": "An account already exists for this address. Sign in instead.", "fields": {}}},
                status=status.HTTP_409_CONFLICT,
            )

        user = User.objects.create_user(username=username, email=invitation.email, password=password)
        try:
            membership = org_services.accept_invitation(raw_token, user=user, request=request)
        except LookupError:
            return Response(
                {"error": {"code": "invalid_invitation", "detail": "This invitation link is not valid. It may have expired or already been used.", "fields": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as exc:
            return Response(
                {"error": {"code": "invitation_for_another_address", "detail": str(exc), "fields": {}}},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return Response(
                {"error": {"code": "invitation_not_usable", "detail": str(exc), "fields": {}}},
                status=status.HTTP_410_GONE,
            )

        return Response(
            {
                "status": "joined",
                "organisation": invitation.organization.display_name,
                "site_url": settings.SITE_URL,
                "member": MemberSerializer(membership, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class InvitationAcceptView(APIView):
    """Accept an invitation. Public by necessity.

    The person clicking the link has no session yet --- that is the point of the
    link --- so this endpoint is open, and the token is the credential. It is
    rate limited and single-use, which is what keeps an open endpoint acceptable
    here.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = []

    def post(self, request):
        serializer = InvitationAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]
        accept = serializer.validated_data.get("accept", True)

        if not request.user or not request.user.is_authenticated:
            return Response(
                {
                    "error": {
                        "code": "authentication_required",
                        "detail": "Sign in or register first, then open the invitation link again.",
                        "fields": {},
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            membership = org_services.accept_invitation(token, user=request.user, request=request, accept=accept)
        except LookupError as exc:
            return Response(
                {"error": {"code": "invalid_invitation", "detail": str(exc), "fields": {}}},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as exc:
            # The invitation names a person, not a link holder. A forwarded
            # message must not be a way into someone else's tenant.
            return Response(
                {"error": {"code": "invitation_for_another_address", "detail": str(exc), "fields": {}}},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return Response(
                {"error": {"code": "invitation_not_usable", "detail": str(exc), "fields": {}}},
                status=status.HTTP_410_GONE,
            )
        if membership is None:
            # Declined. A 200 rather than a 204, so the console has a body to
            # render ("You declined this invitation") instead of an empty reply
            # it would have to interpret from the status code alone.
            return Response({"status": "declined"})
        return Response(MemberSerializer(membership, context={"request": request}).data)


# ── Billing ────────────────────────────────────────────────────────────────


class QuoteView(OrgScopedView):
    """The current period's bill, itemised.

    Admin-only: the numbers are the company's commercial terms, and a branch
    viewer has no reason to see what head office pays. The gate is applied in
    the handler rather than declared as a class attribute so it sits next to the
    code it protects.
    """

    def get(self, request):
        self.require_role(OrgMembership.Role.ADMIN)
        return Response(QuoteSerializer(org_billing.quote(self.organization)).data)


class SeatAddonView(OrgScopedView):
    """Buy additional seats up front, or release ones no longer needed.

    Blocked from shrinking below the seats actually in use: an organisation that
    dropped its add-on count below its headcount would owe money it had not
    agreed to, and the invoice would be the first anyone heard of it.
    """

    permission_classes = [*OrgScopedView.permission_classes, HasFreshJWT]

    def post(self, request):
        self.require_role(OrgMembership.Role.OWNER)
        try:
            count = int(request.data.get("count", 0))
        except (TypeError, ValueError):
            count = -1
        if count < 0:
            return Response(
                {"error": {"code": "validation_error", "detail": "count must be a non-negative integer.", "fields": {"count": ["Invalid."]}}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if count > org_billing.MAX_SEAT_ADDON:
            # A plausible typo (an extra zero) would otherwise produce an
            # invoice two orders of magnitude too large, discovered a month
            # later by the accountant rather than by the person who typed it.
            return Response(
                {
                    "error": {
                        "code": "validation_error",
                        "detail": f"A single add-on is limited to {org_billing.MAX_SEAT_ADDON} seats. Contact us for more.",
                        "fields": {"count": [f"At most {org_billing.MAX_SEAT_ADDON}."]},
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        in_use = org_billing.active_seat_count(self.organization)
        if count < in_use:
            return Response(
                {
                    "error": {
                        "code": "below_active_seats",
                        "detail": f"{in_use} seat(s) are in use; the add-on cannot be set below that.",
                        "fields": {"count": ["Too few."]},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        before = self.organization.seat_addon_count
        self.organization.seat_addon_count = count
        self.organization.save(update_fields=["seat_addon_count", "updated_at"])
        audit.record(
            request,
            AuditLog.Action.PLAN_CHANGED,
            target=self.organization,
            changes={"seat_addon_count": {"from": before, "to": count}},
        )
        return Response(QuoteSerializer(org_billing.quote(self.organization)).data)


# ── Audit trail ────────────────────────────────────────────────────────────


class AuditLogListView(OrgScopedView):
    """The audit trail, filterable.

    Admin-only and JWT-only. This is the endpoint a compliance officer reads,
    and it must be attributable to a person for the same reason the entries
    themselves are.
    """

    permission_classes = [*OrgScopedView.permission_classes, HasFreshJWT]

    def get(self, request):
        self.require_role(OrgMembership.Role.ADMIN)
        entries = AuditLog.objects.filter(organization=self.organization).select_related("pharmacy")
        for param, field in (("action", "action"), ("pharmacy", "pharmacy_id"), ("target_type", "target_type")):
            value = request.query_params.get(param)
            if value:
                entries = entries.filter(**{field: value})
        actor = request.query_params.get("actor")
        if actor:
            entries = entries.filter(actor_email__icontains=actor)
        since = request.query_params.get("since")
        if since:
            entries = entries.filter(created_at__gte=since)
        return self.paginate(entries, AuditEntrySerializer)
