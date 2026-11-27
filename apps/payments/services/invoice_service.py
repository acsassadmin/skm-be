from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from payments.models import Invoice, InvoiceConfiguration


from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _amount_in_words(amount: Decimal) -> str:
    """Converts a Decimal INR amount into Indian currency words (e.g., Rupees One Thousand Only)."""
    ones = [
        "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
        "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
        "Seventeen", "Eighteen", "Nineteen",
    ]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eightieth", "Ninety"]
    tens[8] = "Eighty"

    def two_digits(n):
        if n < 20:
            return ones[n]
        return f"{tens[n // 10]} {ones[n % 10]}".strip()

    def three_digits(n):
        if n < 100:
            return two_digits(n)
        rem = n % 100
        return f"{ones[n // 100]} Hundred {two_digits(rem)}".strip()

    rupees = int(amount)
    paise = int(round((amount - rupees) * 100))

    if rupees == 0:
        words = "Zero"
    else:
        parts = []
        crore = rupees // 10000000
        rupees %= 10000000
        lakh = rupees // 100000
        rupees %= 100000
        thousand = rupees // 1000
        rest = rupees % 1000

        if crore:
            parts.append(f"{three_digits(crore)} Crore")
        if lakh:
            parts.append(f"{two_digits(lakh)} Lakh")
        if thousand:
            parts.append(f"{two_digits(thousand)} Thousand")
        if rest:
            parts.append(three_digits(rest))
        words = " ".join(parts)

    result = f"INR {words} Rupees"
    if paise:
        result += f" and {two_digits(paise)} Paise"
    return f"{result} Only"


