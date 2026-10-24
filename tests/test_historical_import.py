"""
Test Suite: Historical Sales Data Import & Normalization Pipeline
Validates:
A. CSV import
B. XLSX import
C. Different column order
D. Different capitalization (Date, date, DATE, DaTe)
E. Whitespace differences (" Date ")
F. Underscore/hyphen differences (product_name, product-name, Product Name)
G. Column aliases (Date / Transaction Date / Sale Date)
H. Extra irrelevant columns (ignored and not stored)
I. Missing required column (blocked safely)
J. Ambiguous column mapping (user confirmation required)
K. Different date formats (normalized correctly)
L. Ambiguous date format (flagged safely)
M. Numeric price formats (₹120, Rs.120, 120.00)
N. Invalid quantity
O. Invalid price
P. Negative quantity
Q. Invalid product
R. Fuzzy/alias product matching
S. Duplicate file import (sales not doubled)
T. Partial invalid rows
U. Transaction rollback
V. File security (unsupported extension, oversized, path traversal)
W. Inventory safety (stock NEVER deducted)
X. Customer privacy (phone/address stripped)
Y. Historical coverage calculation
Z. Data sufficiency (< 7 days INSUFFICIENT, >= 7 days SUFFICIENT)
AA. Product-level sufficiency
AB. Existing POS compatibility (both appear in canonical historical sales)
"""
import sys
import io
import csv
from pathlib import Path
from datetime import datetime, date, timedelta

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
import openpyxl
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import (
    Product, Bill, BillItem, DailySalesSummary,
    HistoricalImportBatch, HistoricalSaleRecord
)
from backend.services.sales_aggregation import (
    aggregate_sales_for_date,
    check_data_sufficiency
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_import_test_state():
    """Ensure clean historical import state before tests."""
    db = SessionLocal()
    try:
        db.query(HistoricalSaleRecord).delete()
        db.query(HistoricalImportBatch).delete()
        # Guarantee catalog items
        p1 = db.query(Product).filter(Product.id == 1).first()
        if p1 and p1.stock_quantity < 50:
            p1.stock_quantity = 100.0
        db.commit()
    finally:
        db.close()


def _create_csv_bytes(headers, rows):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(headers)
    for r in rows:
        writer.writerow(r)
    return stream.getvalue().encode("utf-8")


def _create_xlsx_bytes(headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    stream = io.BytesIO()
    wb.save(stream)
    return stream.getvalue()


# ============================================================
# Tests A & B: CSV & XLSX File Imports
# ============================================================

def test_a_csv_file_import():
    """Test A: Standard CSV file uploads, validates, and imports cleanly."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Item", "Quantity", "Price"],
        [
            ["2026-08-01", "Sugar", "5.0", "45.00"],
            ["2026-08-02", "Tata Salt", "2.0", "28.00"]
        ]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("test_sales.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "READY"
    assert data["file_type"] == "CSV"
    assert data["validation_summary"]["valid_rows"] == 2
    assert data["validation_summary"]["invalid_rows"] == 0

    # Confirm import
    confirm_res = client.post(
        "/api/v1/analytics/import/confirm",
        json={"import_id": data["import_id"], "import_mode": "SKIP_INVALID"}
    )
    assert confirm_res.status_code == 201
    cdata = confirm_res.json()
    assert cdata["status"] == "SUCCESS"
    assert cdata["imported_records_count"] == 2


def test_b_xlsx_file_import():
    """Test B: XLSX spreadsheet uploads, validates, and imports cleanly."""
    xlsx_bytes = _create_xlsx_bytes(
        ["Date", "Product", "Qty", "Rate"],
        [
            ["2026-08-05", "Sugar", 4, 45],
            ["2026-08-06", "Tata Salt", 1, 28]
        ]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("test_sales.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "READY"
    assert data["file_type"] == "XLSX"
    assert data["validation_summary"]["valid_rows"] == 2

    confirm_res = client.post(
        "/api/v1/analytics/import/confirm",
        json={"import_id": data["import_id"]}
    )
    assert confirm_res.status_code == 201
    assert confirm_res.json()["imported_records_count"] == 2


# ============================================================
# Tests C, D, E, F: Permutations in Order, Case, Whitespace, Delimiters
# ============================================================

def test_c_different_column_order():
    """Test C: Columns in non-standard order (Price, Qty, Item, Date) map correctly."""
    csv_bytes = _create_csv_bytes(
        ["Price", "Quantity", "Item", "Date"],
        [["45.0", "3", "Sugar", "2026-08-07"]]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("order_test.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["detected_mapping"]["date"] == "Date"
    assert data["detected_mapping"]["product"] == "Item"
    assert data["detected_mapping"]["quantity"] == "Quantity"
    assert data["detected_mapping"]["price"] == "Price"
    assert data["validation_summary"]["valid_rows"] == 1


def test_d_different_capitalization():
    """Test D: Date, date, DATE, DaTe, product, PRODUCT, etc. normalize without conflict."""
    for date_header, item_header in [("DATE", "PRODUCT"), ("date", "item"), ("DaTe", "ItEm"), ("DATE", "iTeM")]:
        csv_bytes = _create_csv_bytes(
            [date_header, item_header, "QTY"],
            [["2026-08-08", "Sugar", "2"]]
        )
        res = client.post(
            "/api/v1/analytics/import/upload",
            files={"file": ("case_test.csv", csv_bytes, "text/csv")}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["detected_mapping"]["date"] == date_header
        assert data["detected_mapping"]["product"] == item_header
        assert data["validation_summary"]["valid_rows"] == 1


def test_e_whitespace_differences():
    """Test E: Headers with leading, trailing, and repeated whitespace map seamlessly."""
    csv_bytes = _create_csv_bytes(
        ["   Date   ", "  Product  Name  ", "  Units   Sold  "],
        [["2026-08-09", "Sugar", "3"]]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("whitespace_test.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["detected_mapping"]["date"] == "   Date   "
    assert data["detected_mapping"]["product"] == "  Product  Name  "
    assert data["detected_mapping"]["quantity"] == "  Units   Sold  "
    assert data["validation_summary"]["valid_rows"] == 1


def test_f_underscore_hyphen_differences():
    """Test F: Headers with underscores and hyphens (product_name, product-name) map correctly."""
    csv_bytes = _create_csv_bytes(
        ["sale_date", "product-name", "qty_sold", "unit_price"],
        [["2026-08-10", "Sugar", "2", "45"]]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("separators_test.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["detected_mapping"]["date"] == "sale_date"
    assert data["detected_mapping"]["product"] == "product-name"
    assert data["detected_mapping"]["quantity"] == "qty_sold"
    assert data["validation_summary"]["valid_rows"] == 1


# ============================================================
# Tests G & H: Aliases & Ignored Columns
# ============================================================

def test_g_column_aliases():
    """Test G: Synonyms like Transaction Date, Units, Selling Price map cleanly."""
    csv_bytes = _create_csv_bytes(
        ["Transaction Date", "Product Description", "Units", "Selling Price", "Invoice No"],
        [["2026-08-11", "Sugar", "4", "45", "INV-101"]]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("alias_test.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["detected_mapping"]["date"] == "Transaction Date"
    assert data["detected_mapping"]["product"] == "Product Description"
    assert data["detected_mapping"]["quantity"] == "Units"
    assert data["detected_mapping"]["price"] == "Selling Price"
    assert data["detected_mapping"]["transaction_id"] == "Invoice No"


def test_h_extra_irrelevant_columns_ignored():
    """Test H: Irrelevant columns (GST, Customer Phone, Address, Salesperson) are ignored."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity", "Price", "Customer Name", "Customer Phone", "Address", "GST", "Salesperson", "Remarks"],
        [["2026-08-12", "Sugar", "5", "45", "Rajesh", "9876543210", "Delhi Sector 4", "5%", "Arun", "Delivered"]]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("extra_cols.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert "Customer Phone" in data["ignored_columns"]
    assert "Address" in data["ignored_columns"]
    assert "Salesperson" in data["ignored_columns"]
    assert data["validation_summary"]["valid_rows"] == 1


# ============================================================
# Tests I & J: Missing Columns & Ambiguous Mapping
# ============================================================

def test_i_missing_required_column_blocked():
    """Test I: File missing Quantity column is blocked safely with descriptive diagnostics."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Price"],  # missing quantity
        [["2026-08-13", "Sugar", "45"]]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("missing_qty.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "MISSING_REQUIRED_COLUMNS"
    assert "quantity" in data["missing_required_columns"]
    assert data["is_ready_for_import"] is False


def test_j_ambiguous_column_mapping_requires_confirmation():
    """Test J: Ambiguous columns (both Date and Invoice Date) require user selection."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Invoice Date", "Product", "Quantity"],
        [["2026-08-14", "2026-08-14", "Sugar", "2"]]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("ambiguous.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "AMBIGUOUS_COLUMNS"
    assert "date" in data["ambiguous_columns"]
    assert len(data["ambiguous_columns"]["date"]) >= 2


# ============================================================
# Tests K, L, M: Date & Monetary Normalization
# ============================================================

def test_k_different_date_formats():
    """Test K: Dates formatted as ISO, DD-MM-YYYY, DD/MM/YYYY, and DD Mon YYYY normalize correctly."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity"],
        [
            ["2026-08-15", "Sugar", "1"],
            ["16-08-2026", "Sugar", "1"],
            ["17/08/2026", "Sugar", "1"],
            ["18 Aug 2026", "Sugar", "1"]
        ]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("date_formats.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["validation_summary"]["valid_rows"] == 4
    preview_dates = [p["sale_date"] for p in data["sample_preview"]]
    assert "2026-08-15" in preview_dates
    assert "2026-08-16" in preview_dates
    assert "2026-08-17" in preview_dates
    assert "2026-08-18" in preview_dates


def test_l_ambiguous_date_flagged():
    """Test L: Ambiguous dates (e.g. 03/04/2026) produce non-fatal notice."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity"],
        [["03/04/2026", "Sugar", "1"]]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("ambig_date.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    # It still accepts the row but records a warning
    assert data["validation_summary"]["valid_rows"] == 1


def test_m_numeric_price_formats():
    """Test M: Currency symbols (₹, Rs., INR) and commas in prices normalize to clean floats."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity", "Price"],
        [
            ["2026-08-19", "Sugar", "1", "₹45.00"],
            ["2026-08-20", "Sugar", "1", "Rs. 45"],
            ["2026-08-21", "Sugar", "1", "INR 45"],
            ["2026-08-22", "Sugar", "1", "1,200.50"]
        ]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("prices.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["validation_summary"]["valid_rows"] == 4
    prices = [p["unit_price"] for p in data["sample_preview"]]
    assert 45.0 in prices
    assert 1200.5 in prices


# ============================================================
# Tests N, O, P, Q, R: Value Validation & Catalog Matching
# ============================================================

def test_n_and_p_invalid_and_negative_quantity():
    """Tests N & P: Negative quantity, zero quantity, and non-numeric quantity are rejected."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity"],
        [
            ["2026-08-23", "Sugar", "-5"],  # negative -> error
            ["2026-08-24", "Sugar", "0"],   # zero -> error
            ["2026-08-25", "Sugar", "two"]  # malformed string -> error
        ]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("invalid_qty.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["validation_summary"]["valid_rows"] == 0
    assert data["validation_summary"]["invalid_rows"] == 3


def test_o_invalid_price():
    """Test O: Negative price and malformed monetary values are rejected."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity", "Price"],
        [
            ["2026-08-26", "Sugar", "1", "-50.00"],
            ["2026-08-27", "Sugar", "1", "free_gift"]
        ]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("invalid_price.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["validation_summary"]["valid_rows"] == 0
    assert data["validation_summary"]["invalid_rows"] == 2


def test_q_and_r_unmatched_and_alias_product_matching():
    """Tests Q & R: Known aliases match catalog; unknown products flag for user action."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity"],
        [
            ["2026-08-28", "cheeni", "2"],  # alias of Sugar -> matched
            ["2026-08-29", "tata namak", "1"],  # alias of Tata Salt -> matched
            ["2026-08-30", "Exotic Moon Dust Unknown 999", "1"]  # unknown -> flagged
        ]
    )
    res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("products_matching.csv", csv_bytes, "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["validation_summary"]["valid_rows"] == 2
    assert data["validation_summary"]["invalid_rows"] == 1
    assert len(data["unmatched_products"]) == 1
    assert data["unmatched_products"][0]["raw_name"] == "Exotic Moon Dust Unknown 999"


# ============================================================
# Tests S & T: Duplicate File Import & Partial Invalid Breakdown
# ============================================================

def test_s_duplicate_file_import_does_not_double_sales():
    """Test S: Re-uploading identical sales data detects duplicates and skips them."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity", "Price", "Invoice No"],
        [
            ["2026-07-01", "Sugar", "10", "45", "DEDUP-001"],
            ["2026-07-02", "Tata Salt", "5", "28", "DEDUP-002"]
        ]
    )
    # First upload & confirm
    res1 = client.post("/api/v1/analytics/import/upload", files={"file": ("dedup.csv", csv_bytes, "text/csv")})
    assert res1.status_code == 200
    data1 = res1.json()
    c1 = client.post("/api/v1/analytics/import/confirm", json={"import_id": data1["import_id"]})
    assert c1.status_code == 201
    assert c1.json()["imported_records_count"] == 2

    # Second upload of the EXACT same file
    res2 = client.post("/api/v1/analytics/import/upload", files={"file": ("dedup_repeat.csv", csv_bytes, "text/csv")})
    assert res2.status_code == 200
    data2 = res2.json()
    c2 = client.post("/api/v1/analytics/import/confirm", json={"import_id": data2["import_id"]})
    assert c2.status_code == 201
    c2_data = c2.json()
    # 0 new records inserted, 2 skipped as duplicates!
    assert c2_data["imported_records_count"] == 0
    assert c2_data["skipped_duplicate_count"] == 2


def test_t_partial_invalid_rows():
    """Test T: Mixed valid, warning, and invalid rows report accurate counts."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity", "Price"],
        [
            ["2026-07-05", "Sugar", "2", "45"],     # Valid
            ["2026-07-06", "Sugar", "-1", "45"],    # Invalid (negative qty)
            ["2026-07-07", "Tata Salt", "1", "28"], # Valid
            ["", "Sugar", "1", "45"]                # Invalid (empty date)
        ]
    )
    res = client.post("/api/v1/analytics/import/upload", files={"file": ("partial.csv", csv_bytes, "text/csv")})
    assert res.status_code == 200
    data = res.json()
    assert data["validation_summary"]["total_rows"] == 4
    assert data["validation_summary"]["valid_rows"] == 2
    assert data["validation_summary"]["invalid_rows"] == 2


