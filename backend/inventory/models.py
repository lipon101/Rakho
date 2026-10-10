import hashlib
import secrets
import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Pharmacy(TimeStampedModel):
    class Meta:
        verbose_name_plural = "pharmacies"
        constraints = [
            # One branch code per organisation. ``condition`` keeps blank codes
            # out of the constraint: a shop that never sets one must not be
            # limited to a single branch.
            models.UniqueConstraint(
                fields=["organization", "branch_code"],
                condition=models.Q(branch_code__gt=""),
                name="unique_branch_code_per_organization",
            )
        ]
        indexes = [models.Index(fields=["organization", "is_active"])]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=180)
    currency = models.CharField(max_length=3, default="BDT")
    timezone = models.CharField(max_length=64, default="Asia/Dhaka")
    low_stock_default = models.PositiveIntegerField(default=10)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    #: When this shop last opened the app. Nullable so the migration needs no
    #: backfill and "never seen" stays distinguishable from "seen long ago".
    #: Written by the analytics layer, never displayed to anyone.
    last_active_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # ── Phase 1: the branch belongs to an organisation ──────────────────
    # Nullable so every single-shop deployment that predates multi-tenancy
    # keeps working untouched and the migration needs no backfill. A branch
    # with no organisation is simply its own tenant, which is exactly what it
    # was before this field existed.
    organization = models.ForeignKey(
        "Organization",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="pharmacies",
    )
    #: A code a chain uses to tell branches apart in an export ("DHA-01").
    #: Unique per organisation rather than globally, so two companies may each
    #: have a branch "01".
    branch_code = models.CharField(max_length=24, blank=True)
    is_active = models.BooleanField(default=True)

    @property
    def is_authenticated(self):
        """Allows the tenant object returned by API-key auth to satisfy DRF permissions."""
        return True

    def __str__(self):
        return self.name


class PharmacyApiKey(TimeStampedModel):
    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name="api_keys")
    label = models.CharField(max_length=100, default="Primary")
    key_prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    # Optional key expiry: when set, the key stops authenticating after this
    # instant even though it has not been revoked. null = no expiry. Lets the
    # owner hand out a trial key that dies on its own without a revoke reminder.
    expires_at = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def generate_raw_key():
        return f"phm_{secrets.token_urlsafe(32)}"

    @staticmethod
    def hash_key(raw_key):
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @classmethod
    def create_key(cls, pharmacy, label="Primary", expires_at=None):
        raw_key = cls.generate_raw_key()
        record = cls.objects.create(
            pharmacy=pharmacy,
            label=label,
            key_prefix=raw_key[:11],
            key_hash=cls.hash_key(raw_key),
            expires_at=expires_at,
        )
        return record, raw_key

    @property
    def is_live(self):
        """Not revoked and not past its expiry (when one is set)."""
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        return True

    def __str__(self):
        return f"{self.pharmacy} / {self.label}"


class CatalogMedicine(TimeStampedModel):
    """Read-mostly Bangladesh medicine catalog imported from public source data."""

    source_brand_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    brand_name = models.CharField(max_length=255, db_index=True)
    medicine_type = models.CharField(max_length=24, default="allopathic")
    slug = models.SlugField(max_length=280, blank=True)
    dosage_form = models.CharField(max_length=255, blank=True)
    generic_name = models.CharField(max_length=255, blank=True, db_index=True)
    strength = models.CharField(max_length=255, blank=True)
    manufacturer_name = models.CharField(max_length=255, blank=True, db_index=True)
    package_container = models.CharField(max_length=255, blank=True)
    package_size_info = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["brand_name", "strength"]),
            models.Index(fields=["generic_name", "manufacturer_name"]),
        ]
        ordering = ["brand_name", "strength", "id"]

    def __str__(self):
        return f"{self.brand_name} {self.strength}".strip()


