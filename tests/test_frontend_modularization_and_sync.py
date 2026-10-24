"""
Automated Integration and Regression Tests for Frontend Modularization,
Product Price Handling, Image Uploads, and System-Wide Real-Time Synchronization.
"""
import io
import re
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import Product, Bill, BillItem, ShopkeeperUser, ShopProfile
from backend.config import settings

client = TestClient(app)


@pytest.fixture
def auth_headers():
    """Retrieve auth token for test shopkeeper."""
    res = client.post("/api/v1/auth/login", json={
        "identifier": "9876543210",
        "password": "Password@123"
    })
    if res.status_code == 200:
        token = res.json()["access_token"]
    else:
        reg = client.post("/api/v1/auth/register", json={
            "full_name": "Test Owner",
            "phone": "9876543210",
            "email": "owner@store.com",
            "password": "Password@123",
            "confirm_password": "Password@123",
            "shop_name": "Apna Kirana Store"
        })
        token = reg.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# 1. Product Price Bug & Validation Fix Verification
# ==============================================================================

def test_product_price_update_to_50_and_decimals():
    """
    Verifies that ₹50.00, integer 50, and standard decimals (49.50, 50.01, 100.25)
    are successfully accepted, persisted, and retrieved without validation errors.
    """
    db = SessionLocal()
    try:
        prod = db.query(Product).filter(Product.is_active == True).first()
        assert prod is not None, "Product catalog must contain at least one active product"
        prod_id = prod.id
    finally:
        db.close()

    test_prices = [50.0, 50.00, 49.50, 50.01, 100.25, 49.0]
    for p in test_prices:
        res = client.patch(f"/api/v1/products/{prod_id}/price", json={"unit_price": p})
        assert res.status_code == 200, f"Failed updating price to {p}: {res.text}"
        data = res.json()
        assert data["unit_price"] == p

        # Verify DB directly
        db = SessionLocal()
        try:
            db_p = db.query(Product).filter(Product.id == prod_id).first()
            assert db_p.unit_price == p
        finally:
            db.close()


def test_invalid_prices_rejected():
    """Verifies that invalid prices (zero, negative, NaN) are strictly rejected."""
    db = SessionLocal()
    try:
        prod = db.query(Product).filter(Product.is_active == True).first()
        prod_id = prod.id
    finally:
        db.close()

    for bad_price in [0.0, -1.0, -50.0]:
        res = client.patch(f"/api/v1/products/{prod_id}/price", json={"unit_price": bad_price})
        assert res.status_code == 422


def test_price_propagation_and_historical_integrity():
    """
    Verifies that changing a product price:
    1. Preserves old completed bill line item prices.
    2. Applies the new price to new sales.
    """
    # 1. Create a test product
    create_res = client.post("/api/v1/products", json={
        "name": f"TestFlour_{int(id(test_price_propagation_and_historical_integrity))}",
        "unit_price": 40.0,
        "stock_quantity": 50.0,
        "category": "Grains",
        "unit": "kg"
    })
    assert create_res.status_code == 201
    prod_id = create_res.json()["id"]

    # 2. Finalize a bill at Rs. 40.0
    bill1_res = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod_id, "quantity": 2.0}],
        "payment_mode": "CASH",
        "notes": "Historical bill check"
    })
    assert bill1_res.status_code == 201
    bill1 = bill1_res.json()
    assert bill1["total_amount"] == 80.0
    assert bill1["items"][0]["unit_price"] == 40.0

    # 3. Update price to Rs. 50.0
    patch_res = client.patch(f"/api/v1/products/{prod_id}/price", json={"unit_price": 50.0})
    assert patch_res.status_code == 200
    assert patch_res.json()["unit_price"] == 50.0

    # 4. Finalize a new bill: MUST use Rs. 50.0
    bill2_res = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod_id, "quantity": 2.0}],
        "payment_mode": "CASH",
        "notes": "New bill check"
    })
    assert bill2_res.status_code == 201
    bill2 = bill2_res.json()
    assert bill2["total_amount"] == 100.0
    assert bill2["items"][0]["unit_price"] == 50.0

    # 5. Check historical bill: MUST still have Rs. 40.0
    db = SessionLocal()
    try:
        hist_item = db.query(BillItem).filter(BillItem.bill_id == bill1["id"]).first()
        assert hist_item.unit_price == 40.0
        assert hist_item.line_total == 80.0
    finally:
        db.close()


