"""
Step 6 Verification Test Suite
Tests:
- Bill Finalization with atomic inventory deduction
- Transaction persistence in `bills` and `bill_items` tables
- Available stock validation (insufficient stock rejection with 400)
- Input validation (invalid product, zero/negative quantity)
- Idempotency / Duplicate request protection (stock decreases only once)
- Payment mode persistence (CASH, UPI, UDHAAR)
- Dynamic low-stock alert detection upon finalization
- End-to-end flow: Voice/typed input -> Draft Bill -> Finalize -> Database commit -> Stock deduction
"""
import sys
import uuid
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product, Bill, BillItem, Customer

client = TestClient(app)


@pytest.fixture(autouse=True)
def replenish_stock_for_tests():
    """Ensure catalog products have sufficient stock for repeatable testing."""
    db = SessionLocal()
    try:
        products = db.query(Product).all()
        for p in products:
            if p.stock_quantity < 10.0:
                p.stock_quantity = 50.0
        db.commit()
    finally:
        db.close()


def test_successful_bill_finalization():
    """Verify: Draft items finalized -> Bill persisted -> Stock deducted atomically."""
    db = SessionLocal()
    try:
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        milk = db.query(Product).filter(Product.name.like("%Milk%")).first()
        assert sugar and milk

        initial_sugar_stock = sugar.stock_quantity
        initial_milk_stock = milk.stock_quantity

        payload = {
            "items": [
                {"product_id": sugar.id, "quantity": 2.0},
                {"product_id": milk.id, "quantity": 1.0}
            ],
            "payment_mode": "CASH",
            "notes": "Test customer cash sale"
        }

        res = client.post("/api/v1/billing/finalize", json=payload)
        assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
        bill_data = res.json()

        assert bill_data["bill_number"].startswith("BILL-")
        assert bill_data["status"] == "COMPLETED"
        assert bill_data["payment_mode"] == "CASH"
        assert len(bill_data["items"]) == 2

        expected_total = round(2.0 * sugar.unit_price + 1.0 * milk.unit_price, 2)
        assert bill_data["total_amount"] == expected_total

        # Verify database persistence
        db.expire_all()
        persisted_bill = db.query(Bill).filter(Bill.bill_number == bill_data["bill_number"]).first()
        assert persisted_bill is not None
        assert persisted_bill.total_amount == expected_total
        assert len(persisted_bill.items) == 2

        # Verify stock was deducted
        db.refresh(sugar)
        db.refresh(milk)
        assert sugar.stock_quantity == round(initial_sugar_stock - 2.0, 3)
        assert milk.stock_quantity == round(initial_milk_stock - 1.0, 3)

    finally:
        db.close()


def test_insufficient_stock_rejection():
    """Verify: Finalizing with quantity > current stock returns 400 and alters nothing."""
    db = SessionLocal()
    try:
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        initial_stock = sugar.stock_quantity
        initial_bills = db.query(Bill).count()

        payload = {
            "items": [
                {"product_id": sugar.id, "quantity": initial_stock + 500.0}
            ],
            "payment_mode": "CASH"
        }

        res = client.post("/api/v1/billing/finalize", json=payload)
        assert res.status_code == 400, "Expected 400 for excessive stock request"
        assert "Insufficient stock" in res.json()["detail"]

        # Verify zero changes
        db.refresh(sugar)
        assert sugar.stock_quantity == initial_stock
        assert db.query(Bill).count() == initial_bills

    finally:
        db.close()


def test_invalid_product_and_quantity():
    """Verify: Non-existent product ID or negative quantity is rejected."""
    # 1. Non-existent product ID
    res1 = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": 999999, "quantity": 1.0}]
    })
    assert res1.status_code == 400
    assert "does not exist" in res1.json()["detail"]

    # 2. Negative quantity
    res2 = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": 1, "quantity": -5.0}]
    })
    assert res2.status_code == 422, "Expected 422 for negative quantity validation"


def test_idempotency_duplicate_protection():
    """Verify: Re-sending finalize with same idempotency_key returns existing bill without re-deducting stock."""
    db = SessionLocal()
    try:
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        stock_before = sugar.stock_quantity

        idempotency_key = f"IDEMP-TEST-{uuid.uuid4().hex[:8]}"

        payload = {
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "UPI",
            "idempotency_key": idempotency_key
        }

        # First request: should complete and deduct 1.0
        res1 = client.post("/api/v1/billing/finalize", json=payload)
        assert res1.status_code == 201
        data1 = res1.json()
        assert data1["is_duplicate_replay"] is False

        db.refresh(sugar)
        stock_after_first = sugar.stock_quantity
        assert stock_after_first == round(stock_before - 1.0, 3)

        # Second request with SAME idempotency key: should return existing bill without stock deduction!
        res2 = client.post("/api/v1/billing/finalize", json=payload)
        assert res2.status_code in [200, 201]
        data2 = res2.json()
        assert data2["bill_number"] == data1["bill_number"]
        assert data2["is_duplicate_replay"] is True

        # Check stock again: MUST be exactly unchanged!
        db.refresh(sugar)
        assert sugar.stock_quantity == stock_after_first, "Stock was erroneously deducted on duplicate request!"

    finally:
        db.close()


