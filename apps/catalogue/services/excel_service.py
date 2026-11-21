import json
from decimal import Decimal, InvalidOperation
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill
from django.db import transaction
from django.utils.text import slugify
from catalogue.models import InventoryLog
from catalogue.models import Category, Product

EXCEL_HEADERS = [
    "sku",
    "name",
    "category_name",
    "brand",
    "hsn_code",
    "short_description",
    "description",
    "specifications",
    "customer_price",
    "dealer_price",
    "gst_rate",
    "stock_quantity",
    "low_stock_threshold",
    "warranty_months",
    "is_featured",
    "is_active",
]

FIELD_GUIDANCE = [
    ("sku", "Yes", "Unique product SKU (e.g., SKM-IOT-001). Existing SKUs will be updated."),
    ("name", "Yes", "Product title (max 200 characters)."),
    ("category_name", "Yes", "Category name. Auto-created if it does not exist yet."),
    ("brand", "No", "Brand or manufacturer name (max 100 characters)."),
    ("hsn_code", "No", "GST HSN code (max 20 characters, e.g., 85423100)."),
    ("short_description", "No", "Short card summary (max 300 characters)."),
    ("description", "Yes", "Full product description."),
    ("specifications", "No", 'JSON object ({"MCU": "ESP32"}) or semicolon pairs (MCU: ESP32; Voltage: 5V).'),
    ("customer_price", "Yes", "Retail price for customers (e.g., 2499.00)."),
    ("dealer_price", "Yes", "Wholesale price for dealers (e.g., 1850.00)."),
    ("gst_rate", "No", "GST percentage (defaults to 18.00)."),
    ("stock_quantity", "No", "Available stock count (defaults to 0)."),
    ("low_stock_threshold", "No", "Low stock warning level (defaults to 5)."),
    ("warranty_months", "No", "Warranty in months (defaults to 12)."),
    ("is_featured", "No", "TRUE or FALSE (defaults to FALSE)."),
    ("is_active", "No", "TRUE or FALSE (defaults to TRUE)."),
]


def _style_header_row(ws, col_count: int):
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    for col_idx in range(1, col_count + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill


def _auto_fit_columns(ws, max_width: int = 50):
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, max_width)


def _parse_bool(val, default: bool = True) -> bool:
    if val is None or str(val).strip() == "":
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y"}


def _parse_specs(raw_val) -> dict:
    if not raw_val or str(raw_val).strip() == "":
        return {}
    text = str(raw_val).strip()
    if text.startswith("{"):
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Specifications JSON must be a key-value object.")
        return parsed

    specs = {}
    for pair in text.split(";"):
        if ":" in pair:
            k, v = pair.split(":", 1)
            if k.strip():
                specs[k.strip()] = v.strip()
    return specs


