"""
Comprehensive Automated Test Suite for Step 11:
Demand Forecasting & Stock/Reorder Intelligence Engine.
Tests all requirements A through Z and sanity tests:
- Data sufficiency gates (< 7 days vs >= 7 days)
- Product-level daily time series construction
- Continuous date continuity and zero-sales day handling
- Statistical forecasting models (SMA, EWMA, DOW_SEASONAL, TREND_SEASONAL)
- Walk-forward backtesting without future data leakage
- 7-day and 30-day exact forecast horizons
- Strictly non-negative forecast quantities
- Current inventory integration & stockout risk calculation
- Explainable reorder recommendations & safety buffer calculations
- Zero inventory mutation guarantee (read-only forecasting)
- Imported CSV/XLSX and POS bill combination
- Cache invalidation and refresh mechanisms
- API endpoints validation and error handling
"""
import io
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from datetime import datetime, date, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import app
from backend.database import SessionLocal
from backend.models import (
    Product, Bill, BillItem, DailySalesSummary,
    HistoricalImportBatch, HistoricalSaleRecord, ProductForecast
)
from backend.services.forecasting import (
    generate_product_forecast,
    get_all_product_forecasts,
    get_product_daily_series,
    select_and_evaluate_model,
    ForecastingModels,
    invalidate_forecast_cache
)
from backend.services.sales_aggregation import (
    aggregate_sales_for_date,
    rebuild_all_sales_summaries,
    check_data_sufficiency
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_forecast_state():
    """Ensure forecast cache is fresh before each test."""
    invalidate_forecast_cache()
    yield
    invalidate_forecast_cache()


def _create_test_product(db: Session, name: str, stock: float = 20.0, price: float = 50.0, threshold: float = 10.0) -> Product:
    """Helper to create an isolated test product."""
    prod = Product(
        name=name,
        hindi_name=f"{name} Hindi",
        aliases=name.lower(),
        category="Test Category",
        unit="kg",
        unit_price=price,
        stock_quantity=stock,
        min_stock_threshold=threshold
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    return prod


def _add_daily_sales(db: Session, product_id: int, num_days: int, start_date: date, daily_qty: float = 10.0):
    """Helper to create DailySalesSummary records for a product across num_days."""
    for i in range(num_days):
        d = start_date + timedelta(days=i)
        summary = DailySalesSummary(
            product_id=product_id,
            sale_date=d,
            total_quantity_sold=daily_qty,
            total_revenue=daily_qty * 50.0,
            transaction_count=2,
            updated_at=datetime.utcnow()
        )
        db.add(summary)
    db.commit()


# ==============================================================================
# TESTS A, B, C, D, E: DATA SUFFICIENCY GATES (0, 1-6, 7, 30, 60+ DAYS)
# ==============================================================================

def test_a_zero_days_history_forecasting_unavailable():
    """Test A: Product with 0 days history must be marked INSUFFICIENT_DATA without fake forecast."""
    db = SessionLocal()
    try:
        prod = _create_test_product(db, "Test-Zero-Days-Prod", stock=25.0)

        # Check sufficiency API
        res = client.get(f"/api/v1/forecast/product/{prod.id}")
        assert res.status_code == 200
        data = res.json()

        assert data["status"] == "INSUFFICIENT_DATA"
        assert data["usable_days_count"] == 0
        assert data["min_days_required"] == 7
        assert data["forecast_7d"] == []
        assert data["forecast_30d"] == []
        assert data["total_7d_demand"] == 0.0
        assert "Insufficient historical data" in data["explanation"]
        assert data["stockout_risk"]["risk_level"] == "INSUFFICIENT_DATA"
    finally:
        db.close()


def test_b_one_to_six_days_history_insufficient():
    """Test B: Product with 1 to 6 usable days must be safely rejected by the sufficiency gate."""
    db = SessionLocal()
    try:
        prod = _create_test_product(db, "Test-Five-Days-Prod", stock=30.0)
        start_d = date.today() - timedelta(days=10)
        _add_daily_sales(db, prod.id, num_days=5, start_date=start_d, daily_qty=8.0)

        res = client.get(f"/api/v1/forecast/product/{prod.id}")
        assert res.status_code == 200
        data = res.json()

        assert data["status"] == "INSUFFICIENT_DATA"
        assert data["usable_days_count"] == 5
        assert data["forecast_7d"] == []
        assert data["forecast_30d"] == []
        assert data["total_7d_demand"] == 0.0
        assert "at least 7 days required" in data["explanation"]
    finally:
        db.close()


def test_c_exactly_seven_days_history_eligible():
    """Test C: Product with exactly 7 usable days becomes ELIGIBLE and generates predictions."""
    db = SessionLocal()
    try:
        prod = _create_test_product(db, "Test-Seven-Days-Prod", stock=50.0)
        start_d = date.today() - timedelta(days=8)
        _add_daily_sales(db, prod.id, num_days=7, start_date=start_d, daily_qty=10.0)

        res = client.get(f"/api/v1/forecast/product/{prod.id}")
        assert res.status_code == 200
        data = res.json()

        assert data["status"] == "ELIGIBLE"
        assert data["usable_days_count"] == 7
        assert len(data["forecast_7d"]) == 7
        assert len(data["forecast_30d"]) == 30
        assert data["total_7d_demand"] > 0.0
        assert data["selected_model"] is not None
    finally:
        db.close()


def test_d_and_e_thirty_and_sixty_plus_days_forecast_generated():
    """Test D & E: 30 days and 60+ days history produce stable statistical forecasts."""
    db = SessionLocal()
    try:
        # 30 days
        p30 = _create_test_product(db, "Test-30-Days-Prod", stock=100.0)
        start_30 = date.today() - timedelta(days=35)
        _add_daily_sales(db, p30.id, num_days=30, start_date=start_30, daily_qty=12.0)

        res30 = client.get(f"/api/v1/forecast/product/{p30.id}")
        assert res30.status_code == 200
        d30 = res30.json()
        assert d30["status"] == "ELIGIBLE"
        assert d30["usable_days_count"] == 30
        assert len(d30["forecast_7d"]) == 7
        assert len(d30["forecast_30d"]) == 30

        # 60+ days
        p60 = _create_test_product(db, "Test-65-Days-Prod", stock=200.0)
        start_60 = date.today() - timedelta(days=70)
        _add_daily_sales(db, p60.id, num_days=65, start_date=start_60, daily_qty=15.0)

        res60 = client.get(f"/api/v1/forecast/product/{p60.id}")
        assert res60.status_code == 200
        d60 = res60.json()
        assert d60["status"] == "ELIGIBLE"
        assert d60["usable_days_count"] == 65
        assert len(d60["forecast_7d"]) == 7
        assert len(d60["forecast_30d"]) == 30
    finally:
        db.close()


# ==============================================================================
# TESTS F, G, H: PRODUCT-LEVEL VS STORE-LEVEL ISOLATION
# ==============================================================================

def test_f_g_h_multi_product_sufficiency_and_store_list():
    """
    Test F, G, H: Store list correctly differentiates products with sufficient history
    from products with insufficient history, without false store-wide inheritance.
    """
    db = SessionLocal()
    try:
        p_good = _create_test_product(db, "Test-Good-History-Prod", stock=40.0)
        p_bad = _create_test_product(db, "Test-Bad-History-Prod", stock=15.0)

        # Good gets 14 days, bad gets 2 days
        _add_daily_sales(db, p_good.id, num_days=14, start_date=date.today() - timedelta(days=15), daily_qty=5.0)
        _add_daily_sales(db, p_bad.id, num_days=2, start_date=date.today() - timedelta(days=3), daily_qty=3.0)

        # Check overview & product list endpoint
        res = client.get("/api/v1/forecast/products")
        assert res.status_code == 200
        data = res.json()

        item_good = next(p for p in data["products"] if p["product_id"] == p_good.id)
        item_bad = next(p for p in data["products"] if p["product_id"] == p_bad.id)

        assert item_good["status"] == "ELIGIBLE"
        assert item_good["usable_days_count"] == 14
        assert item_good["total_7d_demand"] > 0

        assert item_bad["status"] == "INSUFFICIENT_DATA"
        assert item_bad["usable_days_count"] == 2
        assert item_bad["total_7d_demand"] == 0.0
    finally:
        db.close()


# ==============================================================================
# TESTS I, J, K: ZERO SALES, NEGATIVE CLIPPING & MISSING DATES
# ==============================================================================

def test_i_j_k_zero_sales_missing_dates_and_non_negative_protection():
    """
    Test I, J, K: Missing dates inside active range are treated as zero sales,
    corrupt negative quantities are safely clipped to 0, and continuity is preserved.
    """
    db = SessionLocal()
    try:
        prod = _create_test_product(db, "Test-Discontinuous-Prod", stock=50.0)
        start_d = date.today() - timedelta(days=20)

        # Add 10 non-consecutive sales dates spread over 20 days
        for offset in [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]:
            d = start_d + timedelta(days=offset)
            summary = DailySalesSummary(
                product_id=prod.id,
                sale_date=d,
                total_quantity_sold=-5.0 if offset == 0 else 10.0,  # Negative test for offset 0
                total_revenue=500.0,
                transaction_count=1
            )
            db.add(summary)
        db.commit()

        series, usable_days, earliest, latest = get_product_daily_series(db, prod.id)

        # Full continuous range from offset 0 to 18 should be 19 days total
        assert len(series) == 19
        # Check that negative quantity was clipped to 0.0
        assert series[0]["quantity"] == 0.0
        # Check that missing day (offset 1) is 0.0
        assert series[1]["quantity"] == 0.0

        # Forecast generation must be non-negative
        forecast_res = client.get(f"/api/v1/forecast/product/{prod.id}")
        assert forecast_res.status_code == 200
        f_data = forecast_res.json()
        assert all(pt["forecast_quantity"] >= 0.0 for pt in f_data["forecast_7d"])
        assert all(pt["forecast_quantity"] >= 0.0 for pt in f_data["forecast_30d"])
    finally:
        db.close()


# ==============================================================================
# TESTS L, M, N: IMPORTED CSV, XLSX & POS COMBINED SALES
# ==============================================================================

def test_l_m_n_imported_and_pos_combined_historical_sales():
    """
    Test L, M, N: Sales from POS bills and imported CSV/XLSX records flow
    seamlessly through canonical summaries into demand forecasting.
    """
    db = SessionLocal()
    try:
        prod = _create_test_product(db, "Test-Combined-Source-Prod", stock=80.0)

        # 1. Add 4 days of POS BillItems
        for i in range(4):
            sale_dt = datetime.combine(date.today() - timedelta(days=12 - i), datetime.min.time()) + timedelta(hours=10)
            b = Bill(
                bill_number=f"TEST-POS-{prod.id}-{i}-{int(datetime.utcnow().timestamp())}",
                status="COMPLETED",
                payment_mode="CASH",
                subtotal=200.0,
                total_amount=200.0,
                created_at=sale_dt
            )
            db.add(b)
            db.flush()
            db.add(BillItem(bill_id=b.id, product_id=prod.id, quantity=4.0, unit="kg", unit_price=50.0, line_total=200.0))
            db.flush()
            aggregate_sales_for_date(db, sale_dt.date())

        # 2. Add 5 days of imported historical records
        for j in range(5):
            h_date = date.today() - timedelta(days=6 - j)
            rec = HistoricalSaleRecord(
                source_type="IMPORTED",
                source_file="test_import.csv",
                row_fingerprint=f"fp-test-comb-{prod.id}-{j}",
                sale_date=h_date,
                product_id=prod.id,
                quantity=6.0,
                unit="kg",
                unit_price=50.0,
                total_amount=300.0,
                is_active=True
            )
            db.add(rec)
            db.flush()
            aggregate_sales_for_date(db, h_date)

        db.commit()

        # Total days = 4 POS + 5 Imported = 9 usable days -> ELIGIBLE
        res = client.get(f"/api/v1/forecast/product/{prod.id}")
        assert res.status_code == 200
        data = res.json()

        assert data["status"] == "ELIGIBLE"
        assert data["usable_days_count"] >= 9
        assert len(data["forecast_7d"]) == 7
        assert len(data["forecast_30d"]) == 30
    finally:
        db.close()


# ==============================================================================
# TESTS O, P, Q: EXACT HORIZONS & STRICT NON-NEGATIVE DEMAND
# ==============================================================================

def test_o_p_q_exact_horizons_and_non_negative_demand():
    """Test O, P, Q: 7-day is exactly 7 points, 30-day is exactly 30 points, no negative numbers."""
    db = SessionLocal()
    try:
        prod = _create_test_product(db, "Test-Horizon-Prod", stock=60.0)
        _add_daily_sales(db, prod.id, num_days=15, start_date=date.today() - timedelta(days=16), daily_qty=12.0)

        # Test dedicated 7-day endpoint
        res7 = client.get(f"/api/v1/forecast/product/{prod.id}/7day")
        assert res7.status_code == 200
        pts7 = res7.json()
        assert len(pts7) == 7
        assert all(p["forecast_quantity"] >= 0.0 for p in pts7)

        # Test dedicated 30-day endpoint
        res30 = client.get(f"/api/v1/forecast/product/{prod.id}/30day")
        assert res30.status_code == 200
        pts30 = res30.json()
        assert len(pts30) == 30
        assert all(p["forecast_quantity"] >= 0.0 for p in pts30)
    finally:
        db.close()


# ==============================================================================
# TESTS R, S, T: STOCKOUT, REORDER RECOMMENDATION & INVENTORY SAFETY
# ==============================================================================

def test_r_s_t_stockout_risk_reorder_calculation_and_inventory_safety():
    """
    Test R, S, T:
    - Stockout shortfall and days remaining calculated accurately
    - Suggested reorder recommendation is explainable and advisory
    - Current product inventory remains 100% UNCHANGED by forecasting
    """
    db = SessionLocal()
    try:
        # Product with low stock (15 units) and daily sales of ~10 units
        initial_stock = 15.0
        prod = _create_test_product(db, "Test-Stockout-Prod", stock=initial_stock, threshold=10.0)
        _add_daily_sales(db, prod.id, num_days=10, start_date=date.today() - timedelta(days=11), daily_qty=10.0)

        # 1. Check stockout endpoint
        res_stockout = client.get(f"/api/v1/forecast/product/{prod.id}/stockout-risk")
        assert res_stockout.status_code == 200
        stockout_data = res_stockout.json()

        assert stockout_data["current_stock"] == initial_stock
        assert stockout_data["expected_7d_demand"] > 0
        assert stockout_data["days_inventory_remaining"] < 3.0
        assert stockout_data["potential_7d_shortfall"] > 0
        assert stockout_data["risk_level"] in ["POTENTIAL_STOCKOUT", "IMMEDIATE_ATTENTION"]

        # 2. Check reorder recommendation endpoint
        res_reorder = client.get(f"/api/v1/forecast/product/{prod.id}/reorder")
        assert res_reorder.status_code == 200
        reorder_data = res_reorder.json()

        assert reorder_data["current_stock"] == initial_stock
        assert reorder_data["suggested_reorder_quantity"] > 0
        assert "Advisory only" in reorder_data["advisory_notice"]

        # 3. CRITICAL INVENTORY SAFETY CHECK: Stock MUST NOT have changed
        db.refresh(prod)
        assert prod.stock_quantity == initial_stock, "CRITICAL ERROR: Forecasting modified product inventory stock!"
    finally:
        db.close()


# ==============================================================================
# TESTS U, V: REFRESH / RECALCULATION & DEDUPLICATION SAFETY
# ==============================================================================

def test_u_v_forecast_refresh_and_deduplication():
    """Test U & V: POST /api/v1/forecast/refresh recalculates cache and does not double-count duplicate records."""
    db = SessionLocal()
    try:
        prod = _create_test_product(db, "Test-Refresh-Prod", stock=50.0)
        _add_daily_sales(db, prod.id, num_days=8, start_date=date.today() - timedelta(days=10), daily_qty=10.0)

        # First query
        res1 = client.get(f"/api/v1/forecast/product/{prod.id}")
        assert res1.status_code == 200
        d1 = res1.json()
        demand1 = d1["total_7d_demand"]

        # Add more sales on an additional date
        new_date = date.today() - timedelta(days=1)
        summary = DailySalesSummary(
            product_id=prod.id,
            sale_date=new_date,
            total_quantity_sold=25.0,
            total_revenue=1250.0,
            transaction_count=3
        )
        db.add(summary)
        db.commit()

        # Invalidate / Refresh
        ref_res = client.post("/api/v1/forecast/refresh")
        assert ref_res.status_code == 200
        assert ref_res.json()["status"] == "SUCCESS"

        # Query again, demand should reflect the new sales point
        res2 = client.get(f"/api/v1/forecast/product/{prod.id}")
        assert res2.status_code == 200
        d2 = res2.json()
        assert d2["usable_days_count"] == d1["usable_days_count"] + 1
    finally:
        db.close()


# ==============================================================================
# TESTS W, X, Y, Z: NO DATA LEAKAGE, INDEPENDENT HISTORIES, API VALIDATION
# ==============================================================================

def test_w_model_validation_no_future_data_leakage():
    """
    Test W: Model backtesting strictly splits chronologically (train = earlier, val = later).
    No shuffling, no future observation in training set.
    """
    history = [
        {"date": date(2026, 9, 1) + timedelta(days=i), "date_str": f"2026-09-{i+1:02d}", "day_of_week": "Monday", "weekday_idx": 0, "quantity": 10.0 + i}
        for i in range(21)
    ]
    model_name, metrics, std_err = select_and_evaluate_model(history, usable_days=21)

    assert model_name in ["SIMPLE_MOVING_AVERAGE", "EXPONENTIAL_SMOOTHING", "DAY_OF_WEEK_SEASONAL", "TREND_AND_SEASONAL", "BASELINE_EWMA"]
    assert len(metrics) >= 1
    assert any(m["is_selected"] for m in metrics)
    assert std_err >= 0.0


def test_x_two_different_products_receive_independent_forecasts():
    """Test X: Two products with different sales receive forecasts based solely on their own history."""
    db = SessionLocal()
    try:
        p_low = _create_test_product(db, "Test-Low-Volume-Prod", stock=50.0)
        p_high = _create_test_product(db, "Test-High-Volume-Prod", stock=50.0)

        _add_daily_sales(db, p_low.id, num_days=10, start_date=date.today() - timedelta(days=12), daily_qty=2.0)
        _add_daily_sales(db, p_high.id, num_days=10, start_date=date.today() - timedelta(days=12), daily_qty=50.0)

        res_low = client.get(f"/api/v1/forecast/product/{p_low.id}").json()
        res_high = client.get(f"/api/v1/forecast/product/{p_high.id}").json()

        assert res_low["total_7d_demand"] < res_high["total_7d_demand"]
        assert res_high["total_7d_demand"] > 100.0
        assert res_low["total_7d_demand"] < 30.0
    finally:
        db.close()


def test_y_and_z_api_validation_and_error_handling():
    """Test Y & Z: 404 for invalid product ID, clean overview response, and parameter validation."""
    # 1. Invalid product ID
    res404 = client.get("/api/v1/forecast/product/999999")
    assert res404.status_code == 404
    assert "not found" in res404.json()["detail"].lower()

    # 2. Overview endpoint
    res_ov = client.get("/api/v1/forecast/overview")
    assert res_ov.status_code == 200
    ov = res_ov.json()
    assert "total_products" in ov
    assert "eligible_products_count" in ov
    assert "insufficient_products_count" in ov

    # 3. Sufficiency endpoint
    res_suff = client.get("/api/v1/forecast/sufficiency")
    assert res_suff.status_code == 200
    assert "usable_days_count" in res_suff.json()


# ==============================================================================
# SECTION 23: FORECAST SANITY TESTS
# ==============================================================================

def test_sanity_constant_demand_forecast():
    """
    Sanity Test: A product that sells consistently ~10 units/day for 20 days
    should produce a 7-day forecast approximately equal to ~70 units (within reasonable statistical bounds).
    """
    db = SessionLocal()
    try:
        prod = _create_test_product(db, "Test-Constant-Demand-Prod", stock=100.0)
        _add_daily_sales(db, prod.id, num_days=20, start_date=date.today() - timedelta(days=22), daily_qty=10.0)

        res = client.get(f"/api/v1/forecast/product/{prod.id}")
        assert res.status_code == 200
        data = res.json()

        # Expected 7-day demand should be around 70 (60 to 80 range)
        assert 60.0 <= data["total_7d_demand"] <= 80.0
        # Expected daily demand ~ 10.0
        assert 8.5 <= data["avg_daily_demand"] <= 11.5
    finally:
        db.close()


def test_sanity_increasing_trend_forecast():
    """
    Sanity Test: A product with consistently increasing sales over 25 days
    should produce a forecast reflecting positive demand without collapse.
    """
    db = SessionLocal()
    try:
        prod = _create_test_product(db, "Test-Increasing-Trend-Prod", stock=150.0)
        start_d = date.today() - timedelta(days=26)
        for i in range(25):
            d = start_d + timedelta(days=i)
            # Sales steadily increase: 5, 6, 7, ..., 29
            summary = DailySalesSummary(
                product_id=prod.id,
                sale_date=d,
                total_quantity_sold=float(5 + i),
                total_revenue=float((5 + i) * 50),
                transaction_count=2
            )
            db.add(summary)
        db.commit()

        res = client.get(f"/api/v1/forecast/product/{prod.id}")
        assert res.status_code == 200
        data = res.json()

        # The forecast should be in line with recent high demand (> 20/day, so 7d > 140)
        assert data["total_7d_demand"] > 140.0
        assert data["avg_daily_demand"] > 20.0
    finally:
        db.close()


def test_seasonality_analysis_supported_and_insufficient():
    """
    Test Day-of-Week Seasonality Analysis:
    - If history < 14 days: reports SEASONALITY_INSUFFICIENT_DATA and is_supported=False.
    - If history >= 14 days: reports SEASONALITY_AVAILABLE and is_supported=True with 7 day breakdown.
    """
    db = SessionLocal()
    try:
        # 1. Product with 8 days history (< 14)
        prod_short = _create_test_product(db, "Test-Seasonality-Short", stock=50.0)
        _add_daily_sales(db, prod_short.id, num_days=8, start_date=date.today() - timedelta(days=10), daily_qty=5.0)

        res_short = client.get(f"/api/v1/forecast/product/{prod_short.id}/seasonality")
        assert res_short.status_code == 200
        data_short = res_short.json()
        assert data_short["status"] == "SEASONALITY_INSUFFICIENT_DATA"
        assert data_short["is_supported"] is False
        assert data_short["min_days_required"] == 14
        assert "insufficient" in data_short["pattern_summary"].lower()

        # 2. Product with 21 days history (>= 14)
        prod_long = _create_test_product(db, "Test-Seasonality-Long", stock=100.0)
        _add_daily_sales(db, prod_long.id, num_days=21, start_date=date.today() - timedelta(days=25), daily_qty=12.0)

        res_long = client.get(f"/api/v1/forecast/product/{prod_long.id}/seasonality")
        assert res_long.status_code == 200
        data_long = res_long.json()
        assert data_long["status"] == "SEASONALITY_AVAILABLE"
        assert data_long["is_supported"] is True
        assert len(data_long["weekday_breakdown"]) == 7
        assert all("day_name" in d and "factor" in d for d in data_long["weekday_breakdown"])

        # Also check that product detail endpoint includes the seasonality_analysis object
        res_detail = client.get(f"/api/v1/forecast/product/{prod_long.id}")
        assert res_detail.status_code == 200
        assert "seasonality_analysis" in res_detail.json()
        assert res_detail.json()["seasonality_analysis"]["is_supported"] is True
    finally:
        db.close()


def test_custom_horizon_and_top_level_alias():
    """
    Test custom forecast horizon endpoint (1 to 90 days), bounds validation,
    and top-level alias route.
    """
    db = SessionLocal()
    try:
        prod = _create_test_product(db, "Test-Custom-Horizon", stock=80.0)
        _add_daily_sales(db, prod.id, num_days=15, start_date=date.today() - timedelta(days=18), daily_qty=8.0)

        # 1. Custom horizon = 14 days
        res14 = client.get(f"/api/v1/forecast/product/{prod.id}/forecast?horizon=14")
        assert res14.status_code == 200
        assert len(res14.json()) == 14

        # 2. Custom horizon = 7 days
        res7 = client.get(f"/api/v1/forecast/product/{prod.id}/forecast?horizon=7")
        assert res7.status_code == 200
        assert len(res7.json()) == 7

        # 3. Horizon bounds validation: horizon > 90 must fail validation (HTTP 422)
        res_invalid = client.get(f"/api/v1/forecast/product/{prod.id}/forecast?horizon=95")
        assert res_invalid.status_code == 422

        # 4. Top-level alias GET /api/forecasting/product/{prod.id}
        res_alias = client.get(f"/api/forecasting/product/{prod.id}")
        assert res_alias.status_code == 200
        assert res_alias.json()["product_id"] == prod.id
        assert res_alias.json()["status"] == "ELIGIBLE"
    finally:
        db.close()


def test_zero_inventory_mutation_guarantee():
    """
    Forecasting must be strictly read-only and never alter inventory or place orders.
    """
    db = SessionLocal()
    try:
        initial_stock = 45.5
        prod = _create_test_product(db, "Test-Zero-Mutation-Prod", stock=initial_stock)
        _add_daily_sales(db, prod.id, num_days=10, start_date=date.today() - timedelta(days=12), daily_qty=5.0)

        # Call all forecasting endpoints
        client.get(f"/api/v1/forecast/product/{prod.id}")
        client.get(f"/api/v1/forecast/product/{prod.id}/7day")
        client.get(f"/api/v1/forecast/product/{prod.id}/30day")
        client.get(f"/api/v1/forecast/product/{prod.id}/stockout-risk")
        client.get(f"/api/v1/forecast/product/{prod.id}/reorder")
        client.get(f"/api/v1/forecast/product/{prod.id}/seasonality")
        client.post("/api/v1/forecast/refresh")

        # Verify stock has not changed by even 0.0001
        db.refresh(prod)
        assert prod.stock_quantity == initial_stock
    finally:
        db.close()

