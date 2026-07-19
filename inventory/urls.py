from django.urls import path
from .views import AlertView, BatchListView, CatalogMedicineListView, DashboardView, HealthView, MedicineDetailView, MedicineListCreateView, MovementListView, PurchaseView, SaleListCreateView, WastageView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("catalog/medicines/", CatalogMedicineListView.as_view(), name="catalog-medicines"),
    path("medicines/", MedicineListCreateView.as_view(), name="medicines"),
    path("medicines/<uuid:medicine_id>/", MedicineDetailView.as_view(), name="medicine-detail"),
    path("purchases/receive/", PurchaseView.as_view(), name="purchase-receive"),
    path("batches/", BatchListView.as_view(), name="batches"),
    path("batches/<uuid:batch_id>/wastage/", WastageView.as_view(), name="batch-wastage"),
    path("sales/", SaleListCreateView.as_view(), name="sales"),
    path("alerts/", AlertView.as_view(), name="alerts"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("stock-movements/", MovementListView.as_view(), name="stock-movements"),
]
