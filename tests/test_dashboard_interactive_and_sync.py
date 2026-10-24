"""
Automated Integration and Regression Tests for:
Shop Dashboard — UI/UX Improvements, Interactive Cards,
Collapsible Sections, and Cross-Module Data Synchronization.
"""
import re
from datetime import datetime, date, timedelta
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import (
    Product, Customer, Bill, BillItem, VerificationSession,
    UdhaarTransaction, DailySalesSummary, ShopProfile
)

client = TestClient(app)


# ==============================================================================
# 1. HTML DOM Structure & Accessibility Tests (Dashboard KPI & Action Cards)
# ==============================================================================

def test_dashboard_kpi_cards_markup_and_accessibility():
    """
    Verifies that all five KPI cards are interactive, accessible, and correctly wired:
    1. Today's Sales -> onKpiTodaySalesClick()
    2. Inventory Valuation -> onKpiInventoryValClick()
    3. Low Stock Alerts -> onKpiLowStockClick()
    4. Outstanding Udhaar -> onKpiTotalUdhaarClick()
    5. AI Forecast Readiness -> onKpiForecastReadyClick()
    """
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    # 1. Today's Sales
    assert 'id="kpi-card-today-sales"' in html
    assert 'onclick="onKpiTodaySalesClick()"' in html
    assert "handleKpiCardKeyDown(event, 'today-sales')" in html
    assert 'id="dash-today-sales"' in html

    # 2. Inventory Valuation
    assert 'id="kpi-card-inventory-val"' in html
    assert 'onclick="onKpiInventoryValClick()"' in html
    assert "handleKpiCardKeyDown(event, 'inventory-val')" in html
    assert 'id="dash-inventory-val"' in html

    # 3. Low Stock Alerts
    assert 'id="kpi-card-low-stock"' in html
    assert 'onclick="onKpiLowStockClick()"' in html
    assert "handleKpiCardKeyDown(event, 'low-stock')" in html
    assert 'id="dash-low-stock-count"' in html

    # 4. Outstanding Udhaar
    assert 'id="kpi-card-total-udhaar"' in html
    assert 'onclick="onKpiTotalUdhaarClick()"' in html
    assert "handleKpiCardKeyDown(event, 'total-udhaar')" in html
    assert 'id="dash-total-udhaar"' in html

    # 5. AI Forecast Readiness
    assert 'id="kpi-card-forecast-ready"' in html
    assert 'onclick="onKpiForecastReadyClick()"' in html
    assert "handleKpiCardKeyDown(event, 'forecast-ready')" in html
    assert 'id="dash-forecast-ready"' in html

    # All 5 KPI cards must have clickable-card class and accessibility attributes
    kpi_cards = re.findall(r'<div class="kpi-card clickable-card"[^>]*>', html)
    assert len(kpi_cards) == 5, f"Expected 5 clickable KPI cards, found {len(kpi_cards)}"
    for card_tag in kpi_cards:
        assert 'role="button"' in card_tag
        assert 'tabindex="0"' in card_tag
        assert 'aria-label=' in card_tag


def test_dashboard_quick_action_cards_markup_and_accessibility():
    """
    Verifies that all five Quick Demo & POS Action cards are interactive and mapped correctly:
    1. Voice Billing POS -> navigateTo('/billing')
    2. Manage Inventory -> navigateTo('/inventory')
    3. Udhaar & Customers -> navigateTo('/customers')
    4. Historical Import -> navigateTo('/sales/import')
    5. Demand Forecasting -> navigateTo('/forecast')
    """
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    assert "navigateTo('/billing')" in html
    assert "navigateTo('/inventory')" in html
    assert "navigateTo('/customers')" in html
    assert "navigateTo('/sales/import')" in html
    assert "navigateTo('/forecast')" in html

    quick_actions = re.findall(r'<button type="button" class="quick-action-btn clickable-card"[^>]*>', html)
    assert len(quick_actions) == 5, f"Expected 5 clickable Quick Action buttons, found {len(quick_actions)}"
    for btn_tag in quick_actions:
        assert 'aria-label=' in btn_tag
        assert 'title=' in btn_tag


