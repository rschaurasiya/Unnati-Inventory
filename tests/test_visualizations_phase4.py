"""
Phase 4 Acceptance Criteria Tests — Supplier Analytics & Cross-Module Integration
Verifies:
1. Honest architectural prerequisite handling for absent supplier purchasing schema.
2. Refusal to fabricate synthetic vendor spend or fake purchase quantities.
3. Cross-module health check across all implemented visualization endpoints.
4. Security & tenant data isolation (no unmasked PII, OTPs, or passwords in chart payloads).
"""
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product, Customer, Bill

client = TestClient(app)


def test_supplier_analytics_missing_prerequisite_honesty():
    """
    Verify supplier purchasing analytics honestly reports UNAVAILABLE status
    and documents missing database schema prerequisites without fabricating fake spend.
    """
    response = client.get("/api/v1/analytics/supplier/charts")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "UNAVAILABLE"
    assert data["supplier_module_available"] is False
    assert "not implemented" in data["reason"].lower()
    assert len(data["missing_prerequisites"]) > 0

    # Ensure charts series are empty, not populated with fake/synthetic transactions
    assert len(data["purchase_spend"]["series"]) == 0
    assert len(data["supplier_comparison"]["series"]) == 0
    assert len(data["purchase_quantity_trend"]["series"]) == 0


def test_cross_module_visualizations_health():
    """
    Verify all visualization endpoints across all 4 phases return 200 and valid schemas:
    - Phase 1: Dashboard and Sales History
    - Phase 2: Inventory and Udhaar Customers
    - Phase 3: Demand Forecasting
    - Phase 4: Supplier Analytics
    """
    # 1. Dashboard Charts
    res_dash = client.get("/api/v1/analytics/dashboard/charts?days=7")
    assert res_dash.status_code == 200
    assert "sales_trend" in res_dash.json()
    assert "top_by_units" in res_dash.json()
    assert "top_by_revenue" in res_dash.json()
    assert "payment_breakdown" in res_dash.json()

    # 2. Sales History Charts
    res_sales = client.get("/api/v1/analytics/sales/charts")
    assert res_sales.status_code == 200
    assert "revenue_trend" in res_sales.json()
    assert "transactions_trend" in res_sales.json()
    assert "best_by_units" in res_sales.json()
    assert "category_sales" in res_sales.json()

    # 3. Inventory Charts
    res_inv = client.get("/api/v1/inventory/charts")
    assert res_inv.status_code == 200
    assert "low_stock_comparison" in res_inv.json()
    assert "stock_by_category" in res_inv.json()
    assert "inventory_valuation" in res_inv.json()

    # 4. Udhaar Customer Credit Charts
    res_cust = client.get("/api/v1/customers/charts?days=30")
    assert res_cust.status_code == 200
    assert "highest_outstanding" in res_cust.json()
    assert "credit_vs_collections" in res_cust.json()

    # 5. Demand Forecasting Charts
    res_fc = client.get("/api/v1/forecast/charts?horizon=7")
    assert res_fc.status_code == 200
    assert "demand_chart" in res_fc.json()
    assert "reorder_chart" in res_fc.json()
    assert "model_evaluation" in res_fc.json()

    # 6. Supplier Analytics
    res_supp = client.get("/api/v1/analytics/supplier/charts")
    assert res_supp.status_code == 200
    assert res_supp.json()["supplier_module_available"] is False


def test_security_and_privacy_in_chart_payloads():
    """
    Verify sensitive credentials (passwords, OTPs, auth tokens) and unmasked customer
    phone numbers are never leaked in any chart response payloads.
    """
    endpoints = [
        "/api/v1/analytics/dashboard/charts",
        "/api/v1/analytics/sales/charts",
        "/api/v1/inventory/charts",
        "/api/v1/customers/charts",
        "/api/v1/forecast/charts",
        "/api/v1/analytics/supplier/charts"
    ]

    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code == 200
        text = res.text.lower()

        # Check for secrets
        assert "password_hash" not in text
        assert "secret_key" not in text
        assert "auth_token" not in text
        assert "otp_code" not in text

        # If customers chart, verify phone masking
        if "customers" in ep:
            data = res.json()
            for c in data.get("highest_outstanding", []):
                phone = c.get("phone_masked", "")
                if phone and len(phone) >= 10:
                    assert "****" in phone, f"Phone number '{phone}' was not properly masked"