class Medicine(TimeStampedModel):
    """A pharmacy's sellable catalogue entry, optionally mapped to the national source catalogue."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name="medicines")
    catalog_medicine = models.ForeignKey(CatalogMedicine, on_delete=models.SET_NULL, null=True, blank=True, related_name="pharmacy_medicines")
    brand_name = models.CharField(max_length=255)
    generic_name = models.CharField(max_length=255, blank=True)
    strength = models.CharField(max_length=255, blank=True)
    dosage_form = models.CharField(max_length=255, blank=True)
    manufacturer_name = models.CharField(max_length=255, blank=True)
    barcode = models.CharField(max_length=80, blank=True)
    default_selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    low_stock_threshold = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["pharmacy", "barcode"], name="unique_pharmacy_barcode", condition=~models.Q(barcode=""))]
        indexes = [models.Index(fields=["pharmacy", "brand_name"]), models.Index(fields=["pharmacy", "is_active"])]
        ordering = ["brand_name", "strength", "id"]

    def __str__(self):
        return f"{self.brand_name} {self.strength}".strip()


class Batch(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name="batches")
    medicine = models.ForeignKey(Medicine, on_delete=models.PROTECT, related_name="batches")
    batch_number = models.CharField(max_length=100)
    expiry_date = models.DateField(db_index=True)
    received_at = models.DateTimeField(default=timezone.now)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity_received = models.PositiveIntegerField()
    quantity_available = models.PositiveIntegerField()
    supplier_name = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name_plural = "batches"
        constraints = [
            models.UniqueConstraint(fields=["pharmacy", "medicine", "batch_number"], name="unique_pharmacy_medicine_batch"),
            models.CheckConstraint(condition=models.Q(quantity_available__lte=models.F("quantity_received")), name="available_not_over_received"),
        ]
        indexes = [models.Index(fields=["pharmacy", "medicine", "expiry_date"]), models.Index(fields=["pharmacy", "expiry_date", "quantity_available"])]
        ordering = ["expiry_date", "received_at", "id"]

    @property
    def is_expired(self):
        return self.expiry_date < timezone.localdate()


class Sale(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name="sales")
    invoice_number = models.CharField(max_length=50)
    sold_at = models.DateTimeField(default=timezone.now, db_index=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    # What the customer was actually charged minus the lines: the discount the
    # counter gave. total_amount is stored post-discount (what was paid);
    # without this the receipt and the reports disagreed on every discounted sale.
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    payment_method = models.CharField(max_length=32, default="cash")
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["pharmacy", "invoice_number"], name="unique_pharmacy_invoice")]
        ordering = ["-sold_at", "-created_at"]


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    medicine = models.ForeignKey(Medicine, on_delete=models.PROTECT, related_name="sale_lines")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)


class SaleAllocation(models.Model):
    sale_line = models.ForeignKey(SaleLine, on_delete=models.CASCADE, related_name="allocations")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="sale_allocations")
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["sale_line", "batch"], name="unique_line_batch_allocation")]


class Subscription(TimeStampedModel):
    """What a pharmacy is entitled to right now.

    One row per pharmacy: the current entitlement, whatever it was paid with.
    Google Play purchases are only ever written here after the backend has
    verified the purchase token with the Play Developer API, so the server —
    not the app — decides whether a pharmacy is on a paid plan.
    """

    class Plan(models.TextChoices):
        # The app sells exactly two plans: FREE and Pro (the paid tier). The
        # owner flips pharmacies between them from the console after a manual
        # bKash/Nagad payment, and Google Play purchases unlock Pro as well.
        FREE = "free", "Free"
        PRO = "pro", "Pro"

    class Source(models.TextChoices):
        NONE = "none", "None"
        TRIAL = "trial", "Trial"
        PLAY = "play", "Google Play"
        WEB = "web", "Web"
        MANUAL = "manual", "Manual"

    pharmacy = models.OneToOneField(Pharmacy, on_delete=models.CASCADE, related_name="subscription")
    plan = models.CharField(max_length=16, choices=Plan.choices, default=Plan.FREE)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.NONE)
    product_id = models.CharField(max_length=100, blank=True)
    package_name = models.CharField(max_length=100, blank=True)
    purchase_token = models.CharField(max_length=512, blank=True, db_index=True)
    valid_until = models.DateField(null=True, blank=True)
    auto_renewing = models.BooleanField(default=False)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["plan", "valid_until"])]

    def __str__(self):
        return f"{self.pharmacy} / {self.plan}"

    @property
    def is_active(self):
        """A paid plan is active only while it has not lapsed."""
        if self.plan == self.Plan.FREE:
            return False
        if self.valid_until is None:
            return True
        return self.valid_until >= timezone.localdate()

    @property
    def effective_plan(self):
        """The plan the pharmacy can actually use today."""
        return self.plan if self.is_active else self.Plan.FREE

    @classmethod
    def for_pharmacy(cls, pharmacy):
        subscription, _ = cls.objects.get_or_create(pharmacy=pharmacy)
        return subscription


class SignupRequest(TimeStampedModel):
    """A self-serve lead from the public landing page.

    Lifecycle: a visitor registers (PENDING) -> a key is issued automatically
    for the free tier, or held for manual approval once a bKash/Nagad
    transaction id is supplied for a paid plan (PAID_REVIEW) -> admin approves
    (ACTIVE) or rejects (REJECTED). Keys are never stored in plaintext here;
    only delivery state is tracked. The lookup token lets a customer re-open
    their private status page without an account.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        KEY_ISSUED = "key_issued", "Key issued (free)"
        PAID_REVIEW = "paid_review", "Payment to verify"
        ACTIVE = "active", "Active"
        REJECTED = "rejected", "Rejected"

    pharmacy = models.ForeignKey(
        Pharmacy,
        on_delete=models.CASCADE,
        related_name="signups",
        null=True,
        blank=True,
    )
    owner_name = models.CharField(max_length=120)
    pharmacy_name = models.CharField(max_length=180)
    whatsapp = models.CharField(max_length=32, blank=True)
    plan = models.CharField(max_length=16, default="free")
    trx_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    # Hashed lookup token for the public "check my key" link — never the key itself.
    lookup_token = models.CharField(max_length=64, unique=True, db_index=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"], name="signupreq_status_created")]

    @staticmethod
    def generate_token():
        return hashlib.sha256(secrets.token_bytes(32)).hexdigest()

    def __str__(self):
        return f"{self.owner_name} / {self.pharmacy_name} / {self.status}"


class SignupDailyCount(TimeStampedModel):
    """Persistent per-IP daily signup tally for abuse protection.

    The DRF cache alone resets on worker restart and is not shared across
    gunicorn workers, so the authoritative daily count lives here. One row per
    (ip, day) — tiny, indexed, and prunable.
    """

    ip = models.CharField(max_length=64, db_index=True)
    day = models.DateField(db_index=True)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ip", "day"], name="uniq_signup_ip_day"),
        ]
        indexes = [models.Index(fields=["ip", "day"], name="signupdailycnt_ip_day")]

    def __str__(self):
        return f"{self.ip} · {self.day} · {self.count}"


