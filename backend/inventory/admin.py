from django.contrib import admin, messages
from django.utils import timezone

from .models import (
    Batch, CatalogMedicine, Medicine, Pharmacy, PharmacyApiKey, PlayPurchaseEvent,
    Sale, SaleAllocation, SaleLine, SignupRequest, StockMovement, Subscription,
)

admin.site.register([
    Pharmacy, PharmacyApiKey, CatalogMedicine, Medicine, Batch, Sale, SaleLine,
    SaleAllocation, StockMovement, PlayPurchaseEvent,
])


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """Support tool: comp or extend a plan after a bank transfer or cash deal."""

    list_display = ("pharmacy", "plan", "source", "valid_until", "auto_renewing", "is_active")
    list_filter = ("plan", "source", "auto_renewing")
    search_fields = ("pharmacy__name", "product_id", "purchase_token")
    readonly_fields = ("created_at", "updated_at", "last_verified_at", "raw_response")

    @admin.display(boolean=True, description="Active")
    def is_active(self, obj):
        return obj.is_active


@admin.register(SignupRequest)
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
