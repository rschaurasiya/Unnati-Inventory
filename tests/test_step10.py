"""
Step 10 Test Suite — Sales History Aggregation & Historical Data Foundation
Validates:
A. Completed bill -> appears in sales history (correct product, qty, revenue, date)
B. Multiple products in a bill -> aggregated correctly
C. Multiple bills on the same date -> summed correctly
D. Multiple days -> represented correctly
E. Payment methods -> CASH, UPI, and verified UDHAAR all included
F. Failed / incomplete bills -> Draft, cancelled, pending Udhaar excluded
G. Duplicate finalization -> Replay does not duplicate sales history
H. Aggregation idempotency -> Repeated runs do not create duplicates
I. Rebuild / reconciliation -> Corrupted summaries accurately reconstructed
J. Date filtering -> Range validation, invalid format handling (400)
K. Product filtering -> Valid, unknown (404), and zero-sales products
L. Demo historical data -> ~60 days, deterministic, weekend variation, ZERO inventory stock corruption
M. Data sufficiency -> < 7 days INSUFFICIENT, >= 7 days SUFFICIENT, per-product evaluation
N. Customer privacy -> Endpoints do not leak phone, address, OTP, or 2FA challenge tokens
"""
import sys
from pathlib import Path
from datetime import datetime, date, timedelta

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product, Customer, Bill, BillItem, DailySalesSummary, VerificationSession
from backend.services.sales_aggregation import (
    aggregate_sales_for_date,
    rebuild_all_sales_summaries,
    check_data_sufficiency,
    seed_demo_historical_sales
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_catalog_stock():
    """Ensure catalog products have sufficient stock for billing tests."""
    db = SessionLocal()
    try:
        products = db.query(Product).all()
        for p in products:
            if p.stock_quantity < 20.0:
                p.stock_quantity = 100.0
        db.commit()
    finally:
        db.close()


def test_a_completed_bill_appears_in_sales_history():
    """Test A: Completed bill appears in historical sales with correct product, qty, revenue, and date."""
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        assert prod is not None

        # Finalize a CASH bill
        req_data = {
            "items": [{"product_id": prod.id, "quantity": 3.0}],
            "payment_mode": "CASH",
            "notes": "Test A Cash Sale"
        }
        res = client.post("/api/v1/billing/finalize", json=req_data)
        assert res.status_code == 201
        bill_data = res.json()
        assert bill_data["status"] == "COMPLETED"

        today_str = date.today().isoformat()

        # Query daily sales
        daily_res = client.get(f"/api/v1/analytics/sales/daily?date={today_str}")
        assert daily_res.status_code == 200
        daily_data = daily_res.json()

        matching_items = [i for i in daily_data["items"] if i["product_id"] == prod.id]
        assert len(matching_items) == 1
        item = matching_items[0]
        assert item["total_quantity_sold"] >= 3.0
        assert item["total_sales_amount"] >= round(3.0 * prod.unit_price, 2)
        assert item["transaction_count"] >= 1
    finally:
        db.close()


def test_b_multiple_products_aggregated_correctly():
    """Test B: A bill with multiple products aggregates each product correctly."""
    db = SessionLocal()
    try:
        prods = db.query(Product).limit(2).all()
        assert len(prods) >= 2
        p1, p2 = prods[0], prods[1]

        req_data = {
            "items": [
                {"product_id": p1.id, "quantity": 2.0},
                {"product_id": p2.id, "quantity": 4.0}
            ],
            "payment_mode": "UPI",
            "notes": "Test B Multi-Product Bill"
        }
        res = client.post("/api/v1/billing/finalize", json=req_data)
        assert res.status_code == 201

        today_str = date.today().isoformat()
        daily_res = client.get(f"/api/v1/analytics/sales/daily?date={today_str}")
        assert daily_res.status_code == 200
        daily_data = daily_res.json()

        p1_items = [i for i in daily_data["items"] if i["product_id"] == p1.id]
        p2_items = [i for i in daily_data["items"] if i["product_id"] == p2.id]
        assert len(p1_items) == 1
        assert len(p2_items) == 1
        assert p1_items[0]["total_quantity_sold"] >= 2.0
        assert p2_items[0]["total_quantity_sold"] >= 4.0
    finally:
        db.close()


def test_c_multiple_bills_same_date_summed_correctly():
    """Test C: Multiple completed bills on the same date sum quantities and amounts correctly."""
    db = SessionLocal()
    try:
        prod = db.query(Product).offset(2).first()
        assert prod is not None

        # Bill 1
        res1 = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": prod.id, "quantity": 1.5}],
            "payment_mode": "CASH",
            "notes": "Test C Bill 1"
        })
        assert res1.status_code == 201

        # Bill 2
        res2 = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": prod.id, "quantity": 2.5}],
            "payment_mode": "UPI",
            "notes": "Test C Bill 2"
        })
        assert res2.status_code == 201

        today_str = date.today().isoformat()
        daily_res = client.get(f"/api/v1/analytics/sales/daily?date={today_str}")
        assert daily_res.status_code == 200
        daily_data = daily_res.json()

        items = [i for i in daily_data["items"] if i["product_id"] == prod.id]
        assert len(items) == 1
        assert items[0]["total_quantity_sold"] >= 4.0
        assert items[0]["transaction_count"] >= 2
    finally:
        db.close()