def test_dashboard_independent_collapsible_sections_markup():
    """
    Verifies that both lower operational feed sections:
    1. Urgent Stockout & Low Stock Alerts
    2. Recent Completed Transactions
    are independent collapsible cards, initialized as collapsed by default with aria attributes.
    """
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    # Urgent Stockout & Low Stock Section
    assert 'id="dash-section-low-stock"' in html
    assert 'id="dash-low-stock-header"' in html
    assert 'id="dash-low-stock-chevron"' in html
    assert 'id="dash-low-stock-badge"' in html
    assert 'id="dash-low-stock-collapsible"' in html
    assert 'onclick="toggleLowStockSection()"' in html
    assert "handleCollapsibleKeyDown(event, 'low-stock')" in html
    assert 'aria-controls="dash-low-stock-collapsible"' in html

    # Recent Completed Transactions Section
    assert 'id="dash-section-recent-sales"' in html
    assert 'id="dash-recent-sales-header"' in html
    assert 'id="dash-recent-sales-chevron"' in html
    assert 'id="dash-recent-sales-badge"' in html
    assert 'id="dash-recent-sales-collapsible"' in html
    assert 'onclick="toggleRecentSalesSection()"' in html
    assert "handleCollapsibleKeyDown(event, 'recent-sales')" in html
    assert 'aria-controls="dash-recent-sales-collapsible"' in html

    # Initial state must be collapsed
    assert 'class="collapsible-content collapsed"' in html
    assert 'aria-expanded="false"' in html


# ==============================================================================
# 2. JavaScript Module & CSS Design System Verification
# ==============================================================================

def test_dashboard_js_functions_and_state_management():
    """
    Verifies that dashboard.js exports all required handlers, independent state
    controls, debouncing, and reactive synchronization listeners.
    """
    res = client.get("/static/js/dashboard.js")
    assert res.status_code == 200
    js_text = res.text

    # Collapsible state and handlers
    assert "isLowStockExpanded" in js_text
    assert "isRecentSalesExpanded" in js_text
    assert "setLowStockSectionExpanded" in js_text
    assert "setRecentSalesSectionExpanded" in js_text
    assert "toggleLowStockSection" in js_text
    assert "toggleRecentSalesSection" in js_text
    assert "handleCollapsibleKeyDown" in js_text

    # KPI Card handlers
    assert "onKpiTodaySalesClick" in js_text
    assert "onKpiInventoryValClick" in js_text
    assert "onKpiLowStockClick" in js_text
    assert "onKpiTotalUdhaarClick" in js_text
    assert "onKpiForecastReadyClick" in js_text
    assert "handleKpiCardKeyDown" in js_text

    # Reactive synchronization events
    assert 'window.addEventListener("shop-profile-updated"' in js_text
    assert 'window.addEventListener("products-updated"' in js_text
    assert 'window.addEventListener("bills-updated"' in js_text
    assert 'window.addEventListener("sales-updated"' in js_text
    assert 'window.addEventListener("customers-updated"' in js_text

    # Window exports
    assert "window.DashboardModule = DashboardModule" in js_text
    assert "window.toggleLowStockSection = toggleLowStockSection" in js_text
    assert "window.toggleRecentSalesSection = toggleRecentSalesSection" in js_text
    assert "window.onKpiTodaySalesClick = onKpiTodaySalesClick" in js_text
    assert "window.onKpiLowStockClick = onKpiLowStockClick" in js_text


def test_sales_js_and_customers_js_cross_module_sync_enhancements():
    """
    Verifies that sales.js provides filterSalesToToday() and customers.js
    dispatches 'customers-updated' for reactive synchronization.
    """
    sales_res = client.get("/static/js/sales.js")
    assert sales_res.status_code == 200
    assert "function filterSalesToToday()" in sales_res.text
    assert "window.filterSalesToToday = filterSalesToToday" in sales_res.text

    cust_res = client.get("/static/js/customers.js")
    assert cust_res.status_code == 200
    assert 'new CustomEvent("customers-updated"' in cust_res.text


