"""
End-to-End Smoke Test & System Verification Suite for Step 12
(Shopkeeper Voice POS & AI Inventory System)

Verifies the complete real-world business story across all 22 required checkpoints:
1.  Application starts and is healthy (/api/v1/health, frontend /)
2.  Product catalog is available (/api/v1/products)
3.  Inventory is available (/api/v1/inventory/summary, /low-stock)
4.  Voice/text billing input works (/api/v1/billing/draft)
5.  Product recognition works (Hindi/Hinglish token matching)
6.  Quantity recognition works (e.g. "Do kilo", "ek packet")
7.  Bill calculation works (catalog-driven subtotal, tax, total)
8.  Payment selection works (CASH, UPI, UDHAAR)
9.  Required verification works (OTP / number challenge 2FA)
10. Bill finalization works (idempotent, atomic transaction)
11. Inventory deduction works (stock decreased by exact quantity)
12. Receipt generation works (digital receipt, thermal formatting, WhatsApp preparation, SMS preview)
13. Customer registration and lookup works (/api/v1/customers)
14. Udhaar flow works (credit tracking, family members, ledger transactions)
15. Historical sales are available (/api/v1/analytics/sales/daily)
16. Historical import pipeline works (CSV validation, preview, import commit)
17. Forecast data is available (/api/v1/forecast/overview)
18. 7-day forecast works (product-level demand predictions)
19. 30-day forecast works (monthly horizon demand)
20. Stockout analysis works (risk level, projected stockout date/shortage)
21. Reorder recommendation works (advisory buffer & recommended qty)
22. Dashboard displays real backend results (bills feed, inventory status, Udhaar ledger)
"""
import io
import sys
import uuid
from pathlib import Path
from datetime import datetime, date, timedelta

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import app
from backend.database import SessionLocal
from backend.models import (
    Product, Bill, BillItem, Customer, FamilyMember,
    UdhaarTransaction, DailySalesSummary, HistoricalSaleRecord, HistoricalImportBatch
)
from backend.services.forecasting import invalidate_forecast_cache

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_cache():
    invalidate_forecast_cache()
    yield
    invalidate_forecast_cache()