class PlayPurchaseEvent(TimeStampedModel):
    """Audit trail of every Play verification attempt, verified or rejected.

    Kept separately from the entitlement so a disputed charge can always be
    reconstructed, and so a replayed token is visibly idempotent.
    """

    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name="play_events")
    purchase_token = models.CharField(max_length=512, db_index=True)
    product_id = models.CharField(max_length=100, blank=True)
    package_name = models.CharField(max_length=100, blank=True)
    succeeded = models.BooleanField(default=False)
    detail = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        outcome = "verified" if self.succeeded else "rejected"
        return f"{self.pharmacy} / {self.product_id} / {outcome}"


class StockMovement(TimeStampedModel):
    class Kind(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        SALE = "sale", "Sale"
        WASTAGE = "wastage", "Wastage"
        ADJUSTMENT = "adjustment", "Adjustment"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name="stock_movements")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="movements")
    medicine = models.ForeignKey(Medicine, on_delete=models.PROTECT, related_name="stock_movements")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    quantity_delta = models.IntegerField()
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    reference = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-created_at"]


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1 — multi-tenancy (M2: Organization → Pharmacy → Stock)
# ═══════════════════════════════════════════════════════════════════════════
#
# Everything above this line assumes one pharmacy is one tenant. That is the
# right model for a single shop and the wrong one for a chain, which is what
# the enterprise tier sells: a head office that owns several branches, employs
# several people, and needs to see them together without ever seeing another
# company's.
#
# The shape chosen here is a *hierarchy*, not a flat tenancy flag:
#
#   Organization ──┬── Pharmacy (branch) ──┬── Medicine ── Batch ── Sale
#                  │                        └── StockMovement
#                  ├── OrgMembership (who may sign in, and as what)
#                  ├── StaffInvitation (who has been asked to)
#                  └── AuditLog (who did what)
#
# Two consequences are deliberate. A pharmacy's `organization` is nullable, so
# every existing single-shop deployment keeps working untouched and a branch can
# be created before it is assigned. And scoping is enforced by an explicit
# organization filter on every tenant-owned query rather than by a global
# manager, because a global manager makes the *unscoped* query the awkward one
# to write --- and an awkward query is the one a future contributor will skip.


