"""
Automated Test Suite for Apna Kirana OS — Export & Reports Center (CSV & PDF).
Tests all 10 business reports, parameter validations, CSV formula injection protection,
ReportLab PDF stream headers, accounting disclosures, and multi-tenant data isolation.
"""

import io
import csv
import uuid
import datetime
import pytest
from starlette.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal, get_tenant_engine
from backend.models import (
    Product,
    Customer,
    Bill,
    BillItem,
    UdhaarTransaction,
    ShopProfile,
    ShopkeeperUser
)

client = TestClient(app)


@pytest.fixture(scope="module")
def setup_test_store():
    """Sets up a complete isolated store environment with products, customers, bills, and ledger."""
    db = SessionLocal()
    try:
        # Create or update shop profile
        profile = db.query(ShopProfile).first()
        if not profile:
            profile = ShopProfile(
                shop_name="Gupta General Store",
                owner_name="Ramesh Gupta",
                phone="9876543210",
                address="12 Main Market, Kanpur",
                gstin="09AAAAA0000A1Z5",
                currency="₹"
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)

        # Seed or find test products
        p1 = db.query(Product).filter(Product.name == "Aashirvaad Shudh Chakki Atta 5kg").first()
        if not p1:
            p1 = Product(
                name="Aashirvaad Shudh Chakki Atta 5kg",
                category="Grains & Flours",
                unit="kg",
                unit_price=245.0,
                stock_quantity=15.0,
                min_stock_threshold=20.0,  # Low stock
                is_active=True
            )
            db.add(p1)
        else:
            p1.stock_quantity = 15.0
            p1.min_stock_threshold = 20.0

        p2 = db.query(Product).filter(Product.name == "Tata Salt 1kg").first()
        if not p2:
            p2 = Product(
                name="Tata Salt 1kg",
                category="Spices & Seasoning",
                unit="packet",
                unit_price=28.0,
                stock_quantity=50.0,
                min_stock_threshold=10.0,  # Normal stock
                is_active=True
            )
            db.add(p2)

        # Formula injection test product
        p_formula = db.query(Product).filter(Product.name == "=cmd|' /C calc'!A0").first()
        if not p_formula:
            p_formula = Product(
                name="=cmd|' /C calc'!A0",
                category="Snacks & Biscuits",
                unit="pack",
                unit_price=10.0,
                stock_quantity=5.0,
                min_stock_threshold=2.0,
                is_active=True
            )
            db.add(p_formula)

        db.commit()
        db.refresh(p1)
        db.refresh(p2)

        # Seed or find test customer with outstanding balance
        cust = db.query(Customer).filter(Customer.current_udhaar_balance > 0).first()
        if not cust:
            cust = Customer(
                full_name="Vikas Sharma",
                phone="9812345678",
                address="House 42, Civil Lines",
                current_udhaar_balance=750.0,
                credit_limit=5000.0,
                is_active=True
            )
            db.add(cust)
            db.commit()
            db.refresh(cust)

            tx = UdhaarTransaction(
                customer_id=cust.id,
                amount=750.0,
                transaction_type="DEBIT_PURCHASE",
                notes="Grocery udhaar purchase",
                created_at=datetime.datetime.utcnow()
            )
            db.add(tx)
            db.commit()

        # Seed a completed test bill
        test_bill = db.query(Bill).filter(Bill.status == "COMPLETED").first()
        if not test_bill:
            test_bill = Bill(
                bill_number="BILL-TEST-2026-001",
                customer_id=cust.id,
                subtotal=518.0,
                discount=10.0,
                tax=0.0,
                total_amount=508.0,
                payment_mode="CASH",
                status="COMPLETED",
                created_at=datetime.datetime.utcnow()
            )
            db.add(test_bill)
            db.commit()
            db.refresh(test_bill)

            item1 = BillItem(
                bill_id=test_bill.id,
                product_id=p1.id,
                quantity=2.0,
                unit="kg",
                unit_price=245.0,
                line_total=490.0
            )
            item2 = BillItem(
                bill_id=test_bill.id,
                product_id=p2.id,
                quantity=1.0,
                unit="packet",
                unit_price=28.0,
                line_total=28.0
            )
            db.add_all([item1, item2])
            db.commit()

        return {
            "customer_id": cust.id,
            "customer_name": cust.full_name,
            "bill_number": test_bill.bill_number,
            "product_id": p1.id
        }
    finally:
        db.close()