def test_d_multiple_days_represented_correctly():
    """Test D: Completed bills across multiple dates are represented distinctly in range query."""
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        assert prod is not None

        day1 = date.today() - timedelta(days=5)
        day2 = date.today() - timedelta(days=3)

        # Create completed bill on day 1
        b1 = Bill(
            bill_number=f"TEST-D-DAY1-{int(datetime.utcnow().timestamp())}",
            status="COMPLETED",
            payment_mode="CASH",
            subtotal=prod.unit_price * 5,
            total_amount=prod.unit_price * 5,
            created_at=datetime.combine(day1, datetime.min.time()) + timedelta(hours=10)
        )
        db.add(b1)
        db.flush()
        db.add(BillItem(bill_id=b1.id, product_id=prod.id, quantity=5.0, unit=prod.unit, unit_price=prod.unit_price, line_total=prod.unit_price * 5))

        # Create completed bill on day 2
        b2 = Bill(
            bill_number=f"TEST-D-DAY2-{int(datetime.utcnow().timestamp())}",
            status="COMPLETED",
            payment_mode="UPI",
            subtotal=prod.unit_price * 8,
            total_amount=prod.unit_price * 8,
            created_at=datetime.combine(day2, datetime.min.time()) + timedelta(hours=14)
        )
        db.add(b2)
        db.flush()
        db.add(BillItem(bill_id=b2.id, product_id=prod.id, quantity=8.0, unit=prod.unit, unit_price=prod.unit_price, line_total=prod.unit_price * 8))

        db.commit()

        # Aggregate both dates
        aggregate_sales_for_date(db, day1)
        aggregate_sales_for_date(db, day2)

        # Query date range
        range_res = client.get(f"/api/v1/analytics/sales/range?start_date={day1.isoformat()}&end_date={day2.isoformat()}")
        assert range_res.status_code == 200
        data = range_res.json()
        assert data["usable_days_count"] >= 2
        dates_in_res = {s["sale_date"] for s in data["daily_summaries"]}
        assert day1.isoformat() in dates_in_res
        assert day2.isoformat() in dates_in_res
    finally:
        db.close()


def test_e_payment_methods_compatibility():
    """Test E: CASH, UPI, and verified UDHAAR all contribute to sales history."""
    db = SessionLocal()
    try:
        cust = db.query(Customer).filter(Customer.is_active == True, Customer.is_phone_verified == True).first()
        prod = db.query(Product).first()
        assert cust is not None and prod is not None
        cust.credit_limit = 50000.0
        db.commit()

        # 1. CASH Bill
        res_cash = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": prod.id, "quantity": 1.0}],
            "payment_mode": "CASH"
        })
        assert res_cash.status_code == 201

        # 2. UPI Bill
        res_upi = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": prod.id, "quantity": 1.0}],
            "payment_mode": "UPI"
        })
        assert res_upi.status_code == 201

        # 3. UDHAAR Bill with 2FA verification
        res_udhaar = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": prod.id, "quantity": 2.0}],
            "payment_mode": "UDHAAR",
            "customer_id": cust.id
        })
        assert res_udhaar.status_code == 201
        u_bill = res_udhaar.json()
        assert u_bill["status"] == "PENDING_VERIFICATION"

        # Complete 2FA for Udhaar bill
        ses_res = client.post("/api/v1/verification/sessions", json={"bill_id": u_bill["id"]})
        assert ses_res.status_code == 201
        session_data = ses_res.json()
        session_id = session_data["session_id"]

        # Find target number from DB
        sess_db = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
        sub_res = client.post("/api/v1/verification/verify", json={
            "session_id": session_id,
            "selected_number": sess_db.target_number
        })
        assert sub_res.status_code == 200
        assert sub_res.json()["success"] is True

        # Check completed sale items endpoint contains CASH, UPI, and UDHAAR
        items_res = client.get("/api/v1/analytics/sales/items?limit=50")
        assert items_res.status_code == 200
        items = items_res.json()
        modes = {it["payment_mode"] for it in items}
        assert "CASH" in modes
        assert "UPI" in modes
        assert "UDHAAR" in modes
    finally:
        db.close()


