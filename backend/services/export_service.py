"""
Apna Kirana OS — Export & Reports Engine (CSV & PDF)
Provides deterministic, production-grade report generation for:
1. Sales Summary Report
2. Complete Sales History
3. Individual Invoice / Bill Export
4. Current Inventory Report
5. Low-Stock Report
6. Inventory Valuation Report
7. Customer Udhaar Ledger
8. Outstanding Udhaar Report
9. Supplier Purchase History (Honest prerequisite blocker notice)
10. AI Demand Forecast & Restocking Recommendations

Adheres strictly to tenant-isolated database access, Excel formula injection protection,
clean ReportLab typography, and transparent accounting standards.
"""

import io
import csv
import re
import os
import datetime
from typing import List, Dict, Any, Optional, Tuple

from fastapi import HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.config import settings
from backend.models import (
    Product,
    Customer,
    FamilyMember,
    Bill,
    BillItem,
    UdhaarTransaction,
    DailySalesSummary,
    ShopProfile
)
from backend.services.forecasting import get_all_product_forecasts

# ReportLab Imports
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
    HRFlowable
)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ==============================================================================
# FONT REGISTRATION & TEXT SANITIZATION
# ==============================================================================

FONT_FAMILY = "Helvetica"
FONT_FAMILY_BOLD = "Helvetica-Bold"
HAS_TTF = False

