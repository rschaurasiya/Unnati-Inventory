"""
Demand Forecasting & Stock/Reorder Intelligence Router (Step 11)
Provides endpoints for store-wide forecast overviews, product-level 7-day & 30-day predictions,
stockout risk assessments, advisory reorder recommendations, and cache invalidation.
Strictly read-only: does not modify inventory or place orders.
"""
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Product
from backend.schemas import (
    ForecastListResponse,
    ForecastOverviewResponse,
    ProductForecastDetailResponse,
    ProductForecastSummaryItem,
    RefreshForecastResponse,
    StockoutRiskAnalysis,
    ReorderRecommendation,
    DailyForecastPoint,
    ProductDataSufficiencyResponse,
    StoreDataSufficiencySummaryResponse,
    SeasonalityAnalysis
)
from backend.services.forecasting import (
    generate_product_forecast,
    get_all_product_forecasts,
    invalidate_forecast_cache
)
from backend.services.forecasting_sufficiency import (
    evaluate_product_data_sufficiency,
    evaluate_all_products_data_sufficiency
)
from backend.services.sales_aggregation import check_data_sufficiency

router = APIRouter(prefix="/api/v1/forecast", tags=["Demand Forecasting & Reorder Intelligence"])


@router.get("/overview", response_model=ForecastOverviewResponse, status_code=status.HTTP_200_OK)
@router.get("/summary", response_model=ForecastOverviewResponse, status_code=status.HTTP_200_OK)
def get_forecast_overview(
    db: Session = Depends(get_db)
):
    """
    Returns store-wide demand forecasting overview metrics:
    total products, forecastable products, insufficient history count,
    products at stockout risk, and reorder alerts.
    """
    data = get_all_product_forecasts(db, force_refresh=False)
    return data["overview"]


@router.get("/products", response_model=ForecastListResponse, status_code=status.HTTP_200_OK)
@router.get("/all", response_model=ForecastListResponse, status_code=status.HTTP_200_OK)
def get_products_forecast(
    risk_level: Optional[str] = Query(None, description="Optional filter by risk level: IMMEDIATE_ATTENTION, POTENTIAL_STOCKOUT, LOW_STOCK, SUFFICIENT, INSUFFICIENT_DATA"),
    status_filter: Optional[str] = Query(None, alias="status", description="Optional filter by status: ELIGIBLE, INSUFFICIENT_DATA"),
    force_refresh: bool = Query(False, description="Force recalculation bypassing cache"),
    db: Session = Depends(get_db)
):
    """
    Lists demand forecasts and stockout risk summaries for all active catalog products.
    """
    data = get_all_product_forecasts(db, force_refresh=force_refresh)

    products = data["products"]
    if risk_level:
        products = [p for p in products if p["risk_level"].upper() == risk_level.strip().upper()]
    if status_filter:
        products = [p for p in products if p["status"].upper() == status_filter.strip().upper()]

    return {
        "overview": data["overview"],
        "products": products
    }


