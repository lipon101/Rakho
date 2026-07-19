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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=180)
    currency = models.CharField(max_length=3, default="BDT")
    timezone = models.CharField(max_length=64, default="Asia/Dhaka")
    low_stock_default = models.PositiveIntegerField(default=10)

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

    @staticmethod
    def generate_raw_key():
        return f"phm_{secrets.token_urlsafe(32)}"

    @staticmethod
    def hash_key(raw_key):
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @classmethod
    def create_key(cls, pharmacy, label="Primary"):
        raw_key = cls.generate_raw_key()
        record = cls.objects.create(
            pharmacy=pharmacy,
            label=label,
            key_prefix=raw_key[:11],
            key_hash=cls.hash_key(raw_key),
        )
        return record, raw_key

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
