"""Serializers for the organisation endpoints.

Two rules run through all of them:

* **A tenant id is never accepted from the request body.** It comes from the
  authenticated principal, always. A body-supplied organisation id would let any
  caller read any tenant by editing one field.
* **Nothing derived is accepted from the client.** Seat counts, prices and
  totals are computed server-side and are read-only here. A client that can
  post its own total can post its own bill.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import AuditLog, Organization, OrgMembership, Pharmacy, StaffInvitation

User = get_user_model()


class OrganisationSummarySerializer(serializers.ModelSerializer):
    """The organisation as the console header needs it."""

    seat_utilisation = serializers.SerializerMethodField()
    trial_days_left = serializers.IntegerField(read_only=True)
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "display_name",
            "slug",
            "legal_name",
            "bin",
            "currency",
            "timezone",
            "locale",
            "address",
            "phone",
            "billing_email",
            "plan",
            "branch_allowance",
            "seat_addon_count",
            "trial_ends_on",
            "trial_days_left",
            "seat_utilisation",
            "brand_name",
            "brand_color",
            "logo_url",
            "white_label_enabled",
            "is_active",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "plan",
            "branch_allowance",
            "seat_addon_count",
            "trial_ends_on",
            "is_active",
            "created_at",
        ]

    def get_seat_utilisation(self, obj):
        from .org_billing import seat_utilisation

        return seat_utilisation(obj)


class OrganisationUpdateSerializer(serializers.ModelSerializer):
    """The editable half of an organisation.

    Plan, allowance and trial are absent on purpose: those are commercial terms,
    changed by the platform or by a payment, never by the tenant's own request.
    """

    class Meta:
        model = Organization
        fields = [
            "name",
            "legal_name",
            "bin",
            "currency",
            "timezone",
            "locale",
            "address",
            "phone",
            "billing_email",
            "brand_name",
            "brand_color",
            "logo_url",
            "white_label_enabled",
        ]

    def validate_bin(self, value):
        """A BIN is 9 or 13 digits in Bangladesh; blank means "not registered".

        Validated rather than stored verbatim because it is printed on every
        invoice. A wrong BIN is discovered by a VAT officer, not by the person
        who typed it, and a free-text field makes that mistake easy. Spaces and
        dashes are stripped, because that is how the number is written on the
        certificate and how it should print on the invoice.
        """
        value = (value or "").strip().replace(" ", "").replace("-", "")
        if not value:
            return value
        if not value.isdigit() or len(value) not in (9, 13):
            raise serializers.ValidationError("A BIN must be 9 or 13 digits, e.g. 0012345670102.")
        return value

    def validate_currency(self, value):
        value = (value or "").strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError("Currency must be a three-letter ISO code, e.g. BDT.")
        return value

    def validate_brand_color(self, value):
        """Accept #rgb or #rrggbb, and nothing else.

        The value is interpolated into the console's CSS, so an unvalidated
        string is a style-injection vector, not a cosmetic field.
        """
        value = (value or "").strip()
        if not value:
            return value
        if not value.startswith("#") or len(value) not in (4, 7):
            raise serializers.ValidationError("Use a hex colour such as #0F766E.")
        try:
            int(value[1:], 16)
        except ValueError as exc:
            raise serializers.ValidationError("Use a hex colour such as #0F766E.") from exc
        return value


class BranchSerializer(serializers.ModelSerializer):
    """A branch, as the console lists it."""

    member_count = serializers.SerializerMethodField()
    is_billable = serializers.SerializerMethodField()

    class Meta:
        model = Pharmacy
        fields = [
            "id",
            "name",
            "branch_code",
            "address",
            "phone",
            "currency",
            "timezone",
            "low_stock_default",
            "is_active",
            "member_count",
            "is_billable",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "member_count", "is_billable"]

    def get_member_count(self, obj):
        return obj.scoped_memberships.filter(is_active=True).count()

    def get_is_billable(self, obj):
        organization = obj.organization
        if organization is None:
            return False
        branches = list(organization.pharmacies.filter(is_active=True).order_by("name", "id"))
        for index, branch in enumerate(branches):
            if branch.pk == obj.pk:
                return index >= organization.branch_allowance
        return False

    def validate_branch_code(self, value):
        """Normalise and reject the two characters that break an export.

        A comma or a newline in a branch code silently corrupts every CSV the
        chain downloads, which is discovered by the accountant rather than by
        the person who typed it.
        """
        value = (value or "").strip().upper()
        if any(char in value for char in ",\n\r"):
            raise serializers.ValidationError("A branch code cannot contain a comma or a line break.")
        return value


class MemberSerializer(serializers.ModelSerializer):
    """A person's membership, flattened for the team table."""

    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.SerializerMethodField()
    default_pharmacy_name = serializers.CharField(source="default_pharmacy.name", read_only=True, default=None)
    scoped_pharmacy_ids = serializers.PrimaryKeyRelatedField(
        source="scoped_pharmacies",
        many=True,
        read_only=True,
    )

    class Meta:
        model = OrgMembership
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "is_active",
            "default_pharmacy",
            "default_pharmacy_name",
            "scoped_pharmacy_ids",
            "joined_at",
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.get_username()


class MemberRoleUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=OrgMembership.Role.choices)

    def validate_role(self, value):
        """Refuse a role escalation the caller is not allowed to grant.

        The permission class already stops a non-admin reaching this view; this
        stops an *admin* minting a new owner, which the change-role service
        would otherwise permit. Only an owner may create another owner.
        """
        request = self.context.get("request")
        actor = getattr(request, "org_membership", None) if request else None
        if value == OrgMembership.Role.OWNER and actor is not None and not actor.has_at_least(OrgMembership.Role.OWNER):
            raise serializers.ValidationError("Only an owner can grant the owner role.")
        return value


class MemberScopeUpdateSerializer(serializers.Serializer):
    """Which branches a member is restricted to.

    An empty list means every branch --- the default for anyone who is not
    deliberately restricted.
    """

    scoped_pharmacy_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)

    def validate_scoped_pharmacy_ids(self, value):
        organization = self.context["organization"]
        valid = {str(pk) for pk in organization.pharmacies.values_list("id", flat=True)}
        unknown = [str(item) for item in value if str(item) not in valid]
        if unknown:
            # Deliberately a 400 rather than a silent drop: a restriction that
            # was quietly ignored would leave a manager seeing more branches
            # than the admin believes they configured.
            raise serializers.ValidationError(f"Not branches of this organisation: {', '.join(unknown)}")
        return value


class InvitationSerializer(serializers.ModelSerializer):
    invited_by_email = serializers.CharField(source="invited_by.user.email", read_only=True, default=None)
    is_expired = serializers.BooleanField(read_only=True)
    default_pharmacy_name = serializers.CharField(source="default_pharmacy.name", read_only=True, default=None)

    class Meta:
        model = StaffInvitation
        fields = [
            "id",
            "email",
            "role",
            "status",
            "is_expired",
            "invited_by_email",
            "default_pharmacy",
            "default_pharmacy_name",
            "expires_at",
            "accepted_at",
            "created_at",
        ]
        read_only_fields = ["id", "status", "expires_at", "accepted_at", "created_at"]


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=OrgMembership.Role.choices, default=OrgMembership.Role.STAFF)
    default_pharmacy = serializers.PrimaryKeyRelatedField(
        queryset=Pharmacy.objects.all(),
        required=False,
        allow_null=True,
    )

    def validate_email(self, value):
        return value.strip().lower()

    def validate_role(self, value):
        request = self.context.get("request")
        actor = getattr(request, "org", None) if request else None
        if value == OrgMembership.Role.OWNER and actor is not None and not actor.has_at_least(OrgMembership.Role.OWNER):
            raise serializers.ValidationError("Only an owner can invite another owner.")
        return value

    def validate_default_pharmacy(self, value):
        if value is None:
            return value
        organization = self.context["organization"]
        if value.organization_id != organization.pk:
            raise serializers.ValidationError("That branch belongs to another organisation.")
        return value


class InvitationAcceptSerializer(serializers.Serializer):
    token = serializers.CharField()
    #: ``accept=False`` declines the invitation. Modelled explicitly rather than
    #: as "do nothing" because a decline has an observable effect: the seat the
    #: invitation reserved is released immediately instead of sitting reserved
    #: until the link expires two weeks later.
    accept = serializers.BooleanField(required=False, default=True)


class AuditEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "created_at",
            "actor_email",
            "action",
            "target_type",
            "target_id",
            "pharmacy",
            "changes",
            "ip_address",
            "request_id",
        ]
        read_only_fields = fields


class QuoteLineSerializer(serializers.Serializer):
    """A branch line on a quote or invoice."""

    pharmacy_id = serializers.CharField()
    name = serializers.CharField()
    included = serializers.BooleanField()
    amount = serializers.IntegerField()


class SeatLineSerializer(serializers.Serializer):
    included_seats = serializers.IntegerField()
    active_seats = serializers.IntegerField()
    billable_seats = serializers.IntegerField()
    amount = serializers.IntegerField()


class QuoteSerializer(serializers.Serializer):
    organization_id = serializers.CharField()
    currency = serializers.CharField()
    branches = QuoteLineSerializer(many=True)
    seats = SeatLineSerializer()
    subtotal = serializers.IntegerField()
    vat_percent = serializers.CharField()
    vat_amount = serializers.IntegerField()
    total = serializers.IntegerField()
    plan = serializers.CharField()
    notes = serializers.ListField(child=serializers.CharField())