class Organization(TimeStampedModel):
    """A company: the tenant boundary and the billing entity.

    Prices, currency, timezone and the VAT identity all live here rather than on
    the branch, because a chain has one BIN and one accountant, and invoicing
    each branch under its own tax number would be wrong in Bangladesh and
    confusing everywhere else.
    """

    class Plan(models.TextChoices):
        # TRIAL is a real state, not a flag on FREE: a trial that has not
        # started, one that is running and one that has lapsed are three
        # different things to the billing engine and to the UI.
        TRIAL = "trial", "Trial"
        FREE = "free", "Free"
        BRANCH = "branch", "Branch plan"
        ENTERPRISE = "enterprise", "Enterprise"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    # URL-safe, unique, and stable: it appears in invoice references and in the
    # console URL, so it must not change when the display name is corrected.
    slug = models.SlugField(max_length=120, unique=True)
    legal_name = models.CharField(max_length=255, blank=True)
    # Bangladesh VAT registration number. Optional because a small shop may not
    # have one, and a blank BIN must not block a sale --- it only changes what
    # the invoice prints.
    bin = models.CharField("BIN / VAT registration", max_length=32, blank=True)

    currency = models.CharField(max_length=3, default="BDT")
    timezone = models.CharField(max_length=64, default="Asia/Dhaka")
    locale = models.CharField(max_length=8, default="bn")

    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    billing_email = models.EmailField(blank=True)

    plan = models.CharField(max_length=16, choices=Plan.choices, default=Plan.TRIAL)
    #: How many branches the plan's base price covers. Extra branches beyond
    #: this are billed per branch, which is what makes the plan scale with a
    #: customer instead of needing a new negotiation at every opening.
    branch_allowance = models.PositiveIntegerField(default=1)
    #: Extra seats bought on top of the seats included with each branch (M5).
    seat_addon_count = models.PositiveIntegerField(default=0)
    trial_ends_on = models.DateField(null=True, blank=True)

    # ── White-label branding (Phase 6) ──
    # A chain that resells Rakho under its own name sets these; a shop that does
    # not leaves them blank and the product's own identity is used.
    brand_name = models.CharField(max_length=120, blank=True)
    brand_color = models.CharField(max_length=9, blank=True)
    logo_url = models.URLField(max_length=500, blank=True)
    white_label_enabled = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["plan", "is_active"]),
        ]

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        """What the customer's own staff should see.

        A white-labelled tenant sees its own name everywhere, including in
        emails the platform sends on its behalf; the fallback keeps every
        non-branded tenant unchanged.
        """
        if self.white_label_enabled and self.brand_name:
            return self.brand_name
        return self.name

    @property
    def is_trial_active(self):
        if self.plan != self.Plan.TRIAL:
            return False
        if self.trial_ends_on is None:
            return True
        return self.trial_ends_on >= timezone.localdate()

    @property
    def trial_days_left(self):
        """Days remaining, or ``None`` when the question does not apply.

        Returned rather than computed by the client because the client's clock
        and the server's can differ by hours, and a countdown that reads
        "0 days left" on a trial that still has most of a day is the kind of
        detail that generates a support ticket.
        """
        if not self.is_trial_active or self.trial_ends_on is None:
            return None
        return max((self.trial_ends_on - timezone.localdate()).days, 0)

    def accessible_pharmacy_ids(self):
        """Branch ids this organisation owns. The scoping primitive."""
        return self.pharmacies.values_list("id", flat=True)


class OrgMembership(TimeStampedModel):
    """A person's access to one organisation, and the role that defines it.

    A seat is exactly one active membership, which is why the seat count the
    billing engine reads is a count of this table and not a number typed into a
    settings page. Counting the real thing makes it impossible to be billed for
    seats nobody occupies, or to occupy seats nobody pays for.
    """

    class Role(models.TextChoices):
        # Ordered least to most privileged. The permission classes compare
        # against this order rather than against a set of role names, so adding
        # a role in the middle cannot silently widen an existing gate.
        VIEWER = "viewer", "Viewer"
        STAFF = "staff", "Staff"
        MANAGER = "manager", "Manager"
        ADMIN = "admin", "Admin"
        OWNER = "owner", "Owner"

    #: Privilege order, used by ``has_at_least``.
    ROLE_ORDER = [Role.VIEWER, Role.STAFF, Role.MANAGER, Role.ADMIN, Role.OWNER]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    #: A plain FK to Django's user model. The console signs in with
    #: email + password, so ``auth.User`` is the right principal and a custom
    #: user model would be a migration every tenant pays for.
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE, related_name="org_memberships")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    is_active = models.BooleanField(default=True)
    #: Which branch this person opens by default. Null means "whichever is
    #: first", which is right for an owner who works across all of them.
    default_pharmacy = models.ForeignKey(
        Pharmacy,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="default_for_memberships",
    )
    #: Restricts a staff member to specific branches. Empty means every branch
    #: in the organisation, which is the common case; a manager who must not see
    #: another branch's takings is the reason this exists at all.
    scoped_pharmacies = models.ManyToManyField(Pharmacy, blank=True, related_name="scoped_memberships")
    invited_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invited_members",
    )
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["organization", "user__email"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="unique_membership_per_org_user"),
        ]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"

    def has_at_least(self, role):
        """True when this member's role is at least ``role`` in the order.

        Comparing ranks rather than matching names means a gate written as
        "manager or above" cannot be defeated by adding a new role between
        manager and owner.
        """
        try:
            return self.ROLE_ORDER.index(self.role) >= self.ROLE_ORDER.index(role)
        except ValueError:
            return False

    def visible_pharmacy_ids(self):
        """Branches this member may see, honouring any explicit restriction.

        Returns a queryset rather than a list so a caller can use it directly as
        a filter argument, which is the whole point: the restriction travels
        with the query instead of being re-implemented at each call site.
        """
        scoped = self.scoped_pharmacies.all()
        if scoped.exists():
            return scoped.values_list("id", flat=True)
        return self.organization.pharmacies.values_list("id", flat=True)


