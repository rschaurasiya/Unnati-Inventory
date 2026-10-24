"""
Demand Forecasting & Stock/Reorder Intelligence Service (Step 11)
Provides deterministic, statistical demand forecasting, time-series-aware model selection,
stockout risk analysis, explainable reorder recommendations, and caching.
Zero inventory mutation: forecasting is strictly read-only and advisory.
"""
import math
import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.models import Product, DailySalesSummary, ProductForecast

logger = logging.getLogger(__name__)

# Global in-memory cache for fast repeated reads
_FORECAST_CACHE: Dict[int, Dict[str, Any]] = {}
_LAST_CACHE_CLEAR: datetime = datetime.utcnow()


def invalidate_forecast_cache(product_id: Optional[int] = None) -> None:
    """Invalidates in-memory forecast cache for a specific product or globally."""
    global _FORECAST_CACHE, _LAST_CACHE_CLEAR
    if product_id is not None:
        _FORECAST_CACHE.pop(product_id, None)
    else:
        _FORECAST_CACHE.clear()
        _LAST_CACHE_CLEAR = datetime.utcnow()


# ==============================================================================
# 1. Product-Level Time Series Builder
# ==============================================================================

def get_product_daily_series(db: Session, product_id: int) -> Tuple[List[Dict[str, Any]], int, Optional[date], Optional[date]]:
    """
    Constructs a continuous daily time series for a product from its earliest recorded sale
    to the store's latest recorded sale date.
    Missing dates within this operational range are represented as 0.0 sales.
    Applies outlier winsorization/clamping to prevent extreme single-day bulk spikes from distorting forecasts.
    Returns:
      (continuous_series, usable_days_count, earliest_date, latest_date)
    """
    summaries = (
        db.query(DailySalesSummary)
        .filter(DailySalesSummary.product_id == product_id)
        .order_by(DailySalesSummary.sale_date.asc())
        .all()
    )

    if not summaries:
        return [], 0, None, None

    # Count distinct days with positive sales
    positive_summaries = [s for s in summaries if (s.total_quantity_sold or 0.0) > 0]
    usable_days_count = len({s.sale_date for s in positive_summaries})

    earliest_date = summaries[0].sale_date
    product_latest_date = summaries[-1].sale_date

    # 1. Extend Daily Time-Series Window to Store's Latest Date
    store_max_date = db.query(func.max(DailySalesSummary.sale_date)).scalar()
    series_end_date = max(product_latest_date, store_max_date) if store_max_date else product_latest_date

    # 2. Outlier Winsorization/Clamping for Extreme Bulk Spikes
    outlier_cap = None
    if usable_days_count >= 7:
        pos_quantities = np.array([float(s.total_quantity_sold or 0.0) for s in positive_summaries], dtype=float)
        q25, q75 = np.percentile(pos_quantities, [25, 75])
        iqr = float(q75 - q25)
        med = float(np.median(pos_quantities))
        cap_iqr = med + 3.0 * iqr
        cap_p95 = float(np.percentile(pos_quantities, 95))
        if iqr > 0:
            outlier_cap = min(cap_iqr, cap_p95)
        else:
            outlier_cap = cap_p95

    # Map existing dates with outlier clamping applied
    sales_map: Dict[date, float] = {}
    for s in summaries:
        val = max(0.0, float(s.total_quantity_sold or 0.0))
        if outlier_cap is not None and val > outlier_cap:
            val = round(outlier_cap, 2)
        sales_map[s.sale_date] = val

    continuous_series: List[Dict[str, Any]] = []
    curr = earliest_date
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    while curr <= series_end_date:
        qty = sales_map.get(curr, 0.0)
        continuous_series.append({
            "date": curr,
            "date_str": curr.isoformat(),
            "day_of_week": day_names[curr.weekday()],
            "weekday_idx": curr.weekday(),
            "quantity": qty
        })
        curr += timedelta(days=1)

    return continuous_series, usable_days_count, earliest_date, series_end_date


# ==============================================================================
# 2. Statistical Forecasting Models (Deterministic, Non-LLM)
# ==============================================================================

