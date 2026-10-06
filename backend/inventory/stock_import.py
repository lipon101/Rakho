"""Bulk stock import: turning a spreadsheet into batches.

The design goal is that a manager with a messy file gets their good rows in and
a list of the bad ones --- never a single "import failed" that tells them
nothing about which of four hundred lines to fix.

Three rules make that work:

* **Row-by-row, in one transaction per row.** A failure on line 397 must not
  roll back line 1. Each row is its own atomic unit, so the import is
  resumable: fix the reported lines, re-upload, and the already-imported ones
  are matched rather than duplicated.
* **Errors carry the line number and the column.** "invalid date" is useless;
  "line 42: expiry_date must be YYYY-MM-DD" is a fix.
* **Idempotent on (branch, medicine, batch number).** Re-uploading a file that
  was already imported adds stock rather than creating a second batch of the
  same batch number, which is the mistake that silently doubles a catalogue.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction

from . import audit
from .models import AuditLog, Batch, Medicine

logger = logging.getLogger("inventory.import")

REQUIRED_COLUMNS = ("brand_name", "batch_number", "expiry_date", "quantity")

#: Header spellings seen in the wild, mapped to the canonical column. A
#: Bangladeshi pharmacy's spreadsheet may say "Medicine", "Product Name" or
#: "Expiry" --- refusing those would make the feature unusable for exactly the
#: customer it is built for.
HEADER_ALIASES = {
    "brand_name": {"brand_name", "brandname", "medicine", "medicine_name", "product", "product_name", "name", "ওষুধ"},
    "generic_name": {"generic_name", "generic", "molecule", "জেনেরিক"},
    "batch_number": {"batch_number", "batch", "batchno", "batch_no", "lot", "লট"},
    "expiry_date": {"expiry_date", "expiry", "exp", "exp_date", "expires", "মেয়াদ"},
    "quantity": {"quantity", "qty", "units", "stock", "পরিমাণ"},
    "unit_cost": {"unit_cost", "cost", "cost_price", "purchase_price", "ক্রয়মূল্য"},
    "selling_price": {"selling_price", "price", "mrp", "sale_price", "বিক্রয়মূল্য"},
    "branch_code": {"branch_code", "branch", "outlet", "শাখা"},
}

#: Date formats accepted in the expiry column. Ordered most-likely-first for the
#: region: a Bangladesh spreadsheet writes day-first, and a US-style file would
#: otherwise be read as month-first and silently mis-date a whole delivery.
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%b %Y")


def _canonical_headers(fieldnames):
    """Map the file's own header spellings onto canonical column names."""
    mapping = {}
    for raw in fieldnames or []:
        key = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
        for canonical, aliases in HEADER_ALIASES.items():
            if key in aliases:
                mapping[raw] = canonical
                break
    return mapping


def _parse_date(value):
    text = (value or "").strip()
    if not text:
        raise ValueError("expiry_date is required")
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        if fmt == "%b %Y":
            # A month with no day means the end of that month --- the date the
            # stock is last usable. Using the 1st would write off a month early.
            next_month = date(parsed.year + (parsed.month == 12), (parsed.month % 12) + 1, 1)
            return date.fromordinal(next_month.toordinal() - 1)
        return parsed
    raise ValueError(f"expiry_date '{text}' is not a date (try YYYY-MM-DD)")


def _parse_quantity(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        raise ValueError("quantity is required")
    try:
        quantity = int(Decimal(text))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"quantity '{value}' is not a whole number") from exc
    if quantity <= 0:
        raise ValueError("quantity must be greater than zero")
    return quantity


def _parse_money(value, *, default="0.00"):
    text = str(value if value is not None else "").strip().replace(",", "").replace("৳", "")
    if not text:
        return Decimal(default)
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"'{value}' is not an amount") from exc