class StaffInvitation(TimeStampedModel):
    """A pending invitation to join an organisation.

    The invitation is a row rather than a signed link, for two reasons. It can
    be revoked before it is used --- a link cannot --- and the seat it will
    occupy is visible to the billing engine the moment it is issued, so an owner
    sees that inviting the sixth person will cost money before they send it.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=OrgMembership.Role.choices, default=OrgMembership.Role.STAFF)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    #: Only the hash is stored. A database dump must not be a pile of usable
    #: invitation links, and the raw token exists only in the email.
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        OrgMembership,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_invitations",
    )
    default_pharmacy = models.ForeignKey(
        Pharmacy,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invitations",
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accepted_invitations",
    )
    #: Set when the invitation email could not be delivered, so a failed send is
    #: visible in the console instead of leaving the owner waiting for a message
    #: that never arrives.
    last_send_error = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["email", "status"]),
        ]
        constraints = [
            # One live invitation per address per organisation. Re-inviting the
            # same person should resend the existing invitation rather than
            # create a second one that occupies a second seat.
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=models.Q(status="pending"),
                name="unique_pending_invitation_per_email",
            )
        ]

    def __str__(self):
        return f"{self.email} -> {self.organization} ({self.status})"

    @staticmethod
    def generate_raw_token():
        return f"inv_{secrets.token_urlsafe(32)}"

    @staticmethod
    def hash_token(raw_token):
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()

    @property
    def is_actionable(self):
        """Pending and still inside its window: the only state that accepts."""
        return self.status == self.Status.PENDING and not self.is_expired


class AuditLog(TimeStampedModel):
    """An append-only record of what changed, by whom, and from where.

    Immutability is enforced in the model rather than by convention: ``save()``
    refuses an update to an existing row and ``delete()`` is blocked outright.
    An audit trail that can be edited is not evidence, and the whole reason a
    chain's compliance officer accepts this deployment is that the answer to
    "who changed this price" is not "someone with database access".
    """

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        LOGIN = "login", "Login"
        LOGIN_FAILED = "login_failed", "Login failed"
        INVITE = "invite", "Invite"
        INVITE_ACCEPTED = "invite_accepted", "Invitation accepted"
        ROLE_CHANGED = "role_changed", "Role changed"
        SEAT_LIMIT_REACHED = "seat_limit_reached", "Seat limit reached"
        PLAN_CHANGED = "plan_changed", "Plan changed"
        EXPORT = "export", "Export"
        API_KEY_ISSUED = "api_key_issued", "API key issued"
        API_KEY_REVOKED = "api_key_revoked", "API key revoked"
        PAYMENT_RECORDED = "payment_recorded", "Payment recorded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.CASCADE, related_name="audit_entries")
    #: Denormalised on purpose. If a membership is later removed the entry must
    #: still say who did it, so the actor is recorded as text as well as by FK.
    actor_email = models.CharField(max_length=254, blank=True)
    actor = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    pharmacy = models.ForeignKey(
        Pharmacy,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=24, choices=Action.choices)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    #: Field-level before/after. Stored as JSON so a new field needs no
    #: migration, and rendered by the console as a diff.
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["pharmacy", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["target_type", "target_id"]),
        ]
        verbose_name_plural = "audit log entries"

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_email or 'system'} {self.action}"

    def save(self, *args, **kwargs):
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise ValueError("Audit entries are append-only and cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit entries are append-only and cannot be deleted.")


class Invoice(TimeStampedModel):
    """A VAT invoice for one organisation and one period.

    This is the document a Bangladeshi business needs to expense the software
    and, for a reseller, to re-bill their own customers --- so it is a real
    record, not a rendered view of the current quote. The amounts and the tax
    identity are **snapshotted** at issue. An invoice whose total is recomputed
    every time it is opened would silently change the day a branch closes or a
    customer's BIN is corrected, and a number that moves after the fact is not
    an invoice.

    Money is stored as whole taka. Invoicing a pharmacy in fractions of a taka
    would print a total no bank transfer can match.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="invoices")
    number = models.CharField(max_length=32, unique=True, db_index=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT, db_index=True)

    period_start = models.DateField()
    period_end = models.DateField()
    issued_on = models.DateField(null=True, blank=True)
    due_on = models.DateField(null=True, blank=True)
    paid_on = models.DateField(null=True, blank=True)

    currency = models.CharField(max_length=3, default="BDT")
    #: Tax identity as it stood on the issue date. Blank is legitimate --- a
    #: shop without a BIN gets a plain receipt, and copying it onto the invoice
    #: is what keeps a later BIN correction from rewriting history.
    seller_name = models.CharField(max_length=255, blank=True)
    seller_bin = models.CharField(max_length=32, blank=True)
    buyer_name = models.CharField(max_length=255, blank=True)
    buyer_bin = models.CharField(max_length=32, blank=True)
    buyer_address = models.CharField(max_length=255, blank=True)

    #: Integer taka throughout. ``subtotal + vat_amount == total`` is asserted
    #: by a test, because an invoice that does not add up is the one arithmetic
    #: error a finance team will always find.
    subtotal = models.PositiveIntegerField(default=0)
    vat_percent = models.CharField(max_length=8, default="15.00")
    vat_amount = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)

    notes = models.CharField(max_length=500, blank=True)
    #: The plan quoted, kept for the same reason as the amounts.
    plan = models.CharField(max_length=16, blank=True)

    class Meta:
        ordering = ["-period_start", "-created_at"]
        constraints = [
            # One live invoice per tenant per period. A re-run must amend the
            # draft it produced, not stack a second invoice for the same month.
            models.UniqueConstraint(
                fields=["organization", "period_start", "period_end"],
                condition=~models.Q(status="void"),
                name="unique_live_invoice_per_period",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["status", "-period_start"]),
        ]

    def __str__(self):
        return f"{self.number} {self.organization_id} {self.total} {self.currency}"

    def recalculate(self):
        """Re-derive subtotal/VAT/total from the lines, in whole taka."""
        self.subtotal = sum(line.amount for line in self.lines.all())
        try:
            percent = float(self.vat_percent or "0")
        except (TypeError, ValueError):
            percent = 0.0
        self.vat_amount = round(self.subtotal * percent / 100)
        self.total = self.subtotal + self.vat_amount
        return self


