from datetime import timedelta

from django.contrib import admin, messages
from django.core.management import CommandError, call_command
from django.db.models import Exists, OuterRef, Q, Subquery
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .admin_dashboard import dashboard_stats
from .models import (
    CatalogMedicine, Pharmacy, PharmacyApiKey, SignupRequest, Subscription,
)


#: Exact durations offered for comping and key rotation. "Custom" is handled
#: separately by a date input, so the list stays the short one a dropdown wants.
DURATION_CHOICES = (
    ("1m", "1 month"),
    ("3m", "3 months"),
    ("6m", "6 months"),
    ("1y", "1 year"),
    ("lifetime", "No expiry (lifetime)"),
    ("custom", "Custom end date…"),
)


def _duration_end(kind, custom_date=None):
    """Turn a DURATION_CHOICES value into an entitlement end date.

    Returns ``None`` for lifetime (no expiry). "custom" requires a valid date;
    anything unparseable falls back to one month rather than erroring out, so a
    malformed submission can never leave the form half-applied.
    """
    days = {"1m": 30, "3m": 91, "6m": 182, "1y": 365}
    if kind == "lifetime":
        return None
    if kind == "custom":
        try:
            end = timezone.datetime.fromisoformat(str(custom_date or "").strip())
        except ValueError:
            end = None
        if end is None:
            return timezone.localdate() + timedelta(days=30)
        # The date input yields a datetime at midnight; a DateField wants a date.
        return end.date() if hasattr(end, "hour") else end
    return timezone.localdate() + timedelta(days=days.get(kind, 30))


class RakhoAdminSite(admin.AdminSite):
    """Owner console with a live dashboard as the landing page."""

    site_header = "Rakho Console"
    site_title = "Rakho"
    index_title = "Overview"

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["rk"] = dashboard_stats()
        return super().index(request, extra_context)


admin_site = RakhoAdminSite(name="rakho_admin")

# ── The console is deliberately five models ──────────────────────────────
#
# The owner runs shops, their API access, their subscriptions and the
# payments waiting to be verified. Everything else in the schema belongs to a
# pharmacy's own operation — medicines, batches, sales and the ledgers behind
# them — and is written by the Android app through the API, not typed by the
# owner. Registering those made the console a wall of thirteen tables with
# half-empty "Add" forms for records no person should ever create, which is
# how a one-person console stops being readable.
#
# CatalogMedicine stays because it is the one piece of *product data* the
# owner must be able to load: the console raises "the catalogue is empty"
# itself, and leaving no way to fix that would be worse than the extra entry.
# It is read-only, so it is not a form.
#
# PharmacyApiKey, Subscription and SignupRequest are registered by the
# decorators below, which carry the issue-key, comp-a-plan and
# approve-payment actions this console is for.
admin_site.register(Pharmacy)


