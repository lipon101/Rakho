from django.http import JsonResponse
from django.urls import path, re_path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView

from .exceptions import error_payload
from .invoice_views import (
    BillingOverviewView,
    BillingQuotePdfView,
    InvoiceDetailView,
    InvoiceIssueView,
    InvoiceListView,
    InvoicePaymentView,
    InvoicePdfView,
)
from .observability import MetricsView, VersionView, sentry_check_view
from .org_views import (
    AuditLogListView,
    BranchDetailView,
    BranchListCreateView,
    InvitationAcceptView,
    InvitationDetailView,
    InvitationInfoView,
    InvitationListCreateView,
    InvitationRegisterView,
    MemberDetailView,
    MemberListView,
    OrganisationView,
    QuoteView,
    SeatAddonView,
    SeatStatusView,
)
from .profile_views import ProfilePrivacyView
from .report_views import (
    BrandingView,
    DeadStockView,
    ExpiryReportView,
    ExportQueueView,
    ExportView,
    SalesReportView,
    ScorecardView,
    StockImportView,
    UsageMetricsView,
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
    # Which commit is this process running? Public on purpose: the sha is already
    # in the public repo, and a deploy check that needs a secret is one that gets
    # skipped when it is finally needed. Used by scripts/render_deploy.py.
    path("version/", VersionView.as_view(), name="version"),
    # ── Operations (Phase 6) ──
    # Both are token-guarded and both 404 when no token is configured, so an
    # unset METRICS_TOKEN removes the endpoints instead of exposing them.
    path("metrics/", MetricsView.as_view(), name="metrics"),
    path("ops/sentry/", sentry_check_view, name="ops-sentry"),
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
    # Public context + account creation for the join page (/console/join).
    # Read-only info never consumes the token; registration is bound to the
    # invited address, so only the recipient can claim the seat. Both carry the
    # login throttle: token-bearing, unauthenticated, and worth brute-forcing.
    path("org/invitations/info/", InvitationInfoView.as_view(), name="org-invitation-info"),
    path("org/invitations/register/", InvitationRegisterView.as_view(), name="org-invitation-register"),
    path("org/audit/", AuditLogListView.as_view(), name="org-audit"),
    # ── Reporting & analytics (Phase 4) ──
    # Every one of these is scoped through the caller's own branch access, so a
    # manager pinned to a single branch gets that branch's numbers and not the
    # chain's. The scoping is applied inside the view from the resolved context
    # rather than accepted from the request --- there is no branch id to edit.
    path("org/reports/sales/", SalesReportView.as_view(), name="org-report-sales"),
    path("org/reports/expiry/", ExpiryReportView.as_view(), name="org-report-expiry"),
    path("org/reports/dead-stock/", DeadStockView.as_view(), name="org-report-dead-stock"),
    path("org/reports/scorecard/", ScorecardView.as_view(), name="org-report-scorecard"),
    # CSV downloads. Large ones are refused with a pointer to the async job,
    # because a synchronous request that builds a 300k-row file holds a worker.
    path("org/exports/<str:kind>.csv", ExportView.as_view(), name="org-export"),
    path("org/exports/queue/", ExportQueueView.as_view(), name="org-export-queue"),
    # ── Bulk onboarding ──
    path("org/import/stock/", StockImportView.as_view(), name="org-stock-import"),
    # ── Branding & usage (Phase 6) ──
    path("org/branding/", BrandingView.as_view(), name="org-branding"),
    path("org/usage/", UsageMetricsView.as_view(), name="org-usage"),
    # ── Invoicing / billing (Phase 3) ──
    # Admin-only and JWT-only: a device key must not be able to read or settle a
    # financial document. The path prefix stays under /org/ so the whole
    # enterprise surface is one thing to reason about.
    path("org/billing/overview/", BillingOverviewView.as_view(), name="org-billing-overview"),
    path("org/invoices/", InvoiceListView.as_view(), name="org-invoices"),
    path("org/invoices/<uuid:invoice_id>/", InvoiceDetailView.as_view(), name="org-invoice-detail"),
    path("org/invoices/<uuid:invoice_id>/issue/", InvoiceIssueView.as_view(), name="org-invoice-issue"),
    path("org/invoices/<uuid:invoice_id>/payment/", InvoicePaymentView.as_view(), name="org-invoice-payment"),
    # ── Invoice / quotation PDFs (Phase 3) ──
    # Separate paths from the JSON views above: these return a file the browser
    # renders, not a body the console parses. ``?lang=bn|en`` selects the
    # language; Bengali is the default.
    path("org/invoices/<uuid:invoice_id>/pdf/", InvoicePdfView.as_view(), name="org-invoice-pdf"),
    path("org/billing/quote.pdf", BillingQuotePdfView.as_view(), name="org-billing-quote-pdf"),
    # ── Privacy: optional profile & consent (progressive profiling) ──
    # Device-key scoped like every other app endpoint: the profile belongs to
    # the shop whose key is presented, and the licence number inside it is
    # decrypted only for a caller holding that key. Absence of rows is the
    # default answer, so GET works for an account that never filled anything in.
    path("profile/", ProfilePrivacyView.as_view(), name="profile-privacy"),
    # ── Catch-all ──
    # Must stay last. An unmatched path under /api/v1/ otherwise fell through
    # to Django's HTML 404 page, which a JSON client cannot parse — the one
    # error shape the envelope could not reach, because it is raised during
    # URL resolution rather than inside a view.
    re_path(r"^.*$", api_not_found, name="api-not-found"),
]
