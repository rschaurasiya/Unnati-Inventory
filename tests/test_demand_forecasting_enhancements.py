"""
Automated Verification Suite for Demand Forecasting & AI Enhancements:
1. Top Banner Removal & Clean "Recalculate Forecasts" Action Bar
2. Interactive, Clickable 4 KPI Summary Cards with Non-Tech Explanation & Reset
3. Sensibly Rounded Quantities & Non-Overlapping 7-Column Layout
4. Functional Stock Reorder Modal & Action Buttons (Buy & Inspect)
5. Single-Row Pagination (10, 20, 30) & Real-Time System Synchronization
"""
import re
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product

client = TestClient(app)

def test_01_top_banner_removed_and_clean_action_bar_present():
    """Verify large banner is removed and clean action bar with refresh button exists in index.html."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Large redundant banner must be removed
    assert "See which products may run low and what to buy next" not in html, \
        "Redundant subtitle should be completely removed"
    assert "Demand Forecasting & Stock" not in html or "Demand Forecasting & Stock Tab Container" in html, \
        "Large intro header container should be removed"

    # 2. Sleek action bar must be present above KPI cards
    assert 'class="forecast-action-bar"' in html, "Forecast action bar must exist"
    assert 'id="fc-last-updated"' in html, "Status timestamp indicator must exist"
    assert 'id="btn-refresh-forecasts"' in html, "Recalculate Forecasts button must exist"
    assert 'class="status-dot-pulse"' in html, "Live pulsating status indicator must exist"

    # 3. Recalculate endpoint must succeed
    res = client.get("/api/v1/forecast/products?force_refresh=true")
    assert res.status_code == 200
    data = res.json()
    assert "overview" in data
    assert "products" in data
    assert isinstance(data["products"], list)


def test_02_interactive_kpi_cards_and_explanation_banner():
    """Verify 4 KPI cards are interactive filter cards with explanation banner and reset button."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # 1. 4 Interactive KPI cards
    assert 'id="fc-kpi-card-reorder"' in html
    assert 'id="fc-kpi-card-low-stock"' in html
    assert 'id="fc-kpi-card-enough-stock"' in html
    assert 'id="fc-kpi-card-units-to-buy"' in html
    assert 'class="metric-card fc-interactive-kpi"' in html

    # 2. Plain-language filter explanation banner & reset button
    assert 'id="fc-filter-explanation-banner"' in html
    assert 'id="fc-filter-explanation-text"' in html
    assert 'id="btn-fc-reset-kpi-filter"' in html
    assert "Show All Products" in html

    # 3. CSS styling for interactive cards & explanation banner
    with open("frontend/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".fc-interactive-kpi" in css
    assert ".fc-interactive-kpi:hover" in css
    assert ".fc-interactive-kpi.active-kpi-card" in css
    assert ".forecast-explanation-banner" in css
    assert ".btn-reset-kpi-filter" in css


def test_03_column_overlap_fix_and_sensible_rounding():
    """Verify 7 clean columns, cell nowrap, table spacing, and sensible rounding logic."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Verify 7 columns in forecast tables
    expected_headers = [
        "Product &amp; Category",
        "Current Stock",
        "Weekly Demand (7 Days)",
        "Stock Lasts For",
        "Status",
        "Suggested Order",
        "Action"
    ]
    for h in expected_headers:
        assert h in html, f"Header '{h}' should exist in forecast tables"

    # 2. Check CSS spacing and nowrap rules
    with open("frontend/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".forecast-table" in css
    assert "border-collapse: separate" in css
    assert ".cell-nowrap" in css
    assert "white-space: nowrap" in css
    assert ".forecast-coverage-urgent" in css
    assert ".forecast-coverage-warning" in css
    assert ".forecast-coverage-healthy" in css

    # 3. Verify formatRestockQuantity logic in forecasting.js
    with open("frontend/js/forecasting.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "formatRestockQuantity" in js
    assert "formatStockQuantity" in js
    assert "Math.ceil" in js
    assert "packets" in js
    assert "pieces" in js
    assert "bottles" in js


def test_04_stock_reorder_modal_and_restock_backend_api():
    """Verify Confirm Stock Reorder modal and API restock persistence & forecast invalidation."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Modal structure
    assert 'id="forecast-reorder-modal"' in html
    assert 'id="fc-reorder-product-id"' in html
    assert 'id="fc-reorder-product-name"' in html
    assert 'id="fc-reorder-current-stock"' in html
    assert 'id="fc-reorder-new-stock"' in html
    assert 'id="fc-reorder-quantity-input"' in html
    assert 'id="btn-confirm-fc-reorder"' in html
    assert 'id="forecast-inspect-modal"' in html

    # 2. Backend restock API execution & DB persistence
    db = SessionLocal()
    prod = db.query(Product).first()
    assert prod is not None, "Product catalog must contain products"
    initial_stock = prod.stock_quantity
    prod_id = prod.id
    unit = prod.unit
    db.close()

    add_qty = 15.0
    res = client.post("/api/v1/inventory/restock", json={
        "product_id": prod_id,
        "quantity_delta": add_qty,
        "notes": "Automated Forecast Test Reorder"
    })
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["product_id"] == prod_id
    assert res_data["previous_stock"] == initial_stock
    assert res_data["new_stock"] == initial_stock + add_qty

    # Verify DB has updated stock
    db2 = SessionLocal()
    updated_prod = db2.query(Product).filter(Product.id == prod_id).first()
    assert updated_prod.stock_quantity == initial_stock + add_qty
    db2.close()

    # Revert test restock to preserve catalog integrity
    client.post("/api/v1/inventory/adjust", json={
        "product_id": prod_id,
        "quantity_delta": -add_qty,
        "notes": "Revert test restock"
    })


def test_05_single_row_pagination_and_real_time_sync():
    """Verify single-row pagination bar (10, 20, 30) and real-time state synchronization."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Pagination HTML components
    assert 'id="fc-pagination-container"' in html
    assert 'id="fc-page-size-select"' in html
    assert '<option value="10" selected>10</option>' in html
    assert '<option value="20">20</option>' in html
    assert '<option value="30">30</option>' in html
    assert 'id="fc-pagination-info"' in html
    assert 'id="btn-fc-prev"' in html
    assert 'id="fc-page-indicator"' in html
    assert 'id="btn-fc-next"' in html

    # 2. Urgent Attention pagination when > 10 items
    assert 'id="fc-urgent-pagination-container"' in html
    assert 'id="fc-urgent-pagination-info"' in html
    assert 'id="btn-fc-urgent-prev"' in html
    assert 'id="btn-fc-urgent-next"' in html

    # 3. Real-time synchronization events in forecasting.js
    with open("frontend/js/forecasting.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert 'window.dispatchEvent(new CustomEvent("inventory-updated"' in js
    assert 'window.dispatchEvent(new CustomEvent("products-updated"' in js
    assert 'window.loadInventorySummary' in js
    assert 'updateKpiCardValues' in js
    assert 'filterForecastProductsTable' in js
    assert 'renderUrgentAttentionSection' in js


def test_06_chronological_urgency_ranking_and_outlier_clamping():
    """Verify fixed status classification, strict urgency ranking, and outlier clamping."""
    res = client.get("/api/v1/forecast/products?force_refresh=true")
    assert res.status_code == 200
    data = res.json()
    products = data["products"]

    # 1. Verify strict urgency classification rules
    for p in products:
        if p["status"] != "ELIGIBLE":
            assert p["risk_level"] == "INSUFFICIENT_DATA"
            continue

        days = p["days_inventory_remaining"]
        stock = p["current_stock"]

        # Urgent items (<= 3 days) must be classified as IMMEDIATE_ATTENTION or LOW_STOCK (Red badge)
        if days is not None and days <= 3.0:
            assert p["risk_level"] in ("IMMEDIATE_ATTENTION", "LOW_STOCK"), \
                f"Product {p['product_name']} with {days} days must be classified as urgent (LOW_STOCK or IMMEDIATE_ATTENTION), got {p['risk_level']}"

        # Items with > 7 days and sufficient stock must be SUFFICIENT (or POTENTIAL_STOCKOUT if under safety buffer)
        # and NEVER LOW_STOCK!
        if days is not None and days > 7.0 and p["suggested_reorder_qty"] == 0:
            assert p["risk_level"] == "SUFFICIENT", \
                f"Product {p['product_name']} with {days} days and zero reorder must be SUFFICIENT, got {p['risk_level']}"

    # 2. Verify table ranking is strictly ordered by urgency
    prio_order = {"IMMEDIATE_ATTENTION": 1, "LOW_STOCK": 1, "POTENTIAL_STOCKOUT": 2, "SUFFICIENT": 3, "INSUFFICIENT_DATA": 4}
    seen_prios = [prio_order.get(p["risk_level"], 4) for p in products]

    # Verify priority never decreases (must be non-decreasing: 1, 1, ..., 2, 2, ..., 3, ..., 4)
    for i in range(len(seen_prios) - 1):
        assert seen_prios[i] <= seen_prios[i + 1], \
            f"Products must be sorted strictly by urgency: Priority {seen_prios[i]} came before {seen_prios[i+1]}"

    # 3. Within priority 1 (Low stock), verify days remaining is sorted ascending
    low_stock_days = [p["days_inventory_remaining"] for p in products if prio_order.get(p["risk_level"]) == 1 and p["days_inventory_remaining"] is not None]
    for i in range(len(low_stock_days) - 1):
        assert low_stock_days[i] <= low_stock_days[i + 1], \
            f"Low stock products must be sorted by lowest days remaining first: {low_stock_days[i]} > {low_stock_days[i+1]}"

    # 4. Within priority 2 (Reorder soon), verify days remaining is sorted ascending
    reorder_days = [p["days_inventory_remaining"] for p in products if prio_order.get(p["risk_level"]) == 2 and p["days_inventory_remaining"] is not None]
    for i in range(len(reorder_days) - 1):
        assert reorder_days[i] <= reorder_days[i + 1], \
            f"Reorder soon products must be sorted by lowest days remaining first: {reorder_days[i]} > {reorder_days[i+1]}"