@admin.register(CatalogMedicine, site=admin_site)
class CatalogMedicineAdmin(admin.ModelAdmin):
    """Read-only window onto the national catalogue the app searches.

    These rows are *data*, not inventory: they arrive from the public Assorted
    Medicine Dataset of Bangladesh (a Kaggle export) via
    ``manage.py import_bangladesh_catalog`` and every install searches the same
    server-side copy. Hand-typing or editing one here would silently fork the
    owner's copy from the dataset, so the console shows the records and offers a
    one-click re-import instead of an add/change form.
    """

    list_display = (
        "brand_name", "generic_name", "strength", "dosage_form",
        "manufacturer_name", "medicine_type",
    )
    list_filter = ("medicine_type",)
    search_fields = ("brand_name", "generic_name", "manufacturer_name", "source_brand_id")
    readonly_fields = [field.name for field in CatalogMedicine._meta.fields]
    list_per_page = 50
    change_list_template = "admin/inventory/catalogmedicine/change_list.html"

    # No `actions` here on purpose: Django only renders the changelist action
    # dropdown when `has_change_permission` is true, so an action on a read-only
    # admin is reachable by POST but invisible in the UI. The refresh lives on
    # its own URL, surfaced as an object-tools button by the change_list
    # template, so the owner can actually see and click it.
    def get_urls(self):
        return [
            path(
                "import/",
                self.admin_site.admin_view(self.import_from_dataset),
                name="inventory_catalogmedicine_import",
            ),
        ] + super().get_urls()

    def has_add_permission(self, request):
        # The dataset is the only writer; a blank row here would have no
        # source_brand_id and could never be updated by the next import.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Deleting rows here only makes the next import recreate them.
        return False

    def import_from_dataset(self, request):
        """Fetch the source archive and upsert it. Never clears a live row.

        POST-only: the import mutates the whole table, so it must not be
        triggerable by a link a browser, crawler or prefetcher could follow.
        """
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        before = CatalogMedicine.objects.count()
        try:
            call_command("import_bangladesh_catalog", "--download", verbosity=0)
        except CommandError as exc:
            self.message_user(
                request, f"Import failed, catalogue unchanged: {exc}", messages.ERROR)
        else:
            after = CatalogMedicine.objects.count()
            self.message_user(
                request,
                f"Catalogue re-imported: {after - before:+,} new, {after:,} total.",
                messages.SUCCESS,
            )
        return HttpResponseRedirect(
            reverse("admin:inventory_catalogmedicine_changelist"))


def _pharmacy_subscription(pharmacy):
    """The pharmacy's subscription row, creating the free default if missing."""
    return Subscription.for_pharmacy(pharmacy)


def _set_paid(subscription, *, duration="1m", custom_date=None,
              source=Subscription.Source.MANUAL):
    """Mark a pharmacy PAID (Pro) until the chosen duration's end.

    Payments are collected manually (bKash/Nagad TrxID verified by the owner,
    or Google Play), so nothing here implies auto-renewal: when the date
    passes, `effective_plan` simply reports FREE again. A Play-managed row
    keeps its PLAY source and purchase token so Play can re-verify it later.
    """
    was_play = subscription.source == Subscription.Source.PLAY
    subscription.plan = Subscription.Plan.PRO
    if not was_play:
        subscription.source = source
    subscription.last_verified_at = timezone.now()
    subscription.valid_until = _duration_end(duration, custom_date)
    subscription.save()


def _set_free(subscription):
    """Move a pharmacy to FREE. Paid features cut off immediately.

    A Play-managed row keeps its purchase token — evidence of a real purchase
    the server can re-verify later; a manual row's stale product metadata is
    cleared. Manual rows never auto-renew, so the flag is reset defensively.
    """
    was_play = subscription.source == Subscription.Source.PLAY
    subscription.plan = Subscription.Plan.FREE
    subscription.source = Subscription.Source.MANUAL
    subscription.auto_renewing = False
    subscription.last_verified_at = timezone.now()
    subscription.valid_until = None
    if not was_play:
        subscription.product_id = ""
        subscription.purchase_token = ""
    subscription.save()


def _key_expiry(kind, custom_instant=None):
    """Datetime a rotated key should die at, from a DURATION_CHOICES value."""
    now = timezone.now()
    spans = {
        "1m": timedelta(days=30),
        "3m": timedelta(days=91),
        "6m": timedelta(days=182),
        "1y": timedelta(days=365),
    }
    if kind == "lifetime":
        return None
    if kind == "custom":
        try:
            end = timezone.datetime.fromisoformat(str(custom_instant or "").strip())
        except ValueError:
            return now + timedelta(days=30)
        if timezone.is_naive(end):
            end = timezone.make_aware(end)
        return max(end, now)
    return now + spans.get(kind, timedelta(days=30))