class InvoiceLine(TimeStampedModel):
    """One billable item on an invoice: a branch, a seat block, or a plan fee.

    Rows rather than four columns on the invoice, so the invoice can explain
    itself ("Dhanmondi branch --- 1,499") and so a new line type --- an SMS pack,
    a support retainer --- needs no migration.
    """

    class Kind(models.TextChoices):
        BASE = "base", "Base plan"
        BRANCH = "branch", "Additional branch"
        SEAT = "seat", "Additional seat"
        ADDON = "addon", "Add-on"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.BRANCH)
    description = models.CharField(max_length=255)
    #: Free-text quantity (a headcount, a branch count) kept as an integer; the
    #: unit price is what turns it into money, and both are shown on the invoice.
    quantity = models.PositiveIntegerField(default=1)
    unit_amount = models.PositiveIntegerField(default=0)
    amount = models.PositiveIntegerField(default=0)
    #: Links the row back to the branch it bills, when there is one, so the
    #: console can say which branch a line refers to without parsing text.
    pharmacy_id = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["kind", "description", "id"]

    def __str__(self):
        return f"{self.description} x{self.quantity} = {self.amount}"

    def save(self, *args, **kwargs):
        if not self.amount:
            self.amount = (self.unit_amount or 0) * (self.quantity or 0)
        return super().save(*args, **kwargs)


# ──────────────────────────────────────────────────────────────
#  Privacy layer: optional profile, preferences, consent, and
#  the two analytics tables (Phase: privacy).
#
#  Every table here is *optional* by construction: a pharmacy with no
#  UserProfile, no UserPreference and no UserConsent rows is a fully working
#  account, which is what "the app works even if you skip every question"
#  means at the schema level. Nothing in this section holds a phone number or
#  any other core credential — the core identity stays on Pharmacy, and the
#  analytics tables deliberately carry no FK to it, so a join back to a shop
#  is not expressible in the schema rather than merely forbidden in code.
# ──────────────────────────────────────────────────────────────