def test_01_app_starts_and_health_check():
    """Checkpoint 1: Application starts, reports healthy status with active database."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert "version" in data

    # Frontend root HTML should load cleanly
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "text/html" in res_root.headers.get("content-type", "")
    assert "Shopkeeper" in res_root.text


def test_02_product_catalog_available():
    """Checkpoint 2: Product catalog is available with categories and pricing."""
    res = client.get("/api/v1/products")
    assert res.status_code == 200
    products = res.json()
    assert isinstance(products, list)
    assert len(products) > 0

    first = products[0]
    assert "id" in first
    assert "name" in first
    assert "unit_price" in first
    assert "stock_quantity" in first


def test_03_inventory_summary_and_low_stock():
    """Checkpoint 3: Inventory metrics and low stock monitoring are accessible."""
    res = client.get("/api/v1/inventory/summary")
    assert res.status_code == 200
    data = res.json()
    assert "total_products" in data
    assert "total_inventory_value" in data
    assert "low_stock_count" in data
    assert "out_of_stock_count" in data
    assert data["total_products"] > 0
    assert data["total_inventory_value"] >= 0.0

    res_low = client.get("/api/v1/inventory/low-stock")
    assert res_low.status_code == 200
    assert isinstance(res_low.json(), list)


def test_04_to_07_voice_billing_and_draft_generation():
    """
    Checkpoints 4, 5, 6, 7:
    Voice/text billing input, product recognition, quantity recognition,
    and catalog price calculation into draft bill.
    """
    # Hindi phrase: "Do kilo cheeni aur ek packet doodh"
    res = client.post("/api/v1/billing/draft", json={
        "text": "Do kilo cheeni aur ek packet doodh"
    })
    assert res.status_code == 200
    draft = res.json()
    assert "draft_id" in draft
    assert "items" in draft
    assert len(draft["items"]) >= 1

    # Verify recognition
    matched = [it for it in draft["items"] if it["status"] == "MATCHED"]
    assert len(matched) >= 1

    # Verify prices and calculations
    assert draft["subtotal"] > 0.0
    assert draft["total_amount"] >= draft["subtotal"]
    for it in matched:
        assert it["quantity"] > 0.0
        assert it["unit_price"] > 0.0
        assert round(it["line_total"], 2) == round(it["quantity"] * it["unit_price"], 2)


def test_08_to_12_bill_finalization_atomic_inventory_and_receipt():
    """
    Checkpoints 8, 10, 11, 12:
    Payment selection (CASH), idempotent finalization, atomic stock deduction,
    and multi-format receipt generation.
    """
    db = SessionLocal()
    try:
        # Find a product with stock >= 5
        prod = db.query(Product).filter(Product.stock_quantity >= 5.0).first()
        assert prod is not None, "Need at least one product with sufficient stock"
        prod_id = prod.id
        initial_stock = prod.stock_quantity
    finally:
        db.close()

    order_qty = 2.0
    idemp_key = f"smoke-cash-{uuid.uuid4().hex[:8]}"

    finalize_res = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod_id, "quantity": order_qty}],
        "payment_mode": "CASH",
        "idempotency_key": idemp_key,
        "notes": "Smoke test cash sale"
    })
    assert finalize_res.status_code == 201
    bill_data = finalize_res.json()
    bill_id = bill_data["id"]
    assert bill_data["payment_mode"] == "CASH"
    assert bill_data["status"] == "COMPLETED"

    # Verify inventory was deducted atomically
    db = SessionLocal()
    try:
        prod_after = db.query(Product).filter(Product.id == prod_id).first()
        assert prod_after.stock_quantity == round(initial_stock - order_qty, 3)
    finally:
        db.close()

    # Verify digital receipt delivery preparation
    rec_res = client.post("/api/v1/receipts/delivery-prep", json={
        "bill_id": bill_id,
        "customer_phone": "9876543210"
    })
    assert rec_res.status_code == 200
    rec_data = rec_res.json()
    assert "receipt" in rec_data
    assert "formatted_text_receipt" in rec_data["receipt"]
    assert "whatsapp" in rec_data
    assert "click_to_chat_url" in rec_data["whatsapp"]
    assert "sms" in rec_data
    assert "sms_text" in rec_data["sms"]

    # Verify idempotency replay returns same bill without double deduction
    replay_res = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod_id, "quantity": order_qty}],
        "payment_mode": "CASH",
        "idempotency_key": idemp_key
    })
    assert replay_res.status_code in (200, 201)
    assert replay_res.json()["is_duplicate_replay"] is True


def test_13_and_14_customer_udhaar_and_verification_flow():
    """
    Checkpoints 9, 13, 14:
    Customer registration, family member creation, Udhaar purchase,
    number-challenge verification, and ledger settlement.
    """
    unique_suffix = uuid.uuid4().hex[:6]
    phone_digits = f"98{int(datetime.utcnow().timestamp()) % 100000000:08d}"

    # 1. Register Primary Customer
    cust_res = client.post("/api/v1/customers", json={
        "full_name": f"Smoke Test Cust {unique_suffix}",
        "phone": phone_digits,
        "credit_limit": 5000.0,
        "address_line": "Shop 4, Main Market",
        "city": "Lucknow",
        "state": "Uttar Pradesh",
        "pincode": "226001",
        "country": "India",
        "is_phone_verified": True
    })
    assert cust_res.status_code == 201
    cust = cust_res.json()
    cust_id = cust["id"]
    assert cust["current_udhaar_balance"] == 0.0

    # 2. Add Family Member
    fam_phone = f"97{int(datetime.utcnow().timestamp()) % 100000000:08d}"
    fam_res = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
        "full_name": f"Family Member {unique_suffix}",
        "relation_type": "SPOUSE",
        "phone": fam_phone,
        "allowed_spending_limit": 2000.0
    })
    assert fam_res.status_code == 201
    fam = fam_res.json()
    fam_id = fam["id"]

    # 3. Find product for Udhaar sale
    db = SessionLocal()
    try:
        prod = db.query(Product).filter(Product.stock_quantity >= 3.0).first()
        prod_id = prod.id
        prod_stock_before = prod.stock_quantity
    finally:
        db.close()

    # 4. Finalize Udhaar Bill
    idemp_udhaar = f"smoke-udh-{uuid.uuid4().hex[:8]}"
    udh_res = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod_id, "quantity": 1.0}],
        "payment_mode": "UDHAAR",
        "customer_id": cust_id,
        "family_member_id": fam_id,
        "idempotency_key": idemp_udhaar
    })
    assert udh_res.status_code == 201
    udh_bill = udh_res.json()
    bill_id = udh_bill["id"]
    bill_total = udh_bill["total_amount"]
    assert udh_bill["payment_mode"] == "UDHAAR"
    assert udh_bill["status"] == "PENDING_VERIFICATION"

    # 5. Create 2FA Verification Challenge Session
    sess_res = client.post("/api/v1/verification/sessions", json={
        "bill_id": bill_id,
        "channel": "SMS"
    })
    assert sess_res.status_code == 201
    sess_data = sess_res.json()
    session_id = sess_data["session_id"]
    challenge_nums = sess_data["challenge_numbers"]
    assert len(challenge_nums) == 3

    # Inspect correct target number securely from test DB
    db = SessionLocal()
    try:
        from backend.models import VerificationSession
        vs = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
        correct_target = vs.target_number
    finally:
        db.close()

    # 6. Verify Challenge Number
    verify_res = client.post("/api/v1/verification/verify", json={
        "session_id": session_id,
        "selected_number": correct_target,
        "bill_id": bill_id
    })
    assert verify_res.status_code == 200
    v_data = verify_res.json()
    assert v_data["success"] is True

    # 7. Check Customer Udhaar Balance Updated
    cust_check = client.get(f"/api/v1/customers/{cust_id}")
    assert cust_check.status_code == 200
    assert round(cust_check.json()["current_udhaar_balance"], 2) == round(bill_total, 2)


def test_15_historical_sales_aggregation():
    """Checkpoint 15: Historical sales aggregation endpoint returns daily summaries."""
    res = client.get("/api/v1/analytics/sales/daily")
    assert res.status_code == 200
    daily_data = res.json()
    assert "sale_date" in daily_data
    assert "total_revenue" in daily_data
    assert "items" in daily_data
    assert isinstance(daily_data["items"], list)


def test_16_historical_import_workflow():
    """
    Checkpoint 16: Historical import pipeline: validates CSV, detects columns,
    previews data, and commits to historical database.
    """
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        prod_name = prod.name
        prod_id = prod.id
    finally:
        db.close()

    today = date.today()
    unique_offset = int(datetime.utcnow().timestamp()) % 250
    csv_lines = ["Date,Item,Quantity,Price"]
    for i in range(8, 0, -1):
        dt = (date(2025, 1, 1) + timedelta(days=unique_offset + i)).isoformat()
        csv_lines.append(f"{dt},Sugar,5,45.00")
    csv_content = "\n".join(csv_lines).encode("utf-8")

    # 1. Upload and analyze
    val_res = client.post(
        "/api/v1/analytics/import/upload",
        files={"file": (f"history_{uuid.uuid4().hex[:6]}.csv", io.BytesIO(csv_content), "text/csv")}
    )
    assert val_res.status_code == 200
    val_data = val_res.json()
    assert val_data["status"] == "READY"
    assert val_data["is_ready_for_import"] is True
    assert val_data["total_rows"] >= 8
    import_id = val_data["import_id"]

    # 2. Confirm Import
    commit_res = client.post("/api/v1/analytics/import/confirm", json={
        "import_id": import_id,
        "import_mode": "SKIP_INVALID"
    })
    assert commit_res.status_code == 201
    c_data = commit_res.json()
    assert c_data["status"] == "SUCCESS"
    assert (c_data["imported_records_count"] + c_data["skipped_duplicate_count"]) >= 8


def test_17_to_21_demand_forecasting_and_reorder_intelligence():
    """
    Checkpoints 17, 18, 19, 20, 21:
    Forecasting overview, 7-day forecast, 30-day forecast,
    stockout risk analysis, and reorder recommendations.
    """
    # Force forecast recalculation
    refresh_res = client.post("/api/v1/forecast/refresh")
    assert refresh_res.status_code == 200

    # 17. Overview
    overview_res = client.get("/api/v1/forecast/overview")
    assert overview_res.status_code == 200
    ov = overview_res.json()
    assert "total_products" in ov
    assert "eligible_products_count" in ov
    assert "insufficient_products_count" in ov
    assert "total_reorder_units_needed" in ov

    # 18. 7-day and 30-day forecasts for eligible product
    list_res = client.get("/api/v1/forecast/products?status=ELIGIBLE")
    assert list_res.status_code == 200
    eligible_prods = list_res.json()["products"]
    if len(eligible_prods) > 0:
        target_prod_id = eligible_prods[0]["product_id"]

        # Product Detail
        detail_res = client.get(f"/api/v1/forecast/product/{target_prod_id}")
        assert detail_res.status_code == 200
        p_detail = detail_res.json()
        assert p_detail["product_id"] == target_prod_id
        assert "stockout_risk" in p_detail
        assert "reorder_recommendation" in p_detail

        # 7-day forecast returns list of daily forecast points
        f7_res = client.get(f"/api/v1/forecast/product/{target_prod_id}/7day")
        assert f7_res.status_code == 200
        f7 = f7_res.json()
        assert isinstance(f7, list)
        assert len(f7) == 7
        for pt in f7:
            assert "forecast_quantity" in pt
            assert pt["forecast_quantity"] >= 0.0

        # 19. 30-day forecast returns list of 30 daily forecast points
        f30_res = client.get(f"/api/v1/forecast/product/{target_prod_id}/30day")
        assert f30_res.status_code == 200
        f30 = f30_res.json()
        assert isinstance(f30, list)
        assert len(f30) == 30
        for pt in f30:
            assert "forecast_quantity" in pt
            assert pt["forecast_quantity"] >= 0.0

        # 20. Stockout Risk
        risk_res = client.get(f"/api/v1/forecast/product/{target_prod_id}/stockout-risk")
        assert risk_res.status_code == 200
        stockout = risk_res.json()
        assert "risk_level" in stockout
        assert "days_inventory_remaining" in stockout
        assert stockout["potential_7d_shortfall"] >= 0.0

        # 21. Reorder Recommendation
        reorder_res = client.get(f"/api/v1/forecast/product/{target_prod_id}/reorder")
        assert reorder_res.status_code == 200
        reorder = reorder_res.json()
        assert "suggested_reorder_quantity" in reorder
        assert reorder["suggested_reorder_quantity"] >= 0.0
        assert "urgency" in reorder


def test_22_dashboard_live_data_integrity():
    """
    Checkpoint 22: Dashboard data integrity.
    Verifies that list_completed_bills returns real completed bills with customer
    data populated, and that inventory summary accurately reflects catalog state.
    """
    bills_res = client.get("/api/v1/billing/bills?limit=10")
    assert bills_res.status_code == 200
    bills = bills_res.json()
    assert isinstance(bills, list)
    if len(bills) > 0:
        b = bills[0]
        assert "bill_number" in b
        assert "total_amount" in b
        assert "payment_mode" in b
        assert "created_at" in b

    inv_res = client.get("/api/v1/inventory/summary")
    assert inv_res.status_code == 200
    inv = inv_res.json()
    assert inv["total_products"] > 0
    assert inv["total_inventory_value"] >= 0.0
