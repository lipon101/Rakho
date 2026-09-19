from django.contrib import admin, messages
from django.core.management import CommandError, call_command
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone

from .admin_dashboard import dashboard_stats, model_counts
from .models import (
    Batch, CatalogMedicine, Medicine, Pharmacy, PharmacyApiKey, PlayPurchaseEvent,
    Sale, SaleAllocation, SaleLine, SignupDailyCount, SignupRequest, StockMovement,
    Subscription,
)


class RakhoAdminSite(admin.AdminSite):
    """Owner console with a live dashboard as the landing page."""

    site_header = "Rakho Console"
    site_title = "Rakho"
    index_title = "Overview"

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["rk"] = dashboard_stats()
        # Flatten the app/model tree into one list and attach a live record
        # count per model so the dashboard's "Manage data" cards are useful.
        # (app_list is built inside super().index(), so fetch it here.)
        model_counts_map = model_counts()
        rk_models = [
            {**model, "count": model_counts_map.get(model["object_name"], 0)}
            for app in self.get_app_list(request)
            for model in app.get("models", [])
        ]
        extra_context["rk_models"] = rk_models
        return super().index(request, extra_context)


admin_site = RakhoAdminSite(name="rakho_admin")

admin_site.register([Pharmacy, Medicine, Batch, Sale])


class LedgerAdmin(admin.ModelAdmin):
    """A record the application writes, shown to the owner read-only.

    Every model on this admin is produced by a service — a sale, a stock
    movement, a Play verification, an abuse tally — and never typed by a person.
    An editable row here invites a hand-edit no service would ever produce: a
    sale line whose total contradicts its own batch allocations, a stock
    movement with no batch behind it, a purchase event that never reached
    Google. The console shows these and stops there, which is what "manage the
    sales" means: read them, not rewrite them.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SaleLine, site=admin_site)
class SaleLineAdmin(LedgerAdmin):
    list_display = ("sale", "medicine", "quantity", "unit_price", "line_total")
    search_fields = ("sale__invoice_number", "medicine__brand_name")
    list_select_related = ("sale", "medicine")


@admin.register(SaleAllocation, site=admin_site)
class SaleAllocationAdmin(LedgerAdmin):
    """Which batch a sale line drew from, and at what cost."""

    list_display = ("sale_line", "batch", "quantity", "unit_cost")
    list_select_related = ("sale_line", "batch")


@admin.register(StockMovement, site=admin_site)
class StockMovementAdmin(LedgerAdmin):
    list_display = ("occurred_at", "pharmacy", "medicine", "kind", "quantity_delta", "reference")
    list_filter = ("kind",)
    search_fields = ("reference", "medicine__brand_name", "batch__batch_number")
    list_select_related = ("pharmacy", "medicine", "batch")


@admin.register(PlayPurchaseEvent, site=admin_site)
class PlayPurchaseEventAdmin(LedgerAdmin):
    """The audit trail behind every "but I paid on Google Play" ticket."""

    list_display = ("created_at", "pharmacy", "product_id", "succeeded", "detail")
    list_filter = ("succeeded",)
    search_fields = ("pharmacy__name", "product_id", "purchase_token")
    list_select_related = ("pharmacy",)


@admin.register(SignupDailyCount, site=admin_site)
class SignupDailyCountAdmin(LedgerAdmin):
    list_display = ("ip", "day", "count")
    search_fields = ("ip",)


@admin.register(CatalogMedicine, site=admin_site)
class CatalogMedicineAdmin(admin.ModelAdmin):
    """Read-only window onto the national catalogue the app searches.

    These rows are *data*, not inventory: they arrive from the public Assorted
    Medicine Dataset of Bangladesh (a Kaggle export) via
    ``manage.py import_bangladesh_catalog`` and every install searches the same
    server-side copy. Hand-typing or editing one here would silently fork the
    owner's copy from the dataset, so the console shows the records and offers a
    one-click re-import instead of an add/change form.

    Browsing a pharmacy's own sellable stock lives on Medicine/Batch, which are
    editable as before.
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


@admin.register(PharmacyApiKey, site=admin_site)
class PharmacyApiKeyAdmin(admin.ModelAdmin):
    """Key management with a safe re-issue path for customers who lost their key.

    The raw key is shown exactly once in the admin right after generation —
    copy it and send it to the verified customer; it is never stored or shown
    again. Revoking a key instantly cuts that device's access.
    """

    list_display = ("pharmacy", "label", "key_prefix", "is_active", "created_at")
    list_filter = ("revoked_at",)
    search_fields = ("pharmacy__name", "label", "key_prefix")
    readonly_fields = ("key_prefix", "key_hash", "created_at", "updated_at")
    actions = ("issue_new_key", "revoke_keys")

    @admin.display(boolean=True, description="Active")
    def is_active(self, obj):
        return obj.revoked_at is None

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


@admin.register(Subscription, site=admin_site)
class SubscriptionAdmin(admin.ModelAdmin):
    """Support tool: comp or extend a plan after a bank transfer or cash deal."""

    list_display = ("pharmacy", "plan", "source", "valid_until", "auto_renewing", "is_active")
    list_filter = ("plan", "source", "auto_renewing")
    search_fields = ("pharmacy__name", "product_id", "purchase_token")
    readonly_fields = ("created_at", "updated_at", "last_verified_at", "raw_response")

    @admin.display(boolean=True, description="Active")
    def is_active(self, obj):
        return obj.is_active


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

    @admin.action(description="Approve & activate Pro (payment received)")
    def approve_pro(self, request, queryset):
        activated = 0
        for signup in queryset.select_related("pharmacy"):
            if signup.pharmacy_id is None:
                continue
            subscription = Subscription.for_pharmacy(signup.pharmacy)
            subscription.plan = Subscription.Plan.PRO
            subscription.source = Subscription.Source.WEB
            subscription.valid_until = timezone.localdate() + timezone.timedelta(days=30)
            subscription.last_verified_at = timezone.now()
            subscription.save()
            signup.status = SignupRequest.Status.ACTIVE
            signup.save(update_fields=["status", "updated_at"])
            activated += 1
        self.message_user(request, f"Activated Pro for {activated} signup(s).", messages.SUCCESS)

    @admin.action(description="Reject selected signups")
    def reject(self, request, queryset):
        updated = queryset.update(status=SignupRequest.Status.REJECTED)
        self.message_user(request, f"Rejected {updated} signup(s).", messages.WARNING)
