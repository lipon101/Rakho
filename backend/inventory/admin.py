from django.contrib import admin

from .models import (
    Batch, CatalogMedicine, Medicine, Pharmacy, PharmacyApiKey, PlayPurchaseEvent,
    Sale, SaleAllocation, SaleLine, StockMovement, Subscription,
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