class ForecastingModels:
    """Deterministic, reproducible statistical time-series forecasting models."""

    @staticmethod
    def sma(history_qty: List[float], horizon: int, window: int = 7) -> List[float]:
        """Simple Moving Average (SMA)."""
        if not history_qty:
            return [0.0] * horizon
        w = min(len(history_qty), max(1, window))
        avg = float(np.mean(history_qty[-w:]))
        val = max(0.0, round(avg, 2))
        return [val] * horizon

    @staticmethod
    def ewma(history_qty: List[float], horizon: int, alpha: float = 0.3) -> List[float]:
        """Exponentially Weighted Moving Average (EWMA)."""
        if not history_qty:
            return [0.0] * horizon
        s = history_qty[0]
        for y in history_qty[1:]:
            s = alpha * y + (1.0 - alpha) * s
        val = max(0.0, round(float(s), 2))
        return [val] * horizon

    @staticmethod
    def dow_seasonal(
        history: List[Dict[str, Any]],
        horizon: int,
        start_date: date,
        base_method: str = "ewma"
    ) -> List[float]:
        """Day-of-Week Seasonality Model."""
        if not history:
            return [0.0] * horizon

        quantities = [h["quantity"] for h in history]
        overall_mean = float(np.mean(quantities))
        if overall_mean <= 0:
            return [0.0] * horizon

        # Calculate weekday factors
        weekday_sums = {i: [] for i in range(7)}
        for h in history:
            weekday_sums[h["weekday_idx"]].append(h["quantity"])

        factors = {}
        for dow, vals in weekday_sums.items():
            if vals:
                dow_mean = float(np.mean(vals))
                factors[dow] = np.clip(dow_mean / overall_mean, 0.25, 2.5)
            else:
                factors[dow] = 1.0

        # Recent baseline level
        if base_method == "ewma":
            base_level = ForecastingModels.ewma(quantities, 1)[0]
        else:
            base_level = ForecastingModels.sma(quantities, 1, window=7)[0]

        predictions: List[float] = []
        for step in range(horizon):
            target_dt = start_date + timedelta(days=step)
            dow = target_dt.weekday()
            pred = max(0.0, round(base_level * factors.get(dow, 1.0), 2))
            predictions.append(pred)

        return predictions

    @staticmethod
    def trend_seasonal(
        history: List[Dict[str, Any]],
        horizon: int,
        start_date: date
    ) -> List[float]:
        """Linear Trend + Day-of-Week Seasonality Model."""
        if not history or len(history) < 14:
            return ForecastingModels.dow_seasonal(history, horizon, start_date)

        n = len(history)
        y = np.array([h["quantity"] for h in history], dtype=float)
        x = np.arange(n, dtype=float)

        mean_x = np.mean(x)
        mean_y = np.mean(y)

        # OLS slope and intercept
        denom = np.sum((x - mean_x) ** 2)
        if denom > 0:
            slope = float(np.sum((x - mean_x) * (y - mean_y)) / denom)
        else:
            slope = 0.0

        intercept = float(mean_y - slope * mean_x)

        # Clamp slope so long-horizon projections don't explode or collapse drastically
        max_slope = 0.05 * max(mean_y, 1.0)
        slope = float(np.clip(slope, -max_slope, max_slope))

        # DOW seasonality factors
        weekday_sums = {i: [] for i in range(7)}
        for h in history:
            weekday_sums[h["weekday_idx"]].append(h["quantity"])

        factors = {}
        for dow, vals in weekday_sums.items():
            if vals and mean_y > 0:
                dow_mean = float(np.mean(vals))
                factors[dow] = np.clip(dow_mean / mean_y, 0.3, 2.5)
            else:
                factors[dow] = 1.0

        predictions: List[float] = []
        for step in range(horizon):
            future_t = n + step
            trend_val = max(0.0, intercept + slope * future_t)
            target_dt = start_date + timedelta(days=step)
            dow = target_dt.weekday()
            pred = max(0.0, round(trend_val * factors.get(dow, 1.0), 2))
            predictions.append(pred)

        return predictions


# ==============================================================================
# 2B. Day-of-Week Seasonality Analysis (G)
# ==============================================================================

