from collections import defaultdict
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import (
    Batch, Medicine, PlayPurchaseEvent, Sale, SaleAllocation, SaleLine,
    StockMovement, Subscription,
)


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


# ──────────────────────────────────────────────
#  Subscriptions / Google Play verification
# ──────────────────────────────────────────────
class PlayNotConfigured(Exception):
    """Play verification is unavailable because credentials are not set."""


class PlayVerificationFailed(Exception):
    """Google rejected the purchase token, or the subscription has lapsed."""


#: Google Play product id -> Rakho plan. Both paid products unlock Pro today;
#: Business is reserved for multi-branch chains sold through the web channel.
PLAY_PRODUCT_PLANS = {
    "rakho_pro_monthly": "pro",
    "rakho_pro_yearly": "pro",
    "rakho_business_monthly": "business",
    "rakho_business_yearly": "business",
}


class PlayVerifier:
    """Verifies subscription purchases with the Google Play Developer API.

    Only this verifier's answer is trusted: the app can never mark itself as
    paid. When no service-account credentials are configured the verifier
    reports that fact instead of pretending a purchase is valid.
    """

    SCOPE = "https://www.googleapis.com/auth/androidpublisher"

    def __init__(self, credentials_info=None, package_name=None, service=None):
        self.credentials_info = credentials_info
        self.package_name = package_name
        self._service = service

    @property
    def configured(self):
        return bool(self._service) or bool(self.credentials_info)

    def _build_service(self):
        if self._service is not None:
            return self._service
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_info(
            self.credentials_info, scopes=[self.SCOPE]
        )
        self._service = build("androidpublisher", "v3", credentials=credentials, cache_discovery=False)
        return self._service

    def verify(self, purchase_token, product_id, package_name=None):
        """Returns the Play subscription payload for a purchase token."""
        if not self.configured:
            raise PlayNotConfigured("Google Play verification is not configured on this server.")
        package = package_name or self.package_name
        if not package:
            raise PlayNotConfigured("No Google Play package name is configured on this server.")
        try:
            service = self._build_service()
            response = (
                service.purchases()
                .subscriptions()
                .get(packageName=package, subscriptionId=product_id, token=purchase_token)
                .execute()
            )
        except PlayNotConfigured:
            raise
        except PlayVerificationFailed:
            raise
        except Exception as exc:  # network / API / auth failures
            raise PlayVerificationFailed(str(exc)) from exc
        return response


def _play_expiry_date(payload):
    raw = payload.get("expiryTimeMillis")
    if not raw:
        return None
    return datetime.fromtimestamp(int(raw) / 1000, tz=dt_timezone.utc).date()


def _play_payment_state_is_paid(payload):
    """Play paymentState: 0 pending, 1 received, 2 free trial, 3 deferred."""
    state = payload.get("paymentState")
    if state is None:
        # Older API versions omit it; an expiry in the future is the signal.
        return True
    return int(state) in (1, 2)


def apply_play_purchase(*, pharmacy, purchase_token, product_id, package_name, verifier):
    """Verify a Play purchase and store the resulting entitlement.

    Idempotent: replaying the same purchase token only re-verifies and updates
    the single subscription row, so a retried request can never double-charge
    or create a second entitlement.
    """
    if product_id not in PLAY_PRODUCT_PLANS:
        raise PlayVerificationFailed(f"Unknown product '{product_id}'.")

    payload = verifier.verify(purchase_token, product_id, package_name)

    expiry = _play_expiry_date(payload)
    today = timezone.localdate()
    if not _play_payment_state_is_paid(payload) or (expiry is not None and expiry < today):
        PlayPurchaseEvent.objects.create(
            pharmacy=pharmacy, purchase_token=purchase_token, product_id=product_id,
            package_name=package_name or "", succeeded=False, detail="not paid or already expired",
        )
        raise PlayVerificationFailed("This subscription is not active in Google Play.")

    with transaction.atomic():
        subscription = Subscription.for_pharmacy(pharmacy)
        subscription.plan = PLAY_PRODUCT_PLANS[product_id]
        subscription.source = Subscription.Source.PLAY
        subscription.product_id = product_id
        subscription.package_name = package_name or ""
        subscription.purchase_token = purchase_token
        subscription.valid_until = expiry
        subscription.auto_renewing = bool(payload.get("autoRenewing", False))
        subscription.last_verified_at = timezone.now()
        subscription.raw_response = payload
        subscription.save()
        PlayPurchaseEvent.objects.create(
            pharmacy=pharmacy, purchase_token=purchase_token, product_id=product_id,
            package_name=package_name or "", succeeded=True,
            detail=f"expires {expiry}" if expiry else "no expiry reported",
        )
    return subscription


def has_paid_plan(pharmacy):
    """True when the pharmacy holds a paid entitlement that has not lapsed.

    Paid features are gated on this, on the server, so access does not depend on
    what a client chooses to show. A lapsed plan reports False, because
    ``effective_plan`` already downgrades an expired subscription to free.
    """
    return current_subscription(pharmacy).effective_plan != Subscription.Plan.FREE


def current_subscription(pharmacy):
    """Entitlement for a pharmacy, including the free default.

    A lapsed paid plan is reported as free with the lapse date retained, so the
    app can honestly show "Pro ended on ..." rather than a stale Pro badge.
    """
    subscription = Subscription.objects.filter(pharmacy=pharmacy).first()
    if subscription is None:
        return Subscription(pharmacy=pharmacy, plan=Subscription.Plan.FREE, source=Subscription.Source.NONE)
    return subscription
