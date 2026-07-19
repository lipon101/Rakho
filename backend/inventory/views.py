from datetime import datetime, time, timedelta

from django.db.models import F, Sum
from django.db.models.functions import Coalesce
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


class PharmacyScopedAPIView(APIView):
    authentication_classes = [PharmacyApiKeyAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @property
    def pharmacy(self):
        if not self.request.user or not getattr(self.request.user, "pk", None):
            raise NotAuthenticated("Provide an X-Pharmacy-Key header.")
        return self.request.user


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"status": "ok", "service": "pharmacy-api", "time": timezone.now()})


class CatalogMedicineListView(generics.ListAPIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    serializer_class = CatalogMedicineSerializer

    def get_queryset(self):
        query = self.request.query_params.get("q", "").strip()
        records = CatalogMedicine.objects.all()
        if query:
            from django.db.models import Q
            records = records.filter(Q(brand_name__icontains=query) | Q(generic_name__icontains=query) | Q(manufacturer_name__icontains=query))
        return records[:100]


class MedicineListCreateView(PharmacyScopedAPIView):
    def get(self, request):
        queryset = Medicine.objects.filter(pharmacy=self.pharmacy).annotate(available_quantity=Coalesce(Sum("batches__quantity_available"), 0))
        query = request.query_params.get("q", "").strip()
        if query:
            from django.db.models import Q
            queryset = queryset.filter(Q(brand_name__icontains=query) | Q(generic_name__icontains=query) | Q(barcode__icontains=query))
        return Response(MedicineSerializer(queryset[:100], many=True).data)

    def post(self, request):
        serializer = MedicineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        catalog = serializer.validated_data.get("catalog_medicine")
        values = serializer.validated_data.copy()
        if catalog:
            for field in ["brand_name", "generic_name", "strength", "dosage_form", "manufacturer_name"]:
                if not values.get(field):
                    values[field] = getattr(catalog, field)
        medicine = Medicine.objects.create(pharmacy=self.pharmacy, **values)
        return Response(MedicineSerializer(medicine).data, status=status.HTTP_201_CREATED)


class MedicineDetailView(PharmacyScopedAPIView):
    def patch(self, request, medicine_id):
        medicine = Medicine.objects.filter(id=medicine_id, pharmacy=self.pharmacy).first()
        if not medicine:
            return Response({"error": {"detail": "Medicine not found."}}, status=404)
        serializer = MedicineSerializer(medicine, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MedicineSerializer(medicine).data)


class PurchaseView(PharmacyScopedAPIView):
    def post(self, request):
        serializer = PurchaseBatchSerializer(data=request.data.get("items"), many=True)
        serializer.is_valid(raise_exception=True)
        batches = receive_purchase(pharmacy=self.pharmacy, validated_items=serializer.validated_data)
        return Response(BatchSerializer(batches, many=True).data, status=status.HTTP_201_CREATED)


class BatchListView(PharmacyScopedAPIView):
    def get(self, request):
        queryset = Batch.objects.filter(pharmacy=self.pharmacy).select_related("medicine")
        active_only = request.query_params.get("active")
        if active_only == "true":
            queryset = queryset.filter(quantity_available__gt=0)
        medicine_id = request.query_params.get("medicine")
        if medicine_id:
            queryset = queryset.filter(medicine_id=medicine_id)
        return Response(BatchSerializer(queryset[:200], many=True).data)


class SaleListCreateView(PharmacyScopedAPIView):
    def get(self, request):
        sales = Sale.objects.filter(pharmacy=self.pharmacy).prefetch_related("lines__allocations__batch", "lines__medicine")[:100]
        return Response(SaleSerializer(sales, many=True).data)

    def post(self, request):
        serializer = CreateSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale = create_fefo_sale(pharmacy=self.pharmacy, payload=serializer.validated_data)
        sale = Sale.objects.prefetch_related("lines__allocations__batch", "lines__medicine").get(id=sale.id)
        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)


class WastageView(PharmacyScopedAPIView):
    def post(self, request, batch_id):
        batch = write_off_batch(pharmacy=self.pharmacy, batch_id=batch_id, note=request.data.get("note", ""))
        return Response(BatchSerializer(batch).data)


class AlertView(PharmacyScopedAPIView):
    def get(self, request):
        days = min(max(int(request.query_params.get("days", 90)), 1), 365)
        today = timezone.localdate()
        cutoff = today + timedelta(days=days)
        batches = Batch.objects.filter(pharmacy=self.pharmacy, quantity_available__gt=0).select_related("medicine")
        expired = batches.filter(expiry_date__lt=today)
        expiring = batches.filter(expiry_date__gte=today, expiry_date__lte=cutoff)
        low_stock = Medicine.objects.filter(pharmacy=self.pharmacy, is_active=True).annotate(available_quantity=Coalesce(Sum("batches__quantity_available"), 0)).filter(available_quantity__lte=F("low_stock_threshold"))
        return Response({
            "expired": BatchSerializer(expired, many=True).data,
            "expiring": BatchSerializer(expiring, many=True).data,
            "low_stock": MedicineSerializer(low_stock, many=True).data,
        })


class DashboardView(PharmacyScopedAPIView):
    def get(self, request):
        today = timezone.localdate()
        day_start = timezone.make_aware(datetime.combine(today, time.min))
        batches = Batch.objects.filter(pharmacy=self.pharmacy, quantity_available__gt=0)
        sales_today = Sale.objects.filter(pharmacy=self.pharmacy, sold_at__gte=day_start)
        return Response({
            "currency": self.pharmacy.currency,
            "stock_units": batches.aggregate(total=Coalesce(Sum("quantity_available"), 0))["total"],
            "stock_value_bdt": batches.aggregate(total=Coalesce(Sum(F("quantity_available") * F("unit_cost")), 0))["total"],
            "sales_today_bdt": sales_today.aggregate(total=Coalesce(Sum("total_amount"), 0))["total"],
            "sales_count_today": sales_today.count(),
            "expired_batches": batches.filter(expiry_date__lt=today).count(),
            "expiring_soon_batches": batches.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=90)).count(),
        })


class MovementListView(PharmacyScopedAPIView):
    def get(self, request):
        movements = StockMovement.objects.filter(pharmacy=self.pharmacy).select_related("medicine", "batch")[:200]
        return Response(StockMovementSerializer(movements, many=True).data)
