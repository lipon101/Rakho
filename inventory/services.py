from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Batch, Medicine, Sale, SaleAllocation, SaleLine, StockMovement


def receive_purchase(*, pharmacy, validated_items):
    created = []
    with transaction.atomic():
        for item in validated_items:
            medicine = Medicine.objects.filter(id=item["medicine"], pharmacy=pharmacy, is_active=True).first()
            if not medicine:
                raise ValidationError({"medicine": f"Medicine {item['medicine']} does not belong to this pharmacy or is inactive."})
            batch, batch_created = Batch.objects.select_for_update().get_or_create(
                pharmacy=pharmacy,
                medicine=medicine,
                batch_number=item["batch_number"],
                defaults={
                    "expiry_date": item["expiry_date"], "unit_cost": item["unit_cost"], "selling_price": item["selling_price"],
                    "quantity_received": item["quantity"], "quantity_available": item["quantity"],
                    "supplier_name": item["supplier_name"], "notes": item["notes"],
                },
            )
            if not batch_created:
                if batch.expiry_date != item["expiry_date"]:
                    raise ValidationError({"batch_number": f"Batch {batch.batch_number} already exists with a different expiry date."})
                Batch.objects.filter(id=batch.id).update(
                    quantity_received=F("quantity_received") + item["quantity"],
                    quantity_available=F("quantity_available") + item["quantity"],
                    unit_cost=item["unit_cost"], selling_price=item["selling_price"],
                )
                batch.refresh_from_db()
            StockMovement.objects.create(
                pharmacy=pharmacy, batch=batch, medicine=medicine, kind=StockMovement.Kind.PURCHASE,
                quantity_delta=item["quantity"], reference=batch.batch_number, note=item["notes"],
            )
            created.append(batch)
    return created


def create_fefo_sale(*, pharmacy, payload):
    with transaction.atomic():
        if Sale.objects.filter(pharmacy=pharmacy, invoice_number=payload["invoice_number"]).exists():
            raise ValidationError({"invoice_number": "This invoice number already exists for this pharmacy."})
        requested = defaultdict(lambda: {"quantity": 0, "unit_price": None})
        for line in payload["lines"]:
            record = requested[str(line["medicine"])]
            record["quantity"] += line["quantity"]
            if line.get("unit_price") is not None:
                if record["unit_price"] is not None and record["unit_price"] != line["unit_price"]:
                    raise ValidationError({"lines": "A medicine cannot have different unit prices in the same sale."})
                record["unit_price"] = line["unit_price"]

        medicine_ids = list(requested.keys())
        medicines = {str(m.id): m for m in Medicine.objects.filter(pharmacy=pharmacy, is_active=True, id__in=medicine_ids)}
        missing = [medicine_id for medicine_id in medicine_ids if medicine_id not in medicines]
        if missing:
            raise ValidationError({"lines": f"Unknown or inactive medicine: {', '.join(missing)}"})

        sale = Sale.objects.create(pharmacy=pharmacy, invoice_number=payload["invoice_number"], payment_method=payload["payment_method"], note=payload["note"])
        total = Decimal("0.00")
        today = timezone.localdate()
        for medicine_id, request in requested.items():
            medicine = medicines[medicine_id]
            quantity_needed = request["quantity"]
            price = request["unit_price"] if request["unit_price"] is not None else medicine.default_selling_price
            batches = list(Batch.objects.select_for_update().filter(
                pharmacy=pharmacy, medicine=medicine, quantity_available__gt=0, expiry_date__gte=today,
            ).order_by("expiry_date", "received_at", "id"))
            available = sum(batch.quantity_available for batch in batches)
            if available < quantity_needed:
                raise ValidationError({"lines": f"Insufficient non-expired stock for {medicine.brand_name}. Available: {available}, required: {quantity_needed}."})
            line_total = price * quantity_needed
            sale_line = SaleLine.objects.create(sale=sale, medicine=medicine, quantity=quantity_needed, unit_price=price, line_total=line_total)
            remaining = quantity_needed
            for batch in batches:
                if not remaining:
                    break
                allocation = min(batch.quantity_available, remaining)
                batch.quantity_available -= allocation
                batch.save(update_fields=["quantity_available", "updated_at"])
                SaleAllocation.objects.create(sale_line=sale_line, batch=batch, quantity=allocation, unit_cost=batch.unit_cost)
                StockMovement.objects.create(
                    pharmacy=pharmacy, batch=batch, medicine=medicine, kind=StockMovement.Kind.SALE,
                    quantity_delta=-allocation, reference=sale.invoice_number,
                )
                remaining -= allocation
            total += line_total
        sale.total_amount = total
        sale.save(update_fields=["total_amount", "updated_at"])
        return sale


def write_off_batch(*, pharmacy, batch_id, note=""):
    with transaction.atomic():
        batch = Batch.objects.select_for_update().filter(id=batch_id, pharmacy=pharmacy).select_related("medicine").first()
        if not batch:
            raise ValidationError({"batch": "Batch not found."})
        quantity = batch.quantity_available
        if quantity == 0:
            raise ValidationError({"batch": "This batch has no available stock."})
        batch.quantity_available = 0
        batch.save(update_fields=["quantity_available", "updated_at"])
        StockMovement.objects.create(pharmacy=pharmacy, batch=batch, medicine=batch.medicine, kind=StockMovement.Kind.WASTAGE, quantity_delta=-quantity, reference=batch.batch_number, note=note)
        return batch
