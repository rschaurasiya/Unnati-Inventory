"""
Analytics & Historical Sales API Router (Step 10)
Provides endpoints to inspect daily sales, product histories, date range summaries,
reconcile/rebuild aggregates, check data sufficiency, and seed historical demo data.
"""
from datetime import datetime, date, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Product, Bill, BillItem, DailySalesSummary
from sqlalchemy import func
from backend.schemas import (
    DailySalesSummaryResponse,
    ProductSalesHistoryResponse,
    SalesDateRangeSummaryResponse,
    CompletedSaleItemResponse,
    DataSufficiencyResponse,
    RebuildHistoryResponse,
    SeedDemoDataResponse
)
from backend.services.sales_aggregation import (
    aggregate_sales_for_date,
    rebuild_all_sales_summaries,
    check_data_sufficiency,
    seed_demo_historical_sales,
    query_sales_by_date,
    query_sales_by_range,
    query_product_sales_history,
    query_completed_sale_items
)

router = APIRouter(prefix="/api/v1/analytics", tags=["Sales Analytics & History Engine"])


def _parse_iso_date(date_str: str, param_name: str) -> date:
    """Parse and validate YYYY-MM-DD date string with clear error messages."""
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format for '{param_name}': '{date_str}'. Expected YYYY-MM-DD format."
        )


class RebuildRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class SeedDemoRequest(BaseModel):
    days: int = Field(60, ge=1, le=365, description="Number of historical days to simulate")
    seed: int = Field(42, description="Random seed for reproducible variation")


@router.get("/sales/daily", response_model=DailySalesSummaryResponse, status_code=status.HTTP_200_OK)
def get_daily_sales(
    date: Optional[str] = Query(None, description="Target date in YYYY-MM-DD format (defaults to today)"),
    db: Session = Depends(get_db)
):
    """
    Get aggregated product-level sales for a specific date.
    Calculated deterministically from completed bills.
    """
    target_date = _parse_iso_date(date, "date") if date else datetime.utcnow().date()
    # Ensure date summary is aggregated
    aggregate_sales_for_date(db, target_date)
    return query_sales_by_date(db, target_date)


@router.get("/sales/range", response_model=SalesDateRangeSummaryResponse, status_code=status.HTTP_200_OK)
def get_sales_range(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    product_id: Optional[int] = Query(None, description="Optional product filter"),
    db: Session = Depends(get_db)
):
    """
    Get aggregated sales and daily summaries across a date range.
    Validates date formats and chronological order.
    """
    d_start = _parse_iso_date(start_date, "start_date")
    d_end = _parse_iso_date(end_date, "end_date")

    if d_start > d_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date range: start_date '{start_date}' is after end_date '{end_date}'."
        )

    if product_id:
        prod = db.query(Product).filter(Product.id == product_id).first()
        if not prod:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with ID {product_id} not found."
            )

    return query_sales_by_range(db, d_start, d_end, product_id)