def import_stock_rows(*, organization, rows, scoped_ids=None, request=None):
    """Import rows, returning what worked and what did not.

    ``scoped_ids`` is the importing member's visible branches. A row that names a
    branch outside that set is refused with a clear message rather than imported
    silently or dropped --- a manager importing a chain-wide file needs to be
    told which branches they cannot write to, not to discover later that half
    their file vanished.
    """
    branches = {branch.branch_code.lower(): branch for branch in organization.pharmacies.filter(is_active=True) if branch.branch_code}
    fallback = _fallback_branch(organization, scoped_ids)
    allowed_ids = {str(branch.pk) for branch in organization.pharmacies.filter(is_active=True)} if scoped_ids is None else {str(pk) for pk in scoped_ids}

    header_map = _canonical_headers(rows[0].keys() if rows else [])
    missing = [column for column in REQUIRED_COLUMNS if column not in header_map.values()]
    if missing:
        return {
            "created": 0,
            "updated": 0,
            "failed": len(rows),
            "resolved_columns": sorted(set(header_map.values())),
            "errors": [
                {
                    "line": 1,
                    "column": ",".join(missing),
                    "message": f"Missing required column(s): {', '.join(missing)}. Expected: {', '.join(REQUIRED_COLUMNS)}.",
                }
            ],
            "branch_codes_known": sorted(branches.keys()),
        }

    created = 0
    updated = 0
    errors = []
    for index, raw_row in enumerate(rows, start=2):  # line 2 is the first data row
        row = {header_map.get(key, key): value for key, value in raw_row.items() if key in header_map}
        try:
            branch = fallback
            code = str(row.get("branch_code", "") or "").strip().lower()
            if code:
                branch = branches.get(code)
                if branch is None:
                    raise ValueError(f"unknown branch_code '{row.get('branch_code')}' (known: {', '.join(sorted(branches)) or 'none'})")
                if str(branch.pk) not in allowed_ids:
                    raise ValueError(f"branch_code '{row.get('branch_code')}' is outside your branch access")
            if branch is None:
                raise ValueError("no branch to import into: set branch_code, or create a branch first")

            brand_name = str(row.get("brand_name", "") or "").strip()
            if not brand_name:
                raise ValueError("brand_name is required")
            batch_number = str(row.get("batch_number", "") or "").strip()
            if not batch_number:
                raise ValueError("batch_number is required")

            expiry = _parse_date(row.get("expiry_date"))
            quantity = _parse_quantity(row.get("quantity"))
            unit_cost = _parse_money(row.get("unit_cost"))
            selling_price = _parse_money(row.get("selling_price"), default=str(unit_cost))

            with transaction.atomic():
                medicine, _ = Medicine.objects.get_or_create(
                    pharmacy=branch,
                    brand_name__iexact=brand_name,
                    defaults={
                        "brand_name": brand_name,
                        "generic_name": str(row.get("generic_name", "") or "").strip(),
                        "default_selling_price": selling_price,
                        "low_stock_threshold": branch.low_stock_default or 10,
                    },
                )
                batch, was_created = Batch.objects.get_or_create(
                    pharmacy=branch,
                    medicine=medicine,
                    batch_number=batch_number,
                    defaults={
                        "expiry_date": expiry,
                        "unit_cost": unit_cost,
                        "selling_price": selling_price,
                        "quantity_received": quantity,
                        "quantity_available": quantity,
                        "supplier_name": str(row.get("supplier_name", "") or "").strip()[:255],
                    },
                )
                if not was_created:
                    # Same batch number at the same branch: this is a second
                    # delivery of stock already on the shelf. Adding to the
                    # quantity is the only reading that does not lose goods or
                    # invent a duplicate batch.
                    batch.quantity_received += quantity
                    batch.quantity_available += quantity
                    batch.save(update_fields=["quantity_received", "quantity_available", "updated_at"])
                    updated += 1
                else:
                    created += 1
        except ValueError as exc:
            errors.append({"line": index, "message": str(exc)})
        except IntegrityError as exc:
            logger.warning("import line %s violated a constraint: %s", index, exc)
            errors.append({"line": index, "message": "conflicts with existing data (duplicate batch for this branch and medicine)"})
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort the file
            logger.exception("import line %s failed unexpectedly", index)
            errors.append({"line": index, "message": f"unexpected error: {type(exc).__name__}"})

    result = {
        "created": created,
        "updated": updated,
        "failed": len(errors),
        "total": len(rows),
        "resolved_columns": sorted(set(header_map.values())),
        "errors": errors[:100],
        "branch_codes_known": sorted(branches.keys()),
    }
    audit.record(
        request,
        AuditLog.Action.CREATE,
        organization=organization,
        target=("StockImport", str(len(rows))),
        changes={"created": {"from": None, "to": created}, "updated": {"from": None, "to": updated}, "failed": {"from": None, "to": len(errors)}},
        note="bulk stock import",
    )
    return result


def _fallback_branch(organization, scoped_ids):
    """Where a row goes when it names no branch.

    Preference order: the only branch the member can see, then the branch that
    already holds stock (the shop's real home), then the oldest branch. Never
    the newest --- a branch created yesterday is usually the one being set up,
    not the one receiving an import of historical stock.
    """
    queryset = organization.pharmacies.filter(is_active=True)
    if scoped_ids is not None:
        queryset = queryset.filter(pk__in=list(scoped_ids))
    if queryset.count() == 1:
        return queryset.first()
    busy = queryset.filter(batches__isnull=False).distinct().order_by("created_at").first()
    return busy or queryset.order_by("created_at").first()
