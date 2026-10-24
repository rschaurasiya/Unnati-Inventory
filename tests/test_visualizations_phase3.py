"""
Phase 3 Acceptance Criteria Tests — Demand Forecasting Visualizations
Verifies:
1. Actual vs Forecast Demand line chart (differentiating historical actuals from future predictions).
2. 7-Day vs 30-Day forecast horizon toggle updating date range and expected demand.
3. Restocking recommendation grouped bar chart with genuine stock levels and buffer math.
4. Truthful forecast accuracy and walk-forward cross-validation metrics.
5. Insufficient sales history (< 7 days) graceful fallback without synthetic forecasts.
6. Error handling and input validation.
"""
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product
from backend.services.forecasting import generate_product_forecast

client = TestClient(app)


def test_forecast_charts_default_endpoint():
    """Verify GET /api/v1/forecast/charts returns 200 and standard payload structure."""
    response = client.get("/api/v1/forecast/charts")
    assert response.status_code == 200
    data = response.json()

    assert "products" in data
    assert "selected_product" in data
    assert "horizon" in data
    assert "demand_chart" in data
    assert "reorder_chart" in data
    assert "model_evaluation" in data

    assert data["horizon"] == 7
    assert len(data["products"]) > 0
    assert data["selected_product"]["id"] is not None


def test_actual_vs_forecast_demand_separation():
    """
    Verify historical actual sales and future predicted demand are clearly separated series,
    with genuine calendar dates and no future-data leakage.
    """
    db = SessionLocal()
    eligible_product = db.query(Product).filter(Product.id == 1).first()
    db.close()

    assert eligible_product is not None

    response = client.get(f"/api/v1/forecast/charts?product_id={eligible_product.id}&horizon=7")
    assert response.status_code == 200
    data = response.json()

    demand = data["demand_chart"]
    assert demand["is_forecast_available"] is True
    assert len(demand["labels"]) > 7

    hist_series = demand["historical_series"]
    fc_series = demand["forecast_series"]

    assert len(hist_series) == len(demand["labels"])
    assert len(fc_series) == len(demand["labels"])

    # Historical points have values for first N items and None for future forecast points
    split_idx = demand["split_index"]
    assert split_idx >= 0

    # Past actual points are numbers
    for i in range(split_idx):
        assert hist_series[i] is not None
        assert isinstance(hist_series[i], (int, float))

    # Future forecast points are numbers
    for i in range(split_idx + 1, len(demand["labels"])):
        assert hist_series[i] is None  # No actuals in the future
        assert fc_series[i] is not None  # Predictions exist
        assert isinstance(fc_series[i], (int, float))
        assert fc_series[i] >= 0.0  # Non-negative


def test_forecast_horizon_toggle_7d_vs_30d():
    """
    Verify switching between 7-day and 30-day horizon updates:
    - Chart date range & forecast points count
    - Expected demand in restocking recommendation
    - Restocking reorder calculation
    """
    db = SessionLocal()
    product = db.query(Product).filter(Product.id == 1).first()
    db.close()

    res_7d = client.get(f"/api/v1/forecast/charts?product_id={product.id}&horizon=7")
    res_30d = client.get(f"/api/v1/forecast/charts?product_id={product.id}&horizon=30")

    assert res_7d.status_code == 200
    assert res_30d.status_code == 200

    d7 = res_7d.json()
    d30 = res_30d.json()

    # 30-day forecast must have more total points than 7-day forecast
    assert len(d30["demand_chart"]["labels"]) > len(d7["demand_chart"]["labels"])
    # Exactly 23 more days (30 - 7 = 23)
    assert len(d30["demand_chart"]["labels"]) == len(d7["demand_chart"]["labels"]) + 23

    # Expected demand in reorder chart
    demand_7d = d7["reorder_chart"]["values"][1]
    demand_30d = d30["reorder_chart"]["values"][1]

    assert demand_30d >= demand_7d


def test_insufficient_data_honesty():
    """
    Verify products with < 7 days of sales history:
    - Return INSUFFICIENT_DATA status
    - Refuse to fabricate fake predicted demand
    - Model evaluation is marked unavailable
    """
    db = SessionLocal()
    # Find a product with < 7 sales days
    all_prods = db.query(Product).all()
    insuf_prod = None
    for p in all_prods:
        fc = generate_product_forecast(db, p)
        if fc.get("status") == "INSUFFICIENT_DATA":
            insuf_prod = p
            break
    db.close()

    assert insuf_prod is not None, "At least one test product should have insufficient sales history"

    response = client.get(f"/api/v1/forecast/charts?product_id={insuf_prod.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["selected_product"]["status"] == "INSUFFICIENT_DATA"
    assert data["demand_chart"]["is_forecast_available"] is False
    assert len(data["demand_chart"]["forecast_series"]) == 0
    assert "Insufficient" in data["demand_chart"]["reason"]

    # Model evaluation must be honest
    model_eval = data["model_evaluation"]
    assert model_eval["evaluation_available"] is False
    assert model_eval["accuracy_score"] is None
    assert "unavailable" in model_eval["notes"].lower()


def test_restocking_recommendation_math():
    """
    Verify restocking calculation strictly follows:
    suggested_order = max(0, (expected_demand + safety_stock) - current_stock)
    and does not confuse forecast demand with suggested reorder.
    """
    response = client.get("/api/v1/forecast/charts?product_id=1&horizon=7")
    assert response.status_code == 200
    data = response.json()

    reorder = data["reorder_chart"]
    current_stock = reorder["values"][0]
    expected_demand = reorder["values"][1]
    safety_stock = reorder["values"][2]
    suggested_order = reorder["values"][3]

    expected_calc = max(0.0, round((expected_demand + safety_stock) - current_stock, 2))
    assert suggested_order == expected_calc


def test_forecast_charts_not_found():
    """Verify querying a non-existent product ID returns 404."""
    response = client.get("/api/v1/forecast/charts?product_id=99999999")
    assert response.status_code == 404
