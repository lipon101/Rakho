import json
import re
from datetime import datetime, time, timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone
import rest_framework
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import PharmacyApiKeyAuthentication
from .abuse import SignupDailyThrottle


# ── Input sanitizing ──
# Free text that reaches the database later renders in the admin console, so
# anything that could become markup has to be refused at the edge. Django's ORM
# parameterises queries, so SQLi is not possible; these helpers close the
# HTML-injection gap and stop over-long values reaching Postgres as a DataError.
_TAG_RE = re.compile(r"<[^>]*>")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
# Angle brackets are the only characters that can open a tag, so rejecting them
# outright is what makes markup impossible rather than merely unlikely.
_MARKUP_RE = re.compile(r"[<>]")


def clean_text(value, max_len):
    """Strip tags and control characters, then trim. For opaque identifiers
    (tokens, transaction ids) where mangling is harmless because the value is
    validated against a pattern immediately afterwards."""
    text = str(value or "")
    text = _TAG_RE.sub("", text)          # strip <script>, <b>, etc.
    text = _CTRL_RE.sub("", text)         # strip control chars/newlines
    return text.strip()[:max_len]


def clean_phone(value, max_len):
    """Keep digits, leading +, spaces, dashes — nothing that could carry markup."""
    text = str(value or "")
    text = re.sub(r"[^\d+\-\s()]", "", text)
    return text.strip()[:max_len]


def clean_name(value, max_len, field, allow_blank=False):
    """Validate human-readable text (a name or an address).

    Returns ``(value, error)``. Markup is *rejected* rather than silently
    stripped: quietly turning ``<script>alert(1)</script>`` into ``alert(1)``
    would save a value the sender never meant, and hide the attempt instead of
    reporting it. Length is enforced here too, so an over-long value cannot
    reach Postgres and surface as a 500.
    """
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value.strip()
    else:
        return "", f"{field} must be text."

    if not text:
        return ("", None) if allow_blank else ("", f"{field} is required.")
    if _MARKUP_RE.search(text):
        return "", f"{field} must not contain HTML or angle brackets."
    if _CTRL_RE.search(text):
        return "", f"{field} must not contain control characters."
    if len(text) > max_len:
        return "", f"{field} must be at most {max_len} characters."
    return text, None


def clean_phone_strict(value, max_len, field):
    """As ``clean_phone``, but refuses markup instead of discarding it, and
    enforces length so the value always fits the column."""
    if value is None or value == "":
        return "", None
    if not isinstance(value, str):
        return "", f"{field} must be text."
    text = value.strip()
    if _MARKUP_RE.search(text):
        return "", f"{field} must not contain HTML or angle brackets."
    if _CTRL_RE.search(text):
        return "", f"{field} must not contain control characters."
    text = re.sub(r"[^\d+\-\s()]", "", text).strip()
    if len(text) > max_len:
        return "", f"{field} must be at most {max_len} characters."
    return text, None


def clean_currency(value):
    """A 3-letter ISO code. ``Pharmacy.currency`` is varchar(3), so a longer
    value would otherwise reach Postgres and fail the request with a 500."""
    text = (str(value) if value is not None else "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", text):
        return "", "currency must be a 3-letter code such as BDT."
    return text, None
from .models import Batch, CatalogMedicine, Medicine, Sale, StockMovement
from .serializers import (
    BatchSerializer, CatalogMedicineSerializer, CreateSaleSerializer, MedicineSerializer,
    PlayVerifySerializer, PurchaseBatchSerializer, SaleSerializer,
    StockMovementSerializer, SubscriptionSerializer,
)
from .services import (
    PlayNotConfigured, PlayVerificationFailed, PlayVerifier, apply_play_purchase,
    create_fefo_sale, current_subscription, has_paid_plan, receive_purchase,
    write_off_batch,
)


