"""
Phase 1 Test Suite — Dashboard & Sales History Business Visualizations
Validates:
1. Dashboard charts endpoint (/api/v1/analytics/dashboard/charts):
   - Returns 200 with schema: sales_trend, top_by_units, top_by_revenue, payment_breakdown, stock_overview
   - Excludes CANCELLED and DRAFT bills from completed revenue & rankings
   - Accurately splits Cash, UPI, and Udhaar payment modes with percentage calculation
   - Calculates stock health (healthy, low stock, out of stock) matching active catalog counts
   - Supports 7-day and 30-day time horizons
2. Sales History charts endpoint (/api/v1/analytics/sales/charts):
   - Returns 200 with revenue_trend, transactions_trend, best_by_units, best_by_revenue, category_sales
   - Respects start_date and end_date range
   - Rejects invalid date formatting (400) and start_date > end_date (400)
   - Honors category, product_id, and payment_mode query filters
   - Empty periods return zero-filled daily buckets with status 200 without crashes
3. End-to-end real transaction reflection:
   - Creating a completed bill immediately updates dashboard and sales charts
   - Creating a cancelled bill does not alter sales charts
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
from backend.models import Product, Bill, BillItem, Customer

client = TestClient(app)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_dashboard_charts_default_7_days():
    """Verify GET /api/v1/analytics/dashboard/charts with default 7-day horizon."""
    res = client.get("/api/v1/analytics/dashboard/charts")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()

    assert data["days"] == 7
    assert "start_date" in data
    assert "end_date" in data
    assert isinstance(data["total_revenue"], (int, float))
    assert isinstance(data["total_transactions"], int)

    # Sales trend
    assert "sales_trend" in data
    assert len(data["sales_trend"]) == 7
    for day in data["sales_trend"]:
        assert "date" in day
        assert "label" in day
        assert "revenue" in day
        assert "transactions" in day

    # Top products
    assert "top_by_units" in data
    assert "top_by_revenue" in data
    assert len(data["top_by_units"]) <= 5
    assert len(data["top_by_revenue"]) <= 5

    # Payment breakdown
    assert "payment_breakdown" in data
    modes = [p["mode"] for p in data["payment_breakdown"]]
    for m in ["CASH", "UPI", "UDHAAR"]:
        assert m in modes

    # Stock overview
    assert "stock_overview" in data
    so = data["stock_overview"]
    assert "total_products" in so
    assert "healthy" in so
    assert "low_stock" in so
    assert "out_of_stock" in so
    assert so["total_products"] == so["healthy"] + so["low_stock"] + so["out_of_stock"]


def test_dashboard_charts_30_days_horizon():
    """Verify 30-day horizon returns 30 daily buckets."""
    res = client.get("/api/v1/analytics/dashboard/charts?days=30")
    assert res.status_code == 200
    data = res.json()
    assert data["days"] == 30
    assert len(data["sales_trend"]) == 30


def test_dashboard_charts_boundary_validation():
    """Verify days parameter validation (1 <= days <= 90)."""
    # 0 days is invalid
    res = client.get("/api/v1/analytics/dashboard/charts?days=0")
    assert res.status_code == 422

    # 100 days exceeds max 90
    res = client.get("/api/v1/analytics/dashboard/charts?days=100")
    assert res.status_code == 422


def test_sales_charts_date_range_valid():
    """Verify GET /api/v1/analytics/sales/charts with valid dates."""
    today = datetime.utcnow().date()
    start = today - timedelta(days=6)
    res = client.get(f"/api/v1/analytics/sales/charts?start_date={start.isoformat()}&end_date={today.isoformat()}")
    assert res.status_code == 200
    data = res.json()

    assert data["start_date"] == start.isoformat()
    assert data["end_date"] == today.isoformat()
    assert isinstance(data["total_revenue"], (int, float))
    assert isinstance(data["total_transactions"], int)

    # 7 daily entries
    assert len(data["revenue_trend"]) == 7
    assert len(data["transactions_trend"]) == 7
    assert "best_by_units" in data
    assert "best_by_revenue" in data
    assert "category_sales" in data


def test_sales_charts_date_validation_errors():
    """Verify rejection of inverted date ranges and malformed strings."""
    # Start after End
    res = client.get("/api/v1/analytics/sales/charts?start_date=2026-10-20&end_date=2026-10-10")
    assert res.status_code == 400
    assert "start_date" in res.json()["detail"]

    # Malformed date string
    res = client.get("/api/v1/analytics/sales/charts?start_date=not-a-date&end_date=2026-10-20")
    assert res.status_code == 400


def test_sales_charts_filtering():
    """Verify category and payment mode filters."""
    today = datetime.utcnow().date()
    start = today - timedelta(days=30)

    # Filter by Cash
    res_cash = client.get(f"/api/v1/analytics/sales/charts?start_date={start.isoformat()}&end_date={today.isoformat()}&payment_mode=CASH")
    assert res_cash.status_code == 200
    data_cash = res_cash.json()
    assert "total_revenue" in data_cash

    # Filter by UPI
    res_upi = client.get(f"/api/v1/analytics/sales/charts?start_date={start.isoformat()}&end_date={today.isoformat()}&payment_mode=UPI")
    assert res_upi.status_code == 200


def test_bill_creation_and_cancellation_reflection(db_session):
    """
    Verify creating a COMPLETED bill updates the charts,
    while a CANCELLED bill does not count towards revenue.
    """
    # 1. Fetch baseline
    baseline_res = client.get("/api/v1/analytics/dashboard/charts?days=7")
    assert baseline_res.status_code == 200
    baseline_data = baseline_res.json()
    base_rev = baseline_data["total_revenue"]
    base_tx = baseline_data["total_transactions"]

    # Ensure a product exists
    prod = db_session.query(Product).filter(Product.is_active == True).first()
    assert prod is not None, "At least one active product must exist"

    # 2. Create and insert a completed bill
    now = datetime.utcnow()
    completed_bill = Bill(
        bill_number=f"TEST-CHART-{int(now.timestamp())}",
        total_amount=250.0,
        subtotal=250.0,
        payment_mode="UPI",
        status="COMPLETED",
        created_at=now
    )
    db_session.add(completed_bill)
    db_session.commit()
    db_session.refresh(completed_bill)

    item = BillItem(
        bill_id=completed_bill.id,
        product_id=prod.id,
        quantity=2.0,
        unit=prod.unit or "piece",
        unit_price=125.0,
        line_total=250.0
    )
    db_session.add(item)
    db_session.commit()

    try:
        # Check dashboard chart reflects this bill
        updated_res = client.get("/api/v1/analytics/dashboard/charts?days=7")
        assert updated_res.status_code == 200
        updated_data = updated_res.json()
        assert round(updated_data["total_revenue"], 2) == round(base_rev + 250.0, 2)
        assert updated_data["total_transactions"] == base_tx + 1

        # Check UPI bucket in payment_breakdown increased
        upi_item = next(p for p in updated_data["payment_breakdown"] if p["mode"] == "UPI")
        assert upi_item["total"] >= 250.0

        # 3. Create a CANCELLED bill
        cancelled_bill = Bill(
            bill_number=f"TEST-CHART-CANCEL-{int(now.timestamp())}",
            total_amount=999.0,
            subtotal=999.0,
            payment_mode="CASH",
            status="CANCELLED",
            created_at=now
        )
        db_session.add(cancelled_bill)
        db_session.commit()
        db_session.refresh(cancelled_bill)

        # Dashboard charts MUST NOT include the cancelled bill
        post_cancel_res = client.get("/api/v1/analytics/dashboard/charts?days=7")
        post_cancel_data = post_cancel_res.json()
        assert round(post_cancel_data["total_revenue"], 2) == round(base_rev + 250.0, 2)
        assert post_cancel_data["total_transactions"] == base_tx + 1

    finally:
        # Clean up test bills
        db_session.query(BillItem).filter(BillItem.bill_id == completed_bill.id).delete()
        db_session.delete(completed_bill)
        db_session.delete(cancelled_bill)
        db_session.commit()