def generate_product_import_template() -> BytesIO:
    """Generates a sample .xlsx template with a field guidance tab for admins before upload."""
    wb = openpyxl.Workbook()

    # Sheet 1: Sample Data Sheet
    ws = wb.active
    ws.title = "SKM_Products"
    ws.append(EXCEL_HEADERS)
    _style_header_row(ws, len(EXCEL_HEADERS))

    ws.append([
        "SKM-SAMPLE-001",
        "Arduino Uno R3 Development Board",
        "Development Boards",
        "Arduino",
        "85423100",
        "ATmega328P microcontroller board for academic & prototyping use.",
        "Complete Arduino Uno R3 kit with USB cable and pin headers.",
        '{"Microcontroller": "ATmega328P", "Operating Voltage": "5V"}',
        550.00,
        420.00,
        18.00,
        100,
        10,
        12,
        "TRUE",
        "TRUE",
    ])
    _auto_fit_columns(ws, max_width=45)

    # Sheet 2: Instructions & Column Guidance
    guide_ws = wb.create_sheet(title="Instructions_Guide")
    guide_ws.append(["Column Name", "Required", "Format & Guidance"])
    _style_header_row(guide_ws, 3)

    for row_data in FIELD_GUIDANCE:
        guide_ws.append(list(row_data))
    _auto_fit_columns(guide_ws, max_width=75)

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def export_products_from_db(queryset=None) -> BytesIO:
    """Exports actual Product records from the database into an .xlsx file."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SKM_Products_Export"

    ws.append(EXCEL_HEADERS)
    _style_header_row(ws, len(EXCEL_HEADERS))

    products = queryset if queryset is not None else Product.objects.select_related("category").all()
    for p in products:
        ws.append([
            p.sku,
            p.name,
            p.category.name,
            p.brand,
            p.hsn_code,
            p.short_description,
            p.description,
            json.dumps(p.specifications) if p.specifications else "{}",
            float(p.customer_price),
            float(p.dealer_price),
            float(p.gst_rate),
            p.stock_quantity,
            p.low_stock_threshold,
            p.warranty_months,
            "TRUE" if p.is_featured else "FALSE",
            "TRUE" if p.is_active else "FALSE",
        ])

    _auto_fit_columns(ws, max_width=45)

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def import_products_from_excel(file_obj, performed_by=None) -> dict:
    """Reads an uploaded .xlsx file and creates or updates Product rows matched by SKU."""
    wb = openpyxl.load_workbook(file_obj, data_only=True)
    ws = wb["SKM_Products"] if "SKM_Products" in wb.sheetnames else wb.active

    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        raise ValueError("Excel file has no product rows to import.")

    raw_headers = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    required_cols = {"sku", "name", "category_name", "description", "customer_price", "dealer_price"}
    missing_cols = required_cols - set(raw_headers)
    if missing_cols:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_cols))}")

    col_index = {name: idx for idx, name in enumerate(raw_headers) if name}

    def get_val(row, col_name, default=None):
        idx = col_index.get(col_name)
        if idx is None or idx >= len(row):
            return default
        val = row[idx]
        return val if val is not None else default

    created_count = 0
    updated_count = 0
    errors = []
    category_cache = {c.name.lower(): c for c in Category.objects.all()}

    for row_num, row in enumerate(rows[1:], start=2):
        if not any(cell is not None and str(cell).strip() != "" for cell in row):
            continue

        sku = str(get_val(row, "sku", "")).strip()
        name = str(get_val(row, "name", "")).strip()
        cat_name = str(get_val(row, "category_name", "")).strip()

        if not sku or not name or not cat_name:
            errors.append({"row": row_num, "sku": sku, "error": "sku, name, and category_name are required."})
            continue

        try:
            customer_price = Decimal(str(get_val(row, "customer_price", "")))
            dealer_price = Decimal(str(get_val(row, "dealer_price", "")))
            gst_rate = Decimal(str(get_val(row, "gst_rate", "18.00") or "18.00"))
            stock_qty = int(get_val(row, "stock_quantity", 0) or 0)
            low_stock = int(get_val(row, "low_stock_threshold", 5) or 5)
            warranty = int(get_val(row, "warranty_months", 12) or 12)
            specs = _parse_specs(get_val(row, "specifications", "{}"))
        except (InvalidOperation, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append({"row": row_num, "sku": sku, "error": f"Invalid field format: {str(exc)}"})
            continue

        description = str(get_val(row, "description", name)).strip()
        short_desc = str(get_val(row, "short_description", "")).strip()[:300]
        brand = str(get_val(row, "brand", "")).strip()[:100]
        hsn_code = str(get_val(row, "hsn_code", "")).strip()[:20]
        is_featured = _parse_bool(get_val(row, "is_featured"), default=False)
        is_active = _parse_bool(get_val(row, "is_active"), default=True)
        final_stock = max(0, stock_qty)

        with transaction.atomic():
            category = category_cache.get(cat_name.lower())
            if not category:
                category, _ = Category.objects.get_or_create(
                    name=cat_name[:120],
                    defaults={"slug": slugify(cat_name)[:140], "is_active": True},
                )
                category_cache[cat_name.lower()] = category

            defaults = {
                "category": category,
                "name": name[:200],
                "brand": brand,
                "hsn_code": hsn_code,
                "short_description": short_desc,
                "description": description,
                "specifications": specs,
                "customer_price": customer_price,
                "dealer_price": dealer_price,
                "gst_rate": gst_rate,
                "stock_quantity": max(0, stock_qty),
                "low_stock_threshold": max(0, low_stock),
                "warranty_months": max(0, warranty),
                "is_featured": is_featured,
                "is_active": is_active,
            }

            existing = Product.objects.filter(sku__iexact=sku).first()
            if existing:
                old_stock=existing.stock_quantity
                for field, value in defaults.items():
                    setattr(existing, field, value)
                existing.save()
                delta = final_stock - old_stock
                if delta != 0:
                    InventoryLog.objects.create(
                        product=existing,
                        transaction_type=InventoryLog.TransactionType.EXCEL_IMPORT,
                        quantity_change=delta,
                        stock_before=old_stock,
                        stock_after=final_stock,
                        notes=f"Excel bulk update (row {row_num})",
                        performed_by=performed_by,
                    )
                updated_count += 1
            else:
                new_product = Product.objects.create(sku=sku[:60], **defaults)
                if final_stock > 0:
                    InventoryLog.objects.create(
                        product=new_product,
                        transaction_type=InventoryLog.TransactionType.EXCEL_IMPORT,
                        quantity_change=final_stock,
                        stock_before=0,
                        stock_after=final_stock,
                        notes=f"Initial stock via Excel import (row {row_num})",
                        performed_by=performed_by,
                    )
                created_count += 1

    return {
        "created": created_count,
        "updated": updated_count,
        "failed": len(errors),
        "errors": errors,
    }