class InvoiceService:
    @staticmethod
    def get_config():
        config, _ = InvoiceConfiguration.objects.get_or_create(id=1)
        return config

    @classmethod
    def create_or_get_invoice(
        cls,
        order,
        transaction,
        is_gst: bool,
        buyer_gstin: str = "",
        buyer_company_name: str = "",
    ) -> Invoice:
        existing = Invoice.objects.filter(order=order).first()
        if existing:
            return existing

        if not transaction:
            raise ValidationError("A verified payment transaction is required to generate an invoice.")

        with db_transaction.atomic():
            config = InvoiceConfiguration.objects.select_for_update().get_or_create(id=1)[0]
            existing = Invoice.objects.filter(order=order).first()
            if existing:
                return existing

            use_gst = bool(is_gst)

            if use_gst:
                invoice_number = f"{config.gst_invoice_prefix}{config.gst_next_sequence:04d}"
                config.gst_next_sequence += 1
                tax_data = cls._calculate_gst_split(order, config.company_state)
            else:
                invoice_number = f"{config.non_gst_invoice_prefix}{config.non_gst_next_sequence:04d}"
                config.non_gst_next_sequence += 1
                tax_data = {
                    "subtotal": order.total_amount,
                    "cgst": Decimal("0.00"),
                    "sgst": Decimal("0.00"),
                    "igst": Decimal("0.00"),
                    "total_tax": Decimal("0.00"),
                }

            config.save()

            invoice = Invoice.objects.create(
                order=order,
                transaction=transaction,
                invoice_number=invoice_number,
                is_gst=use_gst,
                buyer_gstin=buyer_gstin if use_gst else "",
                buyer_company_name=buyer_company_name if use_gst else "",
                subtotal_amount=tax_data["subtotal"],
                cgst_amount=tax_data["cgst"],
                sgst_amount=tax_data["sgst"],
                igst_amount=tax_data["igst"],
                total_tax_amount=tax_data["total_tax"],
                grand_total=order.total_amount,
                generated_at=timezone.now(),
            )
            return invoice

    @staticmethod
    def _calculate_gst_split(order, seller_state: str) -> dict:
        is_intrastate = order.shipping_state.strip().lower() == seller_state.strip().lower()
        subtotal = Decimal("0.00")
        total_tax = Decimal("0.00")
        total_cgst = Decimal("0.00")
        total_sgst = Decimal("0.00")
        total_igst = Decimal("0.00")

        for item in order.items.all():
            paid_line = item.line_total or (item.unit_price * item.quantity)
            rate = item.gst_rate or Decimal("0.00")

            if rate > 0:
                divisor = Decimal("1") + (rate / Decimal("100"))
                base = (paid_line / divisor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                tax = paid_line - base
            else:
                base = paid_line
                tax = Decimal("0.00")

            subtotal += base
            total_tax += tax

            if is_intrastate:
                half = (tax / Decimal("2")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                total_cgst += half
                total_sgst += (tax - half)
            else:
                total_igst += tax

        return {
            "subtotal": subtotal,
            "cgst": total_cgst,
            "sgst": total_sgst,
            "igst": total_igst,
            "total_tax": total_tax,
        }

    @classmethod
    def build_invoice_pdf_buffer(cls, invoice: Invoice) -> BytesIO:
        config = cls.get_config()
        order = invoice.order
        is_gst = invoice.is_gst
        is_intrastate = order.shipping_state.strip().lower() == config.company_state.strip().lower()

        buffer = BytesIO()
        # A4 width = 595.27 pt -> with 32pt left/right margins, usable width = 531 pt
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=32,
            leftMargin=32,
            topMargin=32,
            bottomMargin=32,
        )

        # Color Palette (Slate Navy & Soft Gray)
        primary_color = colors.HexColor("#0F172A")
        accent_color = colors.HexColor("#1E3A8A")
        light_bg = colors.HexColor("#F8FAFC")
        zebra_bg = colors.HexColor("#F1F5F9")
        border_color = colors.HexColor("#CBD5E1")
        muted_text = colors.HexColor("#475569")

        base_styles = getSampleStyleSheet()
        style_company = ParagraphStyle(
            "CompanyTitle", parent=base_styles["Normal"], fontName="Helvetica-Bold",
            fontSize=15, leading=19, textColor=primary_color
        )
        style_doc_badge = ParagraphStyle(
            "DocBadge", parent=base_styles["Normal"], fontName="Helvetica-Bold",
            fontSize=14, leading=18, textColor=accent_color, alignment=TA_RIGHT
        )
        style_normal = ParagraphStyle(
            "BodyText", parent=base_styles["Normal"], fontName="Helvetica",
            fontSize=8.5, leading=12.5, textColor=primary_color
        )
        style_muted = ParagraphStyle(
            "MutedText", parent=base_styles["Normal"], fontName="Helvetica",
            fontSize=8, leading=11.5, textColor=muted_text
        )
        style_section_hdr = ParagraphStyle(
            "SectionHdr", parent=base_styles["Normal"], fontName="Helvetica-Bold",
            fontSize=8, leading=11, textColor=accent_color
        )
        style_right = ParagraphStyle(
            "RightText", parent=style_normal, alignment=TA_RIGHT
        )
        style_grand_total = ParagraphStyle(
            "GrandTotal", parent=base_styles["Normal"], fontName="Helvetica-Bold",
            fontSize=10, leading=14, textColor=colors.white, alignment=TA_RIGHT
        )
        style_grand_label = ParagraphStyle(
            "GrandLabel", parent=base_styles["Normal"], fontName="Helvetica-Bold",
            fontSize=10, leading=14, textColor=colors.white, alignment=TA_LEFT
        )

        elements = []

        # ---------------------------------------------------------
        # 1. TOP HEADER BANNER (Company Info Left | Document Title Right)
        # ---------------------------------------------------------
        doc_title = "TAX INVOICE" if is_gst else config.non_gst_title.upper()
        sub_badge = "Original for Recipient" if is_gst else "Payment Receipt & Invoice"

        seller_details = (
            f"{config.company_address.replace(chr(10), '<br/>')}<br/>"
            f"State: {config.company_state} (Code: {config.company_state_code})"
        )
        if is_gst and config.gstin:
            seller_details += f"<br/><b>GSTIN:</b> {config.gstin}"

        header_table = Table(
            [
                [
                    Paragraph(config.company_name, style_company),
                    Paragraph(f"{doc_title}<br/><font size='8' color='#64748B'>{sub_badge}</font>", style_doc_badge),
                ],
                [
                    Paragraph(seller_details, style_muted),
                    "",
                ],
            ],
            colWidths=[331, 200],
        )
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 6))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=accent_color, spaceAfter=10))

        # ---------------------------------------------------------
        # 2. BILLING & INVOICE METADATA CARD (2-Column Boxed Grid)
        # ---------------------------------------------------------
        buyer_name = invoice.buyer_company_name or order.shipping_full_name
        buyer_lines = [
            f"<b>{buyer_name}</b>",
            f"{order.shipping_address}",
            f"{order.shipping_city}, {order.shipping_state} - {order.shipping_pincode}",
            f"Phone: {order.shipping_phone}",
        ]
        if is_gst and invoice.buyer_gstin:
            buyer_lines.append(f"<b>GSTIN:</b> {invoice.buyer_gstin}")

        meta_rows = [
            [Paragraph("<b>Invoice No</b>", style_normal), Paragraph(f": {invoice.invoice_number}", style_normal)],
            [Paragraph("<b>Invoice Date</b>", style_normal), Paragraph(f": {invoice.generated_at.strftime('%d %b %Y')}", style_normal)],
            [Paragraph("<b>Order No</b>", style_normal), Paragraph(f": {order.order_number}", style_normal)],
            [Paragraph("<b>Transaction ID</b>", style_normal), Paragraph(f": {invoice.transaction.transaction_number}", style_normal)],
            [Paragraph("<b>Payment Status</b>", style_normal), Paragraph(": PAID", style_normal)],
        ]
        if is_gst:
            meta_rows.append(
                [Paragraph("<b>Place of Supply</b>", style_normal), Paragraph(f": {order.shipping_state}", style_normal)]
            )

        # Right column: Structured key-value table for crisp straight alignment
        meta_rows = [
            [Paragraph("<b>Invoice No</b>", style_normal), Paragraph(f": {invoice.invoice_number}", style_normal)],
            [Paragraph("<b>Invoice Date</b>", style_normal), Paragraph(f": {invoice.generated_at.strftime('%d %b %Y')}", style_normal)],
            [Paragraph("<b>Order No</b>", style_normal), Paragraph(f": {order.order_number}", style_normal)],
            [Paragraph("<b>Transaction ID</b>", style_normal), Paragraph(f": {invoice.transaction.transaction_number}", style_normal)],
            [Paragraph("<b>Payment Status</b>", style_normal), Paragraph(": PAID", style_normal)],
        ]
        if is_gst:
            meta_rows.append(
                [Paragraph("<b>Place of Supply</b>", style_normal), Paragraph(f": {order.shipping_state}", style_normal)]
            )

        # Total width = 240 pt (fits cleanly inside the 256 pt right cell with 8pt left/right padding)
        meta_subtable = Table(meta_rows, colWidths=(82, 158))
        meta_subtable.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))

        info_table = Table(
            [
                [
                    Paragraph("BILLED & SHIPPED TO", style_section_hdr),
                    Paragraph("INVOICE DETAILS", style_section_hdr),
                ],
                [
                    Paragraph("<br/>".join(buyer_lines), style_normal),
                    meta_subtable,
                ],
            ],
            colWidths=(275, 256),
        )
        info_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), light_bg),
            ("BOX", (0, 0), (-1, -1), 0.75, border_color),
            ("LINEAFTER", (0, 0), (0, -1), 0.75, border_color),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 14))

        # ---------------------------------------------------------
        # 3. LINE ITEMS TABLE (Full 531pt Width + Zebra Striping)
        # ---------------------------------------------------------
        if is_gst:
            if is_intrastate:
                headers = ["#", "Item Description", "HSN", "Qty", "Taxable", "CGST", "SGST", "Total"]
                col_widths = [24, 172, 50, 32, 65, 62, 62, 64]
            else:
                headers = ["#", "Item Description", "HSN", "Qty", "Taxable", "IGST", "Total"]
                col_widths = [24, 204, 55, 35, 70, 75, 68]
        else:
            headers = ["#", "Item Description", "SKU", "Qty", "Unit Price", "Total"]
            col_widths = [26, 235, 80, 40, 75, 75]

        rows = [headers]
        for idx, item in enumerate(order.items.all(), start=1):
            paid_line = item.line_total or (item.unit_price * item.quantity)
            item_desc = Paragraph(f"<b>{item.product_name}</b>", style_normal)

            if is_gst:
                rate = item.gst_rate or Decimal("0.00")
                if rate > 0:
                    divisor = Decimal("1") + (rate / Decimal("100"))
                    base = (paid_line / divisor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    tax = paid_line - base
                else:
                    base = paid_line
                    tax = Decimal("0.00")

                if is_intrastate:
                    half_r = rate / Decimal("2")
                    cgst = (tax / Decimal("2")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    sgst = tax - cgst
                    rows.append([
                        str(idx), item_desc, item.hsn_code or "-", str(item.quantity),
                        f"{base:,.2f}", f"{cgst:,.2f}\n({half_r:g}%)", f"{sgst:,.2f}\n({half_r:g}%)", f"{paid_line:,.2f}"
                    ])
                else:
                    rows.append([
                        str(idx), item_desc, item.hsn_code or "-", str(item.quantity),
                        f"{base:,.2f}", f"{tax:,.2f}\n({rate:g}%)", f"{paid_line:,.2f}"
                    ])
            else:
                rows.append([
                    str(idx), item_desc, item.product_sku,
                    str(item.quantity), f"{item.unit_price:,.2f}", f"{paid_line:,.2f}"
                ])

        items_table = Table(rows, colWidths=col_widths, repeatRows=1)
        table_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), primary_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (2, 0), (3, -1), "CENTER"),
            ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("BOX", (0, 0), (-1, -1), 0.75, border_color),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, border_color),
        ]
        # Alternating row shading
        for row_idx in range(1, len(rows)):
            if row_idx % 2 == 0:
                table_cmds.append(("BACKGROUND", (0, row_idx), (-1, row_idx), zebra_bg))

        words_html = (
            f"<font size='7.5' color='#475569'><b>TOTAL AMOUNT IN WORDS</b></font><br/>"
            f"<b>{_amount_in_words(invoice.grand_total)}</b>"
        )
        if is_gst:
            words_html += "<br/><br/><font size='7.5' color='#64748B'>Tax is payable on Reverse Charge: No</font>"

        summary_rows = []
        if is_gst:
            summary_rows.append([
                Paragraph("Taxable Value", style_normal),
                Paragraph(f"Rs. {invoice.subtotal_amount:,.2f}", style_right),
            ])
            if is_intrastate:
                summary_rows.append([
                    Paragraph("CGST", style_normal),
                    Paragraph(f"Rs. {invoice.cgst_amount:,.2f}", style_right),
                ])
                summary_rows.append([
                    Paragraph("SGST", style_normal),
                    Paragraph(f"Rs. {invoice.sgst_amount:,.2f}", style_right),
                ])
            else:
                summary_rows.append([
                    Paragraph("IGST", style_normal),
                    Paragraph(f"Rs. {invoice.igst_amount:,.2f}", style_right),
                ])
            summary_rows.append([
                Paragraph("<b>Total Tax</b>", style_normal),
                Paragraph(f"<b>Rs. {invoice.total_tax_amount:,.2f}</b>", style_right),
            ])
        else:
            summary_rows.append([
                Paragraph("Subtotal", style_normal),
                Paragraph(f"Rs. {invoice.subtotal_amount:,.2f}", style_right),
            ])

        if order.discount_amount > 0:
            summary_rows.append([
                Paragraph("Discount", style_normal),
                Paragraph(f"- Rs. {order.discount_amount:,.2f}", style_right),
            ])
        if order.shipping_amount > 0:
            summary_rows.append([
                Paragraph("Shipping", style_normal),
                Paragraph(f"Rs. {order.shipping_amount:,.2f}", style_right),
            ])

        summary_rows.append([
            Paragraph("GRAND TOTAL", style_grand_label),
            Paragraph(f"Rs. {invoice.grand_total:,.2f}", style_grand_total),
        ])

        totals_subtable = Table(summary_rows, colWidths=(120, 111))
        totals_subtable.setStyle(TableStyle([
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, border_color),
            ("BACKGROUND", (0, -1), (-1, -1), accent_color),
            ("BOX", (0, 0), (-1, -1), 0.75, border_color),
        ]))

        bottom_grid = Table(
            [[Paragraph(words_html, style_normal), totals_subtable]],
            colWidths=(300, 231),
        )
        bottom_grid.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        elements.append(bottom_grid)
        elements.append(Spacer(1, 20))

        # ---------------------------------------------------------
        # 5. TERMS & AUTHORIZED SIGNATORY FOOTER
        # ---------------------------------------------------------
        terms_html = ""
        if config.terms_and_conditions:
            terms_html = (
                f"<b>Terms & Conditions:</b><br/>"
                f"{config.terms_and_conditions.replace(chr(10), '<br/>')}"
            )

        sign_html = (
            f"For <b>{config.company_name}</b><br/><br/><br/>"
            f"_________________________<br/>"
            f"Authorized Signatory"
        )

        footer_table = Table(
            [[Paragraph(terms_html, style_muted), Paragraph(sign_html, style_right)]],
            colWidths=(331, 200),
        )
        footer_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LINEABOVE", (0, 0), (-1, 0), 0.75, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        elements.append(footer_table)


        doc.build(elements)
        buffer.seek(0)
        return buffer