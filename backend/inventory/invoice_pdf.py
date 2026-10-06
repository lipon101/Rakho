"""Invoice and quotation PDFs, in Bengali and English.

The invoice is the document a Bangladeshi business hands to its accountant, so
it has to be right in two ways that a screen does not: the Bengali has to render
as Bengali --- not as boxes, and not as a transliteration --- and the arithmetic
has to be the arithmetic the database already stored.

Both are handled here rather than in a template engine. A Bengali PDF needs a
font with the script's conjuncts and reph forms embedded in the file, because
the reader's machine cannot be assumed to have one; and the numbers are taken
from the invoice's own stored fields rather than recomputed, because an invoice
whose total is recalculated at print time is not an invoice.

Two documents, one renderer:

* an **invoice** is a frozen record --- its amounts and tax identity were
  snapshotted when it was issued, and this module only lays them out;
* a **quotation** is a live estimate --- it is built from the current branch and
  seat counts, and it says so, so nobody mistakes it for a bill.

The distinction is carried into the document itself: the quotation is headed
"Estimate" and carries a note that the figures are not a demand for payment.
"""

from __future__ import annotations

import io
import logging
from datetime import date

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = logging.getLogger("inventory.invoice_pdf")

#: Where the embedded fonts live. Shipped with the code rather than fetched at
#: render time: a PDF that depends on a network call is a PDF that fails on the
#: day the network is slow, and the font is a few hundred KB.
#:
#: Hind Siliguri rather than Noto Sans Bengali, and the reason is not aesthetic.
#: Noto Sans Bengali contains **no Latin glyphs at all** --- its ``cmap`` maps
#: the Bengali block and the Bengali digits, and nothing in ``A-Z``. A document
#: set entirely in it therefore renders every Latin word --- the brand name, the
#: customer's legal name, "Base plan" --- as *nothing*: not boxes, not a
#: fallback, just blank space, which is the worst kind of failure because the
#: page still looks finished. Hind Siliguri carries both scripts in one file, so
#: a mixed Bengali/English invoice needs no font switching and no second font
#: embedded. This was caught by rendering a real invoice and reading it back,
#: not by the tests --- which is why the tests now assert on the Latin text too.
FONT_DIR = settings.BASE_DIR / "inventory" / "fonts"
FONT_REGULAR = FONT_DIR / "HindSiliguri-Regular.ttf"
FONT_BOLD = FONT_DIR / "HindSiliguri-Bold.ttf"

FONT_NAME = "HindSiliguri"
FONT_NAME_BOLD = "HindSiliguri-Bold"

_fonts_registered = False

#: Bengali digits, indexed by the ASCII digit they replace. Bengali uses its own
#: numerals, and a Bangladeshi invoice that prints "1,499" where the reader
#: expects "১,৪৯৯" looks like a foreign document.
BENGALI_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")

#: Every user-visible string, in both languages. Kept as one table so a missing
#: translation is a KeyError at import rather than a blank cell on a customer's
#: invoice.
LABELS = {
    "bn": {
        "invoice": "ভ্যাট ইনভয়েস",
        "quotation": "মূল্য প্রস্তাব (Estimate)",
        "number": "ইনভয়েস নম্বর",
        "status": "অবস্থা",
        "period": "সময়কাল",
        "issued": "ইস্যু তারিখ",
        "due": "পরিশোধের শেষ তারিখ",
        "paid": "পরিশোধিত",
        "seller": "বিক্রেতা",
        "buyer": "ক্রেতা",
        "bin": "বিআইএন / ভ্যাট নিবন্ধন",
        "address": "ঠিকানা",
        "description": "বিবরণ",
        "quantity": "পরিমাণ",
        "unit_price": "একক মূল্য",
        "amount": "টাকা",
        "subtotal": "উপমোট",
        "vat": "ভ্যাট",
        "total": "সর্বমোট",
        "currency": "টাকা",
        "notes": "নোট",
        "estimate_note": "এটি একটি মূল্য প্রস্তাব, কোনো পরিশোধের দাবি নয়। প্রকৃত ইনভয়েস ইস্যুর সময় চূড়ান্ত হবে।",
        "status_draft": "খসড়া",
        "status_issued": "ইস্যুকৃত",
        "status_paid": "পরিশোধিত",
        "status_void": "বাতিল",
        "page": "পৃষ্ঠা",
        "generated": "তৈরি",
    },
    "en": {
        "invoice": "VAT Invoice",
        "quotation": "Quotation (Estimate)",
        "number": "Invoice number",
        "status": "Status",
        "period": "Period",
        "issued": "Issued",
        "due": "Due",
        "paid": "Paid",
        "seller": "Seller",
        "buyer": "Buyer",
        "bin": "BIN / VAT registration",
        "address": "Address",
        "description": "Description",
        "quantity": "Qty",
        "unit_price": "Unit price",
        "amount": "Amount",
        "subtotal": "Subtotal",
        "vat": "VAT",
        "total": "Total",
        "currency": "BDT",
        "notes": "Notes",
        "estimate_note": "This is a quotation, not a demand for payment. The final figures are fixed when an invoice is issued.",
        "status_draft": "Draft",
        "status_issued": "Issued",
        "status_paid": "Paid",
        "status_void": "Void",
        "page": "Page",
        "generated": "Generated",
    },
}