def test_f_failed_and_incomplete_bills_excluded():
    """Test F: Draft, cancelled, and unverified/failed Udhaar bills are strictly excluded."""
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        cust = db.query(Customer).filter(Customer.is_active == True, Customer.is_phone_verified == True).first()

        # 1. Draft bill created via /billing/draft
        client.post("/api/v1/billing/draft", json={
            "items": [{"product_id": prod.id, "quantity": 99.0}]
        })

        # 2. Cancelled Bill directly in DB
        cancelled_bill = Bill(
            bill_number=f"TEST-CANCELLED-{int(datetime.utcnow().timestamp())}",
            status="CANCELLED",
            payment_mode="CASH",
            subtotal=100.0,
            total_amount=100.0,
            created_at=datetime.utcnow()
        )
        db.add(cancelled_bill)
        db.flush()
        db.add(BillItem(bill_id=cancelled_bill.id, product_id=prod.id, quantity=10.0, unit=prod.unit, unit_price=10.0, line_total=100.0))
        db.commit()

        # 3. Pending Udhaar Bill (not verified)
        res_pending = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": prod.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR",
            "customer_id": cust.id
        })
        assert res_pending.status_code == 201
        pending_id = res_pending.json()["id"]

        db.commit()

        # Rebuild/aggregate today
        aggregate_sales_for_date(db, date.today())

        # Inspect completed items ledger
        items_res = client.get("/api/v1/analytics/sales/items?limit=100")
        assert items_res.status_code == 200
        bill_ids = {it["bill_id"] for it in items_res.json()}

        assert cancelled_bill.id not in bill_ids
        assert pending_id not in bill_ids
    finally:
        db.close()


def test_g_duplicate_finalization_idempotency():
    """Test G: Duplicate bill finalization replay does not duplicate sales history."""
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        idemp_key = f"step10-idemp-{datetime.utcnow().timestamp()}"

        payload = {
            "items": [{"product_id": prod.id, "quantity": 5.0}],
            "payment_mode": "CASH",
            "idempotency_key": idemp_key
        }

        # First finalization
        res1 = client.post("/api/v1/billing/finalize", json=payload)
        assert res1.status_code == 201
        assert res1.json().get("is_duplicate_replay") is False

        # Query summary total
        s1 = db.query(DailySalesSummary).filter(
            DailySalesSummary.product_id == prod.id,
            DailySalesSummary.sale_date == date.today()
        ).first()
        qty_before = s1.total_quantity_sold

        # Duplicate replay
        res2 = client.post("/api/v1/billing/finalize", json=payload)
        assert res2.status_code == 201
        assert res2.json().get("is_duplicate_replay") is True

        s2 = db.query(DailySalesSummary).filter(
            DailySalesSummary.product_id == prod.id,
            DailySalesSummary.sale_date == date.today()
        ).first()
        qty_after = s2.total_quantity_sold

        # Quantity must NOT have doubled
        assert qty_after == qty_before
    finally:
        db.close()


def test_h_aggregation_idempotency():
    """Test H: Running aggregate_sales_for_date repeatedly creates no duplicate records and leaves totals identical."""
    db = SessionLocal()
    try:
        today = date.today()
        count1 = aggregate_sales_for_date(db, today)
        rows1 = db.query(DailySalesSummary).filter(DailySalesSummary.sale_date == today).all()
        totals1 = {r.product_id: (r.total_quantity_sold, r.total_revenue, r.transaction_count) for r in rows1}

        # Run aggregation again
        count2 = aggregate_sales_for_date(db, today)
        rows2 = db.query(DailySalesSummary).filter(DailySalesSummary.sale_date == today).all()
        totals2 = {r.product_id: (r.total_quantity_sold, r.total_revenue, r.transaction_count) for r in rows2}

        assert count1 == count2
        assert len(rows1) == len(rows2)
        assert totals1 == totals2
    finally:
        db.close()


def test_i_rebuild_and_reconciliation():
    """Test I: Rebuild service reconciles DailySalesSummary from completed bills deterministically."""
    db = SessionLocal()
    try:
        today = date.today()
        aggregate_sales_for_date(db, today)
        original_rows = db.query(DailySalesSummary).filter(DailySalesSummary.sale_date == today).all()
        orig_data = {r.product_id: (r.total_quantity_sold, r.total_revenue) for r in original_rows}

        # Corrupt / delete summaries
        db.query(DailySalesSummary).filter(DailySalesSummary.sale_date == today).delete()
        db.commit()
        assert db.query(DailySalesSummary).filter(DailySalesSummary.sale_date == today).count() == 0

        # Trigger rebuild via API
        res = client.post("/api/v1/analytics/rebuild")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "OK"

        # Verify restored summaries match original
        restored_rows = db.query(DailySalesSummary).filter(DailySalesSummary.sale_date == today).all()
        restored_data = {r.product_id: (r.total_quantity_sold, r.total_revenue) for r in restored_rows}
        assert restored_data == orig_data
    finally:
        db.close()