def analyze_seasonality(
    series: List[Dict[str, Any]],
    usable_days: int
) -> Dict[str, Any]:
    """
    Analyzes day-of-week demand patterns for a product.
    Requires at least 14 days of history to avoid spurious seasonality claims.
    If < 14 days, returns explicit SEASONALITY_INSUFFICIENT_DATA status.
    """
    if usable_days < 14 or len(series) < 14:
        return {
            "status": "SEASONALITY_INSUFFICIENT_DATA",
            "is_supported": False,
            "min_days_required": 14,
            "history_days_available": usable_days,
            "weekday_breakdown": [],
            "pattern_summary": (
                f"Insufficient historical depth for day-of-week seasonality analysis. "
                f"Found {usable_days} usable days; at least 14 days required."
            )
        }

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekday_vals: Dict[int, List[float]] = {i: [] for i in range(7)}
    for h in series:
        q = float(h.get("quantity", 0.0) or 0.0)
        weekday_vals[h["weekday_idx"]].append(q)

    all_quantities = [float(h.get("quantity", 0.0) or 0.0) for h in series]
    overall_mean = float(np.mean(all_quantities)) if all_quantities else 0.0

    breakdown = []
    for idx in range(7):
        vals = weekday_vals[idx]
        day_avg = float(np.mean(vals)) if vals else 0.0
        factor = round(day_avg / overall_mean, 2) if overall_mean > 0 else 1.0
        breakdown.append({
            "day_name": day_names[idx],
            "weekday_idx": idx,
            "avg_quantity": round(day_avg, 2),
            "factor": factor
        })

    weekend_vals = weekday_vals[5] + weekday_vals[6]
    weekday_only_vals = []
    for i in range(5):
        weekday_only_vals.extend(weekday_vals[i])

    wknd_avg = float(np.mean(weekend_vals)) if weekend_vals else 0.0
    wkdy_avg = float(np.mean(weekday_only_vals)) if weekday_only_vals else 0.0

    if wkdy_avg > 0:
        diff_pct = int(round((wknd_avg - wkdy_avg) / wkdy_avg * 100))
        if diff_pct > 15:
            summary = f"Strong weekend peak: Saturday-Sunday demand averages {diff_pct}% higher than weekdays."
        elif diff_pct < -15:
            summary = f"Weekday-dominant demand: Weekend sales average {abs(diff_pct)}% lower than weekdays."
        else:
            summary = "Evenly distributed weekly demand with no extreme weekend skew."
    else:
        summary = "Day-of-week seasonality analyzed across active history."

    return {
        "status": "SEASONALITY_AVAILABLE",
        "is_supported": True,
        "min_days_required": 14,
        "history_days_available": usable_days,
        "weekday_breakdown": breakdown,
        "pattern_summary": summary
    }


# ==============================================================================
# 3. Time-Series-Aware Model Selection (NO FUTURE-DATA LEAKAGE)
# ==============================================================================