@router.get("/dashboard/charts", status_code=status.HTTP_200_OK)
def get_dashboard_charts(
    days: int = Query(7, ge=1, le=90, description="Window in days (e.g. 7 or 30)"),
    db: Session = Depends(get_db)
):
    """
    Returns pre-aggregated dataset optimized for Shop Command Center visualizations:
    1. Sales Trend (daily revenue and transaction count over the last N days)
    2. Top-Selling Products (ranked by units sold and revenue from completed sales)
    3. Payment Breakdown (totals and percentages for Cash, UPI, and Udhaar)
    4. Stock Health Overview (healthy, low stock, out of stock)
    """
    today = datetime.utcnow().date()
    d_start = today - timedelta(days=days - 1)
    d_end = today
    dt_start = datetime.combine(d_start, datetime.min.time())
    dt_end = datetime.combine(d_end, datetime.max.time())

    # 1. Query completed bills in window
    bills = (
        db.query(Bill)
        .filter(
            Bill.status == "COMPLETED",
            Bill.created_at >= dt_start,
            Bill.created_at <= dt_end
        )
        .order_by(Bill.created_at.asc())
        .all()
    )

    # 2. Daily revenue & transaction mapping for every single day in window
    daily_map = {}
    curr = d_start
    while curr <= d_end:
        daily_map[curr] = {"revenue": 0.0, "transactions": 0}
        curr += timedelta(days=1)

    bill_ids = []
    payment_counts = {"CASH": 0, "UPI": 0, "UDHAAR": 0}
    payment_totals = {"CASH": 0.0, "UPI": 0.0, "UDHAAR": 0.0}

    total_revenue = 0.0
    for b in bills:
        b_date = b.created_at.date()
        if b_date in daily_map:
            daily_map[b_date]["revenue"] += round(b.total_amount, 2)
            daily_map[b_date]["transactions"] += 1
        bill_ids.append(b.id)

        mode = (b.payment_mode or "CASH").upper()
        if mode not in payment_totals:
            payment_totals[mode] = 0.0
            payment_counts[mode] = 0
        payment_totals[mode] += round(b.total_amount, 2)
        payment_counts[mode] += 1
        total_revenue += round(b.total_amount, 2)

    sales_trend = []
    for d, info in sorted(daily_map.items()):
        sales_trend.append({
            "date": d.isoformat(),
            "label": d.strftime("%d %b"),
            "revenue": round(info["revenue"], 2),
            "transactions": info["transactions"]
        })

    # 3. Top Products from BillItem
    product_stats = {}
    if bill_ids:
        items = (
            db.query(
                BillItem.product_id,
                Product.name,
                Product.category,
                Product.unit,
                func.sum(BillItem.quantity).label("units_sold"),
                func.sum(BillItem.line_total).label("revenue")
            )
            .join(Product, BillItem.product_id == Product.id)
            .filter(BillItem.bill_id.in_(bill_ids))
            .group_by(BillItem.product_id, Product.name, Product.category, Product.unit)
            .all()
        )
        for it in items:
            product_stats[it.product_id] = {
                "product_id": it.product_id,
                "name": it.name,
                "category": it.category or "General",
                "unit": it.unit or "unit",
                "units_sold": round(float(it.units_sold or 0.0), 2),
                "revenue": round(float(it.revenue or 0.0), 2)
            }

    top_by_units = sorted(product_stats.values(), key=lambda x: x["units_sold"], reverse=True)[:5]
    top_by_revenue = sorted(product_stats.values(), key=lambda x: x["revenue"], reverse=True)[:5]

    # 4. Payment breakdown
    payment_breakdown = []
    for mode, amt in payment_totals.items():
        pct = round((amt / total_revenue * 100), 1) if total_revenue > 0 else 0.0
        label = "Cash" if mode == "CASH" else ("UPI / Online" if mode == "UPI" else ("Udhaar / Credit" if mode == "UDHAAR" else mode))
        payment_breakdown.append({
            "mode": mode,
            "label": label,
            "total": round(amt, 2),
            "count": payment_counts.get(mode, 0),
            "percentage": pct
        })

    # 5. Stock Overview
    total_products = db.query(Product).filter(Product.is_active == True).count()
    out_of_stock = db.query(Product).filter(Product.is_active == True, Product.stock_quantity <= 0).count()
    low_stock = db.query(Product).filter(
        Product.is_active == True,
        Product.stock_quantity > 0,
        Product.stock_quantity <= Product.min_stock_threshold
    ).count()
    healthy = max(0, total_products - out_of_stock - low_stock)

    return {
        "days": days,
        "start_date": d_start.isoformat(),
        "end_date": d_end.isoformat(),
        "total_revenue": round(total_revenue, 2),
        "total_transactions": len(bills),
        "sales_trend": sales_trend,
        "top_by_units": top_by_units,
        "top_by_revenue": top_by_revenue,
        "payment_breakdown": payment_breakdown,
        "stock_overview": {
            "total_products": total_products,
            "healthy": healthy,
            "low_stock": low_stock,
            "out_of_stock": out_of_stock
        }
    }