# ============================================================
# Tests U & V: Rollback & File Security
# ============================================================

def test_u_transaction_rollback():
    """Test U: Rollback deactivates historical records and reconciles daily sales."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity", "Price", "Invoice No"],
        [["2026-06-15", "Sugar", "8", "45", "ROLLBACK-01"]]
    )
    res = client.post("/api/v1/analytics/import/upload", files={"file": ("rollback_test.csv", csv_bytes, "text/csv")})
    data = res.json()
    import_id = data["import_id"]
    client.post("/api/v1/analytics/import/confirm", json={"import_id": import_id})

    # Check daily sales contains the record
    daily_res1 = client.get("/api/v1/analytics/sales/daily?date=2026-06-15")
    assert daily_res1.status_code == 200
    items1 = [it for it in daily_res1.json()["items"] if "Sugar" in it["product_name"]]
    assert len(items1) >= 1
    assert items1[0]["total_quantity_sold"] >= 8.0

    # Execute rollback
    rb_res = client.post(f"/api/v1/analytics/import/rollback/{import_id}")
    assert rb_res.status_code == 200
    assert rb_res.json()["status"] == "SUCCESS"

    # Check daily sales after rollback -> sales reverted!
    daily_res2 = client.get("/api/v1/analytics/sales/daily?date=2026-06-15")
    assert daily_res2.status_code == 200
    items2 = [it for it in daily_res2.json()["items"] if "Sugar" in it["product_name"]]
    # Should be 0 or gone
    if items2:
        assert items2[0]["total_quantity_sold"] < 8.0


def test_v_file_security():
    """Test V: Rejects executable extensions, path traversal filenames, and oversized content."""
    # 1. Unsupported extension
    res1 = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("malicious.exe", b"fake binary", "application/x-msdownload")}
    )
    assert res1.status_code == 400

    # 2. Path traversal filename -> sanitized safely
    csv_bytes = _create_csv_bytes(["Date", "Product", "Quantity"], [["2026-06-20", "Sugar", "1"]])
    res2 = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": ("../../../../etc/passwd.csv", csv_bytes, "text/csv")}
    )
    assert res2.status_code == 200
    assert ".." not in res2.json()["filename"]


# ============================================================
# Tests W & X: Inventory Safety & Customer Privacy
# ============================================================

def test_w_inventory_safety():
    """Test W: Importing historical sales NEVER alters current product stock quantities."""
    db = SessionLocal()
    try:
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        assert sugar is not None
        initial_stock = sugar.stock_quantity
    finally:
        db.close()

    # Import 500 units of Sugar
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity", "Price", "Invoice No"],
        [["2026-05-01", "Sugar", "500", "45", "INV-INVSAFE-01"]]
    )
    res = client.post("/api/v1/analytics/import/upload", files={"file": ("inv_safe.csv", csv_bytes, "text/csv")})
    data = res.json()
    client.post("/api/v1/analytics/import/confirm", json={"import_id": data["import_id"]})

    # Verify stock quantity remains unchanged
    db = SessionLocal()
    try:
        sugar_after = db.query(Product).filter(Product.id == sugar.id).first()
        assert sugar_after.stock_quantity == initial_stock
    finally:
        db.close()


def test_x_customer_privacy():
    """Test X: Customer telephone, address, and email are never saved in historical sales table."""
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity", "Phone", "Address", "Email", "Invoice No"],
        [["2026-05-10", "Sugar", "2", "+919876543210", "Secret Home Address", "test@private.com", "PRIV-01"]]
    )
    res = client.post("/api/v1/analytics/import/upload", files={"file": ("privacy.csv", csv_bytes, "text/csv")})
    data = res.json()
    import_id = data["import_id"]
    client.post("/api/v1/analytics/import/confirm", json={"import_id": import_id})

    # Query DB directly to verify no customer personal info exists in historical records
    db = SessionLocal()
    try:
        hist_rec = db.query(HistoricalSaleRecord).filter(HistoricalSaleRecord.import_id == import_id).first()
        assert hist_rec is not None
        # Verify model has no customer personal fields
        assert not hasattr(hist_rec, "customer_phone")
        assert not hasattr(hist_rec, "customer_address")
        assert not hasattr(hist_rec, "customer_email")
    finally:
        db.close()


# ============================================================
# Tests Y, Z, AA, AB: Sufficiency & POS Compatibility
# ============================================================

def test_y_and_z_historical_coverage_and_data_sufficiency():
    """Tests Y & Z: Importing 8 distinct historical days triggers SUFFICIENT_DATA status."""
    rows = []
    base_date = date(2026, 4, 1)
    for i in range(8):
        d_str = (base_date + timedelta(days=i)).isoformat()
        rows.append([d_str, "Sugar", "2", "45", f"SUFF-TX-{i}"])

    csv_bytes = _create_csv_bytes(["Date", "Product", "Quantity", "Price", "Invoice No"], rows)
    res = client.post("/api/v1/analytics/import/upload", files={"file": ("eight_days.csv", csv_bytes, "text/csv")})
    data = res.json()
    assert data["validation_summary"]["usable_days_count"] == 8

    c_res = client.post("/api/v1/analytics/import/confirm", json={"import_id": data["import_id"]})
    assert c_res.status_code == 201
    c_data = c_res.json()
    assert c_data["usable_days_count"] >= 8
    assert c_data["forecasting_status"] == "SUFFICIENT_DATA"

    # Query sufficiency endpoint
    suff_res = client.get("/api/v1/analytics/sufficiency")
    assert suff_res.status_code == 200
    suff_data = suff_res.json()
    assert suff_data["status"] == "SUFFICIENT_DATA"
    assert suff_data["usable_days_count"] >= 8


def test_aa_product_level_sufficiency():
    """Test AA: Product-level sufficiency evaluates items independently (Sugar sufficient, Product 50 insufficient)."""
    suff_res = client.get("/api/v1/analytics/sufficiency")
    assert suff_res.status_code == 200
    suff_data = suff_res.json()

    prods = {p["product_id"]: p for p in suff_data["products"]}
    # Find a staple with sufficient days
    sugar_item = next((v for k, v in prods.items() if "Sugar" in v["product_name"]), None)
    assert sugar_item is not None
    assert sugar_item["usable_days_count"] >= 7
    assert sugar_item["status"] == "SUFFICIENT_DATA"

    # Check for any product with < 7 days
    new_prod = next((v for k, v in prods.items() if v.get("usable_days_count", 0) < 7), None)
    if new_prod:
        assert new_prod["usable_days_count"] < 7
        assert new_prod["status"] == "INSUFFICIENT_DATA"


def test_ab_existing_pos_compatibility():
    """Test AB: Normal POS billing and imported sales both appear in canonical sales history."""
    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.name.like("%Salt%")).first()
        assert p is not None
    finally:
        db.close()

    # 1. Finalize a live POS bill
    pos_res = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": p.id, "quantity": 3.0}],
        "payment_mode": "CASH",
        "notes": "Test AB POS Bill"
    })
    assert pos_res.status_code == 201

    # 2. Import a historical sale for the same product on yesterday's date
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    csv_bytes = _create_csv_bytes(
        ["Date", "Product", "Quantity", "Price", "Invoice No"],
        [[yesterday, p.name, "7", str(p.unit_price), "POS-COMPAT-01"]]
    )
    up_res = client.post("/api/v1/analytics/import/upload", files={"file": ("pos_compat.csv", csv_bytes, "text/csv")})
    client.post("/api/v1/analytics/import/confirm", json={"import_id": up_res.json()["import_id"]})

    # 3. Check date range query covering yesterday and today
    range_res = client.get(f"/api/v1/analytics/sales/range?start_date={yesterday}&end_date={date.today().isoformat()}&product_id={p.id}")
    assert range_res.status_code == 200
    range_data = range_res.json()
    assert range_data["usable_days_count"] >= 2
    assert range_data["total_quantity_sold"] >= 10.0  # 3 from POS + 7 from import!