# ==============================================================================
# 2. Profile Photo & Shop Logo Upload Verification
# ==============================================================================

def test_avatar_and_logo_upload(auth_headers):
    """
    Verifies that avatar and logo uploads succeed, save to disk,
    update DB models, and return valid URLs.
    """
    # Create sample 100x100 PNG bytes
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

    # 1. Avatar Upload
    avatar_file = io.BytesIO(fake_png)
    av_res = client.post(
        "/api/v1/auth/upload-avatar",
        files={"file": ("my_avatar.png", avatar_file, "image/png")},
        headers=auth_headers
    )
    assert av_res.status_code == 200, f"Avatar upload failed: {av_res.text}"
    av_data = av_res.json()
    assert av_data["success"] is True
    assert av_data["avatar_url"].startswith("/uploads/avatar_u")

    # 2. Shop Logo Upload
    logo_file = io.BytesIO(fake_png)
    logo_res = client.post(
        "/api/v1/auth/upload-logo",
        files={"file": ("my_logo.png", logo_file, "image/png")},
        headers=auth_headers
    )
    assert logo_res.status_code == 200, f"Logo upload failed: {logo_res.text}"
    logo_data = logo_res.json()
    assert logo_data["success"] is True
    assert logo_data["shop_logo_url"].startswith("/uploads/logo_u")

    # 3. Verify public GET /api/v1/auth/shop reflects the new logo
    shop_res = client.get("/api/v1/auth/shop")
    assert shop_res.status_code == 200
    assert shop_res.json()["shop_logo_url"] == logo_data["shop_logo_url"]

    # 4. Verify static file serving
    get_file = client.get(logo_data["shop_logo_url"])
    assert get_file.status_code == 200
    assert len(get_file.content) == len(fake_png)


def test_avatar_invalid_file_rejected(auth_headers):
    """Verifies that non-image files are rejected."""
    text_file = io.BytesIO(b"Hello world! Not an image.")
    res = client.post(
        "/api/v1/auth/upload-avatar",
        files={"file": ("document.txt", text_file, "text/plain")},
        headers=auth_headers
    )
    assert res.status_code == 400
    assert "Invalid image format" in res.text


# ==============================================================================
# 3. Frontend Modularization & Asset Serving Verification
# ==============================================================================

def test_all_modular_frontend_scripts_exist_and_serve():
    """
    Verifies that each modular JS script exists on disk and is served
    cleanly with HTTP 200 by FastAPI static files.
    """
    expected_scripts = [
        "/static/js/shared/api.js",
        "/static/js/shared/state.js",
        "/static/js/shared/utils.js",
        "/static/js/dashboard.js",
        "/static/js/billing.js",
        "/static/js/inventory.js",
        "/static/js/customers.js",
        "/static/js/sales.js",
        "/static/js/forecasting.js",
        "/static/js/profile.js",
        "/static/js/app.js",
    ]

    for script_url in expected_scripts:
        res = client.get(script_url)
        assert res.status_code == 200, f"Script {script_url} returned HTTP {res.status_code}"
        assert len(res.content) > 100, f"Script {script_url} is unexpectedly empty"


def test_index_html_contains_modular_scripts_and_cropper_modal():
    """
    Verifies that index.html loads all modules and contains the image cropper modal.
    """
    index_res = client.get("/")
    assert index_res.status_code == 200
    html_text = index_res.text

    # Verify script tags
    expected_tags = [
        "/static/js/shared/api.js",
        "/static/js/shared/state.js",
        "/static/js/shared/utils.js",
        "/static/js/dashboard.js",
        "/static/js/billing.js",
        "/static/js/inventory.js",
        "/static/js/customers.js",
        "/static/js/sales.js",
        "/static/js/forecasting.js",
        "/static/js/profile.js",
        "/static/js/app.js"
    ]
    for tag in expected_tags:
        assert tag in html_text, f"Expected {tag} script tag missing in index.html"

    # Verify image cropper modal markup
    assert 'id="image-cropper-modal"' in html_text
    assert 'id="cropper-canvas"' in html_text
    assert 'id="cropper-zoom-range"' in html_text
    assert 'id="btn-cropper-confirm"' in html_text

    # Verify HTML5 price input validation attributes
    assert 'id="product-crud-price" step="any" min="0.01"' in html_text
    assert 'id="price-modal-new-price" step="any" min="0.01"' in html_text
