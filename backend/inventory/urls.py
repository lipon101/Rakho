from django.urls import path, re_path
from .views import (
    AlertView, ApiRootView, AppView, BatchDetailView, BatchListView,
    BootstrapAdminView, CatalogImportView, CatalogMedicineListView, CreatePharmacyView,
    DashboardView, HealthView, MedicineDetailView, MedicineListCreateView,
    PharmacySettingsView, PingView, PublicPaymentView, PublicSignupView,
    SignupStatusView,
    MovementListView, PlayPurchaseVerifyView, PurchaseView, SaleListCreateView,
    SubscriptionView, WastageView,
)

urlpatterns = [
    # ── Public ──
    path("",                    ApiRootView.as_view(),         name="api-root"),
    path("health/",             HealthView.as_view(),          name="health"),
    path("ping/",               PingView.as_view(),            name="ping"),
    path("catalog/medicines/",  CatalogMedicineListView.as_view(), name="catalog-medicines"),

    # ── Self-serve signup / payment (public, rate-limited) ──
    path("signup/",                       PublicSignupView.as_view(),  name="public-signup"),
    path("signup/pay/",                   PublicPaymentView.as_view(), name="public-pay"),
    path("signup/status/<str:token>/",    SignupStatusView.as_view(),  name="signup-status"),

    # ── Setup (public, one-time) ──
    path("setup/pharmacy/",     CreatePharmacyView.as_view(),  name="setup-pharmacy"),
    path("setup/catalog/",      CatalogImportView.as_view(),   name="setup-catalog"),
    path("setup/bootstrap-admin/", BootstrapAdminView.as_view(), name="bootstrap-admin"),

    # ── App (SPA) ──
    path("app/",                AppView.as_view(),             name="app"),

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
    path("inventory/pharmacy/",                     PharmacySettingsView.as_view(),  name="pharmacy"),

    # ── Billing / subscriptions ──
    path("billing/subscription/",                    SubscriptionView.as_view(),      name="subscription"),
    path("billing/play/verify/",                     PlayPurchaseVerifyView.as_view(), name="play-verify"),
]
