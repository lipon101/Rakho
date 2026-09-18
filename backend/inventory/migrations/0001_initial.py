# Generated manually for initial deployment. Run `python manage.py migrate`.
import uuid
from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="CatalogMedicine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("source_brand_id", models.PositiveIntegerField(blank=True, null=True, unique=True)),
                ("brand_name", models.CharField(db_index=True, max_length=255)), ("medicine_type", models.CharField(default="allopathic", max_length=24)),
                ("slug", models.SlugField(blank=True, max_length=280)), ("dosage_form", models.CharField(blank=True, max_length=255)),
                ("generic_name", models.CharField(blank=True, db_index=True, max_length=255)), ("strength", models.CharField(blank=True, max_length=255)),
                ("manufacturer_name", models.CharField(blank=True, db_index=True, max_length=255)),
                ("package_container", models.CharField(blank=True, max_length=255)), ("package_size_info", models.CharField(blank=True, max_length=255)),
            ],
            options={"ordering": ["brand_name", "strength", "id"]},
        ),
        migrations.CreateModel(
            name="Pharmacy",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=180)), ("currency", models.CharField(default="BDT", max_length=3)),
                ("timezone", models.CharField(default="Asia/Dhaka", max_length=64)), ("low_stock_default", models.PositiveIntegerField(default=10)),
            ],
        ),
        migrations.CreateModel(
            name="Medicine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("brand_name", models.CharField(max_length=255)), ("generic_name", models.CharField(blank=True, max_length=255)),
                ("strength", models.CharField(blank=True, max_length=255)), ("dosage_form", models.CharField(blank=True, max_length=255)),
                ("manufacturer_name", models.CharField(blank=True, max_length=255)), ("barcode", models.CharField(blank=True, max_length=80)),
                ("default_selling_price", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("low_stock_threshold", models.PositiveIntegerField(default=10)), ("is_active", models.BooleanField(default=True)),
                ("catalog_medicine", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pharmacy_medicines", to="inventory.catalogmedicine")),
                ("pharmacy", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="medicines", to="inventory.pharmacy")),
            ],
            options={"ordering": ["brand_name", "strength", "id"]},
        ),
        migrations.CreateModel(
            name="Sale",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("invoice_number", models.CharField(max_length=50)), ("sold_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("total_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)), ("payment_method", models.CharField(default="cash", max_length=32)),
                ("note", models.CharField(blank=True, max_length=500)),
                ("pharmacy", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sales", to="inventory.pharmacy")),
            ],
            options={"ordering": ["-sold_at", "-created_at"]},
        ),
        migrations.CreateModel(
            name="PharmacyApiKey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("label", models.CharField(default="Primary", max_length=100)), ("key_prefix", models.CharField(db_index=True, max_length=12)),
                ("key_hash", models.CharField(max_length=64, unique=True)), ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("pharmacy", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="api_keys", to="inventory.pharmacy")),
            ],
        ),
        migrations.CreateModel(
            name="Batch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("batch_number", models.CharField(max_length=100)), ("expiry_date", models.DateField(db_index=True)), ("received_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("unit_cost", models.DecimalField(decimal_places=2, max_digits=12)), ("selling_price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("quantity_received", models.PositiveIntegerField()), ("quantity_available", models.PositiveIntegerField()),
                ("supplier_name", models.CharField(blank=True, max_length=255)), ("notes", models.CharField(blank=True, max_length=500)),
                ("medicine", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="batches", to="inventory.medicine")),
                ("pharmacy", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="batches", to="inventory.pharmacy")),
            ],
            options={"ordering": ["expiry_date", "received_at", "id"]},
        ),
        migrations.CreateModel(
            name="SaleLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()), ("unit_price", models.DecimalField(decimal_places=2, max_digits=12)), ("line_total", models.DecimalField(decimal_places=2, max_digits=14)),
                ("medicine", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_lines", to="inventory.medicine")),
                ("sale", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="inventory.sale")),
            ],
        ),
        migrations.CreateModel(
            name="StockMovement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("kind", models.CharField(choices=[("purchase", "Purchase"), ("sale", "Sale"), ("wastage", "Wastage"), ("adjustment", "Adjustment")], max_length=16)),
                ("quantity_delta", models.IntegerField()), ("occurred_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("reference", models.CharField(blank=True, max_length=80)), ("note", models.CharField(blank=True, max_length=500)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="movements", to="inventory.batch")),
                ("medicine", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_movements", to="inventory.medicine")),
                ("pharmacy", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stock_movements", to="inventory.pharmacy")),
            ],
            options={"ordering": ["-occurred_at", "-created_at"]},
        ),
        migrations.CreateModel(
            name="SaleAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()), ("unit_cost", models.DecimalField(decimal_places=2, max_digits=12)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_allocations", to="inventory.batch")),
                ("sale_line", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="allocations", to="inventory.saleline")),
            ],
        ),
        migrations.AddConstraint(model_name="medicine", constraint=models.UniqueConstraint(condition=~models.Q(("barcode", "")), fields=("pharmacy", "barcode"), name="unique_pharmacy_barcode")),
        migrations.AddIndex(model_name="medicine", index=models.Index(fields=["pharmacy", "brand_name"], name="inventory_m_pharmac_97fe31_idx")),
        migrations.AddIndex(model_name="medicine", index=models.Index(fields=["pharmacy", "is_active"], name="inventory_m_pharmac_c50663_idx")),
        migrations.AddConstraint(model_name="sale", constraint=models.UniqueConstraint(fields=("pharmacy", "invoice_number"), name="unique_pharmacy_invoice")),
        migrations.AddConstraint(model_name="batch", constraint=models.UniqueConstraint(fields=("pharmacy", "medicine", "batch_number"), name="unique_pharmacy_medicine_batch")),
        migrations.AddConstraint(model_name="batch", constraint=models.CheckConstraint(condition=models.Q(("quantity_available__lte", models.F("quantity_received"))), name="available_not_over_received")),
        migrations.AddIndex(model_name="batch", index=models.Index(fields=["pharmacy", "medicine", "expiry_date"], name="inventory_b_pharmac_389ecc_idx")),
        migrations.AddIndex(model_name="batch", index=models.Index(fields=["pharmacy", "expiry_date", "quantity_available"], name="inventory_b_pharmac_461579_idx")),
        migrations.AddConstraint(model_name="saleallocation", constraint=models.UniqueConstraint(fields=("sale_line", "batch"), name="unique_line_batch_allocation")),
        migrations.AddIndex(model_name="catalogmedicine", index=models.Index(fields=["brand_name", "strength"], name="inventory_c_brand_n_6d68b4_idx")),
        migrations.AddIndex(model_name="catalogmedicine", index=models.Index(fields=["generic_name", "manufacturer_name"], name="inventory_c_generic_9dd376_idx")),
    ]