@router.get("/sales/charts", status_code=status.HTTP_200_OK)
def get_sales_charts(
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD (defaults to 30 days ago)"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD (defaults to today)"),
    product_id: Optional[int] = Query(None, description="Optional product filter"),
    category: Optional[str] = Query(None, description="Optional category filter"),
    payment_mode: Optional[str] = Query(None, description="Optional payment mode filter"),
    db: Session = Depends(get_db)
):
    """
    Returns aggregated series for Sales History visualizations:
    1. Revenue Over Time (line chart)
    2. Transactions by Day (bar chart)
    3. Best-Selling Products (horizontal bar chart by units & revenue)
    4. Category-wise Sales (bar chart)
    """
    if end_date:
        d_end = _parse_iso_date(end_date, "end_date")
    else:
        d_end = datetime.utcnow().date()

    if start_date:
        d_start = _parse_iso_date(start_date, "start_date")
    else:
        d_start = d_end - timedelta(days=29)

    if d_start > d_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date range: start_date '{start_date}' is after end_date '{end_date}'."
        )

    dt_start = datetime.combine(d_start, datetime.min.time())
    dt_end = datetime.combine(d_end, datetime.max.time())

    # Build bills query
    bill_query = db.query(Bill).filter(
        Bill.status == "COMPLETED",
        Bill.created_at >= dt_start,
        Bill.created_at <= dt_end
    )
    if payment_mode and payment_mode.strip() and payment_mode.upper() != "ALL":
        bill_query = bill_query.filter(Bill.payment_mode == payment_mode.strip().upper())

    bills = bill_query.order_by(Bill.created_at.asc()).all()
    bill_ids = [b.id for b in bills]

    # Date range buckets
    date_map = {}
    curr = d_start
    while curr <= d_end:
        date_map[curr] = {"revenue": 0.0, "transactions": 0}
        curr += timedelta(days=1)

    for b in bills:
        b_date = b.created_at.date()
        if b_date in date_map:
            date_map[b_date]["revenue"] += round(b.total_amount, 2)
            date_map[b_date]["transactions"] += 1

    revenue_trend = []
    transactions_trend = []
    for d, info in sorted(date_map.items()):
        lbl = d.strftime("%d %b")
        revenue_trend.append({"date": d.isoformat(), "label": lbl, "revenue": round(info["revenue"], 2)})
        transactions_trend.append({"date": d.isoformat(), "label": lbl, "count": info["transactions"]})

    # Line items query for product rankings & category breakdown
    category_totals = {}
    product_totals = {}

    if bill_ids:
        item_q = (
            db.query(
                BillItem.product_id,
                Product.name,
                Product.category,
                Product.unit,
                func.sum(BillItem.quantity).label("units_sold"),
                func.sum(BillItem.line_total).label("revenue")
            )
            .join(Product, BillItem.product_id == Product.id)
            .filter(BillItem.bill_id.in_(bill_ids))
        )
        if product_id:
            item_q = item_q.filter(BillItem.product_id == product_id)
        if category and category.strip() and category.upper() != "ALL":
            item_q = item_q.filter(Product.category == category.strip())

        item_q = item_q.group_by(BillItem.product_id, Product.name, Product.category, Product.unit)
        for it in item_q.all():
            cat = it.category or "General"
            category_totals[cat] = category_totals.get(cat, 0.0) + float(it.revenue or 0.0)
            product_totals[it.product_id] = {
                "product_id": it.product_id,
                "name": it.name,
                "category": cat,
                "unit": it.unit or "unit",
                "units_sold": round(float(it.units_sold or 0.0), 2),
                "revenue": round(float(it.revenue or 0.0), 2)
            }

    best_by_units = sorted(product_totals.values(), key=lambda x: x["units_sold"], reverse=True)[:8]
    best_by_revenue = sorted(product_totals.values(), key=lambda x: x["revenue"], reverse=True)[:8]

    category_sales = [
        {"category": cat, "revenue": round(rev, 2)}
        for cat, rev in sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_revenue": round(sum(b.total_amount for b in bills), 2),
        "total_transactions": len(bills),
        "revenue_trend": revenue_trend,
        "transactions_trend": transactions_trend,
        "best_by_units": best_by_units,
        "best_by_revenue": best_by_revenue,
        "category_sales": category_sales
    }



@router.get("/sales/product/{product_id}", response_model=ProductSalesHistoryResponse, status_code=status.HTTP_200_OK)
def get_product_sales_history(
    product_id: int,
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD (defaults to 30 days ago)"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD (defaults to today)"),
    db: Session = Depends(get_db)
):
    """
    Get historical daily sales time-series for a specific product.
    """
    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found in store catalog."
        )

    d_end = _parse_iso_date(end_date, "end_date") if end_date else datetime.utcnow().date()
    d_start = _parse_iso_date(start_date, "start_date") if start_date else (d_end - timedelta(days=30))

    if d_start > d_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date range: start_date '{d_start}' is after end_date '{d_end}'."
        )

    return query_product_sales_history(db, prod, d_start, d_end)


