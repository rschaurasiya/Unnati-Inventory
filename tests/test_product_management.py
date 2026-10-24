"""
Comprehensive automated tests for Product Management functionality (Update 2).
Covers points 1-19:
1. Add product successfully
2. Add product with invalid name fails
3. Add product with invalid price fails
4. Add product with negative stock fails
5. Duplicate/conflicting product behavior is correct
6. Product appears in product list after creation
7. Product search works
8. Product edit works
9. Product price update works
10. Future bill uses updated price
11. Historical transaction prices remain correct
12. Stock update uses existing inventory rules
13. Negative inventory is prevented
14. Product deletion/archive behavior works
15. Product referenced by historical data cannot corrupt history
16. Product referenced by Udhaar data cannot corrupt history
17. Product deletion behavior is correctly reflected in UI/listing
18. Invalid product ID is handled
19. Backend validation works even if frontend validation is bypassed
"""
import uuid
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import Product, Bill, BillItem, Customer, HistoricalSaleRecord, UdhaarTransaction

client = TestClient(app)


def _unique_product_name(base: str = "TestItem") -> str:
    return f"{base}_{uuid.uuid4().hex[:6]}"


def test_01_add_product_successfully():
    """Point 1: Add product successfully with required and optional metadata."""
    name = _unique_product_name("BasmatiRice")
    payload = {
        "name": name,
        "hindi_name": "बासमती चावल",
        "aliases": "chawal, basmati",
        "category": "Grains",
        "unit": "kg",
        "unit_price": 95.50,
        "stock_quantity": 50.0,
        "min_stock_threshold": 10.0
    }
    res = client.post("/api/v1/products", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == name
    assert data["unit_price"] == 95.50
    assert data["stock_quantity"] == 50.0
    assert data["category"] == "Grains"
    assert data["unit"] == "kg"
    assert data["is_active"] is True
    assert data["id"] is not None


def test_02_to_05_add_product_validation_errors():
    """Points 2-5: Invalid name, invalid price, negative stock, and duplicate rejection."""
    # Point 2: Invalid name (empty or whitespace)
    res_name = client.post("/api/v1/products", json={
        "name": "   ",
        "unit_price": 50.0,
        "stock_quantity": 10.0
    })
    assert res_name.status_code == 422
    assert "Product name cannot be empty" in res_name.text

    # Point 3: Invalid price (zero or negative)
    res_price_zero = client.post("/api/v1/products", json={
        "name": _unique_product_name(),
        "unit_price": 0.0,
        "stock_quantity": 10.0
    })
    assert res_price_zero.status_code == 422

    res_price_neg = client.post("/api/v1/products", json={
        "name": _unique_product_name(),
        "unit_price": -15.0,
        "stock_quantity": 10.0
    })
    assert res_price_neg.status_code == 422

    # Point 4: Negative stock
    res_stock = client.post("/api/v1/products", json={
        "name": _unique_product_name(),
        "unit_price": 40.0,
        "stock_quantity": -5.0
    })
    assert res_stock.status_code == 422

    # Point 5: Duplicate name rejection (case-insensitive)
    dup_name = _unique_product_name("UniqueSoap")
    res_orig = client.post("/api/v1/products", json={
        "name": dup_name,
        "unit_price": 25.0,
        "stock_quantity": 100.0
    })
    assert res_orig.status_code == 201

    res_dup = client.post("/api/v1/products", json={
        "name": dup_name.upper(),
        "unit_price": 30.0,
        "stock_quantity": 20.0
    })
    assert res_dup.status_code == 409
    assert "already exists" in res_dup.json()["detail"].lower()


def test_06_to_07_product_listing_and_search():
    """Points 6-7: Product appears in listing and search works across name, hindi, and aliases."""
    name = _unique_product_name("SpecialMasala")
    hindi = "खास मसाला"
    aliases = "garam_masala_special"
    res = client.post("/api/v1/products", json={
        "name": name,
        "hindi_name": hindi,
        "aliases": aliases,
        "category": "Spices",
        "unit_price": 120.0,
        "stock_quantity": 15.0
    })
    assert res.status_code == 201
    prod_id = res.json()["id"]

    # Point 6: Listing contains new product
    list_res = client.get("/api/v1/products")
    assert list_res.status_code == 200
    all_prods = list_res.json()
    found = any(p["id"] == prod_id for p in all_prods)
    assert found is True

    # Point 7: Search by name
    s1 = client.get(f"/api/v1/products/search?q={name[:8]}")
    assert s1.status_code == 200
    assert any(p["id"] == prod_id for p in s1.json())

    # Search by alias
    s2 = client.get("/api/v1/products/search?q=garam_masala")
    assert s2.status_code == 200
    assert any(p["id"] == prod_id for p in s2.json())


def test_08_to_09_product_edit_and_price_patch():
    """Points 8-9: Product edit works and price update via PATCH works."""
    name = _unique_product_name("SunflowerOil")
    res = client.post("/api/v1/products", json={
        "name": name,
        "unit_price": 140.0,
        "stock_quantity": 30.0,
        "category": "Oils"
    })
    prod_id = res.json()["id"]

    # Point 8: PUT update metadata
    put_res = client.put(f"/api/v1/products/{prod_id}", json={
        "category": "Edible Oils",
        "min_stock_threshold": 12.0,
        "unit_price": 145.0
    })
    assert put_res.status_code == 200
    updated = put_res.json()
    assert updated["category"] == "Edible Oils"
    assert updated["min_stock_threshold"] == 12.0
    assert updated["unit_price"] == 145.0

    # Point 9: PATCH /price endpoint
    patch_res = client.patch(f"/api/v1/products/{prod_id}/price", json={
        "unit_price": 155.0
    })
    assert patch_res.status_code == 200
    assert patch_res.json()["unit_price"] == 155.0

    # Invalid PATCH price (<= 0)
    bad_patch = client.patch(f"/api/v1/products/{prod_id}/price", json={
        "unit_price": -5.0
    })
    assert bad_patch.status_code == 422


def test_10_to_11_future_bill_uses_new_price_past_bills_intact():
    """Points 10-11: Price updates affect future bills without modifying past historical transactions."""
    prod_res = client.post("/api/v1/products", json={
        "name": _unique_product_name("WheatFlour"),
        "unit_price": 40.0,
        "stock_quantity": 100.0,
        "category": "Grains"
    })
    prod_id = prod_res.json()["id"]

    # Create bill at original price (40.0 * 2 = 80.0)
    bill1_res = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod_id, "quantity": 2.0}],
        "payment_mode": "CASH"
    })
    assert bill1_res.status_code == 201
    bill1 = bill1_res.json()
    assert bill1["total_amount"] == 80.0
    assert bill1["items"][0]["unit_price"] == 40.0
    assert bill1["items"][0]["line_total"] == 80.0

    # Point 9 & 10: Update product price to 50.0
    client.patch(f"/api/v1/products/{prod_id}/price", json={"unit_price": 50.0})

    # Create second bill: must use updated price (50.0 * 3 = 150.0)
    bill2_res = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod_id, "quantity": 3.0}],
        "payment_mode": "CASH"
    })
    assert bill2_res.status_code == 201
    bill2 = bill2_res.json()
    assert bill2["total_amount"] == 150.0
    assert bill2["items"][0]["unit_price"] == 50.0
    assert bill2["items"][0]["line_total"] == 150.0

    # Point 11: Inspect bill1 in database to verify historical record was NOT altered
    db = SessionLocal()
    try:
        past_item = db.query(BillItem).filter(BillItem.bill_id == bill1["id"]).first()
        assert past_item.unit_price == 40.0
        assert past_item.line_total == 80.0
        past_bill = db.query(Bill).filter(Bill.id == bill1["id"]).first()
        assert past_bill.total_amount == 80.0
    finally:
        db.close()