@router.get("/charts", status_code=status.HTTP_200_OK)
def get_forecasting_charts(
    product_id: Optional[int] = Query(None, description="Product ID to visualize (defaults to first priority product)"),
    horizon: int = Query(7, ge=7, le=30, description="Forecast horizon in days (7 or 30)"),
    db: Session = Depends(get_db)
):
    """
    Returns verified, structured visualization payloads for Demand Forecasting:
    - Actual vs Forecast Demand timeline (differentiating past actuals from future predictions)
    - Restocking & stock comparison (current stock vs forecast demand vs safety buffer vs suggested reorder)
    - Model selection & walk-forward accuracy evaluation disclosure.
    Strictly tenant-safe and read-only.
    """
    products_db = db.query(Product).order_by(Product.name.asc()).all()
    if not products_db:
        return {
            "products": [],
            "selected_product": None,
            "horizon": horizon,
            "demand_chart": {"labels": [], "historical_series": [], "forecast_series": [], "is_forecast_available": False},
            "reorder_chart": {"labels": [], "values": [], "is_forecast_based": False},
            "model_evaluation": {"evaluation_available": False, "selected_model": None, "metrics": [], "notes": "No products found in store catalog."}
        }

    target_product = None
    if product_id is not None:
        target_product = next((p for p in products_db if p.id == product_id), None)
        if not target_product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with ID {product_id} not found."
            )
    else:
        # Default to first urgent or low stock item if available
        all_fc = get_all_product_forecasts(db, force_refresh=False)
        urgent_pids = [
            p["product_id"] for p in all_fc.get("products", [])
            if p.get("risk_level") in ("IMMEDIATE_ATTENTION", "LOW_STOCK", "POTENTIAL_STOCKOUT")
        ]
        if urgent_pids:
            target_product = next((p for p in products_db if p.id == urgent_pids[0]), products_db[0])
        else:
            normal_prods = [p for p in products_db if not p.name.startswith("=")]
            target_product = normal_prods[0] if normal_prods else products_db[0]

    fc_data = generate_product_forecast(db, target_product, force_recalculate=False)
    status_str = fc_data.get("status", "INSUFFICIENT_DATA")
    usable_days = fc_data.get("usable_days_count", 0)
    current_stock = float(target_product.stock_quantity or 0.0)
    unit = target_product.unit or "units"
    recent_history = fc_data.get("recent_history", [])
    fc_points = fc_data.get("forecast_30d" if horizon > 7 else "forecast_7d", [])
    reorder_rec = fc_data.get("reorder_recommendation", {})
    safety_stock = float(reorder_rec.get("safety_stock", target_product.min_stock_threshold or 10.0))

    # 1. Demand Chart Series
    if status_str == "ELIGIBLE" and fc_points:
        disp_history = recent_history[-14:] if len(recent_history) > 14 else recent_history
        hist_labels = [h["date"] for h in disp_history]
        fc_labels = [f["date"] for f in fc_points]
        all_labels = hist_labels + fc_labels

        hist_values = [h["actual_quantity"] for h in disp_history] + [None] * len(fc_labels)
        if disp_history:
            fc_values = [None] * (len(disp_history) - 1) + [disp_history[-1]["actual_quantity"]] + [f["forecast_quantity"] for f in fc_points]
        else:
            fc_values = [f["forecast_quantity"] for f in fc_points]

        lower_bounds = [None] * len(disp_history) + [f.get("lower_bound") for f in fc_points]
        upper_bounds = [None] * len(disp_history) + [f.get("upper_bound") for f in fc_points]

        demand_chart = {
            "labels": all_labels,
            "historical_series": hist_values,
            "forecast_series": fc_values,
            "lower_bounds": lower_bounds,
            "upper_bounds": upper_bounds,
            "is_forecast_available": True,
            "split_index": len(disp_history) - 1 if disp_history else 0,
            "split_date": disp_history[-1]["date"] if disp_history else None,
            "reason": None
        }
    else:
        hist_labels = [h["date"] for h in recent_history]
        hist_values = [h["actual_quantity"] for h in recent_history]
        demand_chart = {
            "labels": hist_labels,
            "historical_series": hist_values,
            "forecast_series": [],
            "lower_bounds": [],
            "upper_bounds": [],
            "is_forecast_available": False,
            "split_index": -1,
            "split_date": None,
            "reason": f"Insufficient sales history ({usable_days} recorded sales days). Minimum 7 days required."
        }

    # 2. Reorder Comparison Chart
    if status_str == "ELIGIBLE":
        expected_demand = float(fc_data.get("total_30d_demand" if horizon > 7 else "total_7d_demand", 0.0))
        suggested_order = max(0.0, round((expected_demand + safety_stock) - current_stock, 2))
        reorder_chart = {
            "labels": ["Current Stock", f"Expected {horizon}d Demand", "Safety Buffer", "Suggested Order"],
            "values": [current_stock, expected_demand, safety_stock, suggested_order],
            "unit": unit,
            "is_forecast_based": True,
            "formula": f"max(0, ({expected_demand} + {safety_stock}) - {current_stock}) = {suggested_order} {unit}"
        }
    else:
        suggested_order = max(0.0, round(safety_stock - current_stock, 2))
        reorder_chart = {
            "labels": ["Current Stock", "Min Threshold", "Suggested Restock"],
            "values": [current_stock, safety_stock, suggested_order],
            "unit": unit,
            "is_forecast_based": False,
            "formula": f"max(0, {safety_stock} - {current_stock}) = {suggested_order} {unit} (Threshold fallback)"
        }

    # 3. Model Accuracy & Evaluation Disclosure
    if status_str == "ELIGIBLE":
        selected_model = fc_data.get("selected_model", "EXPONENTIAL_SMOOTHING")
        metrics = fc_data.get("model_metrics", [])
        winning_metric = next((m for m in metrics if m.get("is_selected")), None)
        accuracy_score = None
        if winning_metric and winning_metric.get("wape") is not None:
            wape = winning_metric["wape"]
            if wape < 1.0:
                accuracy_score = round((1.0 - wape) * 100, 1)

        model_evaluation = {
            "evaluation_available": True,
            "selected_model": selected_model,
            "model_label": selected_model.replace("_", " ").title(),
            "accuracy_score": accuracy_score,
            "accuracy_label": f"{accuracy_score}% Accuracy" if accuracy_score is not None else "High Volatility",
            "metrics": metrics,
            "winning_metric": winning_metric,
            "notes": "Model selected via walk-forward cross-validation on actual historical daily sales records without lookahead bias."
        }
    else:
        model_evaluation = {
            "evaluation_available": False,
            "selected_model": "None (Insufficient Data)",
            "model_label": "Unavailable",
            "accuracy_score": None,
            "accuracy_label": "N/A",
            "metrics": [],
            "winning_metric": None,
            "notes": f"Evaluation unavailable: Product has only {usable_days} sales days (< 7 required)."
        }

    return {
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category or "General",
                "unit": p.unit or "units",
                "current_stock": float(p.stock_quantity or 0.0),
                "is_selected": (p.id == target_product.id)
            }
            for p in products_db
        ],
        "selected_product": {
            "id": target_product.id,
            "name": target_product.name,
            "category": target_product.category or "General",
            "unit": target_product.unit or "units",
            "current_stock": current_stock,
            "status": status_str,
            "usable_days_count": usable_days,
            "min_days_required": 7
        },
        "horizon": horizon,
        "demand_chart": demand_chart,
        "reorder_chart": reorder_chart,
        "model_evaluation": model_evaluation
    }


