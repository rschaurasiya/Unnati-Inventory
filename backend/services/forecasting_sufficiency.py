"""
Forecasting Data Sufficiency Validation Service (Step 11A)
Determines, independently for each product, whether enough usable historical
sales observations exist in the canonical sales foundation to make forecasting eligible.

Business Rules:
- Less than 7 usable product-level historical days -> eligibility_status = "insufficient_data"
- 7 or more usable product-level historical days    -> eligibility_status = "eligible"
- Multiple sales transactions/rows on the same date count as ONE distinct historical day.
- Products are evaluated strictly independently (no store-wide data inheritance).
- Safe date normalization, ignoring future dates and inactive/cancelled records.
- Deterministic, read-only calculation without LLM fabrication or fake forecasts.
"""
from datetime import date, datetime
from typing import Optional, List, Dict, Any, Set
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.models import Product, DailySalesSummary, HistoricalSaleRecord, Bill, BillItem

MIN_USABLE_DAYS_REQUIRED: int = 7


def _to_valid_date(val: Any) -> Optional[date]:
    """Converts a datetime, date, or ISO string to a date object, discarding invalid/future dates."""
    if val is None:
        return None
    d: Optional[date] = None
    if isinstance(val, datetime):
        d = val.date()
    elif isinstance(val, date):
        d = val
    elif isinstance(val, str):
        try:
            d = date.fromisoformat(val[:10])
        except Exception:
            return None

    if d and d <= date.today():
        return d
    return None


def evaluate_product_data_sufficiency(db: Session, product_id: int) -> Optional[Dict[str, Any]]:
    """
    Evaluates historical sales data sufficiency for a specific product.
    Queries the canonical sales records (DailySalesSummary, active HistoricalSaleRecord,
    and completed BillItem) to determine distinct calendar days with valid positive sales.
    
    Returns:
      {
          "product_id": int,
          "product_name": str,
          "historical_days": int,
          "earliest_date": Optional[str],
          "latest_date": Optional[str],
          "eligibility_status": "eligible" | "insufficient_data",
          "eligibility_reason": str
      }
      or None if product does not exist.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return None

    distinct_dates: Set[date] = set()

    # 1. Check canonical DailySalesSummary
    dss_rows = (
        db.query(DailySalesSummary.sale_date)
        .filter(
            DailySalesSummary.product_id == product_id,
            DailySalesSummary.total_quantity_sold > 0
        )
        .all()
    )
    for r in dss_rows:
        d = _to_valid_date(r.sale_date)
        if d:
            distinct_dates.add(d)

    # 2. Check active imported historical records
    hsr_rows = (
        db.query(HistoricalSaleRecord.sale_date)
        .filter(
            HistoricalSaleRecord.product_id == product_id,
            HistoricalSaleRecord.is_active == True,
            HistoricalSaleRecord.quantity > 0
        )
        .all()
    )
    for r in hsr_rows:
        d = _to_valid_date(r.sale_date)
        if d:
            distinct_dates.add(d)

    # 3. Check completed bill items
    bill_rows = (
        db.query(Bill.created_at)
        .join(BillItem, BillItem.bill_id == Bill.id)
        .filter(
            BillItem.product_id == product_id,
            BillItem.quantity > 0,
            Bill.status == "COMPLETED"
        )
        .all()
    )
    for r in bill_rows:
        d = _to_valid_date(r.created_at)
        if d:
            distinct_dates.add(d)

    historical_days = len(distinct_dates)
    earliest_date_str = min(distinct_dates).isoformat() if distinct_dates else None
    latest_date_str = max(distinct_dates).isoformat() if distinct_dates else None

    if historical_days >= MIN_USABLE_DAYS_REQUIRED:
        eligibility_status = "eligible"
        eligibility_reason = "7 or more usable historical days"
    else:
        eligibility_status = "insufficient_data"
        eligibility_reason = "Fewer than 7 usable historical days"

    return {
        "product_id": product.id,
        "product_name": product.name,
        "historical_days": historical_days,
        "earliest_date": earliest_date_str,
        "latest_date": latest_date_str,
        "eligibility_status": eligibility_status,
        "eligibility_reason": eligibility_reason
    }


def evaluate_all_products_data_sufficiency(db: Session) -> Dict[str, Any]:
    """
    Evaluates historical data sufficiency independently for every active catalog product.
    Guarantees no cross-product contamination:
    one product having extensive history never makes another product eligible.
    Returns store summary + list of product-level evaluations.
    """
    products = db.query(Product).order_by(Product.name.asc()).all()

    # Pre-fetch all positive daily sales grouped by product_id
    product_dates_map: Dict[int, Set[date]] = {p.id: set() for p in products}

    # 1. From DailySalesSummary
    dss_rows = (
        db.query(DailySalesSummary.product_id, DailySalesSummary.sale_date)
        .filter(DailySalesSummary.total_quantity_sold > 0)
        .all()
    )
    for pid, s_date in dss_rows:
        if pid in product_dates_map:
            d = _to_valid_date(s_date)
            if d:
                product_dates_map[pid].add(d)

    # 2. From HistoricalSaleRecord
    hsr_rows = (
        db.query(HistoricalSaleRecord.product_id, HistoricalSaleRecord.sale_date)
        .filter(
            HistoricalSaleRecord.is_active == True,
            HistoricalSaleRecord.quantity > 0
        )
        .all()
    )
    for pid, s_date in hsr_rows:
        if pid in product_dates_map:
            d = _to_valid_date(s_date)
            if d:
                product_dates_map[pid].add(d)

    # 3. From completed bills
    bill_rows = (
        db.query(BillItem.product_id, Bill.created_at)
        .join(Bill, BillItem.bill_id == Bill.id)
        .filter(
            BillItem.quantity > 0,
            Bill.status == "COMPLETED"
        )
        .all()
    )
    for pid, c_at in bill_rows:
        if pid in product_dates_map:
            d = _to_valid_date(c_at)
            if d:
                product_dates_map[pid].add(d)

    product_results: List[Dict[str, Any]] = []
    eligible_count = 0
    insufficient_count = 0

    for prod in products:
        p_dates = product_dates_map.get(prod.id, set())
        h_days = len(p_dates)
        e_str = min(p_dates).isoformat() if p_dates else None
        l_str = max(p_dates).isoformat() if p_dates else None

        if h_days >= MIN_USABLE_DAYS_REQUIRED:
            status = "eligible"
            reason = "7 or more usable historical days"
            eligible_count += 1
        else:
            status = "insufficient_data"
            reason = "Fewer than 7 usable historical days"
            insufficient_count += 1

        product_results.append({
            "product_id": prod.id,
            "product_name": prod.name,
            "historical_days": h_days,
            "earliest_date": e_str,
            "latest_date": l_str,
            "eligibility_status": status,
            "eligibility_reason": reason
        })

    return {
        "total_products": len(products),
        "eligible_count": eligible_count,
        "insufficient_count": insufficient_count,
        "min_days_required": MIN_USABLE_DAYS_REQUIRED,
        "products": product_results
    }
