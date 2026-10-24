"""
Automated Test Suite for UI Layout, Image Cropper Preview, Product Archive & Delete,
Bulk Delete of Test Items, and Inventory Click-to-Filter Features.
"""
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product, BillItem, HistoricalSaleRecord, DailySalesSummary, ProductForecast
from backend.config import settings

client = TestClient(app)


def test_1_password_styling_and_cropper_preview_elements():
    """Requirement 1 & 2: Verify CSS and HTML elements for password layout and cropper circular preview."""
    # 1. HTML Verification
    html_path = settings.FRONTEND_DIR / "index.html"
    assert html_path.exists()
    html = html_path.read_text(encoding="utf-8")

    # Re-enter new password inputs & classes
    assert 'id="pwd-confirm"' in html
    assert 'id="pwd-new"' in html
    assert 'class="form-row-2"' in html
    assert 'class="input-with-icon password-input-wrap"' in html

    # Image cropper circular preview options & canvases
    assert 'id="image-cropper-modal"' in html
    assert 'id="btn-preview-circle"' in html
    assert 'id="btn-preview-square"' in html
    assert 'setCropperPreviewMode(\'circle\')' in html
    assert 'id="cropper-preview-canvas"' in html
    assert 'id="cropper-preview-square-canvas"' in html
    assert 'Circular Preview (Profile' in html

    # 2. CSS Verification
    css_path = settings.FRONTEND_DIR / "css" / "style.css"
    assert css_path.exists()
    css = css_path.read_text(encoding="utf-8")

    # Form layout and box-sizing rules
    assert ".form-row-2 > *" in css
    assert "min-width: 0" in css
    assert "box-sizing: border-box" in css
    assert ".password-input-wrap" in css
    assert ".btn-preview-option" in css
    assert ".cropper-preview-options-bar" in css
    assert ".metric-card.clickable-filter" in css
    assert ".inventory-bulk-toolbar" in css


def test_2_product_archive_and_hard_delete_backend():
    """Requirement 3: Verify archive (soft delete) and delete permanently (hard delete) update backend DB."""
    db = SessionLocal()
    test_prod = Product(
        name="Test-Archive-Debug-Item",
        hindi_name="टेस्ट उत्पाद",
        aliases="test archive item",
        category="Test Category",
        unit="packet",
        unit_price=45.0,
        stock_quantity=20.0,
        min_stock_threshold=5.0,
        is_active=True
    )
    db.add(test_prod)
    db.commit()
    db.refresh(test_prod)
    prod_id = test_prod.id
    db.close()

    # 1. Verify product appears in active inventory list
    res_list = client.get("/api/v1/products?query=Test-Archive-Debug-Item")
    assert res_list.status_code == 200
    items = res_list.json()
    assert any(p["id"] == prod_id for p in items)

    # 2. Soft-delete / Archive the product
    res_arch = client.delete(f"/api/v1/products/{prod_id}")
    assert res_arch.status_code == 200
    arch_data = res_arch.json()
    assert arch_data["is_active"] is False
    assert arch_data["soft_deleted"] is True

    # 3. Verify product is immediately removed from the active inventory list
    res_list_after = client.get("/api/v1/products?query=Test-Archive-Debug-Item")
    assert res_list_after.status_code == 200
    assert not any(p["id"] == prod_id for p in res_list_after.json())

    # 4. Hard-delete permanently from backend database
    res_hard = client.delete(f"/api/v1/products/{prod_id}?hard_delete=true")
    assert res_hard.status_code == 200
    hard_data = res_hard.json()
    assert hard_data["soft_deleted"] is False

    # 5. Verify database record is completely deleted
    db = SessionLocal()
    deleted_p = db.query(Product).filter(Product.id == prod_id).first()
    db.close()
    assert deleted_p is None