@router.get("/product/{product_id}", response_model=ProductForecastDetailResponse, status_code=status.HTTP_200_OK)
def get_product_forecast_detail(
    product_id: int,
    force_refresh: bool = Query(False, description="Force recalculation bypassing cache"),
    db: Session = Depends(get_db)
):
    """
    Comprehensive demand intelligence for a single product:
    7-day and 30-day daily predictions, historical demand time series,
    selected statistical model with walk-forward validation metrics,
    deterministic stockout risk timeline, explainable reorder recommendations.
    If product has < 7 usable historical days, clearly returns INSUFFICIENT_DATA status.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found in catalog."
        )

    return generate_product_forecast(db, product, force_recalculate=force_refresh)


@router.get("/product/{product_id}/7day", response_model=List[DailyForecastPoint], status_code=status.HTTP_200_OK)
def get_product_7day_forecast(
    product_id: int,
    db: Session = Depends(get_db)
):
    """
    Returns exactly the 7-day daily forecast for the specified product.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found in catalog."
        )

    forecast_data = generate_product_forecast(db, product)
    return forecast_data.get("forecast_7d", [])


@router.get("/product/{product_id}/30day", response_model=List[DailyForecastPoint], status_code=status.HTTP_200_OK)
def get_product_30day_forecast(
    product_id: int,
    db: Session = Depends(get_db)
):
    """
    Returns exactly the 30-day daily forecast for the specified product.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found in catalog."
        )

    forecast_data = generate_product_forecast(db, product)
    return forecast_data.get("forecast_30d", [])


@router.get("/product/{product_id}/stockout-risk", response_model=StockoutRiskAnalysis, status_code=status.HTTP_200_OK)
def get_product_stockout_risk(
    product_id: int,
    db: Session = Depends(get_db)
):
    """
    Returns deterministic stockout risk metrics and projected stockout timeline.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found in catalog."
        )

    forecast_data = generate_product_forecast(db, product)
    return forecast_data["stockout_risk"]