class UserProfile(TimeStampedModel):
    """The light, optional profile behind the progressive question cards.

    One row per pharmacy, created only when the first answer arrives. Every
    field is blankable: skipping a question never writes a row, and deleting
    the row (``DELETE /api/v1/profile/``) leaves the account untouched.

    ``license_no_encrypted`` is AES-GCM ciphertext produced by
    ``inventory.field_crypto``; the plaintext never reaches the database, and
    the API decrypts only for the caller who already proved ownership of the
    pharmacy with its own key.
    """

    class ShopType(models.TextChoices):
        RETAIL = "retail", "Retail pharmacy"
        WHOLESALE = "wholesale", "Wholesale"
        CLINIC = "clinic", "Clinic or hospital pharmacy"
        OTHER = "other", "Other"

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        PHARMACIST = "pharmacist", "Pharmacist"
        STAFF = "staff", "Staff"

    class SizeRange(models.TextChoices):
        UNDER_100 = "under_100", "Under 100 items"
        FROM_100_TO_500 = "100_500", "100 to 500 items"
        FROM_500_TO_2000 = "500_2000", "500 to 2000 items"
        OVER_2000 = "over_2000", "Over 2000 items"

    #: The user_id of the privacy plan. OneToOne rather than a plain FK, so a
    #: shop can never accumulate two profiles through a retried request.
    pharmacy = models.OneToOneField(Pharmacy, on_delete=models.CASCADE, related_name="profile")
    owner_name = models.CharField(max_length=80, blank=True)
    district = models.CharField(max_length=80, blank=True, db_index=True)
    upazila = models.CharField(max_length=80, blank=True)
    shop_type = models.CharField(max_length=16, choices=ShopType.choices, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, blank=True)
    size_range = models.CharField(max_length=16, choices=SizeRange.choices, blank=True)
    #: Drug licence number, encrypted at rest. Never logged, never exported to
    #: the analytics tables, never shown to a sponsor.
    license_no_encrypted = models.TextField(blank=True)
    #: Percentage of the seven optional fields answered (0-100), recomputed on
    #: every save so a field cleared through the API cannot leave a stale "you
    #: are 60% done" behind.
    profile_completeness = models.PositiveSmallIntegerField(default=0)

    #: The seven fields whose answers count towards completeness. Kept beside
    #: the model so the API and the console cannot drift apart on what "done"
    #: means.
    OPTIONAL_FIELDS = ("owner_name", "district", "upazila", "shop_type", "role", "size_range", "license_no")

    def __str__(self):
        return f"profile for {self.pharmacy_id}"

    @property
    def license_no(self) -> str:
        """Plaintext licence number, decrypted for the authenticated owner."""
        from .field_crypto import decrypt_field

        return decrypt_field("license_no", self.license_no_encrypted)

    @license_no.setter
    def license_no(self, value: str) -> None:
        from .field_crypto import encrypt_field

        self.license_no_encrypted = encrypt_field("license_no", value) if value else ""

    def completeness(self) -> int:
        """Share of the optional fields that carry an answer, as 0-100.

        Reads the ciphertext column for the licence rather than decrypting it:
        answering "is it filled in" must never depend on the key being
        healthy, or a rotated key would start failing ordinary profile saves.
        """
        answered = 0
        for field in self.OPTIONAL_FIELDS:
            if field == "license_no":
                answered += bool(self.license_no_encrypted)
            else:
                answered += bool(getattr(self, field))
        return round(100 * answered / len(self.OPTIONAL_FIELDS))

    def save(self, *args, **kwargs):
        self.profile_completeness = self.completeness()
        return super().save(*args, **kwargs)


class UserPreference(TimeStampedModel):
    """Optional multi-select answers that do not belong on the profile row.

    Split from ``UserProfile`` because a list that changes independently (the
    wholesalers a shop buys from) should not rewrite the row a completeness
    percentage is computed from, and because the privacy plan promises the two
    can be cleared separately.
    """

    pharmacy = models.OneToOneField(Pharmacy, on_delete=models.CASCADE, related_name="preferences")
    #: List of free-text wholesaler names, e.g. ["Square", "Incepta"].
    #: Validated at the API boundary (max 10 entries, 80 chars each).
    preferred_wholesalers = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"preferences for {self.pharmacy_id}"


