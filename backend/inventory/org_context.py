"""Who is calling, and what may they see?

Every enterprise endpoint needs the same three answers before it does anything:
which organisation is calling, who within it, and which branches that person is
allowed to touch. Answering those in each view would mean the answer is
implemented once per view --- and the one view where it is forgotten is a
cross-tenant data leak.

So the answers are computed once, here, and handed to the view as a single
object. A view that has an ``OrgContext`` cannot accidentally query another
tenant's rows, because the context is the only source of scope it is given.

Two kinds of caller arrive at these endpoints, and both must work:

* the **web console**, a Django user authenticated with a JWT, who reaches the
  organisation through an active ``OrgMembership``;
* the **Android app**, a ``Pharmacy`` object authenticated with
  ``X-Pharmacy-Key``, whose organisation is the branch's organisation.

Neither is privileged over the other: a branch manager using the app and the
same manager using the console must see exactly the same rows.
"""

from dataclasses import dataclass

from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from .models import OrgMembership, Pharmacy


@dataclass(frozen=True)
class OrgContext:
    """The resolved answer to "who is calling, and what may they see?"."""

    organization: object
    membership: OrgMembership | None
    pharmacy: Pharmacy | None

    @property
    def role(self):
        """The caller's role, or the effective role of an API-key branch.

        A branch key belongs to the pharmacy rather than to a person, so it is
        treated as the highest branch-level role and *not* as an owner: a key
        embedded in an Android install must never be able to change billing or
        invite the finance team. Treating it as ``MANAGER`` is the deliberate
        ceiling.
        """
        if self.membership is not None:
            return self.membership.role
        return OrgMembership.Role.MANAGER

    @property
    def actor_email(self):
        if self.membership is not None:
            return self.membership.user.email
        if self.pharmacy is not None:
            return f"api-key@{self.pharmacy.pk}"
        return ""

    @property
    def user(self):
        if self.membership is not None:
            return self.membership.user
        return None

    def has_at_least(self, role):
        if self.membership is not None:
            return self.membership.has_at_least(role)
        # An API key is a branch credential: it may do branch work and nothing
        # above it. Comparing through a synthetic membership keeps one code path
        # for the check itself.
        return OrgMembership.ROLE_ORDER.index(OrgMembership.Role.MANAGER) >= OrgMembership.ROLE_ORDER.index(role)

    def visible_pharmacy_ids(self):
        """The branches this caller may read. The one scoping primitive."""
        if self.membership is not None:
            return self.membership.visible_pharmacy_ids()
        if self.pharmacy is not None:
            return Pharmacy.objects.filter(pk=self.pharmacy.pk).values_list("id", flat=True)
        return Pharmacy.objects.none().values_list("id", flat=True)

    def visible_pharmacies(self):
        return Pharmacy.objects.filter(pk__in=self.visible_pharmacy_ids())

    def can_see_pharmacy(self, pharmacy_id):
        return self.visible_pharmacy_ids().filter(pk=pharmacy_id).exists()

    @property
    def is_seat_based(self):
        """True when this caller occupies a billable seat.

        An API key does not: it is a credential for a branch that already
        exists, and counting it would mean a shop with one employee and four
        devices pays for four seats.
        """
        return self.membership is not None


def resolve_org_context(request):
    """Build the context, or ``None`` when the caller is not an organisation.

    Returning ``None`` rather than raising is deliberate: an endpoint may
    legitimately serve both a tenant caller and a legacy single-shop caller, and
    it is the permission class --- not this function --- that decides whether
    the absence is acceptable.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    if isinstance(user, Pharmacy):
        # API-key caller. Its organisation may be null for a pre-multi-tenancy
        # shop, in which case the branch is its own tenant.
        if user.organization_id is None:
            return None
        return OrgContext(organization=user.organization, membership=None, pharmacy=user)

    # JWT / session caller. The organisation comes from an *active* membership;
    # an inactive one means the person has been removed and must not retain
    # access through a token that has not yet expired.
    membership = OrgMembership.objects.select_related("organization", "user").filter(user=user, is_active=True, organization__is_active=True).order_by("-created_at").first()
    if membership is None:
        return None
    return OrgContext(organization=membership.organization, membership=membership, pharmacy=membership.default_pharmacy)


class OrgContextMixin:
    """Gives a view its ``OrgContext``, or refuses the request.

    Used as a base class on every organisation endpoint so that ``self.org`` is
    guaranteed non-null below the permission check --- the alternative, calling
    ``resolve_org_context`` in each view body, is one forgotten call away from
    an unscoped query.
    """

    #: Set to ``False`` on a view that may serve callers with no organisation.
    require_org = True

    @property
    def org(self):
        context = getattr(self, "_org_context", None)
        if context is None:
            context = resolve_org_context(self.request)
            self._org_context = context
        if context is None and self.require_org:
            raise PermissionDenied("This account is not part of an organisation.")
        return context

    @property
    def organization(self):
        return self.org.organization

    @property
    def membership(self):
        return self.org.membership

    def scoped_pharmacies(self):
        return self.org.visible_pharmacies()

    def require_role(self, role):
        """Raise 403 unless the caller holds at least ``role``."""
        if not self.org.has_at_least(role):
            raise PermissionDenied(f"This action requires the {role} role or above.")


class IsOrganisationMember(permissions.BasePermission):
    """Any authenticated caller that belongs to an organisation."""

    message = "This account is not part of an organisation."

    def has_permission(self, request, view):
        return resolve_org_context(request) is not None


class HasOrgRole(permissions.BasePermission):
    """A role gate. Set ``required_role`` on the view.

    The comparison is by rank, not by name, so inserting a role between manager
    and owner cannot silently widen a gate written as "manager or above".
    """

    message = "Your role does not permit this action."

    def has_permission(self, request, view):
        required = getattr(view, "required_role", OrgMembership.Role.VIEWER)
        context = resolve_org_context(request)
        if context is None:
            return False
        return context.has_at_least(required)


class IsOrgAdmin(HasOrgRole):
    """Shorthand for the common "admin or above" gate."""

    def has_permission(self, request, view):
        view.required_role = OrgMembership.Role.ADMIN
        return super().has_permission(request, view)


class HasFreshJWT(permissions.BasePermission):
    """Refuses an API-key caller on endpoints that must be human-attributable.

    Billing changes, role changes and audit reads are actions a compliance
    officer will ask about by name. "A device key did it" is not an answer, so
    those endpoints require a person behind them.
    """

    message = "This action requires a signed-in user, not a branch API key."

    def has_permission(self, request, view):
        context = resolve_org_context(request)
        return context is not None and context.membership is not None