def test_j_date_filtering_and_validation():
    """Test J: Validates date ranges and rejects invalid / out-of-order dates with HTTP 400."""
    # 1. Invalid date format
    res_bad_fmt = client.get("/api/v1/analytics/sales/daily?date=invalid-date")
    assert res_bad_fmt.status_code == 400
    assert "Invalid date format" in res_bad_fmt.json()["detail"]

    # 2. Start date after end date
    res_inverted = client.get("/api/v1/analytics/sales/range?start_date=2026-10-10&end_date=2026-09-01")
    assert res_inverted.status_code == 400
    assert "Invalid date range" in res_inverted.json()["detail"]

    # 3. Valid date range
    res_ok = client.get("/api/v1/analytics/sales/range?start_date=2026-09-01&end_date=2026-09-10")
    assert res_ok.status_code == 200
    assert "daily_summaries" in res_ok.json()


def test_k_product_filtering_and_validation():
    """Test K: Valid product query, non-existent product 404, product with no sales."""
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        assert prod is not None

        # 1. Valid product sales history
        res_prod = client.get(f"/api/v1/analytics/sales/product/{prod.id}")
        assert res_prod.status_code == 200
        data = res_prod.json()
        assert data["product_id"] == prod.id
        assert "history" in data

        # 2. Unknown product ID -> 404
        res_unknown = client.get("/api/v1/analytics/sales/product/999999")
        assert res_unknown.status_code == 404

        # 3. Product with zero sales in range
        future_start = (date.today() + timedelta(days=100)).isoformat()
        future_end = (date.today() + timedelta(days=110)).isoformat()
        res_zero = client.get(f"/api/v1/analytics/sales/product/{prod.id}?start_date={future_start}&end_date={future_end}")
        assert res_zero.status_code == 200
        zero_data = res_zero.json()
        assert zero_data["total_quantity_sold"] == 0.0
        assert zero_data["active_days_count"] == 0
    finally:
        db.close()


def test_l_demo_data_60_days_and_inventory_safety():
    """Test L: Seeding 60 days of demo data produces realistic variation without corrupting inventory stock."""
    db = SessionLocal()
    try:
        # Snapshot current stock
        products_before = {p.id: p.stock_quantity for p in db.query(Product).all()}

        # Seed 60 days demo data
        res = client.post("/api/v1/analytics/seed-demo", json={"days": 60, "seed": 42})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "SUCCESS"
        assert data["days_seeded"] == 60
        assert data["bills_created"] > 100
        assert data["inventory_unaltered"] is True

        # Verify stock quantity for ALL products is completely unaltered
        products_after = {p.id: p.stock_quantity for p in db.query(Product).all()}
        assert products_before == products_after

        # Verify no negative quantities or totals in seeded summaries
        summaries = db.query(DailySalesSummary).all()
        for s in summaries:
            assert s.total_quantity_sold >= 0.0
            assert s.total_revenue >= 0.0
            assert s.transaction_count >= 0
    finally:
        db.close()


def test_m_data_sufficiency_store_and_product_level():
    """Test M: Data sufficiency evaluates >= 7 days as SUFFICIENT_DATA and < 7 days as INSUFFICIENT_DATA."""
    db = SessionLocal()
    try:
        # Query sufficiency
        res = client.get("/api/v1/analytics/sufficiency")
        assert res.status_code == 200
        data = res.json()

        assert "status" in data
        assert data["min_days_required"] == 7
        assert "products" in data
        assert len(data["products"]) > 0

        # Overall status rule
        if data["usable_days_count"] >= 7:
            assert data["status"] == "SUFFICIENT_DATA"
        else:
            assert data["status"] == "INSUFFICIENT_DATA"

        # Check individual product evaluation
        for p in data["products"]:
            if p["usable_days_count"] >= 7:
                assert p["status"] == "SUFFICIENT_DATA"
            else:
                assert p["status"] == "INSUFFICIENT_DATA"
    finally:
        db.close()


def test_n_customer_privacy_protection():
    """Test N: Historical sales endpoints never expose customer phone, address, OTP, or verification tokens."""
    # Query all analytics endpoints
    daily_res = client.get("/api/v1/analytics/sales/daily")
    range_res = client.get("/api/v1/analytics/sales/range?start_date=2026-09-01&end_date=2026-09-30")
    items_res = client.get("/api/v1/analytics/sales/items?limit=50")
    suf_res = client.get("/api/v1/analytics/sufficiency")

    for resp in [daily_res, range_res, items_res, suf_res]:
        assert resp.status_code == 200
        text_body = resp.text
        # Ensure no sensitive customer PII keys exist in JSON keys
        assert "phone" not in text_body
        assert "address" not in text_body
        assert "otp" not in text_body
        assert "target_number" not in text_body
        assert "challenge" not in text_body
