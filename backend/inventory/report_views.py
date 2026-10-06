"""Reporting, export, branding and bulk-onboarding endpoints.

These are the endpoints an enterprise buyer asks about in the first demo ---
"can I see all my branches side by side", "can I get this into Excel", "can I
upload my existing stock list" --- so they are treated as product surface, not
as admin extras. Every one of them is scoped through ``scoped_pharmacies()``,
which means a manager restricted to one branch gets that branch's report and
nothing else, without any endpoint having to remember the rule.
"""

from __future__ import annotations

import csv
import io

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from . import reports
from . import tasks as async_tasks
from .models import AuditLog, Medicine, OrgMembership
from .org_context import HasFreshJWT
from .org_views import OrgScopedView

# ── Shared helpers ──────────────────────────────────────────────────────


def _window_from_request(request, organization):
    """Resolve the reporting window from the query string.

    Defaults to 30 days because that is the period a shop manager thinks in,
    and accepts either ``days=`` or an explicit ``start=&end=``. An invalid
    range is answered as a validation error rather than silently corrected:
    quietly changing a date filter is how a report gets signed off with numbers
    nobody chose.
    """
    start = request.query_params.get("start")
    end = request.query_params.get("end")
    if start and end:
        try:
            start_date = timezone.datetime.fromisoformat(start).date()
            end_date = timezone.datetime.fromisoformat(end).date()
        except ValueError:
            return None, Response(
                {"error": {"code": "invalid_date", "detail": "start and end must be ISO dates (YYYY-MM-DD).", "fields": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if end_date < start_date:
            return None, Response(
                {"error": {"code": "invalid_range", "detail": "end must not be before start.", "fields": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return reports.DateWindow.from_dates(start_date, end_date, organization=organization), None

    raw_days = request.query_params.get("days", "30")
    try:
        days = max(1, min(int(raw_days), 366))
    except (TypeError, ValueError):
        return None, Response(
            {"error": {"code": "invalid_window", "detail": "days must be a whole number between 1 and 366.", "fields": {}}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return reports.DateWindow.last_days(days, organization=organization), None


def _csv_response(text: str, filename: str, *, organization) -> HttpResponse:
    """A CSV download with the two headers that make it open correctly.

    The UTF-8 BOM is not optional here: without it, Excel on a Windows machine
    renders a Bengali medicine name as mojibake, and this is a Bangladesh-first
    product where every product name is Bengali. The disposition filename is
    quoted because an organisation name may contain a space.
    """
    response = HttpResponse(text.encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Organisation"] = organization.slug
    return response


# ── Reporting ───────────────────────────────────────────────────────────


class SalesReportView(OrgScopedView):
    """Revenue by branch and by day over a window."""

    def get(self, request):
        self.require_role(OrgMembership.Role.MANAGER)
        window, error = _window_from_request(request, self.organization)
        if error:
            return error
        scoped = self.scoped_pharmacy_ids()
        return Response(reports.sales_summary(self.organization, window, scoped_ids=scoped))


class ExpiryReportView(OrgScopedView):
    """What expires when, and what it is worth at cost."""

    def get(self, request):
        days = request.query_params.get("horizon", "90")
        try:
            horizon = max(1, min(int(days), 730))
        except (TypeError, ValueError):
            horizon = 90
        return Response(reports.expiry_summary(self.organization, days=horizon, scoped_ids=self.scoped_pharmacy_ids()))


class DeadStockView(OrgScopedView):
    """Stock that has not moved in a while --- the money quietly sitting still."""

    def get(self, request):
        self.require_role(OrgMembership.Role.MANAGER)
        idle = request.query_params.get("days", "90")
        try:
            idle_days = max(7, min(int(idle), 365))
        except (TypeError, ValueError):
            idle_days = 90
        return Response(reports.dead_stock(self.organization, days=idle_days, scoped_ids=self.scoped_pharmacy_ids()))


class ScorecardView(OrgScopedView):
    """One row per branch: sales, catalogue size and value at risk."""

    def get(self, request):
        self.require_role(OrgMembership.Role.MANAGER)
        window, error = _window_from_request(request, self.organization)
        if error:
            return error
        return Response(
            {
                "window": {"start": window.start.isoformat(), "end": (window.end - timezone.timedelta(days=1)).isoformat()},
                "timezone": window.timezone_name,
                "branches": reports.branch_scorecard(self.organization, window, scoped_ids=self.scoped_pharmacy_ids()),
            }
        )


# ── Exports ─────────────────────────────────────────────────────────────


class ExportView(OrgScopedView):
    """CSV downloads for sales and expiry.

    Synchronous on purpose, and capped. The alternative --- an async job and a
    download link --- is the right shape for a year of a large chain's data, but
    it adds a queue round-trip and a polling UI to the common case of "give me
    this month". When the cap is reached the response says so, and the async
    path is the documented next step rather than a silent truncation.
    """

    #: Rows beyond which the caller is told to narrow the range instead of
    #: being handed a file that may take minutes to generate.
    MAX_ROWS = 100_000

    def get(self, request, kind):
        self.require_role(OrgMembership.Role.MANAGER)
        scoped = self.scoped_pharmacy_ids()

        if kind == "sales":
            window, error = _window_from_request(request, self.organization)
            if error:
                return error
            text = reports.sales_csv(self.organization, window, scoped_ids=scoped)
            rows = text.count("\n")
            if rows > self.MAX_ROWS:
                return Response(
                    {
                        "error": {
                            "code": "export_too_large",
                            "detail": f"{rows} rows exceeds the {self.MAX_ROWS}-row limit. Narrow the date range, or use the asynchronous export.",
                            "fields": {},
                        }
                    },
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
            self._audit_export(kind, rows)
            return _csv_response(text, f"rakho-sales-{window.start.isoformat()}-to-{(window.end - timezone.timedelta(days=1)).isoformat()}.csv", organization=self.organization)

        if kind == "expiry":
            horizon = request.query_params.get("horizon", "90")
            try:
                days = max(1, min(int(horizon), 730))
            except (TypeError, ValueError):
                days = 90
            text = reports.expiry_csv(self.organization, days=days, scoped_ids=scoped)
            self._audit_export(kind, text.count("\n"))
            return _csv_response(text, f"rakho-expiry-{timezone.localdate().isoformat()}.csv", organization=self.organization)

        return Response(
            {"error": {"code": "unknown_export", "detail": "Supported exports: sales, expiry.", "fields": {}}},
            status=status.HTTP_404_NOT_FOUND,
        )

    def _audit_export(self, kind, rows):
        """Every export is recorded. A download of the whole catalogue is an
        event a compliance officer would want to see, and it is cheap to log."""
        from . import audit

        audit.record(
            self.request,
            AuditLog.Action.EXPORT,
            organization=self.organization,
            target=(kind, str(timezone.localdate())),
            changes={"rows": {"from": None, "to": rows}},
        )


# ── Bulk onboarding ─────────────────────────────────────────────────────


STOCK_IMPORT_COLUMNS = ("branch_code", "brand_name", "generic_name", "batch_number", "expiry_date", "quantity", "unit_cost", "selling_price")


class StockImportView(OrgScopedView):
    """Import a stock list as CSV.

    Designed around the file a Bangladeshi pharmacy actually has: it is usually
    an export from whatever spreadsheet they use now, the header names vary, and
    a few rows will be wrong. So the import validates every row, reports the
    failures with their line numbers, and writes the rows that are correct ---
    an all-or-nothing import would force a manager to fix a 400-row file before
    learning about a typo on line 397.
    """

    permission_classes = [*OrgScopedView.permission_classes, HasFreshJWT]
    #: The global DRF parser set is JSON-only --- this API is otherwise JSON in
    #: and JSON out. A file upload is the one exception, so it declares its own
    #: parsers rather than widening the default for every endpoint.
    parser_classes = [MultiPartParser, FormParser]
    #: A cap on the upload, so a mistake in a spreadsheet cell cannot turn into
    #: a request that holds a worker for a minute.
    MAX_ROWS = 5_000

    def post(self, request):
        self.require_role(OrgMembership.Role.MANAGER)
        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"error": {"code": "no_file", "detail": "Attach a CSV file in the 'file' field.", "fields": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return Response(
                {
                    "error": {
                        "code": "bad_encoding",
                        "detail": "The file must be UTF-8. Re-save it as CSV UTF-8 and try again.",
                        "fields": {},
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return Response(
                {"error": {"code": "empty_file", "detail": "No data rows found.", "fields": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(rows) > self.MAX_ROWS:
            return Response(
                {
                    "error": {
                        "code": "too_many_rows",
                        "detail": f"{len(rows)} rows exceeds the {self.MAX_ROWS}-row limit. Split the file and upload in parts.",
                        "fields": {},
                    }
                },
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        from .stock_import import import_stock_rows

        result = import_stock_rows(
            organization=self.organization,
            rows=rows,
            scoped_ids=self.scoped_pharmacy_ids(),
            request=request,
        )
        http_status = status.HTTP_201_CREATED if result["created"] else status.HTTP_400_BAD_REQUEST
        if result["created"] and result["failed"]:
            # Partial success is still a success, and 200 says so more
            # accurately than 201 --- nothing new was created in the failed
            # rows. The body carries both counts either way.
            http_status = status.HTTP_200_OK
        return Response(result, status=http_status)

    def get(self, request):
        """Describe the expected format, so the endpoint documents itself.

        A manager who opens the import screen in a browser gets the column list
        and a sample row rather than a 405, which is the difference between
        "the feature is broken" and "I need a file shaped like this".
        """
        return Response(
            {
                "columns": list(STOCK_IMPORT_COLUMNS),
                "required": ["brand_name", "batch_number", "expiry_date", "quantity"],
                "optional_branches": [{"branch_code": branch.branch_code or "", "name": branch.name} for branch in self.scoped_pharmacies()[:50]],
                "branch_rule": "branch_code is optional; without it the row is imported into your default branch.",
                "sample": {
                    "branch_code": "DHA-01",
                    "brand_name": "Napa Extend",
                    "generic_name": "Paracetamol",
                    "batch_number": "NP-2291",
                    "expiry_date": "2027-04-30",
                    "quantity": "120",
                    "unit_cost": "1.85",
                    "selling_price": "2.00",
                },
                "date_format": "YYYY-MM-DD",
                "max_rows": self.MAX_ROWS,
            }
        )


# ── Branding (white-label, Phase 6) ─────────────────────────────────────


class BrandingView(OrgScopedView):
    """Read and set the organisation's own visual identity.

    Scoped to the tenant and applied per-organisation rather than per-deployment,
    so a reseller can put their brand on the console for their own customers
    without a separate build. The colour is validated as a hex value --- it is
    interpolated into a stylesheet, and a free-text field there is a small
    injection surface for no benefit.
    """

    permission_classes = [*OrgScopedView.permission_classes, HasFreshJWT]

    ALLOWED_COLOURS = "0123456789abcdefABCDEF"

    def get(self, request):
        organization = self.organization
        return Response(self._payload(organization))

    def patch(self, request):
        self.require_role(OrgMembership.Role.ADMIN)
        organization = self.organization
        changes = {}

        if "brand_name" in request.data:
            brand_name = str(request.data["brand_name"]).strip()[:120]
            if not organization.white_label_enabled and brand_name:
                return self._refused("White-labelling is not enabled on this plan. Contact support to turn it on.")
            changes["brand_name"] = brand_name
        if "brand_color" in request.data:
            colour = str(request.data["brand_color"]).strip()
            if colour and (not colour.startswith("#") or any(char not in self.ALLOWED_COLOURS for char in colour[1:])):
                return self._refused("brand_color must be a hex value such as #0F7B6C.")
            changes["brand_color"] = colour
        if "logo_url" in request.data:
            logo = str(request.data["logo_url"]).strip()[:500]
            if logo and not logo.startswith("https://"):
                # https only: a logo is fetched by every client that renders the
                # console, and an http URL would downgrade the page.
                return self._refused("logo_url must be an https:// address.")
            changes["logo_url"] = logo

        if changes:
            for field, value in changes.items():
                setattr(organization, field, value)
            organization.save(update_fields=[*changes.keys(), "updated_at"])

        return Response(self._payload(organization))

    @staticmethod
    def _refused(detail):
        """A validation-style refusal in the API's structured error shape.

        Returned rather than raised so the three rules above read as one flat
        sequence of checks, and so the response body matches every other 400
        the envelope handler produces.
        """
        return Response({"error": {"code": "white_label_refused", "detail": detail, "fields": {}}}, status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    def _payload(organization):
        return {
            "brand_name": organization.brand_name,
            "brand_color": organization.brand_color,
            "logo_url": organization.logo_url,
            "white_label_enabled": organization.white_label_enabled,
            "legal_name": organization.legal_name or organization.name,
            "currency": organization.currency,
            "timezone": organization.timezone,
            "locale": organization.locale,
        }


# ── Usage metrics (Phase 6) ─────────────────────────────────────────────


class UsageMetricsView(OrgScopedView):
    """Product usage for the tenant: the numbers a buyer checks in month two.

    Deliberately answers "are people using this" rather than "how many requests
    did you serve" --- a monthly-active-staff figure and a records-touched
    figure are what justify a renewal, and both are cheap to compute.
    """

    def get(self, request):
        self.require_role(OrgMembership.Role.ADMIN)
        organization = self.organization
        window = reports.DateWindow.last_days(30, organization=organization)

        members = organization.memberships.filter(is_active=True)
        branches = self.scoped_pharmacies()
        medicines = Medicine.objects.filter(pharmacy__in=branches, is_active=True)
        from .models import Batch, Sale, StockMovement

        return Response(
            {
                "window": {"start": window.start.isoformat(), "end": (window.end - timezone.timedelta(days=1)).isoformat()},
                "seats": {
                    "active_members": members.count(),
                    "admins": members.filter(role__in=[OrgMembership.Role.ADMIN, OrgMembership.Role.OWNER]).count(),
                    "invited_pending": organization.invitations.filter(status="pending").count(),
                },
                "branches": {"active": branches.count(), "allowance": organization.branch_allowance},
                "catalogue": {"medicines": medicines.count(), "batches": Batch.objects.filter(pharmacy__in=branches).count()},
                "activity": {
                    "sales_last_30d": Sale.objects.filter(pharmacy__in=branches, sold_at__gte=window.start).count(),
                    "stock_movements_last_30d": StockMovement.objects.filter(pharmacy__in=branches, created_at__gte=window.start).count(),
                },
                "audit_entries_last_30d": organization.audit_entries.filter(created_at__gte=window.start).count(),
            }
        )


class ExportQueueView(OrgScopedView):
    """Hand a large export to the background worker.

    The counterpart to the synchronous cap: the request returns immediately with
    a task id, and the worker writes the file to the tenant's storage. Kept
    alongside the sync endpoint rather than replacing it, because most exports
    are small and a background round-trip would make the common case worse.
    """

    permission_classes = [*OrgScopedView.permission_classes, HasFreshJWT]

    def post(self, request):
        self.require_role(OrgMembership.Role.ADMIN)
        kind = str(request.data.get("kind", "sales"))
        if kind not in ("sales", "expiry"):
            return Response(
                {"error": {"code": "unknown_export", "detail": "Supported exports: sales, expiry.", "fields": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = async_tasks.build_export.delay(
            organization_id=str(self.organization.pk),
            kind=kind,
            requested_by=str(getattr(request.user, "pk", "")),
        )
        return Response({"task_id": result.id, "kind": kind, "status": "queued"}, status=status.HTTP_202_ACCEPTED)