def test_12_to_13_stock_update_rules_and_negative_stock_prevention():
    """Points 12-13: Stock adjustments obey non-negative rules."""
    prod_res = client.post("/api/v1/products", json={
        "name": _unique_product_name("StockTestItem"),
        "unit_price": 20.0,
        "stock_quantity": 10.0
    })
    prod_id = prod_res.json()["id"]

    # Point 12: Restock via inventory router
    restock_res = client.post("/api/v1/inventory/restock", json={
        "product_id": prod_id,
        "quantity_added": 15.0,
        "reason": "Supplier shipment"
    })
    assert restock_res.status_code == 200
    assert restock_res.json()["new_stock"] == 25.0

    # Adjust stock via inventory router
    adjust_res = client.post("/api/v1/inventory/adjust", json={
        "product_id": prod_id,
        "adjustment": -5.0,
        "reason": "Damaged items write-off"
    })
    assert adjust_res.status_code == 200
    assert adjust_res.json()["new_stock"] == 20.0

    # Point 13: Prevent negative stock (cannot adjust below zero)
    neg_adjust = client.post("/api/v1/inventory/adjust", json={
        "product_id": prod_id,
        "adjustment": -30.0,
        "reason": "Excess deduction"
    })
    assert neg_adjust.status_code == 400
    detail_lower = neg_adjust.json()["detail"].lower()
    assert "insufficient" in detail_lower or "cannot" in detail_lower

    # Prevent sale exceeding stock
    over_sale = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod_id, "quantity": 100.0}],
        "payment_mode": "CASH"
    })
    assert over_sale.status_code == 400
    assert "insufficient" in over_sale.json()["detail"].lower()


def _create_verified_customer(name: str, credit_limit: float = 5000.0) -> dict:
    phone = f"98{int(datetime.utcnow().timestamp() * 1000) % 100000000:08d}"
    res = client.post("/api/v1/customers", json={
        "full_name": name,
        "phone": phone,
        "credit_limit": credit_limit,
        "address_line": "Shop 4, Market Complex",
        "city": "Dehradun",
        "state": "Uttarakhand",
        "pincode": "248001",
        "country": "India",
        "is_phone_verified": True
    })
    return res.json()