class UserConsent(TimeStampedModel):
    """One row per pharmacy per consent type: the record the policy promises.

    Default-deny: a missing row and a ``granted=False`` row mean the same
    thing, and every non-core consent starts missing. ``updated_at`` (inherited
    from TimeStampedModel, refreshed on every toggle) is the timestamp of the
    current status, and ``policy_version`` is the privacy policy version in
    force when that status was recorded — so "they agreed to v1.0 in October"
    survives a later policy update.
    """

    class Type(models.TextChoices):
        #: Anonymous usage statistics. Off until the user turns it on.
        ANALYTICS = "analytics", "Anonymous usage statistics"
        #: In-app offers from distributors. Off; contact sharing still needs a
        #: second confirmation at the moment of the tap.
        SPONSOR_OFFERS = "sponsor_offers", "Offers from distributors"
        #: Inclusion in area-level aggregates (suppressed below 10 shops).
        AREA_INSIGHTS = "area_insights", "Area-level market insights"

    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name="consents")
    type = models.CharField(max_length=24, choices=Type.choices)
    granted = models.BooleanField(default=False)
    #: The privacy policy version shown when this status was recorded.
    policy_version = models.CharField(max_length=16, blank=True)

    class Meta:
        ordering = ["type"]
        constraints = [
            # Toggling a consent updates its row instead of stacking duplicates,
            # so "when did they last say yes" is always answered by one row.
            models.UniqueConstraint(fields=["pharmacy", "type"], name="unique_consent_per_pharmacy"),
        ]
        indexes = [models.Index(fields=["pharmacy", "type"])]

    def __str__(self):
        state = "granted" if self.granted else "refused"
        return f"{self.type} {state} for {self.pharmacy_id}"


class AnalyticsEvent(models.Model):
    """An anonymous usage event, deliberately un-joinable to a shop.

    There is no foreign key to Pharmacy here on purpose: the pseudonymous id
    is minted on the device, and the only thing that could link it back is a
    mapping that lives with the profile — not in this table, not in this
    database region of the schema. Retention is enforced by a scheduled
    aggregation job (12 months, then the row is folded into aggregates and
    deleted).
    """

    #: Hex id minted on device; never a phone number, never an API key.
    pseudonymous_id = models.CharField(max_length=40, db_index=True)
    event_name = models.CharField(max_length=64)
    #: Small, allow-listed keys ("screen_viewed", "count": 3). The values are
    #: binned before they get here; raw prices or customer names are not
    #: allowed in.
    properties = models.JSONField(default=dict, blank=True)
    ts = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-ts"]
        indexes = [
            models.Index(fields=["event_name", "ts"]),
            models.Index(fields=["pseudonymous_id", "ts"]),
        ]

    def __str__(self):
        return f"{self.event_name} @{self.ts:%Y-%m-%d}"


#: Below this many distinct shops in a group, no aggregate is ever stored or
#: served. A module-level constant because both the model's check constraint
#: and the aggregation pipeline read it, and a nested class body cannot see
#: the enclosing class's own attributes.
MIN_GROUP_SHOPS = 10


class AggregatedInsight(models.Model):
    """A metric over a group of shops — the only shape a sponsor ever sees.

    Written exclusively by the aggregation pipeline, which suppresses any
    group smaller than MIN_GROUP_SHOPS. The check constraint below makes that
    suppression a database-level guarantee: a bug that tries to store a
    re-identifying sliver fails the write instead of shipping it.
    """

    #: Mirror of the module-level MIN_GROUP_SHOPS, checked by the constraint
    #: below; kept on the class so the pipeline can read it from the model.
    MIN_GROUP_SHOPS = MIN_GROUP_SHOPS

    #: Bucket label, e.g. "2026-10" (month) or "2026-W41" (week).
    period = models.CharField(max_length=32)
    #: Broad geography only — district level, never upazila for small groups.
    area = models.CharField(max_length=80, blank=True, db_index=True)
    #: Medicine category (or "all").
    category = models.CharField(max_length=64, blank=True)
    metric = models.CharField(max_length=64)
    #: Whole units by default; two decimals keep room for money aggregates.
    value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    #: Number of distinct shops behind this number. Must be >= MIN_GROUP_SHOPS.
    shop_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-period", "area", "metric"]
        constraints = [
            models.UniqueConstraint(fields=["period", "area", "category", "metric"], name="unique_insight_cell"),
            models.CheckConstraint(condition=models.Q(shop_count__gte=MIN_GROUP_SHOPS), name="insight_min_group_10"),
        ]
        indexes = [models.Index(fields=["metric", "period"])]

    def __str__(self):
        return f"{self.area or 'all'}/{self.metric}={self.value} ({self.shop_count} shops)"