def test_payment_modes_persistence():
    """Verify: CASH, UPI, and UDHAAR payment modes are recorded correctly."""
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        if prod.stock_quantity < 5.0:
            prod.stock_quantity = 50.0
            db.commit()
            db.refresh(prod)

        cust = db.query(Customer).first()
        for mode in ["CASH", "UPI", "UDHAAR"]:
            payload = {
                "items": [{"product_id": prod.id, "quantity": 0.5}],
                "payment_mode": mode,
                "customer_id": cust.id if mode == "UDHAAR" and cust else None
            }
            res = client.post("/api/v1/billing/finalize", json=payload)
            assert res.status_code == 201
            assert res.json()["payment_mode"] == mode

            # Verify in DB
            b = db.query(Bill).filter(Bill.bill_number == res.json()["bill_number"]).first()
            assert b.payment_mode == mode

    finally:
        db.close()


def test_low_stock_detection_upon_finalization():
    """Verify: When stock drops below min_stock_threshold, low_stock_alerts are returned."""
    db = SessionLocal()
    try:
        prod = db.query(Product).filter(Product.id == 4).first() or db.query(Product).first()
        threshold = prod.min_stock_threshold

        # Drop stock to threshold + 1
        prod.stock_quantity = threshold + 1.0
        db.commit()

        # Buy 2 units so remaining stock is threshold - 1 (triggers low stock!)
        payload = {
            "items": [{"product_id": prod.id, "quantity": 2.0}],
            "payment_mode": "CASH"
        }
        res = client.post("/api/v1/billing/finalize", json=payload)
        assert res.status_code == 201
        data = res.json()

        assert len(data["low_stock_alerts"]) >= 1
        alert = data["low_stock_alerts"][0]
        assert alert["product_id"] == prod.id
        assert alert["current_stock"] <= threshold

        # Restore product stock
        prod.stock_quantity = 50.0
        db.commit()

    finally:
        db.close()


def test_end_to_end_pos_flow():
    """
    End-to-End Test:
    Spoken text -> Draft Bill -> Verified stock unchanged -> Finalize -> Database committed -> Stock decreased.
    """
    db = SessionLocal()
    try:
        # Step A: Voice/Typed Input to Draft Bill
        draft_res = client.post("/api/v1/billing/draft", json={
            "text": "Do kilo cheeni aur ek packet doodh"
        })
        assert draft_res.status_code == 200
        draft_data = draft_res.json()
        assert len(draft_data["items"]) == 2

        prod1_id = draft_data["items"][0]["product_id"]
        prod2_id = draft_data["items"][1]["product_id"]
        prod1 = db.query(Product).filter(Product.id == prod1_id).first()
        prod2 = db.query(Product).filter(Product.id == prod2_id).first()

        stock_prod1_start = prod1.stock_quantity
        stock_prod2_start = prod2.stock_quantity

        # Step B: Assert stock is STRICTLY unchanged during draft phase
        db.refresh(prod1)
        db.refresh(prod2)
        assert prod1.stock_quantity == stock_prod1_start
        assert prod2.stock_quantity == stock_prod2_start

        # Step C: Finalize Bill
        finalize_items = [
            {"product_id": item["product_id"], "quantity": item["quantity"]}
            for item in draft_data["items"]
            if item["status"] == "MATCHED"
        ]

        final_res = client.post("/api/v1/billing/finalize", json={
            "items": finalize_items,
            "payment_mode": "UPI",
            "notes": "E2E Voice POS transaction"
        })
        assert final_res.status_code == 201
        final_bill = final_res.json()
        assert final_bill["status"] == "COMPLETED"

        # Step D: Assert stock is decremented ONLY AFTER successful finalization
        db.refresh(prod1)
        db.refresh(prod2)
        assert prod1.stock_quantity == round(stock_prod1_start - 2.0, 3)
        assert prod2.stock_quantity == round(stock_prod2_start - 1.0, 3)

    finally:
        db.close()


if __name__ == "__main__":
    import uuid
    print("Running Step 6 Bill Finalization & Transaction Persistence Tests...")
    test_successful_bill_finalization()
    print("[PASS] Successful Finalization: Bill persisted & stock decremented atomically")
    test_insufficient_stock_rejection()
    print("[PASS] Stock Protection: Insufficient inventory rejected with HTTP 400")
    test_invalid_product_and_quantity()
    print("[PASS] Input Validation: Invalid product ID and negative quantities rejected")
    test_idempotency_duplicate_protection()
    print("[PASS] Idempotency: Duplicate requests do NOT deduct inventory twice")
    test_payment_modes_persistence()
    print("[PASS] Payment Modes: CASH, UPI, and UDHAAR persisted accurately")
    test_low_stock_detection_upon_finalization()
    print("[PASS] Low Stock Trigger: Immediate alert returned when stock falls below threshold")
    test_end_to_end_pos_flow()
    print("[PASS] End-to-End Flow: Voice -> Draft (no stock change) -> Finalize (stock deducted)")
    print("\nALL STEP 6 TESTS PASSED SUCCESSFULLY!")