#: The invoice's stored status values, mapped to the label key that names them.
STATUS_KEYS = {
    "draft": "status_draft",
    "issued": "status_issued",
    "paid": "status_paid",
    "void": "status_void",
}


def _register_fonts():
    """Register the embedded fonts once per process.

    ``pdfmetrics.registerFont`` is idempotent in effect but not free, and a
    report that renders fifty invoices should not re-parse the font fifty times.
    """
    global _fonts_registered
    if _fonts_registered:
        return
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_REGULAR)))
    pdfmetrics.registerFont(TTFont(FONT_NAME_BOLD, str(FONT_BOLD)))
    _fonts_registered = True


def to_bengali_digits(value) -> str:
    """Render a number with Bengali numerals.

    Applied to the *formatted* string, after the thousands separators are in
    place, so the separators themselves are untouched --- they are punctuation,
    not digits, and Bengali uses the same comma grouping.
    """
    return str(value).translate(BENGALI_DIGITS)


def format_money(amount, *, language: str = "bn") -> str:
    """Whole taka with thousands separators, in the requested numerals.

    The amounts are integers by construction (the model stores whole taka), so
    there is no rounding decision to make here --- which is the point. A float
    would eventually print 199.99999999 on a customer's tax document.
    """
    text = f"{int(amount):,}"
    return to_bengali_digits(text) if language == "bn" else text


def format_date(value: date | None, *, language: str = "bn") -> str:
    """A date as ``DD/MM/YYYY``, in the requested numerals.

    Day-first, because that is how a date is read in Bangladesh and how the
    rest of the product's CSV import already parses them; a month-first date
    would be read as a different day by half the people who see it.
    """
    if value is None:
        return "—"
    text = value.strftime("%d/%m/%Y")
    return to_bengali_digits(text) if language == "bn" else text


def _styles(language: str):
    """The paragraph styles, in the right font for the language.

    English uses the same embedded font rather than Helvetica: mixing two fonts
    on one page is visible, and the Bengali font's Latin glyphs are perfectly
    good. One font, one look.
    """
    return {
        "title": ParagraphStyle("title", fontName=FONT_NAME_BOLD, fontSize=18, leading=24, textColor=colors.HexColor("#0f172a")),
        "subtitle": ParagraphStyle("subtitle", fontName=FONT_NAME, fontSize=10, leading=14, textColor=colors.HexColor("#475569")),
        "label": ParagraphStyle("label", fontName=FONT_NAME_BOLD, fontSize=8, leading=11, textColor=colors.HexColor("#64748b")),
        "value": ParagraphStyle("value", fontName=FONT_NAME, fontSize=10, leading=14, textColor=colors.HexColor("#0f172a")),
        "cell": ParagraphStyle("cell", fontName=FONT_NAME, fontSize=9, leading=12, textColor=colors.HexColor("#0f172a")),
        "cell_right": ParagraphStyle("cell_right", fontName=FONT_NAME, fontSize=9, leading=12, alignment=2, textColor=colors.HexColor("#0f172a")),
        "note": ParagraphStyle("note", fontName=FONT_NAME, fontSize=8, leading=12, textColor=colors.HexColor("#64748b")),
    }


def _header(story, styles, labels, *, title, subtitle, brand_name, brand_color):
    """The masthead: the seller's identity and the document's title."""
    accent = colors.HexColor(brand_color) if brand_color else colors.HexColor("#0d9488")
    left = [
        Paragraph(brand_name or "Rakho", styles["title"]),
        Paragraph(subtitle, styles["subtitle"]),
    ]
    right = [Paragraph(title, styles["title"])]
    table = Table([[left, right]], colWidths=[110 * mm, 60 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, -1), 1.2, accent),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6 * mm))