@router.get("/sales/items", response_model=List[CompletedSaleItemResponse], status_code=status.HTTP_200_OK)
def get_completed_sale_items(
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    product_id: Optional[int] = Query(None, description="Optional product filter"),
    category: Optional[str] = Query(None, description="Optional product category filter"),
    payment_mode: Optional[str] = Query(None, description="Optional payment mode filter (CASH, UPI, UDHAAR)"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    db: Session = Depends(get_db)
):
    """
    Returns itemized records from completed bills.
    Strictly omits customer personal information (phone numbers, addresses, OTPs).
    """
    d_start = _parse_iso_date(start_date, "start_date") if start_date else None
    d_end = _parse_iso_date(end_date, "end_date") if end_date else None

    if d_start and d_end and d_start > d_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date range: start_date '{start_date}' is after end_date '{end_date}'."
        )

    return query_completed_sale_items(db, d_start, d_end, product_id, category, payment_mode, limit)


@router.get("/sufficiency", response_model=DataSufficiencyResponse, status_code=status.HTTP_200_OK)
def get_data_sufficiency(
    product_id: Optional[int] = Query(None, description="Optional product to check specific sufficiency"),
    db: Session = Depends(get_db)
):
    """
    Evaluates whether sufficient historical sales exist for forecasting.
    Threshold:
      < 7 usable days with sales -> INSUFFICIENT_DATA
      >= 7 usable days with sales -> SUFFICIENT_DATA
    Distinguishes store-wide vs individual product-level readiness.
    """
    if product_id:
        prod = db.query(Product).filter(Product.id == product_id).first()
        if not prod:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with ID {product_id} not found."
            )

    return check_data_sufficiency(db, product_id)


@router.post("/rebuild", response_model=RebuildHistoryResponse, status_code=status.HTTP_200_OK)
def rebuild_history(
    payload: Optional[RebuildRequest] = None,
    db: Session = Depends(get_db)
):
    """
    Deterministically rebuilds all DailySalesSummary records from completed bills.
    Safe to run repeatedly. Eliminates duplicate or corrupted summary rows.
    """
    d_start = _parse_iso_date(payload.start_date, "start_date") if (payload and payload.start_date) else None
    d_end = _parse_iso_date(payload.end_date, "end_date") if (payload and payload.end_date) else None

    if d_start and d_end and d_start > d_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date range: start_date '{payload.start_date}' is after end_date '{payload.end_date}'."
        )

    dates_count, summaries_count = rebuild_all_sales_summaries(db, d_start, d_end)

    return RebuildHistoryResponse(
        status="OK",
        message=f"Successfully reconciled DailySalesSummary from completed bills across {dates_count} dates.",
        dates_rebuilt_count=dates_count,
        summaries_created_or_updated=summaries_count
    )


@router.post("/seed-demo", response_model=SeedDemoDataResponse, status_code=status.HTTP_200_OK)
def seed_demo_history(
    payload: Optional[SeedDemoRequest] = None,
    db: Session = Depends(get_db)
):
    """
    Seeds approximately 60 days of realistic, deterministic historical completed sales bills.
    Guarantees current product inventory stock is completely unaltered.
    """
    days = payload.days if payload else 60
    seed = payload.seed if payload else 42

    result = seed_demo_historical_sales(db, days=days, seed=seed)
    return SeedDemoDataResponse(**result)


@router.get("/supplier/charts", status_code=status.HTTP_200_OK)
def get_supplier_charts(
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    """
    Supplier Analytics endpoint (Phase 4).
    The Apna Kirana OS schema currently implements Voice Billing/POS, Inventory,
    Customer Ledgers/Udhaar, and Demand Forecasting, but does NOT contain a
    wholesale Supplier purchasing or Purchase Order ledger.
    Per Phase 4 specifications, this endpoint explicitly and truthfully reports
    supplier purchasing reports as UNAVAILABLE rather than fabricating fake spend.
    """
    return {
        "status": "UNAVAILABLE",
        "supplier_module_available": False,
        "reason": "Wholesale supplier purchasing records and purchase order tables are not implemented in the current system database.",
        "missing_prerequisites": [
            "Supplier / Vendor master table (supplier_id, name, phone, gstin, address)",
            "Purchase Invoices / Goods Receipt ledger (invoice_no, supplier_id, purchase_date, total_cost)",
            "Purchase Line items with quantity received and cost per unit"
        ],
        "purchase_spend": {
            "labels": [],
            "series": [],
            "is_available": False
        },
        "supplier_comparison": {
            "labels": [],
            "series": [],
            "is_available": False
        },
        "purchase_quantity_trend": {
            "labels": [],
            "series": [],
            "is_available": False
        },
        "recommendation": "Wholesale purchasing module must be provisioned before supplier spend and purchase quantity analytics can be rendered."
    }