@router.get("/product/{product_id}/reorder", response_model=ReorderRecommendation, status_code=status.HTTP_200_OK)
def get_product_reorder_recommendation(
    product_id: int,
    db: Session = Depends(get_db)
):
    """
    Returns advisory reorder recommendations with formula breakdown.
    Advisory only: does not place orders or alter stock.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found in catalog."
        )

    forecast_data = generate_product_forecast(db, product)
    return forecast_data["reorder_recommendation"]


@router.get("/product/{product_id}/seasonality", response_model=SeasonalityAnalysis, status_code=status.HTTP_200_OK)
def get_product_seasonality(
    product_id: int,
    db: Session = Depends(get_db)
):
    """
    Returns day-of-week seasonality analysis.
    If historical data < 14 days, reports SEASONALITY_INSUFFICIENT_DATA status.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found in catalog."
        )

    forecast_data = generate_product_forecast(db, product)
    seasonality = forecast_data.get("seasonality_analysis")
    if not seasonality:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Seasonality data unavailable for product {product_id}."
        )
    return seasonality


@router.get("/product/{product_id}/forecast", response_model=List[DailyForecastPoint], status_code=status.HTTP_200_OK)
def get_product_custom_forecast(
    product_id: int,
    horizon: int = Query(7, ge=1, le=90, description="Forecast horizon between 1 and 90 days"),
    db: Session = Depends(get_db)
):
    """
    Returns daily forecast points up to the requested horizon (1-90 days).
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found in catalog."
        )

    forecast_data = generate_product_forecast(db, product)
    full_30d = forecast_data.get("forecast_30d", [])
    if horizon <= len(full_30d):
        return full_30d[:horizon]
    return full_30d


@router.get("/sufficiency", status_code=status.HTTP_200_OK)
def get_forecast_data_sufficiency(
    product_id: Optional[int] = Query(None, description="Optional product ID filter"),
    db: Session = Depends(get_db)
):
    """
    Evaluates historical data sufficiency gate:
    < 7 usable days -> INSUFFICIENT_DATA (Forecasting unavailable)
    >= 7 usable days -> SUFFICIENT_DATA (Forecasting eligible)
    """
    return check_data_sufficiency(db, product_id)


@router.get("/data-sufficiency", status_code=status.HTTP_200_OK)
def get_forecasting_data_sufficiency(
    product_id: Optional[int] = Query(None, description="Optional catalog product ID"),
    db: Session = Depends(get_db)
):
    """
    Step 11A: Product-level Historical Data Sufficiency Validation Gate.
    Determines independently for a product (or all products) whether >= 7 distinct
    usable calendar sales days exist to qualify for forecasting.
    """
    if product_id is not None:
        result = evaluate_product_data_sufficiency(db, product_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with ID {product_id} not found in catalog."
            )
        return result
    return evaluate_all_products_data_sufficiency(db)


@router.get("/data-sufficiency/{product_id}", response_model=ProductDataSufficiencyResponse, status_code=status.HTTP_200_OK)
def get_single_product_data_sufficiency(
    product_id: int,
    db: Session = Depends(get_db)
):
    """
    Step 11A: Product-specific Historical Data Sufficiency Validation Gate.
    """
    result = evaluate_product_data_sufficiency(db, product_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found in catalog."
        )
    return result


@router.post("/refresh", response_model=RefreshForecastResponse, status_code=status.HTTP_200_OK)
def refresh_all_forecasts(
    db: Session = Depends(get_db)
):
    """
    Invalidates forecast cache and recalculates predictions across all catalog products.
    """
    invalidate_forecast_cache()
    data = get_all_product_forecasts(db, force_refresh=True)

    return RefreshForecastResponse(
        status="SUCCESS",
        message="Demand forecasts and stockout analytics successfully recalculated for all products.",
        products_processed=data["overview"]["total_products"],
        eligible_count=data["overview"]["eligible_products_count"],
        refreshed_at=datetime.utcnow()
    )
