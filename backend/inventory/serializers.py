from decimal import Decimal
from rest_framework import serializers
from .models import Batch, CatalogMedicine, Medicine, Sale, SaleAllocation, SaleLine, StockMovement, Subscription


class CatalogMedicineSerializer(serializers.ModelSerializer):
    class Meta:
        model = CatalogMedicine
        fields = ["id", "source_brand_id", "brand_name", "medicine_type", "dosage_form", "generic_name", "strength", "manufacturer_name", "package_container", "package_size_info"]


class MedicineSerializer(serializers.ModelSerializer):
    available_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = Medicine
        fields = ["id", "catalog_medicine", "brand_name", "generic_name", "strength", "dosage_form", "manufacturer_name", "barcode", "default_selling_price", "low_stock_threshold", "is_active", "available_quantity", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at", "available_quantity"]

    def validate_catalog_medicine(self, catalog):
        return catalog


class BatchSerializer(serializers.ModelSerializer):
    medicine_name = serializers.CharField(source="medicine.brand_name", read_only=True)
    medicine_strength = serializers.CharField(source="medicine.strength", read_only=True)

    class Meta:
        model = Batch
        fields = ["id", "medicine", "medicine_name", "medicine_strength", "batch_number", "expiry_date", "received_at", "unit_cost", "selling_price", "quantity_received", "quantity_available", "supplier_name", "notes", "created_at", "updated_at"]
        read_only_fields = ["id", "quantity_available", "created_at", "updated_at"]


class PurchaseBatchSerializer(serializers.Serializer):
    medicine = serializers.UUIDField()
    batch_number = serializers.CharField(max_length=100)
    expiry_date = serializers.DateField()
    quantity = serializers.IntegerField(min_value=1)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    selling_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    supplier_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class SaleRequestLineSerializer(serializers.Serializer):
    medicine = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False)


class CreateSaleSerializer(serializers.Serializer):
    invoice_number = serializers.CharField(max_length=50)
    payment_method = serializers.ChoiceField(choices=["cash", "card", "mobile_banking", "credit"], default="cash")
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    lines = SaleRequestLineSerializer(many=True, allow_empty=False)


class SaleAllocationSerializer(serializers.ModelSerializer):
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True)
    expiry_date = serializers.DateField(source="batch.expiry_date", read_only=True)

    class Meta:
        model = SaleAllocation
        fields = ["batch", "batch_number", "expiry_date", "quantity", "unit_cost"]


class SaleLineSerializer(serializers.ModelSerializer):
    medicine_name = serializers.CharField(source="medicine.brand_name", read_only=True)
    allocations = SaleAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = SaleLine
        fields = ["medicine", "medicine_name", "quantity", "unit_price", "line_total", "allocations"]


class SaleSerializer(serializers.ModelSerializer):
    lines = SaleLineSerializer(many=True, read_only=True)

    class Meta:
        model = Sale
        fields = ["id", "invoice_number", "sold_at", "total_amount", "payment_method", "note", "lines", "created_at"]


class StockMovementSerializer(serializers.ModelSerializer):
    medicine_name = serializers.CharField(source="medicine.brand_name", read_only=True)
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True)

    class Meta:
        model = StockMovement
        fields = ["id", "batch", "batch_number", "medicine", "medicine_name", "kind", "quantity_delta", "occurred_at", "reference", "note"]


class SubscriptionSerializer(serializers.ModelSerializer):
    """Entitlement contract shared by the Android app, the web app and iOS."""

    is_active = serializers.BooleanField(read_only=True)
    effective_plan = serializers.CharField(read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "plan", "effective_plan", "source", "product_id", "valid_until",
            "auto_renewing", "is_active", "last_verified_at",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # A lapsed plan is reported as free, while keeping the lapse date so the
        # app can show "Pro ended on <date>" instead of a stale badge.
        data["plan"] = instance.effective_plan
        data["valid_until"] = instance.valid_until.isoformat() if instance.valid_until else None
        return data


class PlayVerifySerializer(serializers.Serializer):
    purchase_token = serializers.CharField(max_length=512)
    product_id = serializers.CharField(max_length=100)
    package_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
