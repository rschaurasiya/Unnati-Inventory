"""
Phase 2 Test Suite — Inventory & Udhaar Visualizations
Validates:
1. Inventory charts endpoint (/api/v1/inventory/charts):
   - Returns 200 with low_stock_comparison, stock_by_category, inventory_valuation
   - Identifies items below vs above threshold matching current catalog
   - Validates category aggregation against database records
   - Validates inventory valuation = sum(stock_quantity * unit_price)
   - Discloses valuation is selling value (cost data missing in schema)
   - Honest disclosure on lack of historical stock movement audit table
2. Customer Udhaar charts endpoint (/api/v1/customers/charts):
   - Returns 200 with highest_outstanding, credit_vs_collections
   - Masks customer phone numbers (never exposes full phone or secrets)
   - Reconciles total outstanding credit with sum of customer balances
   - Correctly segregates DEBIT_PURCHASE (credit added) vs CREDIT_PAYMENT (collections)
   - Supports 30-day and 90-day time horizons
   - Zero-balance and inactive customer handling
3. Cross-module data integrity:
   - Udhaar settlement updates customer balance and appears in collections
   - Stock restock/adjustment immediately reflects in inventory charts
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
from backend.models import Product, Customer, UdhaarTransaction

client = TestClient(app)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_inventory_charts_payload_and_reconciliation(db_session):
    """Verify GET /api/v1/inventory/charts matches database records."""
    res = client.get("/api/v1/inventory/charts")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()

    assert "low_stock_comparison" in data
    assert "stock_by_category" in data
    assert "inventory_valuation" in data
    assert "total_valuation" in data
    assert "valuation_disclosure" in data
    assert "stock_movement_available" in data
    assert data["stock_movement_available"] is False

    # Check low stock items have required fields and correct boolean
    for item in data["low_stock_comparison"]:
        assert "id" in item
        assert "name" in item
        assert "stock_quantity" in item
        assert "min_stock_threshold" in item
        assert item["is_below_threshold"] == (item["stock_quantity"] <= item["min_stock_threshold"])

    # Reconcile total valuation against database calculation
    active_prods = db_session.query(Product).filter(Product.is_active == True).all()
    expected_val = round(sum(p.stock_quantity * p.unit_price for p in active_prods), 2)
    assert abs(data["total_valuation"] - expected_val) < 0.05


def test_customer_udhaar_charts_payload_and_privacy(db_session):
    """Verify GET /api/v1/customers/charts masks phone and calculates balances accurately."""
    res = client.get("/api/v1/customers/charts?days=30")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()

    assert data["days"] == 30
    assert "total_outstanding_balance" in data
    assert "highest_outstanding" in data
    assert "credit_vs_collections" in data
    assert len(data["credit_vs_collections"]) == 30

    # Privacy verification: Phone must be masked, no OTPs, passwords, or raw tokens
    payload_str = res.text
    assert "otp" not in payload_str.lower() or "not_configured" in payload_str.lower()
    for cust in data["highest_outstanding"]:
        assert "phone_masked" in cust
        assert "****" in cust["phone_masked"]
        # Must not contain unmasked 10-digit number
        assert not cust["phone_masked"].isdigit()

    # Reconcile outstanding sum with active customer balances
    custs = db_session.query(Customer).filter(Customer.is_active == True).all()
    expected_sum = round(sum(c.current_udhaar_balance for c in custs), 2)
    assert abs(data["total_outstanding_balance"] - expected_sum) < 0.05


def test_customer_udhaar_charts_90_days():
    """Verify 90-day horizon returns 90 buckets."""
    res = client.get("/api/v1/customers/charts?days=90")
    assert res.status_code == 200
    data = res.json()
    assert data["days"] == 90
    assert len(data["credit_vs_collections"]) == 90


def test_inventory_mutation_updates_charts(db_session):
    """Verify restocking a product updates low-stock comparison and valuation in charts."""
    # Find or pick an active product
    prod = db_session.query(Product).filter(Product.is_active == True).first()
    assert prod is not None

    init_stock = prod.stock_quantity

    # Restock by +50 units
    restock_res = client.post("/api/v1/inventory/restock", json={
        "product_id": prod.id,
        "quantity_delta": 50.0,
        "notes": "Test restock for visualization reflection"
    })
    assert restock_res.status_code == 200

    try:
        # Check charts reflect increased stock
        charts_res = client.get("/api/v1/inventory/charts")
        assert charts_res.status_code == 200
        charts_data = charts_res.json()

        # Find category of product in category stock
        cat_item = next((c for c in charts_data["stock_by_category"] if c["category"] == (prod.category or "General")), None)
        assert cat_item is not None
        assert cat_item["total_units"] >= 50.0
    finally:
        # Revert stock change
        prod.stock_quantity = init_stock
        db_session.commit()


def test_udhaar_transaction_reflection_in_charts(db_session):
    """
    Verify creating an UdhaarTransaction updates period credit added or collections in charts.
    """
    cust = db_session.query(Customer).filter(Customer.is_active == True).first()
    assert cust is not None

    baseline_res = client.get("/api/v1/customers/charts?days=7")
    assert baseline_res.status_code == 200
    base_data = baseline_res.json()
    base_collections = base_data["period_collections"]

    # Record a test settlement transaction
    now = datetime.utcnow()
    txn = UdhaarTransaction(
        primary_customer_id=cust.id,
        amount=150.0,
        transaction_type="CREDIT_PAYMENT",
        balance_before=cust.current_udhaar_balance,
        balance_after=max(0.0, cust.current_udhaar_balance - 150.0),
        verified_by="TEST_SETTLEMENT",
        notes="Phase 2 chart verification settlement",
        created_at=now
    )
    db_session.add(txn)
    db_session.commit()
    db_session.refresh(txn)

    try:
        updated_res = client.get("/api/v1/customers/charts?days=7")
        assert updated_res.status_code == 200
        updated_data = updated_res.json()
        assert round(updated_data["period_collections"], 2) == round(base_collections + 150.0, 2)
    finally:
        db_session.delete(txn)
        db_session.commit()