# ──────────────────────────────────────────────
#  Base View
# ──────────────────────────────────────────────
class PharmacyScopedAPIView(APIView):
    authentication_classes = [PharmacyApiKeyAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    # Generous ceiling for a real pharmacy's daily traffic, but finite so a
    # leaked key or buggy client cannot hammer the free-tier service.
    throttle_scope = "pharmacy"

    @property
    def pharmacy(self):
        if not self.request.user or not getattr(self.request.user, "pk", None):
            raise NotAuthenticated("Provide an X-Pharmacy-Key header.")
        return self.request.user


# ──────────────────────────────────────────────
#  API Root  ─  /api/v1/
# ──────────────────────────────────────────────
class ApiRootView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({
            "service": "Pharmacy Inventory API",
            "version": "1.0.0",
            "status": "operational",
            "endpoints": {
                "health":       request.build_absolute_uri("/api/v1/health/"),
                "catalog":      request.build_absolute_uri("/api/v1/catalog/medicines/"),
                "medicines":    request.build_absolute_uri("/api/v1/inventory/medicines/"),
                "batches":      request.build_absolute_uri("/api/v1/inventory/batches/"),
                "purchases":    request.build_absolute_uri("/api/v1/inventory/purchases/"),
                "sales":        request.build_absolute_uri("/api/v1/inventory/sales/"),
                "alerts":       request.build_absolute_uri("/api/v1/inventory/alerts/"),
                "dashboard":    request.build_absolute_uri("/api/v1/inventory/dashboard/"),
                "movements":    request.build_absolute_uri("/api/v1/inventory/movements/"),
                "subscription": request.build_absolute_uri("/api/v1/billing/subscription/"),
            },
        })


# ──────────────────────────────────────────────
#  Health  ─  /api/v1/health/
# ──────────────────────────────────────────────
class HealthView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    # Render deployment health checks ping this path; it must never throttle.
    throttle_classes = []

    def get(self, request):
        from django.db import connections
        db_status = "connected"
        try:
            connections["default"].cursor()
        except Exception:
            db_status = "unreachable"

        return Response({
            "status": "healthy",
            "service": "pharmacy-api",
            "version": "1.0.0",
            "database": db_status,
            "timestamp": timezone.now(),
        })


class PingView(APIView):
    """Ultra-light keep-alive probe for free-tier hosts that sleep when idle.

    Returns 204 with no body and never touches the database, so an uptime
    monitor can keep the instance warm at ~5-minute intervals without cost.
    This is an intentional, legitimate use of an uptime monitor, not abuse:
    the endpoint is public, cheap, and documented for exactly this purpose.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get(self, request):
        return Response(status=status.HTTP_204_NO_CONTENT)

    def head(self, request):
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicSignupView(APIView):
    """Self-serve lead capture from the landing page.

    Creates a Pharmacy tenant, issues a free API key immediately (the key is
    returned once and never stored in plaintext), and records a SignupRequest
    so the owner can follow up. Rate-limited per IP to stop abuse of the free
    tier.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "signup"

    def post(self, request):
        from .models import Pharmacy, PharmacyApiKey, SignupRequest

        # Daily cap per client IP (3/day) — authoritative, DB-backed, and keyed on
        # the real client address behind Render's proxy.
        daily = SignupDailyThrottle()
        if daily.is_over_daily_limit(request):
            return Response(
                {"error": "Daily signup limit reached from this network. Try again tomorrow."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Honeypot: a hidden field humans never fill. Bots that fill it get a
        # success-looking reply but create nothing.
        if (request.data.get("website") or "").strip():
            return Response({"status": "ok"}, status=status.HTTP_201_CREATED)

        # Validate free text before it is used: a name like
        # "<script>alert(1)</script>" is refused outright rather than stripped,
        # so nothing the sender did not mean is stored, and markup can never
        # reach the admin console as HTML.
        owner, owner_error = clean_name(
            request.data.get("owner_name"), 120, "owner_name")
        if owner_error:
            return Response({"error": owner_error},
                            status=status.HTTP_400_BAD_REQUEST)
        pharmacy_name, name_error = clean_name(
            request.data.get("pharmacy_name"), 180, "pharmacy_name")
        if name_error:
            return Response({"error": name_error},
                            status=status.HTTP_400_BAD_REQUEST)
        whatsapp, phone_error = clean_phone_strict(
            request.data.get("whatsapp"), 32, "whatsapp")
        if phone_error:
            return Response({"error": phone_error},
                            status=status.HTTP_400_BAD_REQUEST)

        # Idempotency: the same WhatsApp number signing up again within a short
        # window gets their existing status link back instead of minting a
        # duplicate tenant + key.
        if whatsapp:
            recent = SignupRequest.objects.filter(
                whatsapp=whatsapp,
                created_at__gte=timezone.now() - timezone.timedelta(minutes=15),
            ).first()
            if recent is not None:
                return Response({
                    "already_registered": True,
                    "status_url": request.build_absolute_uri(
                        f"/api/v1/signup/status/{recent.lookup_token}/"
                    ),
                    "message": "You already signed up. Open your status link to see your key.",
                }, status=status.HTTP_200_OK)

        pharmacy = Pharmacy.objects.create(name=pharmacy_name)
        _, raw_key = PharmacyApiKey.create_key(pharmacy, "Self-serve")
        signup = SignupRequest.objects.create(
            pharmacy=pharmacy,
            owner_name=owner,
            pharmacy_name=pharmacy_name,
            whatsapp=whatsapp,
            plan="free",
            status=SignupRequest.Status.KEY_ISSUED,
            lookup_token=SignupRequest.generate_token(),
        )
        daily.record_success(request)
        return Response({
            "api_key": raw_key,
            "status_url": request.build_absolute_uri(f"/api/v1/signup/status/{signup.lookup_token}/"),
            "upgrade_url": request.build_absolute_uri(f"/pay/{signup.lookup_token}/"),
            "message": "Save this key now — it will not be shown again.",
        }, status=status.HTTP_201_CREATED)


class PublicPaymentView(APIView):
    """Record a bKash/Nagad TrxID against a signup so the owner can verify and
    flip the plan to Pro. The plan is only activated manually after the owner
    confirms the payment — this endpoint never auto-grants access.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "payment"

    # bKash/Nagad TrxIDs are short alphanumeric codes; anything else is rejected
    # before it reaches the database, and each TrxID may be claimed only once.
    TRX_RE = re.compile(r"^[A-Za-z0-9]{6,20}$")

    def post(self, request):
        from .models import Subscription, SignupRequest

        token = clean_text(request.data.get("token"), 64)
        trx_id = clean_text(request.data.get("trx_id"), 64)
        if not token or not trx_id:
            return Response(
                {"error": "token and trx_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not self.TRX_RE.match(trx_id):
            return Response(
                {"error": "That does not look like a valid transaction ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        signup = SignupRequest.objects.filter(lookup_token=token).first()
        if signup is None:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        # The client never chooses the plan — the app has exactly two plans
        # (FREE and Pro) and only the owner activates Pro after verifying the
        # TrxID in the admin console, so a tampered request unlocks nothing.
        plan = "pro"

        # Replay protection: a TrxID already claimed by a different signup cannot
        # be reused to activate a second account. Under the row lock this is
        # race-free — two concurrent claims cannot both pass the check.
        with transaction.atomic():
            clash = (
                SignupRequest.objects.select_for_update()
                .filter(trx_id=trx_id)
                .exclude(pk=signup.pk)
                .first()
            )
            if clash is not None:
                return Response(
                    {"error": "This transaction ID has already been used."},
                    status=status.HTTP_409_CONFLICT,
                )
            # Re-claim a previous different TrxID on the same signup, but never
            # blank the record of one already used by another signup.
            signup.trx_id = trx_id
            signup.plan = plan
            signup.status = SignupRequest.Status.PAID_REVIEW
            signup.save(update_fields=["trx_id", "plan", "status", "updated_at"])
        return Response({"status": "received", "message": "We will verify and activate shortly."})


class SignupStatusView(APIView):
    """Public, token-gated status page so a customer can re-open their key or
    see whether a paid plan is active — without any account or password.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "anon"

    def get(self, request, token):
        from .models import SignupRequest
        signup = SignupRequest.objects.filter(lookup_token=token).select_related("pharmacy").first()
        if signup is None:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            "pharmacy_name": signup.pharmacy_name,
            "owner_name": signup.owner_name,
            "plan": signup.plan,
            "status": signup.status,
            "created_at": signup.created_at,
        })


# ──────────────────────────────────────────────
#  Catalog search helper
# ──────────────────────────────────────────────
def search_catalog(query, limit=100):
    """Relevance-ranked, de-duplicated Bangladesh catalog search.

    Every whitespace-separated term must match somewhere (AND), across
    brand name, generic name, strength, and manufacturer. Per-term score:
    exact brand > brand prefix > brand substring > generic prefix >
    generic substring > strength substring > manufacturer substring.
    Identical products (same brand/strength/generic/form/manufacturer)
    that appear multiple times in the source data are collapsed.
    """
    terms = [t for t in re.split(r"\s+", query.lower()) if t]
    if not terms:
        return list(CatalogMedicine.objects.all().order_by("brand_name", "strength")[:limit])

    combined = Q()
    for term in terms:
        combined &= (
            Q(brand_name__icontains=term)
            | Q(generic_name__icontains=term)
            | Q(manufacturer_name__icontains=term)
            | Q(strength__icontains=term)
        )

    # Cap the candidate window for ranking; broad one-letter queries can
    # match thousands of rows and the top-100 payload is unaffected.
    candidates = list(CatalogMedicine.objects.filter(combined).order_by("id")[:2000])

    def score(record):
        brand = record.brand_name.lower().strip()
        generic = record.generic_name.lower().strip()
        maker = record.manufacturer_name.lower().strip()
        strength = record.strength.lower().strip()
        total = 0
        for term in terms:
            if brand == term:
                best = 100
            elif brand.startswith(term):
                best = 80
            elif term in brand:
                best = 60
            elif generic.startswith(term):
                best = 40
            elif term in generic:
                best = 30
            elif term in strength:
                best = 20
            elif term in maker:
                best = 10
            else:
                return 0
            total += best
        return total

    ranked = [(score(record), record) for record in candidates]
    ranked = [pair for pair in ranked if pair[0] > 0]
    ranked.sort(key=lambda pair: (-pair[0], pair[1].brand_name.lower(), pair[1].strength.lower()))

    seen, unique = set(), []
    for _, record in ranked:
        key = (
            record.brand_name.lower().strip(),
            record.strength.lower().strip(),
            record.generic_name.lower().strip(),
            record.dosage_form.lower().strip(),
            record.manufacturer_name.lower().strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


# ──────────────────────────────────────────────
#  Catalog  ─  /api/v1/catalog/medicines/
# ──────────────────────────────────────────────
def pro_required_response(request, feature):
    """Refusal for a paid feature, in a shape a client can act on.

    A bare 403 would leave the app showing a broken search; naming the code and
    the upgrade page lets it offer the upgrade instead.
    """
    return Response(
        {
            "error": {
                "code": "pro_required",
                "detail": f"{feature} is part of Rakho Pro.",
                "upgrade_url": request.build_absolute_uri("/#pricing"),
            }
        },
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )


class CatalogMedicineListView(PharmacyScopedAPIView):
    """Bangladesh medicine catalogue search — a Pro feature, enforced here.

    This was ``AllowAny``: no API key and no subscription, so the entire 14,000+
    product national dataset could be paged out of an open endpoint — or rebuilt
    into a competing app — by anyone, without ever paying. It is the main thing a
    subscription buys, so the decision belongs on the server rather than in the
    app, and free installs are refused explicitly instead of seeing a dead
    search box.
    """

    throttle_scope = "catalog"
    throttle_classes = [rest_framework.throttling.ScopedRateThrottle]

    def get(self, request):
        if not has_paid_plan(self.pharmacy):
            return pro_required_response(request, "Medicine catalogue search")
        query = request.query_params.get("q", "").strip()[:60]
        results = search_catalog(query)
        return Response({
            "count": len(results),
            "results": CatalogMedicineSerializer(results[:100], many=True).data,
        })


# ──────────────────────────────────────────────
#  Medicines  ─  /api/v1/inventory/medicines/
# ──────────────────────────────────────────────
class MedicineListCreateView(PharmacyScopedAPIView):
    def get(self, request):
        queryset = Medicine.objects.filter(
            pharmacy=self.pharmacy
        ).annotate(
            available_quantity=Coalesce(Sum("batches__quantity_available"), 0)
        )
        query = request.query_params.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(brand_name__icontains=query)
                | Q(generic_name__icontains=query)
                | Q(barcode__icontains=query)
            )
        results = queryset[:100]
        return Response({
            "count": len(results),
            "results": MedicineSerializer(results, many=True).data,
        })

    def post(self, request):
        serializer = MedicineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        catalog = serializer.validated_data.get("catalog_medicine")
        # Linking to a catalogue row copies its brand/generic/strength onto the
        # new medicine and returns them. Left open, that made the paid dataset
        # readable one sequential id at a time even with search closed, so this
        # path is gated too. Free accounts enter medicines manually, which still
        # works — they just cannot read the catalogue through this route.
        if catalog and not has_paid_plan(self.pharmacy):
            return pro_required_response(request, "Catalogue-linked medicines")
        values = serializer.validated_data.copy()
        if catalog:
            for field in [
                "brand_name", "generic_name", "strength",
                "dosage_form", "manufacturer_name",
            ]:
                if not values.get(field):
                    values[field] = getattr(catalog, field)
        medicine = Medicine.objects.create(pharmacy=self.pharmacy, **values)
        return Response(
            MedicineSerializer(medicine).data,
            status=status.HTTP_201_CREATED,
        )


# ──────────────────────────────────────────────
#  Medicine Detail  ─  /api/v1/inventory/medicines/{id}/
# ──────────────────────────────────────────────
class MedicineDetailView(PharmacyScopedAPIView):
    def get(self, request, medicine_id):
        medicine = Medicine.objects.filter(
            id=medicine_id, pharmacy=self.pharmacy
        ).annotate(
            available_quantity=Coalesce(Sum("batches__quantity_available"), 0)
        ).first()
        if not medicine:
            return Response(
                {"error": {"detail": "Medicine not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        batches = Batch.objects.filter(pharmacy=self.pharmacy, medicine=medicine)
        data = MedicineSerializer(medicine).data
        data["batches"] = BatchSerializer(batches, many=True).data
        return Response(data)

    def patch(self, request, medicine_id):
        medicine = Medicine.objects.filter(
            id=medicine_id, pharmacy=self.pharmacy
        ).first()
        if not medicine:
            return Response(
                {"error": {"detail": "Medicine not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = MedicineSerializer(medicine, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MedicineSerializer(medicine).data)


# ──────────────────────────────────────────────
#  Purchases  ─  /api/v1/inventory/purchases/
# ──────────────────────────────────────────────
class PurchaseView(PharmacyScopedAPIView):
    def post(self, request):
        serializer = PurchaseBatchSerializer(
            data=request.data.get("items"), many=True
        )
        serializer.is_valid(raise_exception=True)
        batches = receive_purchase(
            pharmacy=self.pharmacy,
            validated_items=serializer.validated_data,
        )
        return Response(
            {"message": "Purchase recorded", "batches": BatchSerializer(batches, many=True).data},
            status=status.HTTP_201_CREATED,
        )

    def get(self, request):
        """Return recent purchases (receiving events)."""
        movements = StockMovement.objects.filter(
            pharmacy=self.pharmacy,
            kind=StockMovement.Kind.PURCHASE,
        ).select_related("medicine", "batch").order_by("-occurred_at")[:50]
        return Response({
            "count": len(movements),
            "results": StockMovementSerializer(movements, many=True).data,
        })


# ──────────────────────────────────────────────
#  Batches  ─  /api/v1/inventory/batches/
# ──────────────────────────────────────────────
class BatchListView(PharmacyScopedAPIView):
    def get(self, request):
        queryset = Batch.objects.filter(
            pharmacy=self.pharmacy
        ).select_related("medicine")
        active_only = request.query_params.get("active")
        if active_only == "true":
            queryset = queryset.filter(quantity_available__gt=0)
        medicine_id = request.query_params.get("medicine")
        if medicine_id:
            queryset = queryset.filter(medicine_id=medicine_id)
        return Response({
            "count": queryset.count(),
            "results": BatchSerializer(queryset[:200], many=True).data,
        })


class BatchDetailView(PharmacyScopedAPIView):
    def get(self, request, batch_id):
        batch = Batch.objects.filter(
            id=batch_id, pharmacy=self.pharmacy
        ).select_related("medicine").first()
        if not batch:
            return Response(
                {"error": {"detail": "Batch not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(BatchSerializer(batch).data)


# ──────────────────────────────────────────────
#  Write-Off  ─  /api/v1/inventory/batches/{id}/write-off/
# ──────────────────────────────────────────────
class WastageView(PharmacyScopedAPIView):
    def post(self, request, batch_id):
        batch = write_off_batch(
            pharmacy=self.pharmacy,
            batch_id=batch_id,
            note=request.data.get("note", ""),
        )
        return Response({
            "message": "Batch written off",
            "batch": BatchSerializer(batch).data,
        })


# ──────────────────────────────────────────────
#  Sales  ─  /api/v1/inventory/sales/
# ──────────────────────────────────────────────
class SaleListCreateView(PharmacyScopedAPIView):
    def get(self, request):
        sales = Sale.objects.filter(
            pharmacy=self.pharmacy
        ).prefetch_related(
            "lines__allocations__batch", "lines__medicine"
        ).order_by("-sold_at")[:100]
        return Response({
            "count": len(sales),
            "results": SaleSerializer(sales, many=True).data,
        })

    def post(self, request):
        serializer = CreateSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale = create_fefo_sale(
            pharmacy=self.pharmacy,
            payload=serializer.validated_data,
        )
        sale = Sale.objects.prefetch_related(
            "lines__allocations__batch", "lines__medicine"
        ).get(id=sale.id)
        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)


# ──────────────────────────────────────────────
#  Alerts  ─  /api/v1/inventory/alerts/
# ──────────────────────────────────────────────
class AlertView(PharmacyScopedAPIView):
    def get(self, request):
        try:
            days = min(max(int(request.query_params.get("days", 90)), 1), 365)
            today = timezone.localdate()
            cutoff = today + timedelta(days=days)
            batches = Batch.objects.filter(
                pharmacy=self.pharmacy, quantity_available__gt=0,
            ).select_related("medicine")
            expired = batches.filter(expiry_date__lt=today)
            expiring = batches.filter(expiry_date__gte=today, expiry_date__lte=cutoff)
            low_stock_ids = set()
            for m in Medicine.objects.filter(pharmacy=self.pharmacy, is_active=True).prefetch_related("batches"):
                stock = sum(b.quantity_available for b in m.batches.all())
                if stock <= m.low_stock_threshold:
                    low_stock_ids.add(m.pk)
            low_stock = Medicine.objects.filter(pk__in=low_stock_ids) if low_stock_ids else Medicine.objects.none()
            return Response({
                "overview": {
                    "expired_count": expired.count(),
                    "expiring_count": expiring.count(),
                    "low_stock_count": len(low_stock_ids),
                    "horizon_days": days,
                },
                "expired": BatchSerializer(expired, many=True).data,
                "expiring_soon": BatchSerializer(expiring, many=True).data,
                "low_stock": MedicineSerializer(low_stock, many=True).data,
            })
        except Exception as e:
            return Response(
                {"error": {"detail": f"Could not compute alerts: {e}"}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ──────────────────────────────────────────────
#  Dashboard  ─  /api/v1/inventory/dashboard/
# ──────────────────────────────────────────────
class DashboardView(PharmacyScopedAPIView):
    def get(self, request):
        try:
            today = timezone.localdate()
            day_start = timezone.make_aware(datetime.combine(today, time.min))
            week_start = day_start - timedelta(days=7)

            # All batches for this pharmacy
            all_batches = Batch.objects.filter(pharmacy=self.pharmacy)
            
            # Active (in-stock) batches
            active_batches = all_batches.filter(quantity_available__gt=0)

            # Compute stock value in pure Python (no SQL F-expression multiplication)
            total_units = 0
            total_value = 0
            for b in active_batches:
                total_units += int(b.quantity_available)
                total_value += float(b.quantity_available) * float(b.unit_cost)

            # Sales today
            sales_today = Sale.objects.filter(pharmacy=self.pharmacy, sold_at__gte=day_start)
            today_amount = sum(float(s.total_amount) for s in sales_today)

            # Sales this week
            sales_week = Sale.objects.filter(pharmacy=self.pharmacy, sold_at__gte=week_start)
            week_amount = sum(float(s.total_amount) for s in sales_week)

            # Counts
            expired = all_batches.filter(expiry_date__lt=today).count()
            expiring = all_batches.filter(
                expiry_date__gte=today, expiry_date__lte=today + timedelta(days=90),
            ).count()

            # Low stock — computed in Python from batch sums
            low_stock = 0
            for m in Medicine.objects.filter(pharmacy=self.pharmacy, is_active=True):
                stock = sum(b.quantity_available for b in m.batches.all())
                if stock <= m.low_stock_threshold:
                    low_stock += 1

            unique_meds = Medicine.objects.filter(pharmacy=self.pharmacy, is_active=True).count()

            return Response({
                "pharmacy": {
                    "name": self.pharmacy.name,
                    "currency": self.pharmacy.currency,
                },
                "inventory": {
                    "total_units": total_units,
                    "total_value_bdt": total_value,
                    "unique_medicines": unique_meds,
                },
                "sales": {
                    "today_amount_bdt": today_amount,
                    "today_count": sales_today.count(),
                    "week_amount_bdt": week_amount,
                    "week_count": sales_week.count(),
                },
                "alerts": {
                    "expired_batches": expired,
                    "expiring_soon": expiring,
                    "low_stock_items": low_stock,
                },
                "generated_at": timezone.now(),
            })
        except Exception as e:
            return Response(
                {"error": {"detail": f"Could not compute dashboard: {e}"}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ──────────────────────────────────────────────
#  Stock Movements  ─  /api/v1/inventory/movements/
# ──────────────────────────────────────────────
class MovementListView(PharmacyScopedAPIView):
    def get(self, request):
        movements = StockMovement.objects.filter(
            pharmacy=self.pharmacy
        ).select_related("medicine", "batch").order_by("-created_at")[:200]
        return Response({
            "count": len(movements),
            "results": StockMovementSerializer(movements, many=True).data,
        })


# ──────────────────────────────────────────────
#  One-Time Setup Views (public, no auth)
# ──────────────────────────────────────────────
class CreatePharmacyView(APIView):
    """One-time tenant provisioning. Guarded by the SETUP_TOKEN env variable when set."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        expected = getattr(settings, "SETUP_TOKEN", "")
        if expected and request.headers.get("X-Setup-Token") != expected:
            return Response(
                {"error": {"detail": "Missing or invalid X-Setup-Token header."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        from .models import Pharmacy, PharmacyApiKey
        name, name_error = clean_name(request.data.get("name"), 180, "name")
        if name_error:
            return Response({"error": name_error},
                            status=status.HTTP_400_BAD_REQUEST)
        if Pharmacy.objects.filter(name__iexact=name).exists():
            return Response({"error": f"Pharmacy '{name}' already exists"}, status=status.HTTP_409_CONFLICT)
        pharmacy = Pharmacy.objects.create(name=name)
        _, raw_key = PharmacyApiKey.create_key(pharmacy, "Primary")
        return Response({
            "pharmacy_id": str(pharmacy.id),
            "name": pharmacy.name,
            "api_key": raw_key,
            "warning": "Save this key now — it will not be shown again.",
        }, status=status.HTTP_201_CREATED)


class CatalogImportView(APIView):
    """Catalog import trigger. Guarded by the SETUP_TOKEN env variable when set."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        expected = getattr(settings, "SETUP_TOKEN", "")
        if expected and request.headers.get("X-Setup-Token") != expected:
            return Response(
                {"error": {"detail": "Missing or invalid X-Setup-Token header."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        from django.core.management import call_command
        try:
            call_command("import_bangladesh_catalog", "--download")
            return Response({"status": "success", "message": "Catalog imported successfully."})
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ──────────────────────────────────────────────
#  Pharmacy Settings  ─  /api/v1/inventory/pharmacy/
# ──────────────────────────────────────────────
class PharmacySettingsView(PharmacyScopedAPIView):
    def get(self, request):
        return Response({
            "id": str(self.pharmacy.id),
            "name": self.pharmacy.name,
            "currency": self.pharmacy.currency,
            "address": self.pharmacy.address,
            "phone": self.pharmacy.phone,
        })

    def patch(self, request):
        # Every field is validated before anything is written: an unvalidated
        # setattr() here accepted markup straight into the database, and an
        # over-long currency would fail the write inside Postgres.
        incoming = request.data
        updates = {}

        validators = {
            "name": lambda v: clean_name(v, 180, "name"),
            "currency": clean_currency,
            "address": lambda v: clean_name(v, 255, "address", allow_blank=True),
            "phone": lambda v: clean_phone_strict(v, 32, "phone"),
        }
        for field, validate in validators.items():
            if field not in incoming:
                continue
            raw = incoming.get(field)
            if raw is None:
                # JSON null means "no value supplied", not "clear this field".
                # Rejecting it would break any client that serialises every
                # field of its patch DTO (the Android settings screen does).
                continue
            value, error = validate(raw)
            if error:
                return Response({"error": error},
                                status=status.HTTP_400_BAD_REQUEST)
            updates[field] = value

        for field, value in updates.items():
            setattr(self.pharmacy, field, value)
        self.pharmacy.save()
        return Response({
            "id": str(self.pharmacy.id),
            "name": self.pharmacy.name,
            "currency": self.pharmacy.currency,
            "address": self.pharmacy.address,
            "phone": self.pharmacy.phone,
        })
# ──────────────────────────────────────────────
#  Billing  ─  /api/v1/billing/
# ──────────────────────────────────────────────
def get_play_verifier():
    """Builds the Play verifier from server configuration.

    GOOGLE_PLAY_SERVICE_ACCOUNT_JSON may hold the service-account JSON itself or
    a path to the file. Nothing is inferred: without it the API answers 503 and
    the app keeps the pharmacy on the free plan rather than guessing.
    """
    raw = getattr(settings, "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "") or ""
    credentials_info = None
    if raw:
        stripped = raw.strip()
        if stripped.startswith("{"):
            try:
                credentials_info = json.loads(stripped)
            except json.JSONDecodeError:
                credentials_info = None
        else:
            try:
                credentials_info = json.loads(Path(stripped).read_text())
            except (OSError, json.JSONDecodeError):
                credentials_info = None
    return PlayVerifier(
        credentials_info=credentials_info,
        package_name=getattr(settings, "GOOGLE_PLAY_PACKAGE_NAME", "") or "",
    )


class SubscriptionView(PharmacyScopedAPIView):
    """Current entitlement for the authenticated pharmacy."""

    def get(self, request):
        subscription = current_subscription(self.pharmacy)
        return Response(SubscriptionSerializer(subscription).data)


class PlayPurchaseVerifyView(PharmacyScopedAPIView):
    """Verifies a Google Play purchase and stores the entitlement.

    The app posts the purchase token straight after Play reports a successful
    purchase. Only a Play-verified, currently paid subscription becomes Pro,
    and replaying the same token is idempotent.
    """

    def post(self, request):
        serializer = PlayVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        package_name = data["package_name"] or getattr(settings, "GOOGLE_PLAY_PACKAGE_NAME", "")
        try:
            subscription = apply_play_purchase(
                pharmacy=self.pharmacy,
                purchase_token=data["purchase_token"],
                product_id=data["product_id"],
                package_name=package_name,
                verifier=get_play_verifier(),
            )
        except PlayNotConfigured as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except PlayVerificationFailed as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(SubscriptionSerializer(subscription).data)


# ──────────────────────────────────────────────
#  SPA App View  ─  /app/
# ──────────────────────────────────────────────
class AppView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        index_path = Path(__file__).resolve().parent.parent / "static" / "app" / "index.html"
        if index_path.exists():
            return HttpResponse(index_path.read_text(), content_type="text/html")
        return HttpResponse("<h1>App not found</h1>", status=404)
