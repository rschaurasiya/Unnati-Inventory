"""
Inventory Management API Router
Provides endpoints for restocking/adjusting inventory, detecting low-stock items, and inventory valuation summaries.
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import get_db
from backend.models import Product
from backend.schemas import (
    StockAdjustRequest, StockAdjustResponse, LowStockProductResponse, InventorySummaryResponse
)

router = APIRouter(prefix="/api/v1/inventory", tags=["Inventory Management"])


@router.post("/restock", response_model=StockAdjustResponse)
def adjust_inventory_stock(payload: StockAdjustRequest, db: Session = Depends(get_db)):
    """
    Adjust stock quantity for a product (Restock with positive delta, adjustment/spoilage with negative delta).
    Guarantees stock cannot become negative and executes in an atomic transaction.
    """
    if payload.quantity_delta == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantity delta must be non-zero."
        )

    # Use SELECT FOR UPDATE or simple row query
    product = db.query(Product).filter(Product.id == payload.product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {payload.product_id} not found."
        )

    previous_stock = product.stock_quantity
    new_stock = round(previous_stock + payload.quantity_delta, 3)

    if new_stock < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Insufficient stock for '{product.name}'. Current stock is {previous_stock} {product.unit}, "
                f"cannot adjust by {payload.quantity_delta}."
            )
        )

    # Update stock
    product.stock_quantity = new_stock
    db.commit()
    db.refresh(product)

    try:
        from backend.services.forecasting import invalidate_forecast_cache
        invalidate_forecast_cache(product.id)
    except Exception:
        pass

    return StockAdjustResponse(
        product_id=product.id,
        product_name=product.name,
        previous_stock=previous_stock,
        quantity_delta=payload.quantity_delta,
        new_stock=new_stock,
        unit=product.unit,
        is_low_stock=new_stock <= product.min_stock_threshold,
        notes=payload.notes
    )


@router.post("/adjust", response_model=StockAdjustResponse)
def adjust_inventory(payload: StockAdjustRequest, db: Session = Depends(get_db)):
    """
    Adjust stock quantity for a product (alias for /restock supporting negative and positive deltas).
    Guarantees stock cannot become negative and executes in an atomic transaction.
    """
    return adjust_inventory_stock(payload=payload, db=db)


@router.get("/low-stock", response_model=List[LowStockProductResponse])
def get_low_stock_products(db: Session = Depends(get_db)):
    """
    Retrieve all active products currently at or below their minimum stock threshold.
    Includes calculated shortage quantity to assist in reordering.
    """
    products = (
        db.query(Product)
        .filter(
            Product.is_active == True,
            Product.stock_quantity <= Product.min_stock_threshold
        )
        .order_by(Product.stock_quantity / func.nullif(Product.min_stock_threshold, 0))
        .all()
    )

    results = []
    for p in products:
        shortage = max(0.0, round(p.min_stock_threshold - p.stock_quantity, 2))
        results.append(
            LowStockProductResponse(
                id=p.id,
                name=p.name,
                hindi_name=p.hindi_name,
                category=p.category,
                unit=p.unit,
                stock_quantity=p.stock_quantity,
                min_stock_threshold=p.min_stock_threshold,
                shortage_quantity=shortage
            )
        )
    return results


@router.get("/summary", response_model=InventorySummaryResponse)
def get_inventory_summary(db: Session = Depends(get_db)):
    """
    Get aggregated inventory statistics for active products: total products,
    total stock valuation (INR), low-stock item count, and out-of-stock count.
    Archived products are excluded.
    """
    total_products = db.query(Product).filter(Product.is_active == True).count()

    # Calculate total value in INR: SUM(stock_quantity * unit_price) for active products
    valuation_result = db.query(
        func.sum(Product.stock_quantity * Product.unit_price)
    ).filter(Product.is_active == True).scalar()
    total_value = round(float(valuation_result or 0.0), 2)

    low_stock_count = db.query(Product).filter(
        Product.is_active == True,
        Product.stock_quantity <= Product.min_stock_threshold
    ).count()

    out_of_stock_count = db.query(Product).filter(
        Product.is_active == True,
        Product.stock_quantity <= 0.0
    ).count()

    return InventorySummaryResponse(
        total_products=total_products,
        total_inventory_value=total_value,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count
    )


@router.get("/charts", status_code=status.HTTP_200_OK)
def get_inventory_charts(db: Session = Depends(get_db)):
    """
    Returns aggregated series for Inventory visualizations (Phase 2):
    1. Low-Stock Comparison (current stock vs min threshold for top low-stock items)
    2. Stock by Category (units and product counts per category)
    3. Inventory Valuation (catalog valuation grouped by category with accounting disclosure)
    4. Stock Movement status disclosure
    """
    # 1. Low-Stock comparison (products at or near threshold, ordered by urgency)
    low_stock_query = (
        db.query(Product)
        .filter(Product.is_active == True)
        .order_by((Product.stock_quantity / func.nullif(Product.min_stock_threshold, 0)).asc())
        .limit(10)
        .all()
    )
    low_stock_comparison = []
    for p in low_stock_query:
        thresh = float(p.min_stock_threshold or 0.0)
        curr = float(p.stock_quantity or 0.0)
        low_stock_comparison.append({
            "id": p.id,
            "name": p.name,
            "category": p.category or "General",
            "stock_quantity": round(curr, 2),
            "min_stock_threshold": round(thresh, 2),
            "unit": p.unit or "unit",
            "is_below_threshold": curr <= thresh
        })

    # 2. Stock by Category & Valuation
    products = db.query(Product).filter(Product.is_active == True).all()
    cat_stats = {}
    for p in products:
        cat = p.category or "General"
        if cat not in cat_stats:
            cat_stats[cat] = {"product_count": 0, "total_units": 0.0, "valuation": 0.0}
        cat_stats[cat]["product_count"] += 1
        cat_stats[cat]["total_units"] += float(p.stock_quantity or 0.0)
        cat_stats[cat]["valuation"] += float(p.stock_quantity or 0.0) * float(p.unit_price or 0.0)

    stock_by_category = [
        {
            "category": cat,
            "product_count": s["product_count"],
            "total_units": round(s["total_units"], 2)
        }
        for cat, s in sorted(cat_stats.items(), key=lambda x: x[1]["total_units"], reverse=True)
    ]

    inventory_valuation = [
        {
            "category": cat,
            "valuation": round(s["valuation"], 2)
        }
        for cat, s in sorted(cat_stats.items(), key=lambda x: x[1]["valuation"], reverse=True)
    ]

    total_val = round(sum(s["valuation"] for s in cat_stats.values()), 2)

    return {
        "low_stock_comparison": low_stock_comparison,
        "stock_by_category": stock_by_category,
        "inventory_valuation": inventory_valuation,
        "total_valuation": total_val,
        "valuation_type": "ESTIMATED_SELLING_VALUE",
        "valuation_disclosure": "Valuation computed at catalog selling price. Authoritative purchase-cost records are not tracked in product catalog schema; never construed as net profit.",
        "stock_movement_available": False,
        "stock_movement_disclosure": "Detailed inventory ledger audit log table is not present in SQLite schema. Undocumented movements are not synthetically reconstructed."
    }