def select_and_evaluate_model(
    history: List[Dict[str, Any]],
    usable_days: int
) -> Tuple[str, List[Dict[str, Any]], float]:
    """
    Performs walk-forward time-series validation on past chronological data.
    Strictly avoids future-data leakage:
      - Historical series is split strictly by date order: [0 : N - val_size] vs [N - val_size : N].
      - No random shuffling.
      - Evaluates SMA, EWMA, DOW_SEASONAL, and TREND_SEASONAL where justified.
    Returns:
      (selected_model_name, list_of_model_metrics, residual_std_error)
    """
    n = len(history)
    quantities = [h["quantity"] for h in history]

    # For short histories (<14 days), model comparison is statistically noisy.
    # Use robust EWMA directly.
    if usable_days < 14 or n < 10:
        model_name = "BASELINE_EWMA"
        # In-sample residual calculation for error bounds
        diffs = [abs(quantities[i] - quantities[i - 1]) for i in range(1, n)] if n > 1 else [0.0]
        mae = float(np.mean(diffs)) if diffs else 0.5
        rmse = float(np.sqrt(np.mean([d ** 2 for d in diffs]))) if diffs else 0.5
        total_q = float(np.sum(quantities))
        wape = float(np.sum(diffs) / total_q) if total_q > 0 else mae

        metrics = [{
            "model_name": model_name,
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
            "wape": round(wape, 4),
            "is_selected": True
        }]
        return model_name, metrics, max(0.2, rmse)

    # Validation window: hold out the most recent 7 days (or at least 3 days)
    val_size = min(7, max(3, n // 4))
    train_history = history[:-val_size]
    val_history = history[-val_size:]
    val_start_date = val_history[0]["date"]
    val_actual = np.array([h["quantity"] for h in val_history], dtype=float)
    sum_actual = float(np.sum(val_actual))

    candidate_models: Dict[str, List[float]] = {}
    train_qty = [h["quantity"] for h in train_history]

    # Candidate 1: SMA (7-day window)
    candidate_models["SIMPLE_MOVING_AVERAGE"] = ForecastingModels.sma(train_qty, val_size, window=7)

    # Candidate 2: EWMA (alpha=0.3)
    candidate_models["EXPONENTIAL_SMOOTHING"] = ForecastingModels.ewma(train_qty, val_size, alpha=0.3)

    # Candidate 3: DOW Seasonality (if at least 14 days in training)
    if len(train_history) >= 14:
        candidate_models["DAY_OF_WEEK_SEASONAL"] = ForecastingModels.dow_seasonal(
            train_history, val_size, val_start_date, base_method="ewma"
        )

    # Candidate 4: Trend + Seasonality (if at least 21 days in training)
    if len(train_history) >= 21:
        candidate_models["TREND_AND_SEASONAL"] = ForecastingModels.trend_seasonal(
            train_history, val_size, val_start_date
        )

    results = []
    best_model = "EXPONENTIAL_SMOOTHING"
    lowest_error = float("inf")
    best_rmse = 1.0

    for m_name, preds in candidate_models.items():
        p_arr = np.array(preds, dtype=float)
        mae = float(np.mean(np.abs(val_actual - p_arr)))
        rmse = float(np.sqrt(np.mean((val_actual - p_arr) ** 2)))
        wape = float(np.sum(np.abs(val_actual - p_arr)) / sum_actual) if sum_actual > 0 else mae

        results.append({
            "model_name": m_name,
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
            "wape": round(wape, 4),
            "is_selected": False
        })

        # Select by WAPE (or MAE)
        criterion = wape
        if criterion < lowest_error:
            lowest_error = criterion
            best_model = m_name
            best_rmse = rmse

    # Mark the winner
    for r in results:
        if r["model_name"] == best_model:
            r["is_selected"] = True

    return best_model, results, max(0.2, best_rmse)


# ==============================================================================
# 4. Stockout Risk & Reorder Advisory Logic
# ==============================================================================

def calculate_stockout_and_reorder(
    product: Product,
    forecast_30d: List[Dict[str, Any]],
    total_7d: float,
    total_30d: float,
    lead_time_days: int = 3,
    buffer_days: int = 2
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Computes deterministic stockout risk metrics and advisory reorder recommendations.
    Strictly non-modifying: purely advisory.
    """
    current_stock = max(0.0, float(product.stock_quantity or 0.0))
    avg_daily_demand = round(total_7d / 7.0, 2)

    # Days of inventory remaining
    if avg_daily_demand > 0.0:
        raw_days = current_stock / avg_daily_demand
        days_inventory_remaining = round(raw_days, 1)
    else:
        raw_days = 999.0
        days_inventory_remaining = 999.0

    # Projected stockout date
    cum_demand = 0.0
    projected_stockout_date: Optional[str] = None
    for day in forecast_30d:
        cum_demand += day["forecast_quantity"]
        if cum_demand > current_stock:
            projected_stockout_date = day["date"]
            break

    potential_7d_shortfall = max(0.0, round(total_7d - current_stock, 2))

    # Safety stock: transparent max of configured product threshold and buffer days demand
    min_threshold = float(product.min_stock_threshold or 10.0)
    calculated_buffer = round(avg_daily_demand * buffer_days, 2)
    safety_stock = round(max(min_threshold, calculated_buffer), 2)

    # Suggested stock and reorder quantity
    suggested_minimum_stock = round(total_7d + safety_stock, 2)
    suggested_reorder_qty = max(0.0, round(suggested_minimum_stock - current_stock, 2))

    # Risk level classification strictly ordered by chronological urgency:
    # 1. Low Stock / Immediate Attention (Red Badge):
    #    current_stock <= 0 OR days_inventory_remaining <= 3.0 OR current_stock <= min_threshold
    # 2. Reorder Soon (Amber Badge):
    #    days_inventory_remaining > 3.0 AND (current_stock < (total_7d + safety_stock) OR days_inventory_remaining <= 7.0)
    # 3. Enough Stock (Green Badge):
    #    current_stock >= (total_7d + safety_stock) AND days_inventory_remaining > 7.0 (suggested_reorder_qty == 0)
    if current_stock <= 0.0 or (days_inventory_remaining <= 1.0 and total_7d > 0.0):
        risk_level = "IMMEDIATE_ATTENTION"
        risk_label = "Immediate Attention (Stockout / < 1 Day)"
    elif days_inventory_remaining <= 3.0 or current_stock <= min_threshold:
        risk_level = "LOW_STOCK"
        risk_label = "Low Stock (<= 3 Days / Critical Buffer)"
    elif days_inventory_remaining > 3.0 and (current_stock < (total_7d + safety_stock) or days_inventory_remaining <= 7.0):
        risk_level = "POTENTIAL_STOCKOUT"
        risk_label = "Reorder Soon (3–7 Days / Low Buffer)"
    else:
        risk_level = "SUFFICIENT"
        risk_label = "Sufficient Stock"
        suggested_reorder_qty = 0.0

    # Urgency
    if risk_level in ("IMMEDIATE_ATTENTION", "LOW_STOCK"):
        urgency = "URGENT"
    elif risk_level == "POTENTIAL_STOCKOUT" or suggested_reorder_qty > 0.0:
        urgency = "RECOMMENDED"
    else:
        urgency = "OPTIMAL"

    days_display_str = "> 30" if (raw_days > 30.0 or avg_daily_demand <= 0.0) else str(round(days_inventory_remaining))
    stockout_explanation = (
        f"Current stock of {current_stock} {product.unit} covers ~{days_display_str} days "
        f"at an average demand of {avg_daily_demand} {product.unit}/day. "
        + (f"Projected stockout on {projected_stockout_date}." if projected_stockout_date else "No stockout anticipated within 30 days.")
    )

    formula_breakdown = (
        f"Suggested Reorder = max(0, (Expected 7-Day Demand [{total_7d}] + Safety Stock [{safety_stock}]) "
        f"- Current Stock [{current_stock}]) = {suggested_reorder_qty} {product.unit}."
    )

    # If stock lasts over 30 days or average demand is zero, cap value so no floats > 30 are produced
    days_remaining_val = None if (raw_days > 30.0 or avg_daily_demand <= 0.0) else days_inventory_remaining
    days_remaining_label = "> 30 days left" if (raw_days > 30.0 or avg_daily_demand <= 0.0) else (f"{round(days_inventory_remaining)} days left" if round(days_inventory_remaining) != 1 else "1 day left")

    stockout_analysis = {
        "current_stock": current_stock,
        "expected_7d_demand": total_7d,
        "expected_30d_demand": total_30d,
        "avg_daily_demand": avg_daily_demand,
        "days_inventory_remaining": days_remaining_val,
        "days_inventory_remaining_label": days_remaining_label,
        "projected_stockout_date": projected_stockout_date,
        "potential_7d_shortfall": potential_7d_shortfall,
        "risk_level": risk_level,
        "risk_label": risk_label,
        "explanation": stockout_explanation
    }

    reorder_recommendation = {
        "current_stock": current_stock,
        "expected_7d_demand": total_7d,
        "lead_time_days": lead_time_days,
        "buffer_days": buffer_days,
        "safety_stock": safety_stock,
        "suggested_minimum_stock": suggested_minimum_stock,
        "suggested_reorder_quantity": suggested_reorder_qty,
        "urgency": urgency,
        "formula_breakdown": formula_breakdown,
        "advisory_notice": "Advisory only: No automated orders placed, no inventory altered."
    }

    return stockout_analysis, reorder_recommendation


# ==============================================================================
# 5. Full Product Demand Intelligence Generator
# ==============================================================================

def generate_product_forecast(
    db: Session,
    product: Product,
    force_recalculate: bool = False
) -> Dict[str, Any]:
    """
    Computes 7-day and 30-day demand forecast, stockout risk, and reorder intelligence
    for a specific product using its canonical historical sales series.
    Guarantees:
      - If usable days < 7 -> Returns INSUFFICIENT_DATA status without fake predictions.
      - All predicted quantities >= 0.0.
      - Zero inventory modifications.
    """
    pid = product.id

    # Check in-memory cache if not forced
    if not force_recalculate and pid in _FORECAST_CACHE:
        return _FORECAST_CACHE[pid]

    series, usable_days, earliest_date, latest_date = get_product_daily_series(db, pid)

    # 1. DATA SUFFICIENCY GATE
    if usable_days < 7 or not series:
        msg = (
            f"Insufficient historical data for '{product.name}'. "
            f"Found {usable_days} usable historical sales days; at least 7 days required."
        )
        current_stock = max(0.0, float(product.stock_quantity or 0.0))

        result = {
            "product_id": pid,
            "product_name": product.name,
            "category": product.category,
            "unit": product.unit,
            "current_stock": current_stock,
            "unit_price": float(product.unit_price or 0.0),
            "status": "INSUFFICIENT_DATA",
            "eligibility_status": "insufficient_data",
            "usable_days_count": usable_days,
            "min_days_required": 7,
            "earliest_date": earliest_date.isoformat() if earliest_date else None,
            "latest_date": latest_date.isoformat() if latest_date else None,
            "selected_model": None,
            "model_metrics": [],
            "total_7d_demand": 0.0,
            "total_30d_demand": 0.0,
            "avg_daily_demand": 0.0,
            "forecast_7d": [],
            "forecast_30d": [],
            "recent_history": [
                {
                    "date": h["date_str"],
                    "day_of_week": h["day_of_week"],
                    "actual_quantity": round(h["quantity"], 2)
                }
                for h in series[-14:]
            ] if series else [],
            "stockout_risk": {
                "current_stock": current_stock,
                "expected_7d_demand": 0.0,
                "expected_30d_demand": 0.0,
                "avg_daily_demand": 0.0,
                "days_inventory_remaining": None,
                "projected_stockout_date": None,
                "potential_7d_shortfall": 0.0,
                "risk_level": "INSUFFICIENT_DATA",
                "risk_label": "Insufficient Data",
                "explanation": msg
            },
            "reorder_recommendation": {
                "current_stock": current_stock,
                "expected_7d_demand": 0.0,
                "lead_time_days": 3,
                "buffer_days": 2,
                "safety_stock": float(product.min_stock_threshold or 10.0),
                "suggested_minimum_stock": float(product.min_stock_threshold or 10.0),
                "suggested_reorder_quantity": max(0.0, float(product.min_stock_threshold or 10.0) - current_stock),
                "urgency": "RECOMMENDED" if current_stock < float(product.min_stock_threshold or 10.0) else "OPTIMAL",
                "formula_breakdown": "Forecast unavailable due to insufficient history; using default minimum stock threshold.",
                "advisory_notice": "Advisory only: No automated orders placed, no inventory altered."
            },
            "seasonality_analysis": analyze_seasonality(series, usable_days),
            "explanation": msg,
            "computed_at": datetime.utcnow()
        }

        _FORECAST_CACHE[pid] = result
        return result

    # 2. ELIGIBLE PRODUCT: MODEL SELECTION & PREDICTION
    best_model_name, model_metrics, std_err = select_and_evaluate_model(series, usable_days)

    # Forecast start date is day after latest historical date
    forecast_start = (latest_date + timedelta(days=1)) if latest_date else date.today()
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    # Refit winning model on full history to predict 30 days ahead
    quantities = [h["quantity"] for h in series]

    if best_model_name == "SIMPLE_MOVING_AVERAGE":
        raw_preds = ForecastingModels.sma(quantities, 30, window=7)
    elif best_model_name == "EXPONENTIAL_SMOOTHING" or best_model_name == "BASELINE_EWMA":
        raw_preds = ForecastingModels.ewma(quantities, 30, alpha=0.3)
    elif best_model_name == "DAY_OF_WEEK_SEASONAL":
        raw_preds = ForecastingModels.dow_seasonal(series, 30, forecast_start, base_method="ewma")
    elif best_model_name == "TREND_AND_SEASONAL":
        raw_preds = ForecastingModels.trend_seasonal(series, 30, forecast_start)
    else:
        raw_preds = ForecastingModels.ewma(quantities, 30, alpha=0.3)

    forecast_30d: List[Dict[str, Any]] = []
    margin = 1.96 * std_err

    for i, qty in enumerate(raw_preds):
        f_date = forecast_start + timedelta(days=i)
        f_qty = max(0.0, round(float(qty), 2))
        lower = max(0.0, round(f_qty - margin, 2))
        upper = round(f_qty + margin, 2)

        forecast_30d.append({
            "date": f_date.isoformat(),
            "day_of_week": day_names[f_date.weekday()],
            "forecast_quantity": f_qty,
            "lower_bound": lower,
            "upper_bound": upper
        })

    forecast_7d = forecast_30d[:7]

    total_7d = round(sum(d["forecast_quantity"] for d in forecast_7d), 2)
    total_30d = round(sum(d["forecast_quantity"] for d in forecast_30d), 2)
    avg_daily_demand = round(total_7d / 7.0, 2)

    # Stockout Risk & Reorder
    stockout_risk, reorder_rec = calculate_stockout_and_reorder(
        product, forecast_30d, total_7d, total_30d
    )

    # Construct explainable narrative
    weekend_text = ""
    if len(series) >= 14:
        weekend_vals = [h["quantity"] for h in series if h["weekday_idx"] in (5, 6)]
        weekday_vals = [h["quantity"] for h in series if h["weekday_idx"] < 5]
        if weekend_vals and weekday_vals:
            wknd_avg = float(np.mean(weekend_vals))
            wkdy_avg = float(np.mean(weekday_vals))
            if wkdy_avg > 0 and abs(wknd_avg - wkdy_avg) / wkdy_avg > 0.15:
                pct = int(round((wknd_avg - wkdy_avg) / wkdy_avg * 100))
                if pct > 0:
                    weekend_text = f" Weekend demand historically averages {pct}% higher than weekdays."
                else:
                    weekend_text = f" Weekend demand historically averages {abs(pct)}% lower than weekdays."

    narrative = (
        f"Forecast generated using {best_model_name.replace('_', ' ').title()} based on {usable_days} "
        f"usable historical sales days (covering {earliest_date} to {latest_date}). "
        f"Expected 7-day demand is {total_7d} {product.unit} (avg {avg_daily_demand} {product.unit}/day).{weekend_text} "
        f"Current stock is {stockout_risk['current_stock']} {product.unit}. "
        f"{stockout_risk['explanation']} "
        f"{reorder_rec['formula_breakdown']}"
    )

    recent_history = [
        {
            "date": h["date_str"],
            "day_of_week": h["day_of_week"],
            "actual_quantity": round(h["quantity"], 2)
        }
        for h in series[-30:]
    ]

    result = {
        "product_id": pid,
        "product_name": product.name,
        "category": product.category,
        "unit": product.unit,
        "current_stock": stockout_risk["current_stock"],
        "unit_price": float(product.unit_price or 0.0),
        "status": "ELIGIBLE",
        "eligibility_status": "eligible",
        "usable_days_count": usable_days,
        "min_days_required": 7,
        "earliest_date": earliest_date.isoformat() if earliest_date else None,
        "latest_date": latest_date.isoformat() if latest_date else None,
        "selected_model": best_model_name,
        "model_metrics": model_metrics,
        "total_7d_demand": total_7d,
        "total_30d_demand": total_30d,
        "avg_daily_demand": avg_daily_demand,
        "forecast_7d": forecast_7d,
        "forecast_30d": forecast_30d,
        "recent_history": recent_history,
        "stockout_risk": stockout_risk,
        "reorder_recommendation": reorder_rec,
        "seasonality_analysis": analyze_seasonality(series, usable_days),
        "explanation": narrative,
        "computed_at": datetime.utcnow()
    }

    _FORECAST_CACHE[pid] = result

    # Sync to persistent product_forecasts table
    try:
        pf = db.query(ProductForecast).filter(ProductForecast.product_id == pid).first()
        stockout_dt = datetime.strptime(stockout_risk["projected_stockout_date"], "%Y-%m-%d").date() if stockout_risk.get("projected_stockout_date") else None
        if pf:
            pf.status = "ELIGIBLE"
            pf.model_name = best_model_name
            pf.usable_days_count = usable_days
            pf.avg_daily_demand = avg_daily_demand
            pf.total_7d_demand = total_7d
            pf.total_30d_demand = total_30d
            pf.current_stock = stockout_risk["current_stock"]
            pf.days_inventory_remaining = stockout_risk["days_inventory_remaining"]
            pf.projected_stockout_date = stockout_dt
            pf.risk_level = stockout_risk["risk_level"]
            pf.suggested_reorder_qty = reorder_rec["suggested_reorder_quantity"]
            pf.safety_stock = reorder_rec["safety_stock"]
            pf.reorder_urgency = reorder_rec["urgency"]
            pf.forecast_data_json = json.dumps({
                "forecast_7d": forecast_7d,
                "forecast_30d": forecast_30d,
                "model_metrics": model_metrics
            })
            pf.explanation = narrative
            pf.computed_at = datetime.utcnow()
        else:
            pf = ProductForecast(
                product_id=pid,
                status="ELIGIBLE",
                model_name=best_model_name,
                usable_days_count=usable_days,
                avg_daily_demand=avg_daily_demand,
                total_7d_demand=total_7d,
                total_30d_demand=total_30d,
                current_stock=stockout_risk["current_stock"],
                days_inventory_remaining=stockout_risk["days_inventory_remaining"],
                projected_stockout_date=stockout_dt,
                risk_level=stockout_risk["risk_level"],
                suggested_reorder_qty=reorder_rec["suggested_reorder_quantity"],
                safety_stock=reorder_rec["safety_stock"],
                reorder_urgency=reorder_rec["urgency"],
                forecast_data_json=json.dumps({
                    "forecast_7d": forecast_7d,
                    "forecast_30d": forecast_30d,
                    "model_metrics": model_metrics
                }),
                explanation=narrative,
                computed_at=datetime.utcnow()
            )
            db.add(pf)
        db.commit()
    except Exception as e:
        logger.warning(f"Notice syncing ProductForecast DB row for product {pid}: {e}")
        db.rollback()

    return result


# ==============================================================================
# 6. Store-Wide Forecast Summary & Overview
# ==============================================================================

def get_all_product_forecasts(db: Session, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Evaluates forecasts and stockout risk for all active catalog products.
    Returns:
      overview metrics + list of product summary items.
    """
    if force_refresh:
        invalidate_forecast_cache()

    products = db.query(Product).order_by(Product.name.asc()).all()

    summary_items = []
    eligible_count = 0
    insufficient_count = 0
    immediate_attention_count = 0
    potential_stockout_count = 0
    low_stock_count = 0
    sufficient_count = 0
    total_reorder_units = 0.0

    for prod in products:
        f_data = generate_product_forecast(db, prod, force_recalculate=force_refresh)
        status = f_data["status"]
        risk = f_data["stockout_risk"]["risk_level"]
        reorder_qty = f_data["reorder_recommendation"]["suggested_reorder_quantity"]
        total_reorder_units += reorder_qty

        if status == "ELIGIBLE":
            eligible_count += 1
            if risk == "IMMEDIATE_ATTENTION":
                immediate_attention_count += 1
            elif risk == "POTENTIAL_STOCKOUT":
                potential_stockout_count += 1
            elif risk == "LOW_STOCK":
                low_stock_count += 1
            else:
                sufficient_count += 1
        else:
            insufficient_count += 1

        summary_items.append({
            "product_id": prod.id,
            "product_name": prod.name,
            "category": prod.category,
            "unit": prod.unit,
            "current_stock": f_data["current_stock"],
            "unit_price": f_data["unit_price"],
            "usable_days_count": f_data["usable_days_count"],
            "status": status,
            "selected_model": f_data.get("selected_model"),
            "total_7d_demand": f_data["total_7d_demand"],
            "total_30d_demand": f_data["total_30d_demand"],
            "avg_daily_demand": f_data["avg_daily_demand"],
            "days_inventory_remaining": f_data["stockout_risk"]["days_inventory_remaining"],
            "projected_stockout_date": f_data["stockout_risk"]["projected_stockout_date"],
            "potential_7d_shortfall": f_data["stockout_risk"]["potential_7d_shortfall"],
            "risk_level": risk,
            "suggested_reorder_qty": reorder_qty,
            "reorder_urgency": f_data["reorder_recommendation"]["urgency"],
            "earliest_date": f_data["earliest_date"],
            "latest_date": f_data["latest_date"]
        })

    # Sort strictly by urgency: Low Stock (Red) -> Reorder Soon (Amber) -> Enough Stock (Green) -> Not Enough History (Gray)
    def get_backend_urgency_tuple(item: Dict[str, Any]) -> Tuple[int, float, float, str]:
        risk = item["risk_level"]
        status = item["status"]
        if status != "ELIGIBLE" or risk == "INSUFFICIENT_DATA":
            prio = 4
        elif risk in ("IMMEDIATE_ATTENTION", "LOW_STOCK"):
            prio = 1
        elif risk == "POTENTIAL_STOCKOUT":
            prio = 2
        elif risk == "SUFFICIENT":
            prio = 3
        else:
            prio = 4
        days = item["days_inventory_remaining"] if item["days_inventory_remaining"] is not None else 9999.0
        return (prio, days, -float(item["suggested_reorder_qty"] or 0.0), item["product_name"] or "")

    summary_items.sort(key=get_backend_urgency_tuple)

    overview = {
        "total_products": len(products),
        "eligible_products_count": eligible_count,
        "insufficient_products_count": insufficient_count,
        "immediate_attention_count": immediate_attention_count,
        "potential_stockout_count": potential_stockout_count,
        "low_stock_count": low_stock_count,
        "sufficient_stock_count": sufficient_count,
        "total_reorder_units_needed": round(total_reorder_units, 2),
        "last_refresh_at": datetime.utcnow()
    }

    return {
        "overview": overview,
        "products": summary_items
    }
