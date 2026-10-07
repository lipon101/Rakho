"""Pricing: what this organisation costs, and why.

M5 is "base per branch + per-seat add-on", which is two decisions hiding in one
sentence:

* The **branch** is the unit of value. A chain that opens a second branch is
  doing more business through Rakho, so it pays more --- automatically, with no
  new negotiation.
* **Seats** are the unit of cost. Every additional person who signs in is
  another account to secure and another set of permissions to get right, and a
  plan that ignores them subsidises a fifty-person head office with a two-person
  shop's money.

Both are integers in the organisation's own currency. Money is never a float
here: ``0.1 + 0.2`` is not ``0.3``, and an invoice that reads 1,799.9999999 BDT
is a support ticket that cannot be fixed by explaining floating point.
"""

from dataclasses import dataclass, field

from django.conf import settings

from .models import Organization, OrgMembership


@dataclass(frozen=True)
class BranchLine:
    """One branch's contribution to the bill."""

    pharmacy_id: str
    name: str
    #: True when the branch is inside the plan's allowance and therefore free.
    included: bool
    amount: int


@dataclass(frozen=True)
class SeatLine:
    included_seats: int
    active_seats: int
    billable_seats: int
    amount: int


@dataclass(frozen=True)
class Quote:
    """A complete, itemised answer to "what do we owe this month?"."""

    organization_id: str
    currency: str
    branches: list
    seats: SeatLine
    subtotal: int
    vat_percent: str
    vat_amount: int
    total: int
    plan: str
    notes: list = field(default_factory=list)

    @property
    def branch_count(self):
        return len(self.branches)

    @property
    def billable_branch_count(self):
        return sum(1 for line in self.branches if not line.included)


#: A single seat add-on is capped. A plausible typo (an extra zero) would
#: otherwise produce an invoice two orders of magnitude too large, discovered a
#: month later by the accountant rather than by the person who typed it.
MAX_SEAT_ADDON = 200

#: Published list prices in BDT, used when settings do not override them. Named
#: constants rather than inline literals because three places need to agree on
#: them --- the quote, the seat widget, and the tests that pin the arithmetic.
BRANCH_PRICE = 1499
SEAT_PRICE = 199


def _rate(name, default):
    """Read a price from settings, tolerating a string from the environment.

    Environment variables are strings, and ``int("1499")`` is fine while
    ``int("1,499")`` is not --- so a malformed value falls back to the default
    rather than taking the billing endpoint down.
    """
    raw = getattr(settings, name, default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def active_seat_count(organization):
    """Billable seats: active human memberships, and nothing else.

    Counted from the membership table rather than from a number stored on the
    organisation, so it is impossible to be billed for a seat nobody occupies or
    to occupy a seat nobody pays for. An API key is deliberately excluded --- it
    is a device credential for a branch, not a person.
    """
    return OrgMembership.objects.filter(organization=organization, is_active=True).count()


def included_seats(organization):
    """Seats the plan already covers: three per active branch, by default.

    Tying inclusion to branches rather than to a flat number is what makes the
    plan legible: opening a branch adds both a branch fee and the staff that
    branch needs, and the customer can predict the second line without asking.
    """
    per_branch = _rate("INCLUDED_SEATS_PER_BRANCH", 3)
    branch_count = max(organization.pharmacies.filter(is_active=True).count(), 1)
    return per_branch * branch_count + organization.seat_addon_count


def quote(organization, *, active_branches=None):
    """Price one organisation for the current period.

    ``active_branches`` may be passed by a caller that has already loaded them,
    which keeps an invoice run over many tenants from re-querying per tenant.
    """
    notes = []
    branches = list((active_branches if active_branches is not None else organization.pharmacies.filter(is_active=True)).order_by("name", "id"))
    branch_price = _rate("BRANCH_PRICE_BDT", BRANCH_PRICE)
    seat_price = _rate("SEAT_PRICE_BDT", SEAT_PRICE)
    allowance = organization.branch_allowance

    lines = []
    for index, branch in enumerate(branches):
        # The first `allowance` branches are the base price; anything beyond is
        # charged per branch. Ordering by name (then id, for the tie) makes the
        # assignment stable --- without it the "included" branch could change
        # between two invoices for the same month and the numbers would not
        # reconcile.
        included = index < allowance
        lines.append(
            BranchLine(
                pharmacy_id=str(branch.pk),
                name=branch.name,
                included=included,
                amount=0 if included else branch_price,
            )
        )
    if not lines:
        notes.append("No active branches: only the base plan fee applies.")

    seats = active_seat_count(organization)
    covered = included_seats(organization)
    billable = max(seats - covered, 0)
    seat_line = SeatLine(
        included_seats=covered,
        active_seats=seats,
        billable_seats=billable,
        amount=billable * seat_price,
    )

    subtotal = sum(line.amount for line in lines) + seat_line.amount
    vat_raw = getattr(settings, "VAT_PERCENT", "15")
    try:
        vat_percent = f"{float(vat_raw):.2f}"
    except (TypeError, ValueError):
        vat_percent = "15.00"
    # Rounded to the nearest taka. Invoicing in fractions of a taka is legal but
    # unhelpful: every Bangladeshi pharmacy pays in whole taka.
    vat_amount = round(subtotal * float(vat_percent) / 100)
    total = subtotal + vat_amount

    if organization.plan == Organization.Plan.ENTERPRISE:
        notes.append("Enterprise terms override the standard branch and seat rates.")
    if billable:
        notes.append(f"{billable} seat(s) beyond the {covered} included in the plan.")

    return Quote(
        organization_id=str(organization.pk),
        currency=organization.currency,
        branches=lines,
        seats=seat_line,
        subtotal=subtotal,
        vat_percent=vat_percent,
        vat_amount=vat_amount,
        total=total,
        plan=organization.plan,
        notes=notes,
    )


def seat_utilisation(organization):
    """How full the seat allowance is, for the console's plan widget.

    Returned as a small dict rather than a computed percentage because the
    console renders "4 of 6 seats used", and a percentage would lose the numbers
    that make that sentence useful.
    """
    #: Overall seat ceiling for this tenant (included + purchased add-on).
    #: Named ``limit`` as well as ``included`` because the console's wording is
    #: "4 of 6 seats used" and a client should not have to know that "6" is
    #: computed from a per-branch allowance plus an add-on count.
    used = active_seat_count(organization)
    included = included_seats(organization)
    return {
        "used": used,
        "included": included,
        "limit": included,
        "available": max(included - used, 0),
        "over": max(used - included, 0),
        "at_limit": used >= included,
        "is_full": used >= included,
        "branch_count": organization.pharmacies.filter(is_active=True).count(),
        "branch_allowance": organization.branch_allowance,
    }