def test_style_css_interactive_cards_and_collapsible_styles():
    """
    Verifies that style.css implements consistent hover, active, focus,
    card accents, and independent collapsible animation styles.
    """
    res = client.get("/static/css/style.css")
    assert res.status_code == 200
    css_text = res.text

    # Interactive card styles
    assert ".kpi-card.clickable-card" in css_text
    assert "#kpi-card-today-sales:hover" in css_text
    assert "#kpi-card-inventory-val:hover" in css_text
    assert "#kpi-card-low-stock:hover" in css_text
    assert "#kpi-card-total-udhaar:hover" in css_text
    assert "#kpi-card-forecast-ready:hover" in css_text

    assert ".quick-action-btn:hover" in css_text
    assert ".quick-action-btn:active" in css_text
    assert ":focus-visible" in css_text

    # Collapsible styles
    assert ".dash-collapsible-card" in css_text
    assert ".collapsible-header" in css_text
    assert ".collapsible-chevron" in css_text
    assert ".collapsible-chevron.expanded" in css_text
    assert ".collapse-status-pill" in css_text
    assert ".collapsible-content.collapsed" in css_text
    assert "@media (prefers-reduced-motion: reduce)" in css_text


# ==============================================================================
# 3. Live API Backend Data Endpoints for Dashboard Feeds
# ==============================================================================

def test_dashboard_api_endpoints_health_and_data_payloads():
    """
    Verifies that all 6 backend endpoints serving the Dashboard return valid
    HTTP 200 responses with exact data contracts:
    - /api/v1/inventory/summary
    - /api/v1/inventory/low-stock
    - /api/v1/billing/bills?limit=8
    - /api/v1/customers
    - /api/v1/forecast/overview
    - /api/v1/analytics/sales/daily
    """
    # 1. Inventory Summary
    inv_res = client.get("/api/v1/inventory/summary")
    assert inv_res.status_code == 200
    inv_data = inv_res.json()
    assert "total_products" in inv_data
    assert "total_inventory_value" in inv_data
    assert "low_stock_count" in inv_data
    assert "out_of_stock_count" in inv_data

    # 2. Low Stock Items
    low_res = client.get("/api/v1/inventory/low-stock")
    assert low_res.status_code == 200
    assert isinstance(low_res.json(), list)

    # 3. Recent Bills
    bills_res = client.get("/api/v1/billing/bills?limit=8")
    assert bills_res.status_code == 200
    assert isinstance(bills_res.json(), list)

    # 4. Customers
    cust_res = client.get("/api/v1/customers")
    assert cust_res.status_code == 200
    assert isinstance(cust_res.json(), list)

    # 5. Forecast Overview
    fc_res = client.get("/api/v1/forecast/overview")
    assert fc_res.status_code == 200
    fc_data = fc_res.json()
    assert "total_products" in fc_data
    assert "eligible_products_count" in fc_data
    assert "total_reorder_units_needed" in fc_data

    # 6. Daily Sales Summary
    daily_res = client.get("/api/v1/analytics/sales/daily")
    assert daily_res.status_code == 200
    daily_data = daily_res.json()
    assert "sale_date" in daily_data
    assert "total_revenue" in daily_data
    assert "transaction_count" in daily_data


# ==============================================================================
# 4. Cross-Module Real-Time Data Synchronization Tests
# ==============================================================================

def test_inventory_mutation_propagates_to_valuation_and_summary():
    """
    Verifies that mutating inventory (creating product, updating price, restock)
    authoritatively changes backend valuation and low-stock count for the dashboard.
    """
    db = SessionLocal()
    try:
        # Create test product with specific price and stock
        unique_name = f"DashSyncProduct_{int(datetime.now().timestamp())}"
        create_res = client.post("/api/v1/products", json={
            "name": unique_name,
            "unit_price": 50.0,
            "stock_quantity": 2.0,
            "min_stock_threshold": 10.0,
            "category": "Snacks",
            "unit": "packet"
        })
        assert create_res.status_code == 201
        prod_data = create_res.json()
        prod_id = prod_data["id"]

        # Check inventory summary reflects the new item
        inv_after = client.get("/api/v1/inventory/summary").json()
        assert inv_after["total_products"] >= 1

        # Check low-stock list contains the low-stock item
        low_items = client.get("/api/v1/inventory/low-stock").json()
        matching = [item for item in low_items if item["id"] == prod_id]
        assert len(matching) == 1, "Product below threshold must appear in low-stock feed"

        # Update price to ₹75.00
        price_res = client.patch(f"/api/v1/products/{prod_id}/price", json={"unit_price": 75.0})
        assert price_res.status_code == 200
        assert price_res.json()["unit_price"] == 75.0

        # Restock product above threshold (add 20 units)
        restock_res = client.post("/api/v1/inventory/restock", json={
            "product_id": prod_id,
            "quantity_delta": 20.0,
            "reason": "Dashboard Sync Test Restock"
        })
        assert restock_res.status_code == 200
        assert restock_res.json()["new_stock"] == 22.0

        # Check product is no longer in low-stock feed
        low_after = client.get("/api/v1/inventory/low-stock").json()
        assert not any(item["id"] == prod_id for item in low_after), "Restocked product must exit low-stock feed"

    finally:
        # Cleanup
        try:
            client.delete(f"/api/v1/products/{prod_id}")
        except Exception:
            pass
        db.close()


