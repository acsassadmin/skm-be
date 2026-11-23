# apps/orders/services/report_service.py
import calendar
from datetime import datetime, time
from decimal import Decimal
from io import BytesIO

from django.db import models
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.utils import timezone
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from orders.models import Order, OrderItem, Refund


# Per Section 22.4 of SKM Electronics Agreement:
# Cancelled, returned, and refunded orders shall not be treated as successful sales.
EXCLUDED_ORDER_STATUSES = [
    Order.Status.CANCELLED,
    Order.Status.REFUNDED,
    Order.Status.RETURNED,
]


def resolve_date_range(
    period: str = "monthly",
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[datetime, datetime, str]:
    """
    Resolves period ('monthly', 'quarterly', 'annual', or custom start_date/end_date)
    into timezone-aware (start_dt, end_dt, period_label).
    """
    now = timezone.localtime(timezone.now())
    tz = timezone.get_current_timezone()
    period = (period or "monthly").lower().strip()

    if start_date and end_date:
        s_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        e_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        start_dt = timezone.make_aware(datetime.combine(s_date, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(e_date, time.max), tz)
        return start_dt, end_dt, f"{s_date.isoformat()} to {e_date.isoformat()}"

    if period == "quarterly":
        quarter = (now.month - 1) // 3 + 1
        first_month = 3 * (quarter - 1) + 1
        last_month = first_month + 2
        last_day = calendar.monthrange(now.year, last_month)[1]
        s_date = now.date().replace(month=first_month, day=1)
        e_date = now.date().replace(month=last_month, day=last_day)

        label = f"Q{quarter} {now.year}"
    elif period == "annual":
        s_date = now.date().replace(month=1, day=1)
        e_date = now.date().replace(month=12, day=31)
        label = f"FY {now.year}"
    else:
        last_day = calendar.monthrange(now.year, now.month)[1]
        s_date = now.date().replace(day=1)
        e_date = now.date().replace(day=last_day)
        label = now.strftime("%B %Y")

    start_dt = timezone.make_aware(datetime.combine(s_date, time.min), tz)
    end_dt = timezone.make_aware(datetime.combine(e_date, time.max), tz)
    return start_dt, end_dt, label
def build_sales_report_data(
    period: str = "monthly",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """
    Aggregates SKM Electronics sales & revenue analytics per Sections 3.14, 9, and 22.
    """
    start_dt, end_dt, period_label = resolve_date_range(period, start_date, end_date)
    zero = Decimal("0.00")

    orders_qs = Order.objects.filter(created_at__range=(start_dt, end_dt))

    # Successful paid orders queryset (strictly excludes cancelled/returned/refunded)
    valid_orders_qs = orders_qs.filter(
        payment_status=Order.PaymentStatus.PAID
    ).exclude(status__in=EXCLUDED_ORDER_STATUSES)

    # 1. Order status counts
    counts = orders_qs.aggregate(
        total_orders=Count("id"),
        completed_orders=Count(
            "id",
            filter=Q(status=Order.Status.DELIVERED, payment_status=Order.PaymentStatus.PAID),
        ),
        active_paid_orders=Count(
            "id",
            filter=Q(payment_status=Order.PaymentStatus.PAID)
            & ~Q(status__in=EXCLUDED_ORDER_STATUSES),
        ),
        cancelled_orders=Count("id", filter=Q(status=Order.Status.CANCELLED)),
        returned_orders=Count(
            "id",
            filter=Q(status__in=[Order.Status.RETURNED, Order.Status.RETURN_REQUESTED]),
        ),
        refunded_orders=Count(
            "id",
            filter=Q(status=Order.Status.REFUNDED)
            | Q(payment_status=Order.PaymentStatus.REFUNDED),
        ),
        pending_payment_orders=Count(
            "id",
            filter=Q(payment_status=Order.PaymentStatus.PENDING)
            & ~Q(status=Order.Status.CANCELLED),
        ),
    )

    # 2. Gross revenue totals across valid paid orders
    rev = valid_orders_qs.aggregate(
        gross_subtotal=Coalesce(Sum("subtotal_amount"), zero),
        total_discounts=Coalesce(Sum("discount_amount"), zero),
        total_tax=Coalesce(Sum("tax_amount"), zero),
        total_shipping=Coalesce(Sum("shipping_amount"), zero),
        gross_paid_total=Coalesce(Sum("total_amount"), zero),
    )

    # 3. Completed refunds processed inside the date window
    refund_agg = Refund.objects.filter(
        status=Refund.Status.COMPLETED,
        processed_at__range=(start_dt, end_dt),
    ).aggregate(
        refund_count=Count("id"),
        refunded_subtotal=Coalesce(Sum("subtotal_refund"), zero),
        refunded_tax=Coalesce(Sum("tax_refund"), zero),
        refunded_total=Coalesce(Sum("amount"), zero),
    )

    net_sales_excl_tax = max(
        zero, rev["gross_subtotal"] - rev["total_discounts"] - refund_agg["refunded_subtotal"]
    )
    net_tax_collected = max(zero, rev["total_tax"] - refund_agg["refunded_tax"])
    net_revenue_incl_tax = max(zero, rev["gross_paid_total"] - refund_agg["refunded_total"])

    # 4. Customer vs. Dealer revenue split
    segment_rows = (
        valid_orders_qs.values("is_dealer_order")
        .annotate(
            orders_count=Count("id"),
            net_revenue=Coalesce(Sum("total_amount"), zero),
            tax_collected=Coalesce(Sum("tax_amount"), zero),
        )
        .order_by("-is_dealer_order")
    )
    customer_vs_dealer = [
        {
            "segment": "DEALER" if row["is_dealer_order"] else "CUSTOMER",
            "orders_count": row["orders_count"],
            "net_revenue": str(row["net_revenue"]),
            "tax_collected": str(row["tax_collected"]),
        }
        for row in segment_rows
    ]

    # 5. Product-wise revenue breakdown (Sec 9)
    product_rows = (
        OrderItem.objects.filter(order__in=valid_orders_qs)
        .values("product_id", "product_sku", "product_name", "hsn_code")
        .annotate(
            units_sold=Coalesce(Sum("quantity"), 0),
            subtotal_revenue=Coalesce(Sum("line_subtotal"), zero),
            tax_collected=Coalesce(Sum("tax_amount"), zero),
            total_revenue=Coalesce(Sum("line_total"), zero),
        )
        .order_by("-total_revenue")
    )
    product_wise_revenue = [
        {
            "product_id": row["product_id"],
            "sku": row["product_sku"],
            "product_name": row["product_name"],
            "hsn_code": row["hsn_code"],
            "units_sold": row["units_sold"],
            "subtotal_revenue": str(row["subtotal_revenue"]),
            "tax_collected": str(row["tax_collected"]),
            "total_revenue": str(row["total_revenue"]),
        }
        for row in product_rows
    ]

    # 6. Coupon & campaign conversion tracking (Sec 9 & 22.2)
    coupon_rows = (
        valid_orders_qs.exclude(coupon_code="")
        .values(
            "coupon_code",
            campaign_tag=Coalesce(F("coupon__campaign_tag"), models.Value("")),
        )
        .annotate(
            usage_count=Count("id"),
            discount_given=Coalesce(Sum("discount_amount"), zero),
            attributed_sales=Coalesce(Sum("total_amount"), zero),
        )
        .order_by("-attributed_sales")
    )
    coupon_performance = [
        {
            "coupon_code": row["coupon_code"],
            "campaign_tag": row["campaign_tag"] or "Direct / Untagged",
            "usage_count": row["usage_count"],
            "discount_given": str(row["discount_given"]),
            "attributed_sales": str(row["attributed_sales"]),
        }
        for row in coupon_rows
    ]

    # 7. Time-series trend
    trunc_fn = TruncMonth("created_at") if period == "annual" else TruncDate("created_at")
    trend_rows = (
        valid_orders_qs.annotate(bucket=trunc_fn)
        .values("bucket")
        .annotate(
            orders_count=Count("id"),
            revenue=Coalesce(Sum("total_amount"), zero),
        )
        .order_by("bucket")
    )
    sales_trend = [
        {
            "date": row["bucket"].strftime("%Y-%m" if period == "annual" else "%Y-%m-%d"),
            "orders_count": row["orders_count"],
            "revenue": str(row["revenue"]),
        }
        for row in trend_rows
        if row["bucket"] is not None
    ]

    return {
        "period": period,
        "period_label": period_label,
        "start_date": start_dt.date().isoformat(),
        "end_date": end_dt.date().isoformat(),
        "summary": {
            "total_orders": counts["total_orders"],
            "completed_orders": counts["completed_orders"],
            "active_paid_orders": counts["active_paid_orders"],
            "cancelled_orders": counts["cancelled_orders"],
            "returned_orders": counts["returned_orders"],
            "refunded_orders": counts["refunded_orders"],
            "pending_payment_orders": counts["pending_payment_orders"],
            "gross_subtotal": str(rev["gross_subtotal"]),
            "total_discounts": str(rev["total_discounts"]),
            "total_shipping": str(rev["total_shipping"]),
            "refunds_count": refund_agg["refund_count"],
            "refunded_amount": str(refund_agg["refunded_total"]),
            "net_sales_excl_tax": str(net_sales_excl_tax),
            "net_tax_collected": str(net_tax_collected),
            "net_revenue_incl_tax": str(net_revenue_incl_tax),
        },
        "customer_vs_dealer": customer_vs_dealer,
        "product_wise_revenue": product_wise_revenue,
        "coupon_performance": coupon_performance,
        "sales_trend": sales_trend,
    }
def export_sales_report_excel(report_data: dict) -> BytesIO:
    """Generates a multi-sheet openpyxl Excel report for SKM Electronics."""
    wb = openpyxl.Workbook()
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    title_font = Font(size=14, bold=True)

    # Sheet 1: Executive Summary
    ws_sum = wb.active
    ws_sum.title = "Executive_Summary"
    ws_sum["A1"] = f"SKM Electronics - Sales & Revenue Report ({report_data['period_label']})"
    ws_sum["A1"].font = title_font
    ws_sum["A2"] = f"Date Range: {report_data['start_date']} to {report_data['end_date']}"

    ws_sum.append([])
    ws_sum.append(["Metric", "Value"])
    for cell in ws_sum[ws_sum.max_row]:
        cell.fill = header_fill
        cell.font = header_font

    for key, val in report_data["summary"].items():
        ws_sum.append([key.replace("_", " ").title(), val])

    ws_sum.append([])
    ws_sum.append(
        ["Customer Segment Breakdown", "Orders", "Net Revenue (INR)", "GST Collected (INR)"]
    )
    seg_header_row = ws_sum.max_row
    for cell in ws_sum[seg_header_row]:
        cell.fill = header_fill
        cell.font = header_font

    for seg in report_data["customer_vs_dealer"]:
        ws_sum.append(
            [seg["segment"], seg["orders_count"], seg["net_revenue"], seg["tax_collected"]]
        )

    # Sheet 2: Product-Wise Revenue
    ws_prod = wb.create_sheet(title="Product_Wise_Revenue")
    prod_headers = [
        "Product ID",
        "SKU",
        "Product Name",
        "HSN Code",
        "Units Sold",
        "Subtotal (INR)",
        "GST (INR)",
        "Total Revenue (INR)",
    ]
    ws_prod.append(prod_headers)
    for cell in ws_prod[ws_prod.max_row]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")


    for p in report_data["product_wise_revenue"]:
        ws_prod.append(
            [
                p["product_id"],
                p["sku"],
                p["product_name"],
                p["hsn_code"],
                p["units_sold"],
                p["subtotal_revenue"],
                p["tax_collected"],
                p["total_revenue"],
            ]
        )

    # Sheet 3: Coupon & Campaign Attribution
    ws_coup = wb.create_sheet(title="Coupon_Attribution")
    coup_headers = [
        "Coupon Code",
        "Campaign Tag",
        "Orders Used",
        "Total Discount (INR)",
        "Attributed Sales (INR)",
    ]
    ws_coup.append(coup_headers)
    for cell in ws_coup[ws_coup.max_row]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")


    for c in report_data["coupon_performance"]:
        ws_coup.append(
            [
                c["coupon_code"],
                c["campaign_tag"],
                c["usage_count"],
                c["discount_given"],
                c["attributed_sales"],
            ]
        )

    # Auto-fit column widths across all sheets
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=12)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = min(max_len + 4, 42)


    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
def export_sales_report_pdf(report_data: dict) -> BytesIO:
    """Generates a downloadable landscape A4 PDF business statement via ReportLab."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=28,
        leftMargin=28,
        topMargin=28,
        bottomMargin=28,
    )
    styles = getSampleStyleSheet()
    elements = []

    elements.append(
        Paragraph(
            f"<b>SKM Electronics — Sales & Revenue Statement ({report_data['period_label']})</b>",
            styles["Title"],
        )
    )
    elements.append(
        Paragraph(
            f"Period: {report_data['start_date']} to {report_data['end_date']} "
            "(Excludes cancelled, returned & refunded orders)",
            styles["Normal"],
        )
    )
    elements.append(Spacer(1, 14))

    # Summary KPI Table (total width = 780 pts on landscape A4)
    s = report_data["summary"]
    summary_table_data = [
        [
            "Total Orders",
            str(s["total_orders"]),
            "Completed Orders",
            str(s["completed_orders"]),
            "Cancelled / Returned",
            f"{s['cancelled_orders']} / {s['returned_orders']}",
        ],
        [
            "Net Sales (Excl. Tax)",
            f"INR {s['net_sales_excl_tax']}",
            "Net GST Collected",
            f"INR {s['net_tax_collected']}",
            "Net Revenue (Incl. Tax)",
            f"INR {s['net_revenue_incl_tax']}",
        ],
        [
            "Total Discounts",
            f"INR {s['total_discounts']}",
            "Total Shipping",
            f"INR {s['total_shipping']}",
            "Completed Refunds",
            f"INR {s['refunded_amount']} ({s['refunds_count']})",
        ],
    ]
    t_sum = Table(summary_table_data, colWidths=[130, 130, 130, 130, 130, 130])

    t_sum.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E8EEF5")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#E8EEF5")),
                ("BACKGROUND", (4, 0), (4, -1), colors.HexColor("#E8EEF5")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.append(t_sum)
    elements.append(Spacer(1, 18))

    # Product-wise Revenue Table (total width = 780 pts)
    elements.append(Paragraph("<b>Product-Wise Revenue Breakdown</b>", styles["Heading3"]))
    prod_data = [
        ["SKU", "Product Name", "HSN", "Units", "Subtotal (INR)", "GST (INR)", "Total (INR)"]
    ]
    for p in report_data["product_wise_revenue"][:50]:
        prod_data.append(
            [
                p["sku"],
                p["product_name"][:40],
                p["hsn_code"],
                str(p["units_sold"]),
                p["subtotal_revenue"],
                p["tax_collected"],
                p["total_revenue"],
            ]
        )
    if len(prod_data) == 1:
        prod_data.append(
            ["-", "No completed product sales in selected period", "-", "0", "0.00", "0.00", "0.00"]
        )

    t_prod = Table(prod_data, colWidths=[95, 245, 70, 55, 105, 95, 115])

    t_prod.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elements.append(t_prod)

    doc.build(elements)
    buf.seek(0)
    return buf