def test_3_bulk_delete_products_api():
    """Requirement 4: Verify bulk delete action option removes selected products and test items."""
    db = SessionLocal()
    p1 = Product(name="Test-Bulk-1", category="Test Bulk", unit="kg", unit_price=10.0, stock_quantity=10.0, is_active=True)
    p2 = Product(name="Test-Bulk-2", category="Test Bulk", unit="kg", unit_price=15.0, stock_quantity=10.0, is_active=True)
    p3 = Product(name="Test-Bulk-3", category="Test Bulk", unit="kg", unit_price=20.0, stock_quantity=10.0, is_active=True)
    db.add_all([p1, p2, p3])
    db.commit()
    db.refresh(p1)
    db.refresh(p2)
    db.refresh(p3)
    ids = [p1.id, p2.id, p3.id]
    db.close()

    # Bulk delete selected product IDs
    res = client.post("/api/v1/products/bulk-delete", json={"product_ids": ids, "hard_delete": True})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["deleted_count"] == 3

    # Verify all 3 are deleted from database
    db = SessionLocal()
    found = db.query(Product).filter(Product.id.in_(ids)).all()
    db.close()
    assert len(found) == 0

    # Create dummy test item and verify delete_all_test_items: True
    db = SessionLocal()
    ptest = Product(name="Test-AutoPurge-Sample", category="Test Category", unit="pc", unit_price=5.0, stock_quantity=5.0, is_active=True)
    db.add(ptest)
    db.commit()
    db.refresh(ptest)
    purge_id = ptest.id
    db.close()

    res_purge = client.post("/api/v1/products/bulk-delete", json={"delete_all_test_items": True, "hard_delete": True})
    assert res_purge.status_code == 200
    assert res_purge.json()["status"] == "success"

    db = SessionLocal()
    assert db.query(Product).filter(Product.id == purge_id).first() is None
    db.close()


def test_4_inventory_filtering_endpoints():
    """Requirement 5: Verify click-to-filter backend queries for low_stock_only and out_of_stock_only."""
    # Seed known low-stock and out-of-stock active products
    db = SessionLocal()
    low_prod = Product(
        name="Real-Staple-Low-Stock-Item",
        category="Staples",
        unit="kg",
        unit_price=60.0,
        stock_quantity=3.0,
        min_stock_threshold=10.0,
        is_active=True
    )
    out_prod = Product(
        name="Real-Staple-Out-Stock-Item",
        category="Staples",
        unit="kg",
        unit_price=40.0,
        stock_quantity=0.0,
        min_stock_threshold=10.0,
        is_active=True
    )
    db.add_all([low_prod, out_prod])
    db.commit()
    db.refresh(low_prod)
    db.refresh(out_prod)
    low_id = low_prod.id
    out_id = out_prod.id
    db.close()

    try:
        # 1. Low stock filter: should return both low_prod and out_prod (both stock <= threshold)
        res_low = client.get("/api/v1/products?low_stock_only=true")
        assert res_low.status_code == 200
        low_items = [p["id"] for p in res_low.json()]
        assert low_id in low_items
        assert out_id in low_items

        # 2. Out of stock filter: should return ONLY items where stock <= 0.0
        res_out = client.get("/api/v1/products?out_of_stock_only=true")
        assert res_out.status_code == 200
        out_items = [p["id"] for p in res_out.json()]
        assert out_id in out_items
        assert low_id not in out_items

        # 3. Inventory summary excludes inactive products
        res_summary = client.get("/api/v1/inventory/summary")
        assert res_summary.status_code == 200
        s_data = res_summary.json()
        assert s_data["total_products"] > 0
        assert s_data["low_stock_count"] >= 2
        assert s_data["out_of_stock_count"] >= 1

    finally:
        # Cleanup
        db = SessionLocal()
        db.query(Product).filter(Product.id.in_([low_id, out_id])).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_5_ui_functions_exported_in_scripts():
    """Verify frontend JavaScript files export the required functions."""
    inv_js_path = settings.FRONTEND_DIR / "js" / "inventory.js"
    assert inv_js_path.exists()
    inv_js = inv_js_path.read_text(encoding="utf-8")

    assert "toggleStockFilter" in inv_js
    assert "clearStockFilters" in inv_js
    assert "navigateToInventoryWithFilter" in inv_js
    assert "handleProductCheckboxChange" in inv_js
    assert "toggleSelectAllProducts" in inv_js
    assert "selectTestProducts" in inv_js
    assert "handleBulkDeleteSelected" in inv_js
    assert "purgeAllTestItems" in inv_js

    prof_js_path = settings.FRONTEND_DIR / "js" / "profile.js"
    assert prof_js_path.exists()
    prof_js = prof_js_path.read_text(encoding="utf-8")

    assert "setCropperPreviewMode" in prof_js
    assert "window.setCropperPreviewMode" in prof_js