def _tier_badge(subscription):
    """High-contrast FREE / PAID pill for the key list and subscription list."""
    if subscription.effective_plan == Subscription.Plan.FREE:
        return format_html('<span class="rk-tier rk-free">FREE</span>')
    return format_html('<span class="rk-tier rk-paid">PAID</span>')


@admin.register(PharmacyApiKey, site=admin_site)
class PharmacyApiKeyAdmin(admin.ModelAdmin):
    """Every control the owner has over a pharmacy's API access.

    The raw key is shown exactly once when rotated — copy it and send it to
    the verified customer; it is never stored or shown again. Revoking a key
    cuts that device's access instantly.
    """

    list_display = (
        "pharmacy", "label", "key_prefix", "tier_column", "live_column",
        "expires_at", "created_at", "key_actions",
    )
    list_filter = ("revoked_at", "pharmacy__subscription__plan")
    search_fields = ("pharmacy__name", "label", "key_prefix")
    readonly_fields = ("key_prefix", "key_hash", "created_at", "updated_at")
    actions = ("issue_new_key", "revoke_keys", "restore_keys")
    change_list_template = "admin/inventory/pharmacyapikey/change_list.html"

    # The tier and liveness columns come from two correlated subqueries so the
    # FREE/PAID badge and the row actions read the *current* entitlement state
    # without one query per row.
    def get_queryset(self, request):
        plan_col = Subscription.objects.filter(
            pharmacy=OuterRef("pharmacy"),
            plan__gt=Subscription.Plan.FREE,
        ).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate())
        ).values("plan")[:1]
        active = PharmacyApiKey.objects.filter(
            pharmacy=OuterRef("pharmacy"), revoked_at__isnull=True,
        ).values("pk")[:1]
        return (
            PharmacyApiKey.objects
            .annotate(db_tier=Subquery(plan_col), live_key=Exists(active))
            .select_related("pharmacy")
            .order_by("-created_at")
        )

    # ── Columns ────────────────────────────────────────────────────────────

    @admin.display(description="Plan")
    def tier_column(self, obj):
        # db_tier is the annotated active-plan subquery: no per-row query.
        if not getattr(obj, "live_key", False):
            return format_html('<span class="rk-tier rk-muted">—</span>')
        tier = getattr(obj, "db_tier", None) or Subscription.Plan.FREE
        if tier == Subscription.Plan.FREE:
            return format_html('<span class="rk-tier rk-free">FREE</span>')
        return format_html('<span class="rk-tier rk-paid">PAID</span>')

    @admin.display(boolean=True, description="Active")
    def live_column(self, obj):
        return obj.is_live

    # Per-row buttons are a single formatted <td> whose links carry the row
    # pk; Django renders whatever a list_display method returns, so no custom
    # template hooks are needed to place them.
    @admin.display(description="Controls")
    def key_actions(self, obj):
        revoke = (
            reverse("admin:inventory_pharmacyapikey_revoke", args=[obj.pk])
            if obj.revoked_at is None
            else None
        )
        restore = (
            reverse("admin:inventory_pharmacyapikey_restore", args=[obj.pk])
            if obj.revoked_at is not None
            else None
        )
        rotate = reverse("admin:inventory_pharmacyapikey_rotate", args=[obj.pk])
        rotate_link = format_html(
            '<a class="rk-btn rk-rotate" href="{}">Rotate</a>', rotate)
        if revoke:
            revoke_link = format_html(
                '<a class="rk-btn rk-danger" href="{}" onclick="return confirm(\'Revoke this key now?\')">Revoke</a>',
                revoke)
        elif restore:
            revoke_link = format_html(
                '<a class="rk-btn rk-restore" href="{}">Restore</a>', restore)
        else:
            revoke_link = ""
        return format_html(
            '{} {}', rotate_link, revoke_link)

    # ── Per-row control endpoints ─────────────────────────────────────────

    # One URL each, POST-only, admin_view-wrapped. The confirm dialog keeps a
    # misfire from costing a customer their access; the redirect back to the
    # list with a message keeps the flow one click deep.
    def get_urls(self):
        custom = [
            path(
                "<path:object_id>/rotate/",
                self.admin_site.admin_view(self.rotate_key),
                name="inventory_pharmacyapikey_rotate",
            ),
            path(
                "<path:object_id>/revoke/",
                self.admin_site.admin_view(self.revoke_key),
                name="inventory_pharmacyapikey_revoke",
            ),
            path(
                "<path:object_id>/restore/",
                self.admin_site.admin_view(self.restore_key),
                name="inventory_pharmacyapikey_restore",
            ),
        ]
        return custom + super().get_urls()

    def _redirect(self):
        return HttpResponseRedirect(
            reverse("admin:inventory_pharmacyapikey_changelist"))

    def _get_key(self, request, object_id):
        return self.get_object(request, object_id)

    def rotate_key(self, request, object_id):
        """Issue a fresh key, optionally with an expiry, and show it once.

        GET renders the duration form; POST performs the rotation. The old key
        is revoked the moment the new one is minted, so the two never overlap.
        """
        key = self._get_key(request, object_id)
        if key is None:
            messages.error(request, "Key not found.")
            return self._redirect()
        if request.method != "POST":
            context = {
                **self.admin_site.each_context(request),
                "title": f"Rotate key — {key.pharmacy.name}",
                "key": key,
                "duration_choices": DURATION_CHOICES,
                "opts": self.model._meta,
            }
            return TemplateResponse(
                request,
                "admin/inventory/pharmacyapikey/rotate_form.html",
                context,
            )
        duration = request.POST.get("duration", "lifetime")
        expires_at = _key_expiry(duration, request.POST.get("custom_expires_at"))
        _, raw = PharmacyApiKey.create_key(
            key.pharmacy,
            label=f"{key.label} (rotated {timezone.localdate():%d %b %Y})",
            expires_at=expires_at,
        )
        if key.revoked_at is None:
            key.revoked_at = timezone.now()
            key.save(update_fields=["revoked_at", "updated_at"])
        self.message_user(
            request,
            f"New key for {key.pharmacy.name}: {raw} — copy it now; it will not be shown again.",
            messages.SUCCESS,
        )
        return self._redirect()

    def revoke_key(self, request, object_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        key = self._get_key(request, object_id)
        if key is None:
            messages.error(request, "Key not found.")
            return self._redirect()
        if key.revoked_at is not None:
            messages.warning(request, "That key was already revoked.")
        else:
            key.revoked_at = timezone.now()
            key.save(update_fields=["revoked_at", "updated_at"])
            messages.warning(
                request, f"Revoked {key.key_prefix}… for {key.pharmacy.name}.")
        return self._redirect()

    def restore_key(self, request, object_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        key = self._get_key(request, object_id)
        if key is None:
            messages.error(request, "Key not found.")
            return self._redirect()
        if key.expires_at is not None and key.expires_at <= timezone.now():
            key.expires_at = None
            key.revoked_at = None
            key.save(update_fields=["revoked_at", "expires_at", "updated_at"])
            messages.success(
                request,
                f"Restored {key.key_prefix}… for {key.pharmacy.name} (past expiry cleared).",
            )
        else:
            key.revoked_at = None
            key.save(update_fields=["revoked_at", "updated_at"])
            messages.success(
                request, f"Restored {key.key_prefix}… for {key.pharmacy.name}.")
        return self._redirect()

    # ── Bulk actions (kept alongside the per-row buttons) ─────────────────

    @admin.action(description="Issue NEW key for this pharmacy (shows once)")
    def issue_new_key(self, request, queryset):
        # One key per row so the raw key shown is unambiguous.
        for key in queryset.select_related("pharmacy"):
            _, raw = PharmacyApiKey.create_key(key.pharmacy, label="Re-issued")
            self.message_user(
                request,
                f"New key for {key.pharmacy.name}: {raw} — copy it now; it will not be shown again.",
                messages.SUCCESS,
            )

    @admin.action(description="Revoke selected keys (cuts access immediately)")
    def revoke_keys(self, request, queryset):
        updated = queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        self.message_user(request, f"Revoked {updated} key(s).", messages.WARNING)

    @admin.action(description="Restore selected keys (undo revoke)")
    def restore_keys(self, request, queryset):
        updated = 0
        for key in queryset.filter(revoked_at__isnull=False):
            key.revoked_at = None
            if key.expires_at is not None and key.expires_at <= timezone.now():
                key.expires_at = None
                key.save(update_fields=["revoked_at", "expires_at", "updated_at"])
            else:
                key.save(update_fields=["revoked_at", "updated_at"])
            updated += 1
        self.message_user(request, f"Restored {updated} key(s).", messages.SUCCESS)


@admin.register(Subscription, site=admin_site)
class SubscriptionAdmin(admin.ModelAdmin):
    """Switch a pharmacy between FREE and PAID and set how long PAID lasts.

    Payments are manual (bKash/Nagad TrxID verified by the owner, or Google
    Play). Nothing auto-renews: when `valid_until` passes, the entitlement
    becomes FREE on its own — no admin action needed.
    """

    list_display = ("pharmacy", "tier_badge", "source", "valid_until",
                    "time_left", "plan_actions")
    list_filter = ("plan", "source", "auto_renewing")
    search_fields = ("pharmacy__name", "product_id", "purchase_token")
    readonly_fields = ("created_at", "updated_at", "last_verified_at", "raw_response")
    actions = ("set_paid_1m", "set_paid_6m", "set_paid_1y", "downgrade_free")

    @admin.display(description="Status")
    def tier_badge(self, obj):
        return _tier_badge(obj)

    @admin.display(description="Time left", ordering="valid_until")
    def time_left(self, obj):
        """Human sentence for the remaining paid time — or the lapse."""
        if obj.plan == Subscription.Plan.FREE:
            return format_html('<span class="rk-quiet">free plan</span>')
        if obj.valid_until is None:
            return format_html('<span class="rk-ok-text">no end date</span>')
        today = timezone.localdate()
        days = (obj.valid_until - today).days
        if days < 0:
            return format_html(
                '<span class="rk-lapsed">lapsed {} d ago → FREE</span>', -days)
        if days == 0:
            return format_html('<span class="rk-warn">ends today</span>')
        if days <= 7:
            return format_html(
                '<span class="rk-warn">{} day{} left</span>', days,
                "" if days == 1 else "s")
        return f"{days} days left"

    # Same per-row pattern as the key list: one row of POST links, one per
    # action, so every entitlement lever is one click from the list.
    @admin.display(description="Controls")
    def plan_actions(self, obj):
        free = reverse("admin:inventory_subscription_set_free", args=[obj.pk])
        pro = reverse("admin:inventory_subscription_set_pro", args=[obj.pk])
        return format_html(
            '{} {}',
            format_html('<a class="rk-btn rk-danger" href="{}">Set FREE</a>', free),
            format_html('<a class="rk-btn rk-rotate" href="{}">Set PAID…</a>', pro),
        )

    def get_urls(self):
        return [
            path(
                "<path:object_id>/set-free/",
                self.admin_site.admin_view(self.set_free_view),
                name="inventory_subscription_set_free",
            ),
            path(
                "<path:object_id>/set-pro/",
                self.admin_site.admin_view(self.set_pro_view),
                name="inventory_subscription_set_pro",
            ),
        ] + super().get_urls()

    def _redirect(self):
        return HttpResponseRedirect(
            reverse("admin:inventory_subscription_changelist"))

    def set_free_view(self, request, object_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        subscription = self.get_object(request, object_id)
        if subscription is None:
            messages.error(request, "Subscription not found.")
            return self._redirect()
        _set_free(subscription)
        messages.warning(
            request,
            f"{subscription.pharmacy.name} is now FREE — paid features are cut off.")
        return self._redirect()

    def set_pro_view(self, request, object_id):
        """Set PAID until the duration picked on the form page."""
        subscription = self.get_object(request, object_id)
        if subscription is None:
            messages.error(request, "Subscription not found.")
            return self._redirect()
        if request.method != "POST":
            context = {
                **self.admin_site.each_context(request),
                "title": f"Set PAID — {subscription.pharmacy.name}",
                "subscription": subscription,
                "duration_choices": DURATION_CHOICES,
                "opts": self.model._meta,
            }
            return TemplateResponse(
                request,
                "admin/inventory/subscription/comp_form.html",
                context,
            )
        duration = request.POST.get("duration", "1m")
        _set_paid(
            subscription,
            duration=duration, custom_date=request.POST.get("custom_until"),
        )
        end = subscription.valid_until
        human = end.strftime("%d %b %Y") if end else "no end date"
        messages.success(
            request,
            f"{subscription.pharmacy.name} is PAID until {human}. "
            "Nothing auto-renews — it returns to FREE after that date.")
        return self._redirect()

    @admin.action(description="Set PAID for 1 month")
    def set_paid_1m(self, request, queryset):
        for subscription in queryset:
            _set_paid(subscription, duration="1m")
        self.message_user(request, "Set PAID for 1 month.", messages.SUCCESS)

    @admin.action(description="Set PAID for 6 months")
    def set_paid_6m(self, request, queryset):
        for subscription in queryset:
            _set_paid(subscription, duration="6m")
        self.message_user(request, "Set PAID for 6 months.", messages.SUCCESS)

    @admin.action(description="Set PAID for 1 year")
    def set_paid_1y(self, request, queryset):
        for subscription in queryset:
            _set_paid(subscription, duration="1y")
        self.message_user(request, "Set PAID for 1 year.", messages.SUCCESS)

    @admin.action(description="Set FREE (cuts paid features now)")
    def downgrade_free(self, request, queryset):
        count = 0
        for subscription in queryset:
            _set_free(subscription)
            count += 1
        self.message_user(request, f"Moved {count} pharmacy(ies) to FREE.", messages.WARNING)


@admin.register(SignupRequest, site=admin_site)
class SignupRequestAdmin(admin.ModelAdmin):
    """Owner console for landing-page leads and bKash/Nagad payments.

    Approve flips the pharmacy's subscription to the paid plan; reject marks
    the lead without touching access. Keys themselves are managed on the
    Pharmacy record and are never shown here in plaintext.
    """

    list_display = ("owner_name", "pharmacy_name", "plan", "status", "trx_id", "created_at")
    list_filter = ("status", "plan")
    search_fields = ("owner_name", "pharmacy_name", "whatsapp", "trx_id")
    readonly_fields = ("lookup_token", "created_at", "updated_at")
    actions = ("approve_pro", "reject")

    @admin.action(description="Approve & activate Pro for 1 month (payment received)")
    def approve_pro(self, request, queryset):
        activated = 0
        for signup in queryset.select_related("pharmacy"):
            if signup.pharmacy_id is None:
                continue
            subscription = _pharmacy_subscription(signup.pharmacy)
            _set_paid(subscription, duration="1m", source=Subscription.Source.WEB)
            signup.status = SignupRequest.Status.ACTIVE
            signup.save(update_fields=["status", "updated_at"])
            activated += 1
        self.message_user(
            request,
            f"Activated Pro for {activated} signup(s) — PAID for 1 month, no auto-renew.",
            messages.SUCCESS)

    @admin.action(description="Reject selected signups")
    def reject(self, request, queryset):
        updated = queryset.update(status=SignupRequest.Status.REJECTED)
        self.message_user(request, f"Rejected {updated} signup(s).", messages.WARNING)
