from django.contrib import admin, messages
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

admin_site.register([
    Pharmacy, CatalogMedicine, Medicine, Batch, Sale, SaleLine,
    SaleAllocation, StockMovement, PlayPurchaseEvent, SignupDailyCount,
])


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