def test_14_to_17_safe_delete_and_historical_integrity():
    """Points 14-17: Safe soft-delete preserves foreign-key historical integrity in bills, Udhaar, and analytics."""
    prod_res = client.post("/api/v1/products", json={
        "name": _unique_product_name("HistoricalIntegrityItem"),
        "unit_price": 60.0,
        "stock_quantity": 50.0
    })
    prod_id = prod_res.json()["id"]

    # Create bill and Udhaar transaction referencing this product
    cust = _create_verified_customer(f"Archive Test Cust {uuid.uuid4().hex[:4]}", credit_limit=5000.0)
    cust_id = cust["id"]

    bill_res = client.post("/api/v1/billing/finalize", json={
        "customer_id": cust_id,
        "items": [{"product_id": prod_id, "quantity": 2.0}],
        "payment_mode": "UDHAAR"
    })
    bill_id = bill_res.json()["id"]

    # Complete OTP verification to establish foreign key in Udhaar & Ledger
    sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
    s_id = sess_res.json()["session_id"]
    db = SessionLocal()
    try:
        from backend.models import VerificationSession
        vs = db.query(VerificationSession).filter(VerificationSession.id == s_id).first()
        otp = vs.otp_code
    finally:
        db.close()

    v_res = client.post("/api/v1/verification/verify", json={"session_id": s_id, "otp": otp})
    assert v_res.status_code == 200

    # Also insert a historical sales record referencing this product
    db = SessionLocal()
    try:
        hr = HistoricalSaleRecord(
            row_fingerprint=uuid.uuid4().hex,
            source_file="test_history.csv",
            external_transaction_id=f"HIST-{uuid.uuid4().hex[:6]}",
            sale_date=(datetime.utcnow() - timedelta(days=5)).date(),
            product_id=prod_id,
            raw_product_name="Historical Integrity Item",
            quantity=5.0,
            unit="kg",
            unit_price=60.0,
            total_amount=300.0,
            is_active=True
        )
        db.add(hr)
        db.commit()
    finally:
        db.close()

    # Point 14: Delete product safely (soft-delete / archive)
    del_res = client.delete(f"/api/v1/products/{prod_id}")
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["is_active"] is False
    assert "archived" in del_data["message"].lower()

    # Point 15 & 16: Check that historical bills and historical sales records still exist and are NOT corrupted
    db = SessionLocal()
    try:
        p_db = db.query(Product).filter(Product.id == prod_id).first()
        assert p_db is not None
        assert p_db.is_active is False

        # Bill Item still references product
        bi = db.query(BillItem).filter(BillItem.bill_id == bill_id).first()
        assert bi is not None
        assert bi.product_id == prod_id

        # Historical sale record still references product
        hist = db.query(HistoricalSaleRecord).filter(HistoricalSaleRecord.product_id == prod_id).first()
        assert hist is not None
        assert hist.quantity == 5.0

        # Udhaar transaction still exists
        tx = db.query(UdhaarTransaction).filter(UdhaarTransaction.bill_id == bill_id).first()
        assert tx is not None
        assert tx.amount == 120.0
    finally:
        db.close()

    # Point 17: Product listing reflects archived/inactive status
    list_active = client.get("/api/v1/products?active_only=true")
    assert list_active.status_code == 200
    assert all(p["id"] != prod_id for p in list_active.json())

    list_all = client.get("/api/v1/products?active_only=false")
    assert list_all.status_code == 200
    archived_found = [p for p in list_all.json() if p["id"] == prod_id]
    assert len(archived_found) == 1
    assert archived_found[0]["is_active"] is False


def test_18_to_19_invalid_id_and_backend_validation_enforcement():
    """Points 18-19: Non-existent product ID returns 404, and direct invalid API calls are strictly rejected."""
    # Point 18: Invalid product ID
    non_existent_id = 99999999
    assert client.get(f"/api/v1/products/{non_existent_id}").status_code == 404
    assert client.put(f"/api/v1/products/{non_existent_id}", json={"name": "Ghost"}).status_code == 404
    assert client.patch(f"/api/v1/products/{non_existent_id}/price", json={"unit_price": 50.0}).status_code == 404
    assert client.delete(f"/api/v1/products/{non_existent_id}").status_code == 404

    # Point 19: Backend validation works even if frontend validation bypassed
    # Case: negative min_stock_threshold
    bad_thresh = client.post("/api/v1/products", json={
        "name": _unique_product_name(),
        "unit_price": 50.0,
        "stock_quantity": 10.0,
        "min_stock_threshold": -2.0
    })
    assert bad_thresh.status_code == 422

    # Case: empty string category or invalid structure
    bad_put = client.put(f"/api/v1/products/1", json={
        "unit_price": -10.0
    })
    assert bad_put.status_code == 422
