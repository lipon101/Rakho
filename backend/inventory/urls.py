from django.http import JsonResponse
from django.urls import path, re_path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView

from .exceptions import error_payload
from .org_views import (
    AuditLogListView,
    BranchDetailView,
    BranchListCreateView,
    InvitationAcceptView,
    InvitationDetailView,
    InvitationListCreateView,
    MemberDetailView,
    MemberListView,
    OrganisationView,
    QuoteView,
    SeatAddonView,
    SeatStatusView,
)
from .views import (
    AlertView,
    ApiRootView,
    AppView,
    BatchDetailView,
    BatchListView,
    CatalogImportView,
    CatalogMedicineListView,
    CreatePharmacyView,
    DashboardView,
    HealthView,
    MedicineDetailView,
    MedicineListCreateView,
    MovementListView,
    PharmacySettingsView,
    PingView,
    PlayPurchaseVerifyView,
    PublicPaymentView,
    PublicSignupView,
    PurchaseView,
    ReadinessView,
    SaleListCreateView,
    SignupStatusView,
    SubscriptionView,
    WastageView,
)


def api_not_found(request, *args, **kwargs):
    """A JSON 404 for an unknown path under /api/v1/."""
    return JsonResponse(
        {"error": error_payload("not_found", "No such API endpoint."), "status": 404},
        status=404,
    )


urlpatterns = [
    # ── Public ──
    path("", ApiRootView.as_view(), name="api-root"),
    path("health/", HealthView.as_view(), name="health"),
    path("ready/", ReadinessView.as_view(), name="ready"),
    path("ping/", PingView.as_view(), name="ping"),
    # ── Console authentication ──
    # The organisation console signs in with a JWT, while the Android app uses a
    # branch API key. Two credentials because they answer two different
    # questions: a key identifies a *device*, a token identifies a *person*, and
    # only a person can be held to a role or appear in the audit trail.
    path("auth/token/", TokenObtainPairView.as_view(), name="token-obtain"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/token/verify/", TokenVerifyView.as_view(), name="token-verify"),
    path("catalog/medicines/", CatalogMedicineListView.as_view(), name="catalog-medicines"),
    # ── Self-serve signup / payment (public, rate-limited) ──
    path("signup/", PublicSignupView.as_view(), name="public-signup"),
    path("signup/pay/", PublicPaymentView.as_view(), name="public-pay"),
    path("signup/status/<str:token>/", SignupStatusView.as_view(), name="signup-status"),
    # ── Setup (public, one-time) ──
    path("setup/pharmacy/", CreatePharmacyView.as_view(), name="setup-pharmacy"),
    path("setup/catalog/", CatalogImportView.as_view(), name="setup-catalog"),
    # ── App (SPA) ──
    path("app/", AppView.as_view(), name="app"),
    # ── Pharmacy Inventory ──
    path("inventory/medicines/", MedicineListCreateView.as_view(), name="medicines"),
    path("inventory/medicines/<uuid:medicine_id>/", MedicineDetailView.as_view(), name="medicine-detail"),
    path("inventory/batches/", BatchListView.as_view(), name="batches"),
    path("inventory/batches/<uuid:batch_id>/", BatchDetailView.as_view(), name="batch-detail"),
    path("inventory/batches/<uuid:batch_id>/write-off/", WastageView.as_view(), name="batch-write-off"),
    path("inventory/purchases/", PurchaseView.as_view(), name="purchases"),
    path("inventory/sales/", SaleListCreateView.as_view(), name="sales"),
    path("inventory/alerts/", AlertView.as_view(), name="alerts"),
    path("inventory/dashboard/", DashboardView.as_view(), name="dashboard"),
    path("inventory/movements/", MovementListView.as_view(), name="movements"),
    path("inventory/pharmacy/", PharmacySettingsView.as_view(), name="pharmacy"),
    # ── Billing / subscriptions ──
    path("billing/subscription/", SubscriptionView.as_view(), name="subscription"),
    path("billing/play/verify/", PlayPurchaseVerifyView.as_view(), name="play-verify"),
    # ── Organisation (enterprise / B2B) ──
    # Everything below is scoped to the caller's own organisation. No endpoint
    # accepts an organisation id from the request, so there is no field a caller
    # can edit to reach another tenant.
    path("org/", OrganisationView.as_view(), name="org"),
    path("org/branches/", BranchListCreateView.as_view(), name="org-branches"),
    path("org/branches/<uuid:branch_id>/", BranchDetailView.as_view(), name="org-branch-detail"),
    path("org/members/", MemberListView.as_view(), name="org-members"),
    path("org/members/<uuid:member_id>/", MemberDetailView.as_view(), name="org-member-detail"),
    path("org/seats/", SeatStatusView.as_view(), name="org-seats"),
    path("org/quote/", QuoteView.as_view(), name="org-quote"),
    path("org/seat-addon/", SeatAddonView.as_view(), name="org-seat-addon"),
    path("org/invitations/", InvitationListCreateView.as_view(), name="org-invitations"),
    path("org/invitations/<uuid:invitation_id>/", InvitationDetailView.as_view(), name="org-invitation-detail"),
    # Public by necessity: the person clicking an invitation link has no session
    # yet. The single-use token is the credential.
    path("org/invitations/accept/", InvitationAcceptView.as_view(), name="org-invitation-accept"),
    path("org/audit/", AuditLogListView.as_view(), name="org-audit"),
    # ── Catch-all ──
    # Must stay last. An unmatched path under /api/v1/ otherwise fell through
    # to Django's HTML 404 page, which a JSON client cannot parse — the one
    # error shape the envelope could not reach, because it is raised during
    # URL resolution rather than inside a view.
    re_path(r"^.*$", api_not_found, name="api-not-found"),
]