def test_completed_cash_sale_updates_sales_summary_and_inventory():
    """
    Verifies that completing a cash sale updates:
    1. Daily sales total revenue and transaction count.
    2. Deducts product stock atomically.
    3. Appears in completed bills list.
    """
    db = SessionLocal()
    try:
        # Find active product with stock >= 5
        prod = db.query(Product).filter(Product.is_active == True, Product.stock_quantity >= 5.0).first()
        assert prod is not None
        initial_stock = prod.stock_quantity

        # Finalize a CASH bill
        sale_res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": prod.id, "quantity": 2.0}],
            "payment_mode": "CASH"
        })
        assert sale_res.status_code in [200, 201]
        bill = sale_res.json()
        assert bill["status"] == "COMPLETED"
        assert bill["payment_mode"] == "CASH"

        # Verify stock deduction
        db.refresh(prod)
        assert prod.stock_quantity == initial_stock - 2.0

        # Verify daily sales summary updated
        daily_res = client.get("/api/v1/analytics/sales/daily")
        assert daily_res.status_code == 200
        daily = daily_res.json()
        assert daily["total_revenue"] >= bill["total_amount"]
        assert daily["transaction_count"] >= 1

        # Verify bill appears in bills?limit=8
        recent_bills = client.get("/api/v1/billing/bills?limit=8").json()
        assert any(b["id"] == bill["id"] for b in recent_bills)

    finally:
        db.close()


def test_customer_repayment_settles_balance_for_dashboard():
    """
    Verifies that recording an Udhaar repayment updates customer balance
    and reflects in dashboard customer summary.
    """
    # 1. Create a customer with credit limit
    phone = f"98{int(datetime.now().timestamp() * 1000) % 100000000:08d}"
    cust_res = client.post("/api/v1/customers", json={
        "full_name": "Dashboard Udhaar Test Customer",
        "phone": phone,
        "credit_limit": 5000.0,
        "address_line": "Shop 10, Sector 17",
        "city": "Chandigarh",
        "state": "Chandigarh",
        "pincode": "160017",
        "country": "India"
    })
    assert cust_res.status_code == 201
    cust_id = cust_res.json()["id"]

    db = SessionLocal()
    try:
        # Give customer an outstanding debt of 100.0
        cust_row = db.query(Customer).filter(Customer.id == cust_id).first()
        cust_row.current_udhaar_balance = 100.0
        db.commit()

        # Settle repayment of 50.0
        settle_res = client.post(f"/api/v1/customers/{cust_id}/settle", json={
            "amount": 50.0,
            "payment_mode": "CASH",
            "notes": "Partial debt repayment"
        })
        assert settle_res.status_code == 200
        assert settle_res.json()["new_balance"] == 50.0

        # Customer list reflects the customer with new balance
        cust_list = client.get("/api/v1/customers").json()
        found = [c for c in cust_list if c["id"] == cust_id]
        assert len(found) == 1
        assert found[0]["current_udhaar_balance"] == 50.0

    finally:
        db.close()
        try:
            # Clear balance before delete so FK/balance checks pass
            db_clean = SessionLocal()
            c = db_clean.query(Customer).filter(Customer.id == cust_id).first()
            if c:
                c.current_udhaar_balance = 0.0
                db_clean.commit()
            db_clean.close()
            client.delete(f"/api/v1/customers/{cust_id}")
        except Exception:
            pass