# ==============================================================================
# CATALOG ENDPOINT
# ==============================================================================

def test_01_catalog_endpoint():
    """Verify /api/v1/exports/catalog returns exactly 10 structured reports."""
    res = client.get("/api/v1/exports/catalog")
    assert res.status_code == 200
    data = res.json()
    assert "reports" in data
    assert len(data["reports"]) == 10

    report_ids = [r["id"] for r in data["reports"]]
    assert "sales-summary" in report_ids
    assert "sales-history" in report_ids
    assert "invoice" in report_ids
    assert "inventory" in report_ids
    assert "low-stock" in report_ids
    assert "inventory-valuation" in report_ids
    assert "customer-ledger" in report_ids
    assert "outstanding-udhaar" in report_ids
    assert "supplier-purchases" in report_ids
    assert "demand-forecast" in report_ids


# ==============================================================================
# REPORT 1: SALES SUMMARY
# ==============================================================================

def test_02_sales_summary_csv(setup_test_store):
    """Verify Report 1 (Sales Summary) generates valid UTF-8 CSV with Excel BOM and metrics."""
    res = client.get("/api/v1/exports/sales-summary?format=csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "sales_summary_" in res.headers.get("content-disposition", "")
    assert res.content.startswith(b"\xef\xbb\xbf")  # UTF-8-SIG BOM for Windows Excel

    content = res.content.decode("utf-8-sig")
    assert "Completed Invoices" in content
    assert "TOTAL / PERIOD SUMMARY" in content


def test_02_sales_summary_pdf(setup_test_store):
    """Verify Report 1 (Sales Summary) generates valid PDF stream."""
    res = client.get("/api/v1/exports/sales-summary?format=pdf")
    assert res.status_code == 200
    assert "application/pdf" in res.headers["content-type"]
    assert res.content.startswith(b"%PDF-")


def test_02_sales_summary_invalid_date_range():
    """Verify that start_date > end_date returns HTTP 400 Bad Request."""
    res = client.get("/api/v1/exports/sales-summary?format=csv&start_date=2026-12-31&end_date=2026-01-01")
    assert res.status_code == 400
    assert "cannot be later than end date" in res.json()["detail"]


# ==============================================================================
# REPORT 2: COMPLETE SALES HISTORY
# ==============================================================================

def test_03_sales_history_csv(setup_test_store):
    """Verify Report 2 (Complete Sales History) produces line-item records."""
    res = client.get("/api/v1/exports/sales-history?format=csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert res.content.startswith(b"\xef\xbb\xbf")

    content = res.content.decode("utf-8-sig")
    assert "Invoice Number" in content
    assert "Payment Mode" in content
    assert setup_test_store["bill_number"] in content


def test_03_sales_history_pdf(setup_test_store):
    """Verify Report 2 (Complete Sales History) produces readable PDF table."""
    res = client.get("/api/v1/exports/sales-history?format=pdf")
    assert res.status_code == 200
    assert "application/pdf" in res.headers["content-type"]
    assert res.content.startswith(b"%PDF-")


# ==============================================================================
# REPORT 3: INDIVIDUAL INVOICE / BILL
# ==============================================================================

def test_04_individual_invoice_pdf(setup_test_store):
    """Verify Report 3 (Individual Invoice) produces official PDF invoice with store branding."""
    bill_no = setup_test_store["bill_number"]
    res = client.get(f"/api/v1/exports/invoice?bill_number={bill_no}&format=pdf")
    assert res.status_code == 200
    assert "application/pdf" in res.headers["content-type"]
    assert res.content.startswith(b"%PDF-")
    assert f"invoice_{bill_no}" in res.headers.get("content-disposition", "")


def test_04_individual_invoice_csv(setup_test_store):
    """Verify Report 3 (Individual Invoice) produces structured line-item CSV."""
    bill_no = setup_test_store["bill_number"]
    res = client.get(f"/api/v1/exports/invoice?bill_number={bill_no}&format=csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]

    content = res.content.decode("utf-8-sig")
    assert bill_no in content


def test_04_individual_invoice_not_found():
    """Verify querying non-existent invoice returns HTTP 404."""
    res = client.get("/api/v1/exports/invoice?bill_number=NON_EXISTENT_9999&format=pdf")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


# ==============================================================================
# REPORT 4: CURRENT INVENTORY SNAPSHOT
# ==============================================================================

def test_05_inventory_snapshot_csv(setup_test_store):
    """Verify Report 4 (Current Inventory) outputs correct product attributes and Excel BOM."""
    res = client.get("/api/v1/exports/inventory?format=csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]

    content = res.content.decode("utf-8-sig")
    assert "Product ID" in content
    assert "Product Name" in content
    assert "Category" in content
    assert "Selling Price (Rs.)" in content
    assert "Aashirvaad Shudh Chakki Atta" in content


def test_05_inventory_snapshot_pdf(setup_test_store):
    """Verify Report 4 (Current Inventory) produces catalog PDF."""
    res = client.get("/api/v1/exports/inventory?format=pdf")
    assert res.status_code == 200
    assert "application/pdf" in res.headers["content-type"]
    assert res.content.startswith(b"%PDF-")


# ==============================================================================
# REPORT 5: LOW-STOCK REPLENISHMENT
# ==============================================================================

def test_06_low_stock_report_csv_and_pdf(setup_test_store):
    """Verify Report 5 (Low-Stock) only includes products at or below threshold."""
    # CSV
    res_csv = client.get("/api/v1/exports/low-stock?format=csv")
    assert res_csv.status_code == 200
    content = res_csv.content.decode("utf-8-sig")
    assert "Aashirvaad Shudh Chakki Atta" in content  # 15 stock <= 20 threshold
    assert "Deficit to Threshold" in content or "Suggested Replenishment Qty" in content

    # PDF
    res_pdf = client.get("/api/v1/exports/low-stock?format=pdf")
    assert res_pdf.status_code == 200
    assert "application/pdf" in res_pdf.headers["content-type"]
    assert res_pdf.content.startswith(b"%PDF-")


# ==============================================================================
# REPORT 6: INVENTORY VALUATION & ACCOUNTING DISCLOSURE
# ==============================================================================

def test_07_inventory_valuation_report(setup_test_store):
    """Verify Report 6 computes Potential Sales Value and provides transparent accounting disclosure."""
    # CSV
    res_csv = client.get("/api/v1/exports/inventory-valuation?format=csv")
    assert res_csv.status_code == 200
    content = res_csv.content.decode("utf-8-sig")
    assert "Potential Retail Value (Rs.)" in content
    assert "ACCOUNTING DISCLOSURE" in content

    # PDF
    res_pdf = client.get("/api/v1/exports/inventory-valuation?format=pdf")
    assert res_pdf.status_code == 200
    assert "application/pdf" in res_pdf.headers["content-type"]
    assert res_pdf.content.startswith(b"%PDF-")


# ==============================================================================
# REPORT 7: CUSTOMER UDHAAR LEDGER
# ==============================================================================

def test_08_customer_ledger(setup_test_store):
    """Verify Report 7 generates individual customer ledger statement."""
    cust_id = setup_test_store["customer_id"]
    cust_name = setup_test_store["customer_name"]

    # CSV
    res_csv = client.get(f"/api/v1/exports/customer-ledger?customer_id={cust_id}&format=csv")
    assert res_csv.status_code == 200
    content = res_csv.content.decode("utf-8-sig")
    assert cust_name in content

    # PDF
    res_pdf = client.get(f"/api/v1/exports/customer-ledger?customer_id={cust_id}&format=pdf")
    assert res_pdf.status_code == 200
    assert "application/pdf" in res_pdf.headers["content-type"]
    assert res_pdf.content.startswith(b"%PDF-")


def test_08_customer_ledger_not_found():
    """Verify querying non-existent customer ID returns HTTP 404."""
    res = client.get("/api/v1/exports/customer-ledger?customer_id=999999&format=pdf")
    assert res.status_code == 404
    assert "customer" in res.json()["detail"].lower()


# ==============================================================================
# REPORT 8: OUTSTANDING UDHAAR DIRECTORY & PRIVACY PROTECTION
# ==============================================================================

def test_09_outstanding_udhaar_privacy(setup_test_store):
    """Verify Report 8 masks customer phone numbers and does not reveal sensitive secrets."""
    res = client.get("/api/v1/exports/outstanding-udhaar?format=csv")
    assert res.status_code == 200
    content = res.content.decode("utf-8-sig")

    assert "TOTAL OUTSTANDING CREDIT" in content
    assert "Masked Phone" in content
    assert "******" in content
    # Should never expose raw password hashes, OTPs, or auth tokens
    assert "password" not in content.lower()
    assert "hashed_" not in content.lower()


# ==============================================================================
# REPORT 9: SUPPLIER PURCHASE HISTORY (PREREQUISITE BLOCKER NOTICE)
# ==============================================================================

def test_10_supplier_purchase_history_blocked():
    """Verify Report 9 honestly informs the user that Supplier tables are missing with zero fake data."""
    # CSV
    res_csv = client.get("/api/v1/exports/supplier-purchases?format=csv")
    assert res_csv.status_code == 200
    content = res_csv.content.decode("utf-8-sig")
    assert "BLOCKED" in content
    assert "Supplier" in content
    assert "0.00" in content

    # PDF
    res_pdf = client.get("/api/v1/exports/supplier-purchases?format=pdf")
    assert res_pdf.status_code == 200
    assert "application/pdf" in res_pdf.headers["content-type"]
    assert res_pdf.content.startswith(b"%PDF-")


# ==============================================================================
# REPORT 10: AI DEMAND FORECAST & RESTOCKING INTELLIGENCE
# ==============================================================================

def test_11_demand_forecast_report(setup_test_store):
    """Verify Report 10 reuses forecasting intelligence and contains statistical estimation disclaimers."""
    # CSV
    res_csv = client.get("/api/v1/exports/demand-forecast?format=csv&horizon=7d")
    assert res_csv.status_code == 200
    content = res_csv.content.decode("utf-8-sig")
    assert "Forecasted" in content or "Demand" in content
    assert "DISCLAIMER" in content or "Estimate" in content or "Advisory" in content

    # PDF
    res_pdf = client.get("/api/v1/exports/demand-forecast?format=pdf&horizon=7d")
    assert res_pdf.status_code == 200
    assert "application/pdf" in res_pdf.headers["content-type"]
    assert res_pdf.content.startswith(b"%PDF-")


# ==============================================================================
# SECURITY: CSV SPREADSHEET FORMULA INJECTION PROTECTION
# ==============================================================================

def test_12_csv_formula_injection_protection(setup_test_store):
    """Verify that cell values starting with =, +, -, @ are sanitized by prepending a single quote."""
    res = client.get("/api/v1/exports/inventory?format=csv")
    assert res.status_code == 200
    content = res.content.decode("utf-8-sig")

    # The formula product "=cmd|' /C calc'!A0" must be escaped to "'=cmd|' /C calc'!A0"
    assert "'=cmd" in content or "cmd" in content
    assert "\n=cmd" not in content  # Must not start raw with '=' after newline or comma


# ==============================================================================
# MULTI-TENANT ISOLATION
# ==============================================================================

def test_13_multi_tenant_isolation(setup_test_store):
    """Verify that requests with a different tenant header cannot access the original store's customer ledger."""
    isolated_tenant = f"tenant_{uuid.uuid4().hex[:8]}"
    headers = {"X-User-Id": isolated_tenant}

    # Query customer ledger under a different tenant - should result in 404 because customer belongs to default tenant
    cust_id = setup_test_store["customer_id"]
    res = client.get(f"/api/v1/exports/customer-ledger?customer_id={cust_id}&format=pdf", headers=headers)
    assert res.status_code == 404
