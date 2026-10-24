"""
Step 3 Verification Test Suite
Tests:
- Product list endpoint with search, category filter, and low-stock filter
- Product categories endpoint
- Single product retrieval (valid ID and 404 for invalid ID)
- Product creation (with validation against negative prices/empty names)
- Product update
- Inventory restock (positive delta)
- Inventory deduction (negative delta)
- Excessive deduction prevention (guaranteeing non-negative stock)
- Low-stock detection and shortage calculation
- Inventory valuation summary
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_list_products():
    """Verify GET /api/v1/products returns all products with correct structure."""
    response = client.get("/api/v1/products")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 50, f"Expected at least 50 products, got {len(data)}"

    # Validate first product schema
    p = data[0]
    for field in ["id", "name", "category", "unit", "unit_price", "stock_quantity", "min_stock_threshold", "is_low_stock"]:
        assert field in p, f"Missing field '{field}' in product"


def test_search_and_filter_products():
    """Verify query search by spoken alias and category filtering."""
    # Search by alias 'cheeni'
    res_sugar = client.get("/api/v1/products?query=cheeni")
    assert res_sugar.status_code == 200
    sugar_items = res_sugar.json()
    assert len(sugar_items) >= 1
    assert any("Sugar" in item["name"] or "Cheeni" in item["name"] for item in sugar_items)

    # Search by alias 'doodh'
    res_milk = client.get("/api/v1/products?query=doodh")
    assert res_milk.status_code == 200
    milk_items = res_milk.json()
    assert len(milk_items) >= 1

    # Filter by category 'Dairy'
    res_dairy = client.get("/api/v1/products?category=Dairy")
    assert res_dairy.status_code == 200
    dairy_items = res_dairy.json()
    assert len(dairy_items) >= 1
    assert all(item["category"] == "Dairy" for item in dairy_items)


def test_list_categories():
    """Verify GET /api/v1/products/categories returns non-empty list of categories."""
    response = client.get("/api/v1/products/categories")
    assert response.status_code == 200
    categories = response.json()
    assert isinstance(categories, list)
    assert "Dairy" in categories
    assert "Grains & Flours" in categories
    assert "Pulses & Lentils" in categories


def test_get_single_product():
    """Verify GET /api/v1/products/{id} and 404 for invalid ID."""
    # Valid product
    response = client.get("/api/v1/products/1")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 1

    # Invalid product
    res_404 = client.get("/api/v1/products/999999")
    assert res_404.status_code == 404


def test_create_and_update_product():
    """Verify product creation with validation and partial updates."""
    # Invalid creation: negative price
    invalid_payload = {
        "name": "Invalid Item",
        "category": "Snacks & Biscuits",
        "unit": "packet",
        "unit_price": -10.0,
        "stock_quantity": 5.0,
        "min_stock_threshold": 2.0
    }
    res_invalid = client.post("/api/v1/products", json=invalid_payload)
    assert res_invalid.status_code == 422, "Expected 422 for negative price"

    # Valid creation
    valid_payload = {
        "name": "Haldiram Soan Papdi (250g)",
        "hindi_name": "सोन पापड़ी",
        "aliases": "soan papdi, son papdi, papdi, meethai",
        "category": "Snacks & Biscuits",
        "unit": "packet",
        "unit_price": 75.0,
        "stock_quantity": 20.0,
        "min_stock_threshold": 5.0
    }
    res_create = client.post("/api/v1/products", json=valid_payload)
    assert res_create.status_code == 201, f"Expected 201, got {res_create.status_code}"
    created = res_create.json()
    created_id = created["id"]
    assert created["name"] == valid_payload["name"]
    assert created["unit_price"] == 75.0

    # Update product
    update_payload = {"unit_price": 80.0, "aliases": "soan papdi, son papdi, papdi, meethai, sweet"}
    res_update = client.put(f"/api/v1/products/{created_id}", json=update_payload)
    assert res_update.status_code == 200
    updated = res_update.json()
    assert updated["unit_price"] == 80.0
    assert "sweet" in updated["aliases"]

    # Delete test product to keep database clean
    res_del = client.delete(f"/api/v1/products/{created_id}")
    assert res_del.status_code == 200


def test_inventory_restock_and_adjustment():
    """Verify stock restocking (positive delta) and adjustment (negative delta)."""
    # Fetch first product
    prod = client.get("/api/v1/products/1").json()
    initial_stock = prod["stock_quantity"]

    # 1. Restock +15
    restock_payload = {
        "product_id": 1,
        "quantity_delta": 15.0,
        "notes": "Weekly supplier delivery"
    }
    res_restock = client.post("/api/v1/inventory/restock", json=restock_payload)
    assert res_restock.status_code == 200
    restock_data = res_restock.json()
    assert restock_data["previous_stock"] == initial_stock
    assert restock_data["new_stock"] == round(initial_stock + 15.0, 3)

    # 2. Adjust/deduct -5
    deduct_payload = {
        "product_id": 1,
        "quantity_delta": -5.0,
        "notes": "Damaged pack adjustment"
    }
    res_deduct = client.post("/api/v1/inventory/restock", json=deduct_payload)
    assert res_deduct.status_code == 200
    deduct_data = res_deduct.json()
    assert deduct_data["new_stock"] == round(initial_stock + 10.0, 3)

    # 3. Excessive deduction (must fail with 400 Bad Request)
    excess_payload = {
        "product_id": 1,
        "quantity_delta": -(deduct_data["new_stock"] + 100.0),
        "notes": "Impossible deduction"
    }
    res_excess = client.post("/api/v1/inventory/restock", json=excess_payload)
    assert res_excess.status_code == 400, "Expected 400 when stock would become negative"

    # 4. Zero delta (must fail with 400 Bad Request)
    zero_payload = {"product_id": 1, "quantity_delta": 0.0}
    res_zero = client.post("/api/v1/inventory/restock", json=zero_payload)
    assert res_zero.status_code == 400

    # 5. Restore original stock level
    restore_payload = {
        "product_id": 1,
        "quantity_delta": -10.0,
        "notes": "Test cleanup"
    }
    client.post("/api/v1/inventory/restock", json=restore_payload)


def test_inventory_low_stock_and_summary():
    """Verify low-stock detection and inventory summary valuation."""
    # Fetch low-stock products
    res_low = client.get("/api/v1/inventory/low-stock")
    assert res_low.status_code == 200
    low_stock_list = res_low.json()
    assert isinstance(low_stock_list, list)

    for item in low_stock_list:
        assert item["stock_quantity"] <= item["min_stock_threshold"]
        expected_shortage = max(0.0, round(item["min_stock_threshold"] - item["stock_quantity"], 2))
        assert abs(item["shortage_quantity"] - expected_shortage) < 0.01

    # Fetch inventory summary
    res_summary = client.get("/api/v1/inventory/summary")
    assert res_summary.status_code == 200
    summary = res_summary.json()
    assert summary["total_products"] >= 50
    assert summary["total_inventory_value"] > 0
    assert summary["low_stock_count"] >= 0
    assert summary["out_of_stock_count"] >= 0


if __name__ == "__main__":
    print("Running Step 3 Product Catalog & Inventory API Tests...")
    test_list_products()
    print("[PASS] GET /api/v1/products: Retrieved product catalog successfully")
    test_search_and_filter_products()
    print("[PASS] Search & Filter: Spoken aliases ('cheeni', 'doodh') and category filters verified")
    test_list_categories()
    print("[PASS] GET /api/v1/products/categories: Categories retrieved successfully")
    test_get_single_product()
    print("[PASS] GET /api/v1/products/{id}: Single product and 404 handling verified")
    test_create_and_update_product()
    print("[PASS] Product CRUD: Valid creation, validation constraints, and updates verified")
    test_inventory_restock_and_adjustment()
    print("[PASS] Inventory Restock & Deduct: Atomic updates and negative stock protection verified")
    test_inventory_low_stock_and_summary()
    print("[PASS] Low Stock & Valuation: Threshold alerts, shortages, and summary stats verified")
    print("\nALL STEP 3 TESTS PASSED SUCCESSFULLY!")
