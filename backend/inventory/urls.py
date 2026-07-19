from django.urls import path
from .views import (
    AlertView, ApiRootView, BatchDetailView, BatchListView,
    CatalogMedicineListView, DashboardView, HealthView,
    MedicineDetailView, MedicineListCreateView, MovementListView,
    PurchaseView, SaleListCreateView, WastageView,
)

urlpatterns = [
    # ── Public ──
    path("",                    ApiRootView.as_view(),         name="api-root"),
    path("health/",             HealthView.as_view(),          name="health"),
    path("catalog/medicines/",  CatalogMedicineListView.as_view(), name="catalog-medicines"),

    # ── Pharmacy Inventory ──
    path("inventory/medicines/",                       MedicineListCreateView.as_view(), name="medicines"),
    path("inventory/medicines/<uuid:medicine_id>/",    MedicineDetailView.as_view(),     name="medicine-detail"),
    path("inventory/batches/",                         BatchListView.as_view(),          name="batches"),
    path("inventory/batches/<uuid:batch_id>/",         BatchDetailView.as_view(),        name="batch-detail"),
    path("inventory/batches/<uuid:batch_id>/write-off/", WastageView.as_view(),          name="batch-write-off"),
    path("inventory/purchases/",                       PurchaseView.as_view(),           name="purchases"),
    path("inventory/sales/",                           SaleListCreateView.as_view(),     name="sales"),
    path("inventory/alerts/",                          AlertView.as_view(),              name="alerts"),
    path("inventory/dashboard/",                       DashboardView.as_view(),          name="dashboard"),
    path("inventory/movements/",                       MovementListView.as_view(),        name="movements"),
]
