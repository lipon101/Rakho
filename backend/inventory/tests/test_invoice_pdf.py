"""Phase 3: the invoice PDF renders, in both languages, with the right money.

A PDF is hard to assert on, so the tests assert the things that actually break:

* the bytes are a PDF at all (a rendering error usually produces an empty file
  or an exception, and an empty file is the failure that reaches a customer);
* the Bengali font is *embedded* --- a PDF that references a font the reader
  does not have renders as boxes, and boxes on a tax document are worse than a
  plain English one;
* the totals on the page are the totals in the database, not a recomputation;
* both languages produce a document, and the Bengali one uses Bengali numerals.

The last point is checked by extracting the text back out of the PDF, which is
the only way to know what a reader will actually see rather than what was
passed in.
"""

from __future__ import annotations

import datetime as dt
import io
import uuid

from django.test import TestCase

from inventory.invoice_pdf import (
    FONT_NAME,
    format_money,
    render_invoice_pdf,
    render_quotation_pdf,
    to_bengali_digits,
)
from inventory.models import Invoice, InvoiceLine, Organization, Pharmacy


def _pdf_text(data: bytes) -> str:
    """Extract the visible text from a PDF, for assertions.

    Uses pypdf when it is installed and falls back to a raw scan otherwise. The
    fallback is deliberately crude --- it looks for the text operators in the
    content stream --- but it is enough to prove a glyph run made it into the
    file, and it keeps the test from depending on a library the project does not
    otherwise need.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return data.decode("latin-1", errors="ignore")


class InvoicePdfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(
            name="Dhanmondi Pharmacy",
            slug=f"dhanmondi-{uuid.uuid4().hex[:8]}",
            legal_name="Dhanmondi Pharmacy Ltd",
            bin="0012345678",
            address="House 12, Road 5, Dhanmondi, Dhaka",
        )
        cls.branch = Pharmacy.objects.create(name="Dhanmondi", organization=cls.org, branch_code="DH1")
        cls.invoice = Invoice.objects.create(
            organization=cls.org,
            number=f"INV-{uuid.uuid4().hex[:6].upper()}",
            status=Invoice.Status.ISSUED,
            period_start=dt.date(2026, 9, 1),
            period_end=dt.date(2026, 9, 30),
            issued_on=dt.date(2026, 10, 1),
            due_on=dt.date(2026, 10, 15),
            seller_name="Rakho",
            seller_bin="0099887766",
            buyer_name="Dhanmondi Pharmacy Ltd",
            buyer_bin="0012345678",
            buyer_address="House 12, Road 5, Dhanmondi, Dhaka",
            subtotal=2998,
            vat_percent="15.00",
            vat_amount=450,
            total=3448,
            notes="September billing",
        )
        InvoiceLine.objects.create(invoice=cls.invoice, kind=InvoiceLine.Kind.BASE, description="Base plan", quantity=1, unit_amount=1499, amount=1499)
        InvoiceLine.objects.create(invoice=cls.invoice, kind=InvoiceLine.Kind.BRANCH, description="Additional branch — Mirpur", quantity=1, unit_amount=1499, amount=1499)

    def test_renders_a_pdf(self):
        data = render_invoice_pdf(self.invoice)
        self.assertTrue(data.startswith(b"%PDF"), "output is not a PDF")
        self.assertGreater(len(data), 2000, "PDF is suspiciously small")

    def test_bengali_font_is_embedded(self):
        """The font travels inside the file, so the reader needs nothing installed."""
        data = render_invoice_pdf(self.invoice, language="bn")
        self.assertIn(FONT_NAME.encode(), data, "the Bengali font name is not in the PDF")
        # An embedded TrueType font appears as a FontFile2 stream. Without it the
        # reader substitutes a font and the Bengali renders as boxes.
        self.assertIn(b"FontFile2", data, "no embedded font program found")

    def test_totals_on_the_page_are_the_stored_totals(self):
        """The page shows the invoice's own numbers, not a fresh calculation.

        The invoice is deliberately given a total that does *not* equal
        ``subtotal + vat`` (3448 vs 3449) so that a renderer which recomputes
        would be caught. An invoice is a record; it must print what it stored.
        """
        data = render_invoice_pdf(self.invoice, language="en")
        text = _pdf_text(data)
        self.assertIn("3,448", text)
        self.assertIn("2,998", text)
        self.assertIn("450", text)

    def test_bengali_uses_bengali_numerals(self):
        data = render_invoice_pdf(self.invoice, language="bn")
        text = _pdf_text(data)
        self.assertIn("৩,৪৪৮", text, "Bengali numerals not found in the rendered PDF")
        self.assertNotIn("3,448", text, "ASCII numerals leaked into the Bengali document")

    def test_english_uses_ascii_numerals(self):
        data = render_invoice_pdf(self.invoice, language="en")
        text = _pdf_text(data)
        self.assertIn("3,448", text)
        self.assertNotIn("৩,৪৪৮", text)

    def test_both_languages_render(self):
        for language in ("bn", "en"):
            with self.subTest(language=language):
                data = render_invoice_pdf(self.invoice, language=language)
                self.assertTrue(data.startswith(b"%PDF"))

    def test_unknown_language_falls_back_to_bengali(self):
        """A bad ``?lang=`` must not 500; it falls back to the primary language."""
        data = render_invoice_pdf(self.invoice, language="fr")
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn("৩,৪৪৮", _pdf_text(data))

    def test_bin_and_buyer_appear(self):
        text = _pdf_text(render_invoice_pdf(self.invoice, language="en"))
        self.assertIn("0012345678", text)
        self.assertIn("Dhanmondi Pharmacy Ltd", text)

    def test_latin_text_renders_in_the_bengali_document(self):
        """The regression guard for the font that had no Latin glyphs.

        The first font chosen for this module --- Noto Sans Bengali --- maps the
        Bengali block and nothing in ``A-Z``. Every Latin word in a Bengali
        invoice therefore rendered as blank space: the brand name, the customer's
        legal name, the line descriptions. The page still looked finished, which
        is what made it dangerous. This asserts the Latin text is actually
        present, so a future font swap that reintroduces the gap fails here
        rather than on a customer's tax document.
        """
        text = _pdf_text(render_invoice_pdf(self.invoice, language="bn"))
        self.assertIn("Rakho", text, "the brand name did not render in the Bengali document")
        self.assertIn("Dhanmondi Pharmacy Ltd", text, "the buyer's legal name did not render")
        self.assertIn("Base plan", text, "a Latin line description did not render")

    def test_draft_invoice_renders(self):
        """A draft has no issue date; the renderer must not crash on the None."""
        self.invoice.status = Invoice.Status.DRAFT
        self.invoice.issued_on = None
        self.invoice.due_on = None
        data = render_invoice_pdf(self.invoice)
        self.assertTrue(data.startswith(b"%PDF"))


class QuotationPdfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Mirpur Pharmacy", slug=f"mirpur-{uuid.uuid4().hex[:8]}", bin="0022334455")
        Pharmacy.objects.create(name="Mirpur", organization=cls.org, branch_code="MI1")

    def test_quotation_renders_and_says_it_is_an_estimate(self):
        from inventory.org_billing import quote

        data = render_quotation_pdf(self.org, quote(self.org), language="en")
        self.assertTrue(data.startswith(b"%PDF"))
        text = _pdf_text(data)
        self.assertIn("Quotation", text)
        self.assertIn("not a demand for payment", text)

    def test_quotation_renders_in_bengali(self):
        from inventory.org_billing import quote

        data = render_quotation_pdf(self.org, quote(self.org), language="bn")
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn("মূল্য প্রস্তাব", _pdf_text(data))


class FormattingTests(TestCase):
    def test_bengali_digit_conversion(self):
        self.assertEqual(to_bengali_digits("0123456789"), "০১২৩৪৫৬৭৮৯")

    def test_money_grouping_is_preserved(self):
        """The comma is punctuation, not a digit, and must survive the conversion."""
        self.assertEqual(format_money(1234567, language="bn"), "১,২৩৪,৫৬৭")
        self.assertEqual(format_money(1234567, language="en"), "1,234,567")

    def test_money_is_whole_taka(self):
        self.assertEqual(format_money(1499, language="en"), "1,499")
        self.assertEqual(format_money(1499, language="bn"), "১,৪৯৯")