def _party_block(styles, labels, *, seller, buyer):
    """Seller and buyer side by side, each with its tax identity.

    The BIN is printed even when blank, as an em dash: a finance team that sees
    the field present and empty knows the seller has no registration, whereas a
    missing field looks like a rendering bug.
    """

    def block(title, name, bin_value, address):
        return [
            Paragraph(title, styles["label"]),
            Paragraph(name or "—", styles["value"]),
            Paragraph(f"{labels['bin']}: {bin_value or '—'}", styles["note"]),
            Paragraph(f"{labels['address']}: {address or '—'}", styles["note"]),
        ]

    table = Table(
        [
            [block(labels["seller"], seller["name"], seller["bin"], seller.get("address", "")), block(labels["buyer"], buyer["name"], buyer["bin"], buyer.get("address", ""))],
        ],
        colWidths=[85 * mm, 85 * mm],
    )
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return table


def _meta_block(styles, labels, rows):
    """The document's own facts: number, status, period, dates."""
    data = [[Paragraph(label, styles["label"]), Paragraph(value, styles["value"])] for label, value in rows]
    table = Table(data, colWidths=[45 * mm, 125 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _lines_table(styles, labels, lines, *, language):
    """The billable lines, with the money right-aligned.

    Right alignment is not decoration: a column of amounts that is left-aligned
    cannot be added up by eye, and adding it up by eye is exactly what the
    person holding the invoice will do.
    """
    header = [
        Paragraph(labels["description"], styles["label"]),
        Paragraph(labels["quantity"], styles["label"]),
        Paragraph(labels["unit_price"], styles["label"]),
        Paragraph(labels["amount"], styles["label"]),
    ]
    data = [header]
    for line in lines:
        data.append(
            [
                Paragraph(line["description"], styles["cell"]),
                Paragraph(format_money(line["quantity"], language=language), styles["cell_right"]),
                Paragraph(format_money(line["unit_amount"], language=language), styles["cell_right"]),
                Paragraph(format_money(line["amount"], language=language), styles["cell_right"]),
            ]
        )
    table = Table(data, colWidths=[90 * mm, 20 * mm, 30 * mm, 30 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#cbd5e1")),
                ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _totals_table(styles, labels, *, subtotal, vat_percent, vat_amount, total, language):
    """Subtotal, VAT and total, with the total emphasised.

    The VAT row names its own rate, so the reader can check the arithmetic
    without a second document --- and the three rows are the same three numbers
    the model stores, not a recomputation.
    """
    percent = str(vat_percent).rstrip("0").rstrip(".") if vat_percent else "0"
    percent_text = to_bengali_digits(percent) if language == "bn" else percent
    data = [
        [Paragraph(labels["subtotal"], styles["cell"]), Paragraph(format_money(subtotal, language=language), styles["cell_right"])],
        [Paragraph(f"{labels['vat']} ({percent_text}%)", styles["cell"]), Paragraph(format_money(vat_amount, language=language), styles["cell_right"])],
        [Paragraph(labels["total"], styles["value"]), Paragraph(format_money(total, language=language), styles["value"])],
    ]
    table = Table(data, colWidths=[40 * mm, 40 * mm])
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("LINEABOVE", (0, 2), (-1, 2), 1, colors.HexColor("#0f172a")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _build_pdf(story) -> bytes:
    """Lay the story out on A4 and return the bytes.

    The buffer is in memory rather than a file: the caller is an HTTP response
    or an email attachment, and a temporary file would be one more thing to
    clean up on the error path.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Rakho",
        author="Rakho",
    )
    doc.build(story)
    return buffer.getvalue()


def render_invoice_pdf(invoice, *, language: str = "bn") -> bytes:
    """Render an issued (or draft) invoice to PDF bytes.

    ``language`` selects the labels and the numerals; the amounts come from the
    invoice's own stored fields either way, so the two languages can never
    disagree about the money.
    """
    _register_fonts()
    language = language if language in LABELS else "bn"
    labels = LABELS[language]
    styles = _styles(language)

    organization = invoice.organization
    brand_name = organization.display_name if organization else "Rakho"
    brand_color = getattr(organization, "brand_color", "") if organization else ""

    story = []
    _header(
        story,
        styles,
        labels,
        title=labels["invoice"],
        subtitle=f"{labels['number']}: {invoice.number}",
        brand_name=brand_name,
        brand_color=brand_color,
    )

    story.append(
        _party_block(
            styles,
            labels,
            seller={"name": invoice.seller_name or brand_name, "bin": invoice.seller_bin, "address": ""},
            buyer={"name": invoice.buyer_name, "bin": invoice.buyer_bin, "address": invoice.buyer_address},
        )
    )
    story.append(Spacer(1, 6 * mm))

    story.append(
        _meta_block(
            styles,
            labels,
            [
                (labels["status"], labels[STATUS_KEYS.get(invoice.status, "status_draft")]),
                (labels["period"], f"{format_date(invoice.period_start, language=language)} — {format_date(invoice.period_end, language=language)}"),
                (labels["issued"], format_date(invoice.issued_on, language=language)),
                (labels["due"], format_date(invoice.due_on, language=language)),
            ],
        )
    )
    story.append(Spacer(1, 6 * mm))

    lines = [
        {
            "description": line.description,
            "quantity": line.quantity,
            "unit_amount": line.unit_amount,
            "amount": line.amount,
        }
        for line in invoice.lines.all()
    ]
    story.append(_lines_table(styles, labels, lines, language=language))
    story.append(Spacer(1, 4 * mm))

    totals = _totals_table(
        styles,
        labels,
        subtotal=invoice.subtotal,
        vat_percent=invoice.vat_percent,
        vat_amount=invoice.vat_amount,
        total=invoice.total,
        language=language,
    )
    # The totals sit on the right, under the amount column, which is where the
    # eye already is after reading the last line.
    wrapper = Table([["", totals]], colWidths=[90 * mm, 80 * mm])
    wrapper.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(wrapper)

    if invoice.notes:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(f"{labels['notes']}: {invoice.notes}", styles["note"]))

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(f"{labels['currency']} · {labels['generated']}: {format_date(date.today(), language=language)}", styles["note"]))

    return _build_pdf(story)


def render_quotation_pdf(organization, quote, *, language: str = "bn") -> bytes:
    """Render a live quotation to PDF bytes.

    A quotation is not an invoice and the document says so, twice: in its title
    and in a note. The failure this prevents is a customer treating an estimate
    as a bill --- or, worse, a finance team filing one.
    """
    _register_fonts()
    language = language if language in LABELS else "bn"
    labels = LABELS[language]
    styles = _styles(language)

    brand_name = organization.display_name if organization else "Rakho"
    brand_color = getattr(organization, "brand_color", "") if organization else ""

    story = []
    _header(
        story,
        styles,
        labels,
        title=labels["quotation"],
        subtitle=brand_name,
        brand_name=brand_name,
        brand_color=brand_color,
    )

    story.append(
        _party_block(
            styles,
            labels,
            seller={"name": brand_name, "bin": getattr(settings, "INVOICE_SELLER_BIN", ""), "address": ""},
            buyer={"name": organization.legal_name or organization.display_name, "bin": organization.bin, "address": organization.address},
        )
    )
    story.append(Spacer(1, 6 * mm))

    story.append(
        _meta_block(
            styles,
            labels,
            [
                (labels["status"], labels["quotation"]),
                (labels["period"], format_date(date.today(), language=language)),
            ],
        )
    )
    story.append(Spacer(1, 6 * mm))

    lines = []
    for branch in quote.branches:
        lines.append(
            {
                "description": f"{'Base plan' if branch.included else 'Additional branch'} — {branch.name}",
                "quantity": 1,
                "unit_amount": branch.amount,
                "amount": branch.amount,
            }
        )
    if quote.seats.billable_seats:
        lines.append(
            {
                "description": f"Additional seats ({quote.seats.active_seats} active, {quote.seats.included_seats} included)",
                "quantity": quote.seats.billable_seats,
                "unit_amount": quote.seats.amount // max(quote.seats.billable_seats, 1),
                "amount": quote.seats.amount,
            }
        )

    story.append(_lines_table(styles, labels, lines, language=language))
    story.append(Spacer(1, 4 * mm))

    totals = _totals_table(
        styles,
        labels,
        subtotal=quote.subtotal,
        vat_percent=quote.vat_percent,
        vat_amount=quote.vat_amount,
        total=quote.total,
        language=language,
    )
    wrapper = Table([["", totals]], colWidths=[90 * mm, 80 * mm])
    wrapper.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(wrapper)

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(labels["estimate_note"], styles["note"]))

    return _build_pdf(story)