# Attempt to register Arial if running on Windows (or DejaVuSans on Linux) for native ₹ glyph support
for reg in [
    ("CustomAppFont", "CustomAppFont-Bold", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("CustomAppFont", "CustomAppFont-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
]:
    regular_name, bold_name, reg_path, bold_path = reg
    if os.path.exists(reg_path):
        try:
            pdfmetrics.registerFont(TTFont(regular_name, reg_path))
            if os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont(bold_name, bold_path))
            else:
                pdfmetrics.registerFont(TTFont(bold_name, reg_path))
            from reportlab.pdfbase.pdfmetrics import registerFontFamily
            registerFontFamily("CustomAppFont", normal=regular_name, bold=bold_name, italic=regular_name, boldItalic=bold_name)
            FONT_FAMILY = regular_name
            FONT_FAMILY_BOLD = bold_name
            HAS_TTF = True
            break
        except Exception:
            pass


def clean_pdf_text(text: Any) -> str:
    """Sanitizes text for ReportLab Paragraph rendering."""
    if text is None:
        return ""
    s = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # If TrueType font is not registered, replace ₹ with Rs. to prevent missing glyph errors
    if not HAS_TTF:
        s = s.replace("₹", "Rs. ")
    return s


def format_inr(amount: float) -> str:
    """Formats monetary amounts with correct Indian Rupee glyph or fallback."""
    sym = "₹" if HAS_TTF else "Rs. "
    return f"{sym}{amount:,.2f}"


def format_inr_short(amount: float) -> str:
    """Formats compact monetary amounts with Rupee glyph or fallback."""
    sym = "₹" if HAS_TTF else "Rs. "
    return f"{sym}{amount:,.0f}"


# ==============================================================================
# BRAND STYLING SYSTEM & COLOR PALETTE
# ==============================================================================

CLR_BRAND_DARK = colors.HexColor("#064e3b")      # Deep forest green / dark teal (headers/titles)
CLR_BRAND_PRIMARY = colors.HexColor("#047857")   # Emerald brand accent
CLR_BRAND_TEAL = colors.HexColor("#0f766e")      # Dark teal
CLR_TEXT_MAIN = colors.HexColor("#0f172a")       # Near-black heading
CLR_TEXT_BODY = colors.HexColor("#1e293b")       # Dark charcoal readable body text
CLR_TEXT_MUTED = colors.HexColor("#64748b")      # Subordinate secondary metadata
CLR_BORDER = colors.HexColor("#cbd5e1")          # Subtle card/line border
CLR_CARD_BG = colors.HexColor("#f8fafc")         # Clean soft card background
CLR_GRID = colors.HexColor("#e2e8f0")            # Clean table grid
CLR_ROW_ALT = colors.HexColor("#f8fafc")         # Alternating row background
CLR_TOTAL_BG = colors.HexColor("#ecfdf5")        # Light emerald highlight for TOTAL row
CLR_TOTAL_LINE = colors.HexColor("#059669")      # Border accent for TOTAL row


def sanitize_csv_cell(value: Any) -> str:
    """
    Guards against CSV Formula Injection (CWE-1236).
    If a string cell starts with =, +, -, @, \\t, or \\r, prepend a single quote.
    """
    if value is None:
        return ""
    val_str = str(value)
    if val_str and val_str[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{val_str}"
    return val_str


# ==============================================================================
# NUMBERED CANVAS (PAGINATION & RUNNING FOOTER)
# ==============================================================================

class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas that writes dynamic 'Page X of Y' footers and confidential notice."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        self.setFont(FONT_FAMILY, 8)
        self.setFillColor(CLR_TEXT_MUTED)

        # Footer divider line
        self.setStrokeColor(CLR_GRID)
        self.setLineWidth(0.75)
        self.line(36, 28, self._pagesize[0] - 36, 28)

        # Footer content
        self.drawString(36, 16, "Apna Kirana OS — Official Store Business Report (Confidential)")
        self.drawRightString(self._pagesize[0] - 36, 16, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


# ==============================================================================
# SHOP PROFILE & METADATA HELPERS
# ==============================================================================

def get_active_shop_info(db: Session) -> Dict[str, str]:
    """Retrieves authoritative active shop metadata from tenant database."""
    profile = db.query(ShopProfile).first()
    if profile:
        return {
            "name": profile.shop_name.strip() or settings.SHOP_NAME,
            "address": profile.shop_address.strip() or settings.SHOP_ADDRESS,
            "phone": profile.shop_phone.strip() or settings.SHOP_PHONE,
            "email": profile.shop_email or settings.SHOP_EMAIL,
            "gstin": profile.gstin.strip() if profile.gstin else "",
            "currency": profile.currency or "INR (Rs.)",
            "footer": profile.invoice_footer or "Thank you for shopping with us!"
        }
    return {
        "name": settings.SHOP_NAME,
        "address": settings.SHOP_ADDRESS,
        "phone": settings.SHOP_PHONE,
        "email": settings.SHOP_EMAIL,
        "gstin": "",
        "currency": "INR (Rs.)",
        "footer": "Thank you for shopping with us!"
    }


def parse_date_range(
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None,
    default_days: int = 30
) -> Tuple[datetime.date, datetime.date]:
    """
    Parses and validates ISO date range strings (YYYY-MM-DD).
    Defaults to the past `default_days` if dates are omitted.
    """
    today = datetime.datetime.utcnow().date()
    if not end_date_str:
        end_date = today
    else:
        try:
            end_date = datetime.datetime.strptime(end_date_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid end_date '{end_date_str}'. Expected YYYY-MM-DD."
            )

    if not start_date_str:
        start_date = end_date - datetime.timedelta(days=default_days)
    else:
        try:
            start_date = datetime.datetime.strptime(start_date_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid start_date '{start_date_str}'. Expected YYYY-MM-DD."
            )

    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Start date ({start_date}) cannot be later than end date ({end_date})."
        )

    return start_date, end_date


# ==============================================================================
# RESPONSE BUILDERS (CSV & PDF)
# ==============================================================================

def build_csv_response(filename: str, headers: List[str], rows: List[List[Any]]) -> Response:
    """Builds RFC 4180-compliant UTF-8 CSV download response with formula injection protection."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Write header
    writer.writerow(headers)

    # Write sanitized rows
    for r in rows:
        writer.writerow([sanitize_csv_cell(cell) for cell in r])

    # Prepend UTF-8 BOM so Excel on Windows properly handles Indian & Hindi characters
    csv_bytes = output.getvalue().encode("utf-8-sig")

    headers_dict = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "text/csv; charset=utf-8",
        "Cache-Control": "no-cache, no-store, must-revalidate"
    }
    return Response(content=csv_bytes, headers=headers_dict, media_type="text/csv")


def build_pdf_document(
    filename: str,
    report_title: str,
    report_subtitle: str,
    shop_info: Dict[str, str],
    story_elements: List[Any],
    landscape_mode: bool = False
) -> Response:
    """Builds beautiful, printable PDF document using ReportLab Platypus and NumberedCanvas."""
    buf = io.BytesIO()
    page_size = landscape(letter) if landscape_mode else letter
    margin = 36  # 0.5 inch margins

    doc = SimpleDocTemplate(
        buf,
        pagesize=page_size,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=42
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Normal"],
        fontName=FONT_FAMILY_BOLD,
        fontSize=17,
        leading=21,
        textColor=CLR_BRAND_DARK
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName=FONT_FAMILY,
        fontSize=8.5,
        leading=12,
        textColor=CLR_TEXT_MUTED
    )
    shop_header_style = ParagraphStyle(
        "ShopHeader",
        parent=styles["Normal"],
        fontName=FONT_FAMILY_BOLD,
        fontSize=12,
        leading=15,
        alignment=2,  # Right-aligned
        textColor=CLR_BRAND_DARK
    )
    shop_meta_style = ParagraphStyle(
        "ShopMeta",
        parent=styles["Normal"],
        fontName=FONT_FAMILY,
        fontSize=8,
        leading=11,
        alignment=2,  # Right-aligned
        textColor=CLR_TEXT_BODY
    )

    # Header Layout
    shop_lines = [f"<b>{clean_pdf_text(shop_info['name'])}</b>"]
    if shop_info.get("address"):
        shop_lines.append(clean_pdf_text(shop_info["address"]))
    if shop_info.get("phone"):
        shop_lines.append(f"Phone: {clean_pdf_text(shop_info['phone'])}")
    if shop_info.get("gstin"):
        shop_lines.append(f"GSTIN: {clean_pdf_text(shop_info['gstin'])}")

    shop_html = "<br/>".join(shop_lines)

    header_table_data = [
        [
            Paragraph(f"<b>{clean_pdf_text(report_title)}</b><br/><font size=8 color='#64748b'>{clean_pdf_text(report_subtitle)}</font>", title_style),
            Paragraph(shop_html, shop_meta_style)
        ]
    ]

    available_width = page_size[0] - (margin * 2)
    header_table = Table(header_table_data, colWidths=[available_width * 0.58, available_width * 0.42])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    story = [
        header_table,
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=1.5, color=CLR_BRAND_TEAL, spaceBefore=2, spaceAfter=10),
    ]

    story.extend(story_elements)

    doc.build(story, canvasmaker=NumberedCanvas)
    pdf_bytes = buf.getvalue()

    headers_dict = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "application/pdf",
        "Cache-Control": "no-cache, no-store, must-revalidate"
    }
    return Response(content=pdf_bytes, headers=headers_dict, media_type="application/pdf")


def build_kpi_cards_table(kpis: List[Tuple[str, str, str]], total_width: float) -> Table:
    """Builds high-impact KPI summary cards with light backgrounds and distinct hierarchy."""
    col_width = total_width / len(kpis)
    styles = getSampleStyleSheet()

    card_elements = []
    for label, val, sub in kpis:
        cell_p = Paragraph(
            f"<font size=7 color='#475569'><b>{clean_pdf_text(label.upper())}</b></font><br/>"
            f"<font size=13 color='#064e3b'><b>{clean_pdf_text(val)}</b></font><br/>"
            f"<font size=6.5 color='#64748b'>{clean_pdf_text(sub)}</font>",
            styles["Normal"]
        )
        card_elements.append(cell_p)

    table = Table([card_elements], colWidths=[col_width] * len(kpis))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CLR_CARD_BG),
        ("BOX", (0, 0), (-1, -1), 0.75, CLR_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, CLR_GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


# ==============================================================================
# REPORT 1: SALES SUMMARY REPORT
# ==============================================================================

def export_sales_summary(
    db: Session,
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None,
    export_format: str = "csv"
) -> Response:
    start_date, end_date = parse_date_range(start_date_str, end_date_str)
    shop = get_active_shop_info(db)

    # Query completed bills within range
    dt_start = datetime.datetime.combine(start_date, datetime.time.min)
    dt_end = datetime.datetime.combine(end_date, datetime.time.max)

    bills = db.query(Bill).filter(
        Bill.status == "COMPLETED",
        Bill.created_at >= dt_start,
        Bill.created_at <= dt_end
    ).order_by(Bill.created_at.asc()).all()

    # Aggregate by date
    daily_stats: Dict[datetime.date, Dict[str, Any]] = {}
    total_rev = 0.0
    total_disc = 0.0
    total_units = 0.0
    cash_total = 0.0
    upi_total = 0.0
    udhaar_total = 0.0

    for b in bills:
        d = b.created_at.date()
        if d not in daily_stats:
            daily_stats[d] = {
                "invoices": 0,
                "revenue": 0.0,
                "discount": 0.0,
                "units": 0.0,
                "cash": 0.0,
                "upi": 0.0,
                "udhaar": 0.0
            }

        daily_stats[d]["invoices"] += 1
        daily_stats[d]["revenue"] += b.total_amount
        daily_stats[d]["discount"] += b.discount

        total_rev += b.total_amount
        total_disc += b.discount

        pm = (b.payment_mode or "CASH").upper()
        if pm == "CASH":
            daily_stats[d]["cash"] += b.total_amount
            cash_total += b.total_amount
        elif pm == "UPI":
            daily_stats[d]["upi"] += b.total_amount
            upi_total += b.total_amount
        elif pm == "UDHAAR":
            daily_stats[d]["udhaar"] += b.total_amount
            udhaar_total += b.total_amount

        for item in b.items:
            daily_stats[d]["units"] += item.quantity
            total_units += item.quantity

    date_str_tag = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"

    if export_format.lower() == "csv":
        headers = [
            "Date", "Completed Invoices", "Units Sold", "Discounts (Rs.)",
            "Net Revenue (Rs.)", "Cash (Rs.)", "UPI (Rs.)", "Udhaar (Rs.)"
        ]
        rows = []
        for d in sorted(daily_stats.keys()):
            st = daily_stats[d]
            rows.append([
                d.strftime("%Y-%m-%d"),
                st["invoices"],
                f"{st['units']:.2f}",
                f"{st['discount']:.2f}",
                f"{st['revenue']:.2f}",
                f"{st['cash']:.2f}",
                f"{st['upi']:.2f}",
                f"{st['udhaar']:.2f}"
            ])

        # Overall summary row
        rows.append([
            "TOTAL / PERIOD SUMMARY",
            len(bills),
            f"{total_units:.2f}",
            f"{total_disc:.2f}",
            f"{total_rev:.2f}",
            f"{cash_total:.2f}",
            f"{upi_total:.2f}",
            f"{udhaar_total:.2f}"
        ])

        return build_csv_response(f"sales_summary_{date_str_tag}.csv", headers, rows)

    # PDF Format
    subtitle = f"Period: {start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')} • Generated on {datetime.datetime.utcnow().strftime('%d %b %Y %H:%M UTC')}"
    total_w = letter[0] - 72

    curr_sym = "₹" if HAS_TTF else "Rs. "
    kpis = [
        ("Total Net Sales", format_inr(total_rev), f"{len(bills)} completed bills"),
        ("Units Sold", f"{total_units:,.1f}", "Total retail units"),
        ("Discounts Given", format_inr(total_disc), "Promotional / bill discount"),
        ("Cash / UPI / Udhaar", f"{format_inr_short(cash_total)} / {format_inr_short(upi_total)} / {format_inr_short(udhaar_total)}", f"Payment breakdown ({curr_sym.strip()})")
    ]

    styles = getSampleStyleSheet()
    header_style = ParagraphStyle("HCell", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=10, textColor=colors.white)
    cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=8, leading=10, textColor=CLR_TEXT_BODY)
    cell_bold = ParagraphStyle("CellB", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=10, textColor=CLR_TEXT_BODY)

    table_data = [
        [
            Paragraph("<b>Date</b>", header_style),
            Paragraph("<b>Invoices</b>", header_style),
            Paragraph("<b>Units Sold</b>", header_style),
            Paragraph(f"<b>Discount ({curr_sym.strip()})</b>", header_style),
            Paragraph(f"<b>Net Sales ({curr_sym.strip()})</b>", header_style),
            Paragraph(f"<b>Cash ({curr_sym.strip()})</b>", header_style),
            Paragraph(f"<b>UPI ({curr_sym.strip()})</b>", header_style),
            Paragraph(f"<b>Udhaar ({curr_sym.strip()})</b>", header_style),
        ]
    ]

    for d in sorted(daily_stats.keys()):
        st = daily_stats[d]
        table_data.append([
            Paragraph(d.strftime("%d-%m-%Y"), cell_style),
            Paragraph(str(st["invoices"]), cell_style),
            Paragraph(f"{st['units']:.1f}", cell_style),
            Paragraph(f"{st['discount']:,.2f}", cell_style),
            Paragraph(f"<b>{st['revenue']:,.2f}</b>", cell_style),
            Paragraph(f"{st['cash']:,.2f}", cell_style),
            Paragraph(f"{st['upi']:,.2f}", cell_style),
            Paragraph(f"{st['udhaar']:,.2f}", cell_style),
        ])

    if not daily_stats:
        table_data.append([
            Paragraph("No sales recorded during this period.", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style)
        ])
    else:
        # Summary row
        table_data.append([
            Paragraph("<b>TOTAL</b>", cell_bold),
            Paragraph(f"<b>{len(bills)}</b>", cell_bold),
            Paragraph(f"<b>{total_units:.1f}</b>", cell_bold),
            Paragraph(f"<b>{total_disc:,.2f}</b>", cell_bold),
            Paragraph(f"<b>{format_inr(total_rev)}</b>", cell_bold),
            Paragraph(f"<b>{cash_total:,.2f}</b>", cell_bold),
            Paragraph(f"<b>{upi_total:,.2f}</b>", cell_bold),
            Paragraph(f"<b>{udhaar_total:,.2f}</b>", cell_bold),
        ])

    col_widths = [total_w * 0.15, total_w * 0.11, total_w * 0.12, total_w * 0.12, total_w * 0.16, total_w * 0.11, total_w * 0.11, total_w * 0.12]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CLR_BRAND_DARK),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, CLR_GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2 if daily_stats else -1), [colors.white, CLR_ROW_ALT]),
        ("BACKGROUND", (0, -1), (-1, -1), CLR_TOTAL_BG),
        ("LINEABOVE", (0, -1), (-1, -1), 1.25, CLR_TOTAL_LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 1.25, CLR_TOTAL_LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))

    story = [
        build_kpi_cards_table(kpis, total_w),
        Spacer(1, 14),
        Paragraph("<b>Daily Sales Breakdown</b>", ParagraphStyle("H3", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=10, leading=13, textColor=CLR_BRAND_DARK)),
        Spacer(1, 6),
        table
    ]

    return build_pdf_document(f"sales_summary_{date_str_tag}.pdf", "Sales Summary Report", subtitle, shop, story)


# ==============================================================================
# REPORT 2: COMPLETE SALES HISTORY
# ==============================================================================

def export_sales_history(
    db: Session,
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None,
    payment_mode: Optional[str] = None,
    export_format: str = "csv"
) -> Response:
    start_date, end_date = parse_date_range(start_date_str, end_date_str)
    shop = get_active_shop_info(db)

    dt_start = datetime.datetime.combine(start_date, datetime.time.min)
    dt_end = datetime.datetime.combine(end_date, datetime.time.max)

    q = db.query(Bill).filter(
        Bill.status == "COMPLETED",
        Bill.created_at >= dt_start,
        Bill.created_at <= dt_end
    )
    if payment_mode and payment_mode.strip() and payment_mode.upper() != "ALL":
        q = q.filter(Bill.payment_mode == payment_mode.strip().upper())

    bills = q.order_by(Bill.created_at.desc()).all()
    date_str_tag = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"

    if export_format.lower() == "csv":
        headers = [
            "Invoice Number", "Date", "Time", "Customer Code", "Customer Name",
            "Product Name", "Quantity", "Unit", "Unit Price (Rs.)", "Line Total (Rs.)",
            "Invoice Subtotal (Rs.)", "Invoice Discount (Rs.)", "Invoice Total (Rs.)",
            "Payment Mode", "Payment Status"
        ]
        rows = []
        for b in bills:
            cust_code = getattr(b.customer, "customer_code", None) or (f"C-{b.customer.id:06d}" if b.customer else "WALK-IN")
            cust_name = b.customer.full_name if b.customer else "Walk-in Customer"
            d_str = b.created_at.strftime("%Y-%m-%d")
            t_str = b.created_at.strftime("%H:%M:%S")

            for item in b.items:
                prod_name = item.product.name if item.product else f"Product #{item.product_id}"
                rows.append([
                    b.bill_number,
                    d_str,
                    t_str,
                    cust_code,
                    cust_name,
                    prod_name,
                    f"{item.quantity:.2f}",
                    item.unit,
                    f"{item.unit_price:.2f}",
                    f"{item.line_total:.2f}",
                    f"{b.subtotal:.2f}",
                    f"{b.discount:.2f}",
                    f"{b.total_amount:.2f}",
                    b.payment_mode,
                    b.status
                ])

        return build_csv_response(f"complete_sales_history_{date_str_tag}.csv", headers, rows)

    # PDF Format (Landscape to accommodate tabular detail)
    total_w = landscape(letter)[0] - 72
    subtitle = f"Period: {start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')} • Total Invoices: {len(bills)}"

    styles = getSampleStyleSheet()
    curr_sym = "₹" if HAS_TTF else "Rs. "
    header_style = ParagraphStyle("HCellSH", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=7.5, leading=9, textColor=colors.white)
    cell_style = ParagraphStyle("CellSH", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=7.5, leading=9, textColor=CLR_TEXT_BODY)
    cell_bold = ParagraphStyle("CellBSH", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=7.5, leading=9, textColor=CLR_TEXT_BODY)

    table_data = [
        [
            Paragraph("<b>Invoice #</b>", header_style),
            Paragraph("<b>Date / Time</b>", header_style),
            Paragraph("<b>Customer</b>", header_style),
            Paragraph("<b>Items Count</b>", header_style),
            Paragraph("<b>Payment Mode</b>", header_style),
            Paragraph(f"<b>Discount ({curr_sym.strip()})</b>", header_style),
            Paragraph(f"<b>Total Amount ({curr_sym.strip()})</b>", header_style),
            Paragraph("<b>Status</b>", header_style),
        ]
    ]

    total_amount_sum = sum(b.total_amount for b in bills)

    for b in bills:
        cust_display = b.customer.full_name if b.customer else "Walk-in"
        table_data.append([
            Paragraph(f"<b>{clean_pdf_text(b.bill_number)}</b>", cell_style),
            Paragraph(b.created_at.strftime("%d-%m-%Y %H:%M"), cell_style),
            Paragraph(clean_pdf_text(cust_display), cell_style),
            Paragraph(f"{len(b.items)} items", cell_style),
            Paragraph(b.payment_mode, cell_style),
            Paragraph(f"{b.discount:.2f}", cell_style),
            Paragraph(f"<b>{format_inr(b.total_amount)}</b>", cell_style),
            Paragraph(b.status, cell_style),
        ])

    if not bills:
        table_data.append([
            Paragraph("No transactions recorded for this period.", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style)
        ])

    col_widths = [total_w * 0.18, total_w * 0.15, total_w * 0.20, total_w * 0.11, total_w * 0.11, total_w * 0.11, total_w * 0.14, total_w * 0.08]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CLR_BRAND_DARK),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, CLR_GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CLR_ROW_ALT]),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))

    story = [
        build_kpi_cards_table([
            ("Total Transactions", str(len(bills)), "Invoices matching period"),
            ("Gross Sales Amount", format_inr(total_amount_sum), "Total collected/billed"),
            ("Payment Filter", payment_mode.upper() if payment_mode else "ALL MODES", "Cash / UPI / Udhaar")
        ], total_w),
        Spacer(1, 12),
        table
    ]

    return build_pdf_document(f"complete_sales_history_{date_str_tag}.pdf", "Complete Sales History", subtitle, shop, story, landscape_mode=True)


# ==============================================================================
# REPORT 3: INDIVIDUAL INVOICE / BILL EXPORT
# ==============================================================================

def export_invoice(
    db: Session,
    bill_identifier: str,
    export_format: str = "pdf"
) -> Response:
    bill = None
    if bill_identifier.isdigit():
        bill = db.query(Bill).filter(Bill.id == int(bill_identifier)).first()
    if not bill:
        bill = db.query(Bill).filter(Bill.bill_number == bill_identifier.strip()).first()

    if not bill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice with identifier '{bill_identifier}' was not found."
        )

    shop = get_active_shop_info(db)

    if export_format.lower() == "csv":
        headers = [
            "Invoice Number", "Date", "Customer Name", "Customer Code",
            "Item #", "Product Name", "Quantity", "Unit", "Unit Price (Rs.)",
            "Line Total (Rs.)", "Subtotal (Rs.)", "Discount (Rs.)",
            "Total Amount (Rs.)", "Payment Mode", "Status"
        ]
        rows = []
        cust_name = bill.customer.full_name if bill.customer else "Walk-in"
        cust_code = getattr(bill.customer, "customer_code", "") if bill.customer else ""

        for idx, item in enumerate(bill.items, start=1):
            prod_name = item.product.name if item.product else f"Product #{item.product_id}"
            rows.append([
                bill.bill_number,
                bill.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                cust_name,
                cust_code,
                idx,
                prod_name,
                f"{item.quantity:.2f}",
                item.unit,
                f"{item.unit_price:.2f}",
                f"{item.line_total:.2f}",
                f"{bill.subtotal:.2f}",
                f"{bill.discount:.2f}",
                f"{bill.total_amount:.2f}",
                bill.payment_mode,
                bill.status
            ])

        return build_csv_response(f"invoice_{bill.bill_number}.csv", headers, rows)

    # PDF Invoice (Standard 8.5x11 Portrait Tax Bill Layout)
    total_w = letter[0] - 72
    styles = getSampleStyleSheet()

    meta_left = [
        f"<b>Invoice No:</b> {clean_pdf_text(bill.bill_number)}",
        f"<b>Date:</b> {bill.created_at.strftime('%d-%m-%Y %I:%M %p')}",
        f"<b>Payment Mode:</b> {bill.payment_mode}",
        f"<b>Status:</b> {bill.status}"
    ]

    meta_right = []
    if bill.customer:
        meta_right.append(f"<b>Billed To:</b> {clean_pdf_text(bill.customer.full_name)}")
        meta_right.append(f"<b>Account:</b> {clean_pdf_text(bill.customer.customer_code or f'C-{bill.customer.id:06d}')}")
        if bill.customer.phone:
            # Mask phone for privacy in invoices
            p = bill.customer.phone
            masked_p = f"{p[:2]}******{p[-2:]}" if len(p) >= 4 else p
            meta_right.append(f"<b>Contact:</b> {clean_pdf_text(masked_p)}")
        if bill.customer.address_line or bill.customer.city:
            addr = ", ".join(filter(None, [bill.customer.address_line, bill.customer.city]))
            meta_right.append(f"<b>Address:</b> {clean_pdf_text(addr)}")
    else:
        meta_right.append("<b>Customer:</b> Cash / Walk-in Counter Sale")

    curr_sym = "₹" if HAS_TTF else "Rs. "
    cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=8, leading=11, textColor=CLR_TEXT_BODY)
    cell_bold = ParagraphStyle("CellB", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=11, textColor=CLR_TEXT_BODY)
    header_style = ParagraphStyle("HCell", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=11, textColor=colors.white)
    total_style = ParagraphStyle("TCell", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=9, leading=12, textColor=CLR_BRAND_DARK)

    meta_table_data = [
        [
            Paragraph("<br/>".join(meta_left), cell_style),
            Paragraph("<br/>".join(meta_right), cell_style)
        ]
    ]
    meta_table = Table(meta_table_data, colWidths=[total_w * 0.5, total_w * 0.5])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CLR_CARD_BG),
        ("BOX", (0, 0), (-1, -1), 0.75, CLR_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))

    # Items table
    items_table_data = [
        [
            Paragraph("<b>#</b>", header_style),
            Paragraph("<b>Item Description</b>", header_style),
            Paragraph("<b>Qty</b>", header_style),
            Paragraph("<b>Unit</b>", header_style),
            Paragraph(f"<b>Rate ({curr_sym.strip()})</b>", header_style),
            Paragraph(f"<b>Amount ({curr_sym.strip()})</b>", header_style),
        ]
    ]

    for idx, item in enumerate(bill.items, start=1):
        prod_name = item.product.name if item.product else f"Item #{item.product_id}"
        items_table_data.append([
            Paragraph(str(idx), cell_style),
            Paragraph(clean_pdf_text(prod_name), cell_style),
            Paragraph(f"{item.quantity:.2f}", cell_style),
            Paragraph(item.unit, cell_style),
            Paragraph(f"{item.unit_price:.2f}", cell_style),
            Paragraph(f"<b>{item.line_total:,.2f}</b>", cell_style),
        ])

    items_table = Table(
        items_table_data,
        colWidths=[total_w * 0.08, total_w * 0.44, total_w * 0.12, total_w * 0.12, total_w * 0.12, total_w * 0.12],
        repeatRows=1
    )
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CLR_BRAND_DARK),
        ("GRID", (0, 0), (-1, -1), 0.5, CLR_GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CLR_ROW_ALT]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    # Totals box
    totals_data = [
        [Paragraph("Subtotal:", cell_style), Paragraph(format_inr(bill.subtotal), cell_style)],
        [Paragraph("Discount:", cell_style), Paragraph(f"- {format_inr(bill.discount)}", cell_style)],
        [Paragraph("<b>TOTAL PAYABLE:</b>", total_style), Paragraph(f"<b>{format_inr(bill.total_amount)}</b>", total_style)],
    ]
    totals_table = Table(totals_data, colWidths=[total_w * 0.25, total_w * 0.25])
    totals_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, 2), (-1, 2), 1.25, CLR_BRAND_DARK),
    ]))

    align_wrapper = Table([[Paragraph("", cell_style), totals_table]], colWidths=[total_w * 0.5, total_w * 0.5])
    align_wrapper.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    footer_p = Paragraph(
        f"<font size=8 color='#64748b'><i>{clean_pdf_text(shop.get('footer', 'Thank you!'))}</i></font>",
        ParagraphStyle("Foot", parent=styles["Normal"], alignment=1)
    )

    story = [
        meta_table,
        Spacer(1, 12),
        items_table,
        Spacer(1, 10),
        align_wrapper,
        Spacer(1, 20),
        footer_p
    ]

    return build_pdf_document(f"invoice_{bill.bill_number}.pdf", "RETAIL TAX INVOICE", f"Bill #{bill.bill_number}", shop, story)


# ==============================================================================
# REPORT 4: CURRENT INVENTORY REPORT
# ==============================================================================

def export_inventory(
    db: Session,
    category: Optional[str] = None,
    status_filter: Optional[str] = None,
    export_format: str = "csv"
) -> Response:
    shop = get_active_shop_info(db)

    q = db.query(Product)
    if category and category.strip() and category.upper() != "ALL":
        q = q.filter(Product.category == category.strip())

    if status_filter and status_filter.strip().lower() == "active":
        q = q.filter(Product.is_active == True)  # noqa: E712
    elif status_filter and status_filter.strip().lower() == "archived":
        q = q.filter(Product.is_active == False)  # noqa: E712

    products = q.order_by(Product.category.asc(), Product.name.asc()).all()
    timestamp_str = datetime.datetime.utcnow().strftime("%Y%m%d")

    if export_format.lower() == "csv":
        headers = [
            "Product ID", "Product Name", "Hindi Name", "Category", "Unit",
            "Stock Quantity", "Selling Price (Rs.)", "Min Stock Threshold", "Stock Status", "Is Active"
        ]
        rows = []
        for p in products:
            status_label = "In Stock"
            if p.stock_quantity <= 0:
                status_label = "Out of Stock"
            elif p.stock_quantity <= p.min_stock_threshold:
                status_label = "Low Stock"

            rows.append([
                f"P-{p.id:04d}",
                p.name,
                p.hindi_name or "",
                p.category,
                p.unit,
                f"{p.stock_quantity:.2f}",
                f"{p.unit_price:.2f}",
                f"{p.min_stock_threshold:.2f}",
                status_label,
                "YES" if p.is_active else "NO"
            ])

        return build_csv_response(f"current_inventory_{timestamp_str}.csv", headers, rows)

    # PDF Format
    total_w = letter[0] - 72
    subtitle = f"Category: {category or 'All Categories'} • Active Catalog Items: {len(products)} • Snapshot Date: {datetime.datetime.utcnow().strftime('%d-%m-%Y')}"

    styles = getSampleStyleSheet()
    curr_sym = "₹" if HAS_TTF else "Rs. "
    header_style = ParagraphStyle("HCellInv", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=10, textColor=colors.white)
    cell_style = ParagraphStyle("CellInv", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=8, leading=10, textColor=CLR_TEXT_BODY)
    cell_bold = ParagraphStyle("CellBInv", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=10, textColor=CLR_TEXT_BODY)

    table_data = [
        [
            Paragraph("<b>ID</b>", header_style),
            Paragraph("<b>Product Name</b>", header_style),
            Paragraph("<b>Category</b>", header_style),
            Paragraph("<b>Stock</b>", header_style),
            Paragraph(f"<b>Price ({curr_sym.strip()})</b>", header_style),
            Paragraph("<b>Min Limit</b>", header_style),
            Paragraph("<b>Status</b>", header_style),
        ]
    ]

    total_stock_count = sum(p.stock_quantity for p in products)

    for p in products:
        status_color = "#10b981"
        status_label = "In Stock"
        if p.stock_quantity <= 0:
            status_color = "#ef4444"
            status_label = "Out of Stock"
        elif p.stock_quantity <= p.min_stock_threshold:
            status_color = "#f59e0b"
            status_label = "Low Stock"

        name_display = p.name
        if p.hindi_name:
            name_display += f" ({p.hindi_name})"

        table_data.append([
            Paragraph(f"P-{p.id:04d}", cell_style),
            Paragraph(clean_pdf_text(name_display), cell_style),
            Paragraph(clean_pdf_text(p.category), cell_style),
            Paragraph(f"<b>{p.stock_quantity:.1f}</b> {p.unit}", cell_style),
            Paragraph(format_inr(p.unit_price), cell_style),
            Paragraph(f"{p.min_stock_threshold:.1f}", cell_style),
            Paragraph(f"<font color='{status_color}'><b>{status_label}</b></font>", cell_style),
        ])

    col_widths = [total_w * 0.10, total_w * 0.32, total_w * 0.18, total_w * 0.13, total_w * 0.11, total_w * 0.08, total_w * 0.08]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CLR_BRAND_DARK),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, CLR_GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CLR_ROW_ALT]),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))

    story = [
        build_kpi_cards_table([
            ("Catalog Items", str(len(products)), "Products in view"),
            ("Total Stock Count", f"{total_stock_count:,.1f}", "Aggregate inventory units"),
            ("Inventory Health", "100% Real-Time", "Latest database state")
        ], total_w),
        Spacer(1, 12),
        table
    ]

    return build_pdf_document(f"current_inventory_{timestamp_str}.pdf", "Current Inventory Report", subtitle, shop, story)


# ==============================================================================
# REPORT 5: LOW-STOCK REPORT
# ==============================================================================

def export_low_stock(
    db: Session,
    category: Optional[str] = None,
    export_format: str = "csv"
) -> Response:
    shop = get_active_shop_info(db)

    q = db.query(Product).filter(
        Product.stock_quantity <= Product.min_stock_threshold,
        Product.is_active == True  # noqa: E712
    )
    if category and category.strip() and category.upper() != "ALL":
        q = q.filter(Product.category == category.strip())

    items = q.order_by(Product.stock_quantity.asc()).all()
    timestamp_str = datetime.datetime.utcnow().strftime("%Y%m%d")

    if export_format.lower() == "csv":
        headers = [
            "Product ID", "Product Name", "Category", "Current Stock", "Unit",
            "Min Threshold", "Deficit to Threshold", "Suggested Replenishment Qty", "Status"
        ]
        rows = []
        for p in items:
            deficit = max(0.0, p.min_stock_threshold - p.stock_quantity)
            suggested_reorder = deficit + round(p.min_stock_threshold * 0.5, 1)  # Buffer rule
            status_text = "OUT OF STOCK" if p.stock_quantity <= 0 else "LOW STOCK"

            rows.append([
                f"P-{p.id:04d}",
                p.name,
                p.category,
                f"{p.stock_quantity:.2f}",
                p.unit,
                f"{p.min_stock_threshold:.2f}",
                f"{deficit:.2f}",
                f"{suggested_reorder:.2f}",
                status_text
            ])

        return build_csv_response(f"low_stock_report_{timestamp_str}.csv", headers, rows)

    # PDF Format
    total_w = letter[0] - 72
    out_of_stock_count = sum(1 for p in items if p.stock_quantity <= 0)
    subtitle = f"Items Requiring Replenishment: {len(items)} (Stockouts: {out_of_stock_count}) • Generated {datetime.datetime.utcnow().strftime('%d-%m-%Y')}"

    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=8, leading=10)
    cell_bold = ParagraphStyle("CellB", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=10)

    table_data = [
        [
            Paragraph("<b>ID</b>", cell_bold),
            Paragraph("<b>Product Name</b>", cell_bold),
            Paragraph("<b>Category</b>", cell_bold),
            Paragraph("<b>Current Stock</b>", cell_bold),
            Paragraph("<b>Min Limit</b>", cell_bold),
            Paragraph("<b>Deficit</b>", cell_bold),
            Paragraph("<b>Suggested Order</b>", cell_bold),
            Paragraph("<b>Urgency</b>", cell_bold),
        ]
    ]

    for p in items:
        deficit = max(0.0, p.min_stock_threshold - p.stock_quantity)
        suggested = deficit + round(p.min_stock_threshold * 0.5, 1)
        is_zero = p.stock_quantity <= 0

        urgency_html = "<font color='#ef4444'><b>CRITICAL</b></font>" if is_zero else "<font color='#f59e0b'><b>REORDER</b></font>"

        table_data.append([
            Paragraph(f"P-{p.id:04d}", cell_style),
            Paragraph(clean_pdf_text(p.name), cell_style),
            Paragraph(clean_pdf_text(p.category), cell_style),
            Paragraph(f"<b>{p.stock_quantity:.1f}</b> {p.unit}", cell_style),
            Paragraph(f"{p.min_stock_threshold:.1f}", cell_style),
            Paragraph(f"{deficit:.1f}", cell_style),
            Paragraph(f"<b>{suggested:.1f} {p.unit}</b>", cell_style),
            Paragraph(urgency_html, cell_style),
        ])

    if not items:
        table_data.append([
            Paragraph("All inventory items currently exceed their configured minimum thresholds. No low-stock alerts.", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style)
        ])

    col_widths = [total_w * 0.09, total_w * 0.31, total_w * 0.16, total_w * 0.12, total_w * 0.08, total_w * 0.08, total_w * 0.08, total_w * 0.08]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#991b1b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fff1f2") if items else colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    story = [
        build_kpi_cards_table([
            ("Low-Stock Alerts", str(len(items)), "Items at or below threshold"),
            ("Immediate Stockouts", str(out_of_stock_count), "Zero or negative stock"),
            ("Restock Priority", "High" if out_of_stock_count > 0 else "Normal", "Replenishment urgency")
        ], total_w),
        Spacer(1, 12),
        table
    ]

    return build_pdf_document(f"low_stock_report_{timestamp_str}.pdf", "Low-Stock Replenishment Report", subtitle, shop, story)


# ==============================================================================
# REPORT 6: INVENTORY VALUATION REPORT
# ==============================================================================

def export_inventory_valuation(
    db: Session,
    category: Optional[str] = None,
    export_format: str = "csv"
) -> Response:
    """
    Transparent Inventory Valuation Report.
    Adheres to accounting rule:
    - Products store Selling Price only; Unit Purchase Cost is not configured in schema.
    - Transparently presents Potential Retail Sales Value.
    - Discloses that purchase-cost valuation is unavailable.
    """
    shop = get_active_shop_info(db)

    q = db.query(Product).filter(Product.is_active == True)  # noqa: E712
    if category and category.strip() and category.upper() != "ALL":
        q = q.filter(Product.category == category.strip())

    products = q.order_by(Product.category.asc(), Product.name.asc()).all()
    timestamp_str = datetime.datetime.utcnow().strftime("%Y%m%d")

    total_units = sum(p.stock_quantity for p in products)
    total_potential_retail_val = sum(round(p.stock_quantity * p.unit_price, 2) for p in products)

    disclosure_note = (
        "ACCOUNTING DISCLOSURE: Product catalog records Unit Selling Price only. "
        "Unit Purchase Cost (Cost Price) is not configured in the database schema. "
        "Purchase-cost valuation is unavailable. Displayed valuation represents Potential Retail Sales Value."
    )

    if export_format.lower() == "csv":
        headers = [
            "Product ID", "Product Name", "Category", "Stock Quantity", "Unit",
            "Unit Selling Price (Rs.)", "Potential Retail Value (Rs.)",
            "Purchase Cost (Rs.)", "Cost-Based Valuation", "Accounting Note"
        ]
        rows = []
        for p in products:
            potential_val = round(p.stock_quantity * p.unit_price, 2)
            rows.append([
                f"P-{p.id:04d}",
                p.name,
                p.category,
                f"{p.stock_quantity:.2f}",
                p.unit,
                f"{p.unit_price:.2f}",
                f"{potential_val:.2f}",
                "N/A",
                "N/A (Cost Untracked)",
                "Valuation based on configured retail selling price"
            ])

        # Summary Row
        rows.append([
            "TOTAL POTENTIAL RETAIL VALUATION",
            f"{len(products)} products",
            "",
            f"{total_units:.2f}",
            "",
            "",
            f"{total_potential_retail_val:.2f}",
            "N/A",
            "N/A",
            disclosure_note
        ])

        return build_csv_response(f"inventory_valuation_{timestamp_str}.csv", headers, rows)

    # PDF Format
    total_w = letter[0] - 72
    subtitle = f"Valuation Basis: Potential Retail Sales Value • Generated {datetime.datetime.utcnow().strftime('%d-%m-%Y')}"

    styles = getSampleStyleSheet()
    curr_sym = "₹" if HAS_TTF else "Rs. "
    header_style = ParagraphStyle("HCellVal", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=10, textColor=colors.white)
    cell_style = ParagraphStyle("CellVal", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=8, leading=10, textColor=CLR_TEXT_BODY)
    cell_bold = ParagraphStyle("CellBVal", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=10, textColor=CLR_TEXT_BODY)

    # Disclosure banner
    disclosure_p = Paragraph(
        f"<b>Notice on Accounting Costing:</b> {clean_pdf_text(disclosure_note)}",
        ParagraphStyle("Disc", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=7.5, leading=10, textColor=colors.HexColor("#854d0e"))
    )
    disc_table = Table([[disclosure_p]], colWidths=[total_w])
    disc_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef9c3")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#facc15")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))

    table_data = [
        [
            Paragraph("<b>ID</b>", header_style),
            Paragraph("<b>Product Name</b>", header_style),
            Paragraph("<b>Category</b>", header_style),
            Paragraph("<b>Available Stock</b>", header_style),
            Paragraph(f"<b>Selling Price ({curr_sym.strip()})</b>", header_style),
            Paragraph(f"<b>Potential Retail Value ({curr_sym.strip()})</b>", header_style),
            Paragraph("<b>Purchase Cost</b>", header_style),
        ]
    ]

    for p in products:
        potential_val = round(p.stock_quantity * p.unit_price, 2)
        table_data.append([
            Paragraph(f"P-{p.id:04d}", cell_style),
            Paragraph(clean_pdf_text(p.name), cell_style),
            Paragraph(clean_pdf_text(p.category), cell_style),
            Paragraph(f"{p.stock_quantity:.1f} {p.unit}", cell_style),
            Paragraph(format_inr(p.unit_price), cell_style),
            Paragraph(f"<b>{format_inr(potential_val)}</b>", cell_style),
            Paragraph("<font color='#94a3b8'>N/A</font>", cell_style),
        ])

    # Totals Row
    table_data.append([
        Paragraph("<b>TOTAL</b>", cell_bold),
        Paragraph(f"<b>{len(products)} Items</b>", cell_bold),
        Paragraph("-", cell_bold),
        Paragraph(f"<b>{total_units:,.1f}</b>", cell_bold),
        Paragraph("-", cell_bold),
        Paragraph(f"<b>{format_inr(total_potential_retail_val)}</b>", cell_bold),
        Paragraph("<b>N/A</b>", cell_bold),
    ])

    col_widths = [total_w * 0.10, total_w * 0.30, total_w * 0.18, total_w * 0.14, total_w * 0.12, total_w * 0.16]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CLR_BRAND_DARK),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, CLR_GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, CLR_ROW_ALT]),
        ("BACKGROUND", (0, -1), (-1, -1), CLR_TOTAL_BG),
        ("LINEABOVE", (0, -1), (-1, -1), 1.25, CLR_TOTAL_LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 1.25, CLR_TOTAL_LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))

    story = [
        build_kpi_cards_table([
            ("Potential Retail Value", format_inr(total_potential_retail_val), "Calculated from selling price"),
            ("Available Units", f"{total_units:,.1f}", "Total pieces / kilograms in stock"),
            ("Cost Valuation", "Unavailable", "Catalog tracks selling price only")
        ], total_w),
        Spacer(1, 10),
        disc_table,
        Spacer(1, 12),
        table
    ]

    return build_pdf_document(f"inventory_valuation_{timestamp_str}.pdf", "Inventory Valuation Report", subtitle, shop, story)


# ==============================================================================
# REPORT 7: CUSTOMER UDHAAR LEDGER
# ==============================================================================

def export_customer_ledger(
    db: Session,
    customer_id: int,
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None,
    export_format: str = "csv"
) -> Response:
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer with ID {customer_id} not found."
        )

    shop = get_active_shop_info(db)

    # Optional date filters
    q = db.query(UdhaarTransaction).filter(UdhaarTransaction.primary_customer_id == customer_id)
    if start_date_str:
        s_date = datetime.datetime.strptime(start_date_str.strip(), "%Y-%m-%d").date()
        q = q.filter(UdhaarTransaction.created_at >= datetime.datetime.combine(s_date, datetime.time.min))
    if end_date_str:
        e_date = datetime.datetime.strptime(end_date_str.strip(), "%Y-%m-%d").date()
        q = q.filter(UdhaarTransaction.created_at <= datetime.datetime.combine(e_date, datetime.time.max))

    transactions = q.order_by(UdhaarTransaction.created_at.asc(), UdhaarTransaction.id.asc()).all()

    cust_code = getattr(customer, "customer_code", None) or f"C-{customer.id:06d}"
    clean_p = "".join(filter(str.isdigit, customer.phone or ""))
    masked_phone = f"{clean_p[:2]}******{clean_p[-2:]}" if len(clean_p) >= 4 else clean_p

    if export_format.lower() == "csv":
        headers = [
            "Customer Code", "Customer Name", "Phone", "Tx ID", "Date", "Time",
            "Bill / Ref Number", "Transaction Type", "Debit / Credit Purchase (Rs.)",
            "Payment / Settlement (Rs.)", "Balance Before (Rs.)", "Balance After (Rs.)",
            "Verified By", "Notes"
        ]
        rows = []
        for t in transactions:
            is_debit = t.transaction_type == "DEBIT_PURCHASE"
            debit_val = f"{t.amount:.2f}" if is_debit else "0.00"
            credit_val = f"{t.amount:.2f}" if not is_debit else "0.00"
            ref_no = t.bill.bill_number if t.bill else (t.notes or f"TX-{t.id:05d}")

            rows.append([
                cust_code,
                customer.full_name,
                masked_phone,
                f"TX-{t.id:05d}",
                t.created_at.strftime("%Y-%m-%d"),
                t.created_at.strftime("%H:%M:%S"),
                ref_no,
                t.transaction_type,
                debit_val,
                credit_val,
                f"{t.balance_before:.2f}",
                f"{t.balance_after:.2f}",
                t.verified_by,
                t.notes or ""
            ])

        return build_csv_response(f"customer_ledger_{cust_code}.csv", headers, rows)

    # PDF Khata Statement
    total_w = letter[0] - 72
    subtitle = f"Customer Statement • Account: {cust_code} • {clean_pdf_text(customer.full_name)} (Mob: {masked_phone})"

    styles = getSampleStyleSheet()
    curr_sym = "₹" if HAS_TTF else "Rs. "
    header_style = ParagraphStyle("HCellLed", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=10, textColor=colors.white)
    cell_style = ParagraphStyle("CellLed", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=8, leading=10, textColor=CLR_TEXT_BODY)
    cell_bold = ParagraphStyle("CellBLed", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=10, textColor=CLR_TEXT_BODY)

    # Customer Overview Card
    cust_kpis = [
        ("Current Balance", format_inr(customer.current_udhaar_balance), "Outstanding to store"),
        ("Credit Limit", format_inr(customer.credit_limit), "Authorized store credit"),
        ("Available Credit", format_inr(max(0.0, customer.credit_limit - customer.current_udhaar_balance)), "Remaining limit balance")
    ]

    table_data = [
        [
            Paragraph("<b>Tx ID</b>", header_style),
            Paragraph("<b>Date / Time</b>", header_style),
            Paragraph("<b>Reference</b>", header_style),
            Paragraph("<b>Description / Type</b>", header_style),
            Paragraph("<b>Debit (Purchase)</b>", header_style),
            Paragraph("<b>Credit (Paid)</b>", header_style),
            Paragraph(f"<b>Balance ({curr_sym.strip()})</b>", header_style),
        ]
    ]

    for t in transactions:
        is_debit = t.transaction_type == "DEBIT_PURCHASE"
        debit_html = format_inr(t.amount) if is_debit else "-"
        credit_html = f"<font color='#059669'>{format_inr(t.amount)}</font>" if not is_debit else "-"
        type_str = "Udhaar Purchase" if is_debit else "Debt Settlement"
        ref_str = t.bill.bill_number if t.bill else f"TX-{t.id:05d}"

        table_data.append([
            Paragraph(f"TX-{t.id:05d}", cell_style),
            Paragraph(t.created_at.strftime("%d-%m-%Y %H:%M"), cell_style),
            Paragraph(clean_pdf_text(ref_str), cell_style),
            Paragraph(clean_pdf_text(type_str), cell_style),
            Paragraph(debit_html, cell_style),
            Paragraph(credit_html, cell_style),
            Paragraph(f"<b>{format_inr(t.balance_after)}</b>", cell_style),
        ])

    if not transactions:
        table_data.append([
            Paragraph("No ledger transactions recorded for this customer account.", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style)
        ])

    col_widths = [total_w * 0.12, total_w * 0.16, total_w * 0.18, total_w * 0.18, total_w * 0.12, total_w * 0.12, total_w * 0.12]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CLR_BRAND_DARK),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, CLR_GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CLR_ROW_ALT]),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))

    story = [
        build_kpi_cards_table(cust_kpis, total_w),
        Spacer(1, 12),
        table
    ]

    return build_pdf_document(f"customer_ledger_{cust_code}.pdf", "Customer Udhaar Ledger Statement", subtitle, shop, story)


# ==============================================================================
# REPORT 8: OUTSTANDING UDHAAR REPORT
# ==============================================================================

def export_outstanding_udhaar(
    db: Session,
    min_balance: float = 0.0,
    export_format: str = "csv"
) -> Response:
    shop = get_active_shop_info(db)

    customers = db.query(Customer).filter(
        Customer.current_udhaar_balance > min_balance,
        Customer.is_active == True  # noqa: E712
    ).order_by(Customer.current_udhaar_balance.desc()).all()

    timestamp_str = datetime.datetime.utcnow().strftime("%Y%m%d")
    total_outstanding = sum(c.current_udhaar_balance for c in customers)

    if export_format.lower() == "csv":
        headers = [
            "Customer Code", "Customer Name", "Masked Phone", "Credit Limit (Rs.)",
            "Outstanding Balance (Rs.)", "Available Credit (Rs.)", "Address"
        ]
        rows = []
        for c in customers:
            clean_p = "".join(filter(str.isdigit, c.phone or ""))
            masked_p = f"{clean_p[:2]}******{clean_p[-2:]}" if len(clean_p) >= 4 else clean_p
            avail = max(0.0, c.credit_limit - c.current_udhaar_balance)
            cust_code = getattr(c, "customer_code", None) or f"C-{c.id:06d}"

            rows.append([
                cust_code,
                c.full_name,
                masked_p,
                f"{c.credit_limit:.2f}",
                f"{c.current_udhaar_balance:.2f}",
                f"{avail:.2f}",
                c.address_line or c.city or ""
            ])

        # Summary Row
        rows.append([
            "TOTAL OUTSTANDING CREDIT",
            f"{len(customers)} accounts",
            "",
            "",
            f"{total_outstanding:.2f}",
            "",
            ""
        ])

        return build_csv_response(f"outstanding_udhaar_{timestamp_str}.csv", headers, rows)

    # PDF Format
    total_w = letter[0] - 72
    subtitle = f"Accounts with Outstanding Debt: {len(customers)} • Total Pending Credit: {format_inr(total_outstanding)}"

    styles = getSampleStyleSheet()
    curr_sym = "₹" if HAS_TTF else "Rs. "
    header_style = ParagraphStyle("HCellUdh", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=10, textColor=colors.white)
    cell_style = ParagraphStyle("CellUdh", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=8, leading=10, textColor=CLR_TEXT_BODY)
    cell_bold = ParagraphStyle("CellBUdh", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=8, leading=10, textColor=CLR_TEXT_BODY)

    table_data = [
        [
            Paragraph("<b>Account Code</b>", header_style),
            Paragraph("<b>Customer Name</b>", header_style),
            Paragraph("<b>Phone</b>", header_style),
            Paragraph(f"<b>Credit Limit ({curr_sym.strip()})</b>", header_style),
            Paragraph(f"<b>Outstanding Balance ({curr_sym.strip()})</b>", header_style),
            Paragraph(f"<b>Available Limit ({curr_sym.strip()})</b>", header_style),
        ]
    ]

    for c in customers:
        clean_p = "".join(filter(str.isdigit, c.phone or ""))
        masked_p = f"{clean_p[:2]}******{clean_p[-2:]}" if len(clean_p) >= 4 else clean_p
        avail = max(0.0, c.credit_limit - c.current_udhaar_balance)
        cust_code = getattr(c, "customer_code", None) or f"C-{c.id:06d}"

        table_data.append([
            Paragraph(cust_code, cell_style),
            Paragraph(clean_pdf_text(c.full_name), cell_style),
            Paragraph(masked_p, cell_style),
            Paragraph(format_inr(c.credit_limit), cell_style),
            Paragraph(f"<font color='#dc2626'><b>{format_inr(c.current_udhaar_balance)}</b></font>", cell_style),
            Paragraph(format_inr(avail), cell_style),
        ])

    if not customers:
        table_data.append([
            Paragraph("No customers currently have an outstanding credit balance.", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style)
        ])
    else:
        # Summary row
        table_data.append([
            Paragraph("<b>TOTAL</b>", cell_bold),
            Paragraph(f"<b>{len(customers)} Accounts</b>", cell_bold),
            Paragraph("-", cell_bold),
            Paragraph("-", cell_bold),
            Paragraph(f"<b>{format_inr(total_outstanding)}</b>", cell_bold),
            Paragraph("-", cell_bold),
        ])

    col_widths = [total_w * 0.16, total_w * 0.26, total_w * 0.15, total_w * 0.14, total_w * 0.15, total_w * 0.14]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7f1d1d")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, CLR_GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2 if customers else -1), [colors.white, colors.HexColor("#fff1f2")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fee2e2") if customers else colors.white),
        ("LINEABOVE", (0, -1), (-1, -1), 1.25, colors.HexColor("#dc2626")),
        ("LINEBELOW", (0, -1), (-1, -1), 1.25, colors.HexColor("#dc2626")),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))

    story = [
        build_kpi_cards_table([
            ("Total Outstanding Credit", format_inr(total_outstanding), "Total shopkeeper receivables"),
            ("Debtor Accounts", str(len(customers)), "Customers with pending Udhaar"),
            ("Average Pending Debt", format_inr(total_outstanding / len(customers)) if customers else ("₹0.00" if HAS_TTF else "Rs. 0.00"), "Per customer with debt")
        ], total_w),
        Spacer(1, 12),
        table
    ]

    return build_pdf_document(f"outstanding_udhaar_{timestamp_str}.pdf", "Outstanding Udhaar Ledger Report", subtitle, shop, story)


# ==============================================================================
# REPORT 9: SUPPLIER PURCHASE HISTORY (PREREQUISITE LIMITATION)
# ==============================================================================

def export_supplier_purchases(
    db: Session,
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None,
    export_format: str = "csv"
) -> Response:
    """
    Honest, transparent implementation for Supplier Purchase History.
    Database schema inspection proves Supplier and Purchase Order tables do not exist.
    Outputs an official notice explaining the architectural prerequisite rather than fabricating records.
    """
    shop = get_active_shop_info(db)
    timestamp_str = datetime.datetime.utcnow().strftime("%Y%m%d")

    notice_text = (
        "PREREQUISITE STATUS: BLOCKED / NOT CONFIGURED. "
        "Supplier Purchase Management and Incoming Invoices are not currently implemented "
        "in the Apna Kirana OS database schema. To export supplier purchases, supplier catalog "
        "and procurement tables must first be configured."
    )

    if export_format.lower() == "csv":
        headers = [
            "Module Status", "Prerequisite Requirement", "Recorded Purchases",
            "Supplier ID", "Supplier Name", "Purchase Invoice Ref", "Purchase Date", "Amount (Rs.)"
        ]
        rows = [
            ["BLOCKED", notice_text, "0", "N/A", "N/A", "N/A", "N/A", "0.00"]
        ]
        return build_csv_response(f"supplier_purchases_notice_{timestamp_str}.csv", headers, rows)

    # PDF Format
    total_w = letter[0] - 72
    subtitle = "Prerequisite Status: Blocked • Module Not Configured in Current Schema"
    styles = getSampleStyleSheet()

    notice_p = Paragraph(
        f"<b>Feature Architectural Status:</b><br/>{clean_pdf_text(notice_text)}<br/><br/>"
        "<i>Apna Kirana OS strictly enforces data integrity: synthetic, simulated, or fabricated "
        "supplier purchases are never created or substituted. When incoming shipment logging is "
        "introduced, purchase records will appear here automatically.</i>",
        ParagraphStyle("Notice", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=9, leading=13, textColor=colors.HexColor("#991b1b"))
    )

    notice_box = Table([[notice_p]], colWidths=[total_w])
    notice_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef2f2")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#ef4444")),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))

    story = [
        build_kpi_cards_table([
            ("Module Status", "BLOCKED", "Prerequisite table missing"),
            ("Supplier Records", "0", "No supplier table"),
            ("Integrity Guarantee", "Zero Fake Data", "Honest fallback enforced")
        ], total_w),
        Spacer(1, 16),
        notice_box
    ]

    return build_pdf_document(f"supplier_purchases_notice_{timestamp_str}.pdf", "Supplier Purchase History Report", subtitle, shop, story)


# ==============================================================================
# REPORT 10: AI DEMAND FORECAST & RESTOCKING RECOMMENDATIONS
# ==============================================================================

def export_demand_forecast(
    db: Session,
    horizon: str = "7d",
    risk_level: Optional[str] = None,
    export_format: str = "csv"
) -> Response:
    """
    Exports deterministic Demand Forecasting and Reorder Intelligence.
    Reuses existing forecasting engine (get_all_product_forecasts).
    """
    shop = get_active_shop_info(db)
    forecast_result = get_all_product_forecasts(db, force_refresh=False)
    products = forecast_result.get("products", [])

    if risk_level and risk_level.strip() and risk_level.upper() != "ALL":
        products = [p for p in products if p.get("risk_level", "").upper() == risk_level.strip().upper()]

    timestamp_str = datetime.datetime.utcnow().strftime("%Y%m%d")
    is_30d = horizon.strip().lower() == "30d"
    horizon_label = "30-Day Demand Forecast" if is_30d else "7-Day Demand Forecast"

    disclaimer = (
        "STATISTICAL ESTIMATE DISCLAIMER: Demand forecasts and restocking recommendations are generated "
        "via empirical sales velocity and statistical exponential smoothing. They represent statistical "
        "advisory projections and do not guarantee future sales."
    )

    if export_format.lower() == "csv":
        headers = [
            "Product ID", "Product Name", "Current Stock", "Unit", "Forecast Horizon",
            "Predicted Demand (Units)", "Days Inventory Remaining", "Stockout Risk Level",
            "Suggested Reorder Qty", "Safety Stock", "Reorder Urgency", "Forecast Status", "Disclaimer"
        ]
        rows = []
        for p in products:
            predicted = p.get("total_30d_demand" if is_30d else "total_7d_demand", 0.0)
            rows.append([
                f"P-{p.get('product_id', 0):04d}",
                p.get("product_name", ""),
                f"{p.get('current_stock', 0.0):.2f}",
                p.get("unit", "unit"),
                "30 Days" if is_30d else "7 Days",
                f"{predicted:.2f}",
                f"{p.get('days_inventory_remaining', 0.0):.1f}" if p.get("days_inventory_remaining") is not None else "N/A",
                p.get("risk_level", "SUFFICIENT"),
                f"{p.get('suggested_reorder_qty', 0.0):.2f}",
                f"{p.get('safety_stock', 0.0):.2f}",
                p.get("reorder_urgency", "OPTIMAL"),
                p.get("status", "ELIGIBLE"),
                disclaimer
            ])

        return build_csv_response(f"demand_forecast_{horizon}_{timestamp_str}.csv", headers, rows)

    # PDF Format (Landscape)
    total_w = landscape(letter)[0] - 72
    subtitle = f"Horizon: {horizon_label} • Analyzed Products: {len(products)} • Generated {datetime.datetime.utcnow().strftime('%d-%m-%Y')}"

    styles = getSampleStyleSheet()
    header_style = ParagraphStyle("HCellFC", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=7.5, leading=9, textColor=colors.white)
    cell_style = ParagraphStyle("CellFC", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=7.5, leading=9, textColor=CLR_TEXT_BODY)
    cell_bold = ParagraphStyle("CellBFC", parent=styles["Normal"], fontName=FONT_FAMILY_BOLD, fontSize=7.5, leading=9, textColor=CLR_TEXT_BODY)

    # Disclaimer note
    disc_p = Paragraph(
        f"<b>Advisory Note:</b> {clean_pdf_text(disclaimer)}",
        ParagraphStyle("Disc", parent=styles["Normal"], fontName=FONT_FAMILY, fontSize=7, leading=9, textColor=colors.HexColor("#475569"))
    )
    disc_table = Table([[disc_p]], colWidths=[total_w])
    disc_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CLR_CARD_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, CLR_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))

    table_data = [
        [
            Paragraph("<b>ID</b>", header_style),
            Paragraph("<b>Product Name</b>", header_style),
            Paragraph("<b>Current Stock</b>", header_style),
            Paragraph("<b>Predicted Demand</b>", header_style),
            Paragraph("<b>Days Remaining</b>", header_style),
            Paragraph("<b>Risk Level</b>", header_style),
            Paragraph("<b>Suggested Order</b>", header_style),
            Paragraph("<b>Urgency</b>", header_style),
        ]
    ]

    for p in products:
        predicted = p.get("total_30d_demand" if is_30d else "total_7d_demand", 0.0)
        risk = p.get("risk_level", "SUFFICIENT")
        risk_color = "#10b981"
        if risk in ("IMMEDIATE_ATTENTION", "POTENTIAL_STOCKOUT"):
            risk_color = "#ef4444"
        elif risk == "LOW_STOCK":
            risk_color = "#f59e0b"
        elif risk == "INSUFFICIENT_DATA":
            risk_color = "#94a3b8"

        days_val = p.get("days_inventory_remaining")
        days_str = f"{days_val:.1f} days" if days_val is not None else "N/A"

        table_data.append([
            Paragraph(f"P-{p.get('product_id', 0):04d}", cell_style),
            Paragraph(clean_pdf_text(p.get("product_name", "")), cell_style),
            Paragraph(f"{p.get('current_stock', 0.0):.1f} {p.get('unit', '')}", cell_style),
            Paragraph(f"<b>{predicted:.1f}</b> {p.get('unit', '')}", cell_style),
            Paragraph(days_str, cell_style),
            Paragraph(f"<font color='{risk_color}'><b>{risk}</b></font>", cell_style),
            Paragraph(f"<b>{p.get('suggested_reorder_qty', 0.0):.1f}</b> {p.get('unit', '')}", cell_style),
            Paragraph(clean_pdf_text(p.get("reorder_urgency", "OPTIMAL")), cell_style),
        ])

    col_widths = [total_w * 0.08, total_w * 0.28, total_w * 0.12, total_w * 0.12, total_w * 0.10, total_w * 0.14, total_w * 0.08, total_w * 0.08]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CLR_BRAND_DARK),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, CLR_GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CLR_ROW_ALT]),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))

    story = [
        build_kpi_cards_table([
            ("Forecast Horizon", horizon_label, "Statistical projection window"),
            ("Products Tracked", str(len(products)), "Items analyzed in catalog"),
            ("Risk Filter", risk_level.upper() if risk_level else "ALL LEVELS", "Stockout risk category")
        ], total_w),
        Spacer(1, 8),
        disc_table,
        Spacer(1, 10),
        table
    ]

    return build_pdf_document(f"demand_forecast_{horizon}_{timestamp_str}.pdf", "AI Demand Forecast & Restocking Intelligence", subtitle, shop, story, landscape_mode=True)
