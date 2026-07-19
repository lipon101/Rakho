from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inventory.models import Batch, Medicine, Pharmacy, PharmacyApiKey, Sale, StockMovement


class PharmacyApiTestCase(TestCase):
    def setUp(self):
        self.pharmacy = Pharmacy.objects.create(name="Bhai Bhai Pharmacy")
        _, key = PharmacyApiKey.create_key(self.pharmacy)
        self.client = APIClient(HTTP_X_PHARMACY_KEY=key)
        self.medicine = Medicine.objects.create(
            pharmacy=self.pharmacy,
            brand_name="Napa Extra",
            generic_name="Paracetamol",
            strength="500 mg",
            dosage_form="Tablet",
            default_selling_price=Decimal("2.00"),
            low_stock_threshold=5,
        )

    def receive(self, batch_number, expiry_date, quantity, selling_price="2.00"):
        return self.client.post("/api/v1/purchases/receive/", {"items": [{
            "medicine": str(self.medicine.id), "batch_number": batch_number,
            "expiry_date": expiry_date.isoformat(), "quantity": quantity,
            "unit_cost": "1.50", "selling_price": selling_price,
        }]}, format="json")

    def test_health_is_public_and_protected_data_requires_key(self):
        self.assertEqual(self.client.get("/api/v1/health/").status_code, 200)
        self.assertEqual(APIClient().get("/api/v1/medicines/").status_code, 403)

    def test_sale_allocates_batches_in_fefo_order(self):
        today = timezone.localdate()
        self.assertEqual(self.receive("EARLY", today + timedelta(days=20), 3).status_code, 201)
        self.assertEqual(self.receive("LATE", today + timedelta(days=50), 8).status_code, 201)
        response = self.client.post("/api/v1/sales/", {
            "invoice_number": "INV-001", "payment_method": "cash",
            "lines": [{"medicine": str(self.medicine.id), "quantity": 5}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["total_amount"], "10.00")
        allocations = response.data["lines"][0]["allocations"]
        self.assertEqual([(item["batch_number"], item["quantity"]) for item in allocations], [("EARLY", 3), ("LATE", 2)])
        self.assertEqual(Batch.objects.get(batch_number="EARLY").quantity_available, 0)
        self.assertEqual(Batch.objects.get(batch_number="LATE").quantity_available, 6)
        self.assertEqual(StockMovement.objects.filter(kind="sale").count(), 2)

    def test_expired_stock_is_never_allocated(self):
        today = timezone.localdate()
        self.receive("EXPIRED", today - timedelta(days=1), 10)
        response = self.client.post("/api/v1/sales/", {
            "invoice_number": "INV-EXPIRED", "lines": [{"medicine": str(self.medicine.id), "quantity": 1}],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(Batch.objects.get(batch_number="EXPIRED").quantity_available, 10)

    def test_sale_is_atomic_when_any_line_cannot_be_fulfilled(self):
        today = timezone.localdate()
        self.receive("ONLY", today + timedelta(days=30), 2)
        response = self.client.post("/api/v1/sales/", {
            "invoice_number": "INV-ATOMIC", "lines": [{"medicine": str(self.medicine.id), "quantity": 3}],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(Batch.objects.get(batch_number="ONLY").quantity_available, 2)

    def test_wastage_creates_inventory_audit_movement(self):
        today = timezone.localdate()
        self.receive("WRITE-OFF", today + timedelta(days=30), 4)
        batch = Batch.objects.get(batch_number="WRITE-OFF")
        response = self.client.post(f"/api/v1/batches/{batch.id}/wastage/", {"note": "Damaged"}, format="json")
        self.assertEqual(response.status_code, 200)
        batch.refresh_from_db()
        self.assertEqual(batch.quantity_available, 0)
        movement = StockMovement.objects.get(kind="wastage")
        self.assertEqual(movement.quantity_delta, -4)
        self.assertEqual(movement.note, "Damaged")
