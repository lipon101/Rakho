import re
from datetime import datetime, time, timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import PharmacyApiKeyAuthentication
from .models import Batch, CatalogMedicine, Medicine, Sale, StockMovement
from .serializers import (
    BatchSerializer, CatalogMedicineSerializer, CreateSaleSerializer, MedicineSerializer,
    PurchaseBatchSerializer, SaleSerializer, StockMovementSerializer,
)
from .services import create_fefo_sale, receive_purchase, write_off_batch


# ──────────────────────────────────────────────
#  Base View
# ──────────────────────────────────────────────
class PharmacyScopedAPIView(APIView):
    authentication_classes = [PharmacyApiKeyAuthentication]
    permission_classes = [permissions.IsAuthenticated]

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
            },
        })


# ──────────────────────────────────────────────
#  Health  ─  /api/v1/health/
# ──────────────────────────────────────────────
class HealthView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

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
class CatalogMedicineListView(generics.ListAPIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    serializer_class = CatalogMedicineSerializer

    def list(self, request, *args, **kwargs):
        query = request.query_params.get("q", "").strip()
        results = search_catalog(query)
        return Response({
            "count": len(results),
            "results": self.get_serializer(results[:100], many=True).data,
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
        name = request.data.get("name", "").strip()
        if not name:
            return Response({"error": "Missing 'name' field"}, status=status.HTTP_400_BAD_REQUEST)
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
        for field in ["name", "currency", "address", "phone"]:
            if field in request.data:
                setattr(self.pharmacy, field, request.data[field])
        self.pharmacy.save()
        return Response({
            "id": str(self.pharmacy.id),
            "name": self.pharmacy.name,
            "currency": self.pharmacy.currency,
            "address": self.pharmacy.address,
            "phone": self.pharmacy.phone,
        })
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
