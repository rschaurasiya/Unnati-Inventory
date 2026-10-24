"""
Product Catalog API Router
Provides endpoints for listing, searching, retrieving, creating, updating, price adjustment, and safe deletion/archival of products.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from backend.database import get_db
from backend.models import Product, BillItem, HistoricalSaleRecord, DailySalesSummary, ProductForecast
from backend.schemas import (
    ProductCreate, ProductUpdate, ProductPriceUpdate, ProductResponse
)

router = APIRouter(prefix="/api/v1/products", tags=["Product Catalog"])


class BulkDeleteProductsRequest(BaseModel):
    product_ids: Optional[List[int]] = None
    delete_all_test_items: Optional[bool] = False
    hard_delete: bool = True



def _to_product_response(product: Product) -> dict:
    """Helper to convert Product ORM instance to ProductResponse dictionary with computed fields."""
    return {
        "id": product.id,
        "name": product.name,
        "hindi_name": product.hindi_name,
        "aliases": product.aliases or "",
        "category": product.category,
        "unit": product.unit,
        "unit_price": product.unit_price,
        "stock_quantity": product.stock_quantity,
        "min_stock_threshold": product.min_stock_threshold,
        "is_low_stock": product.stock_quantity <= product.min_stock_threshold,
        "is_active": getattr(product, "is_active", True),
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }


@router.get("", response_model=List[ProductResponse])
def list_products(
    query: Optional[str] = Query(None, description="Search term matching product name or spoken aliases"),
    search: Optional[str] = Query(None, description="Alias for query parameter"),
    q: Optional[str] = Query(None, description="Short alias for search parameter"),
    category: Optional[str] = Query(None, description="Filter by product category"),
    low_stock_only: bool = Query(False, description="Filter for products at or below min stock threshold"),
    out_of_stock_only: bool = Query(False, description="Filter for products with stock quantity <= 0"),
    include_inactive: bool = Query(False, description="Include archived/inactive products"),
    active_only: Optional[bool] = Query(None, description="Filter active products only"),
    db: Session = Depends(get_db)
):
    """
    List all catalog products with optional keyword search, category filter, low-stock, and out-of-stock filter.
    By default, only active products are returned.
    """
    is_low_stock = bool(low_stock_only) if isinstance(low_stock_only, bool) else False
    is_out_of_stock = bool(out_of_stock_only) if isinstance(out_of_stock_only, bool) else False
    is_inc_inactive = bool(include_inactive) if isinstance(include_inactive, bool) else False
    is_active_only = active_only if isinstance(active_only, bool) else None

    db_query = db.query(Product)
    if is_active_only is True:
        db_query = db_query.filter(Product.is_active == True)
    elif is_active_only is False:
        pass  # return all products
    elif not is_inc_inactive:
        db_query = db_query.filter(Product.is_active == True)

    active_search = query or search or q
    if active_search:
        search_term = f"%{active_search.strip().lower()}%"
        db_query = db_query.filter(
            or_(
                func.lower(Product.name).like(search_term),
                func.lower(Product.aliases).like(search_term),
                func.lower(Product.hindi_name).like(search_term)
            )
        )

    if category:
        db_query = db_query.filter(Product.category == category)

    if is_out_of_stock:
        db_query = db_query.filter(Product.stock_quantity <= 0.0)
    elif is_low_stock:
        db_query = db_query.filter(Product.stock_quantity <= Product.min_stock_threshold)

    products = db_query.order_by(Product.category, Product.name).all()
    return [_to_product_response(p) for p in products]


@router.get("/search", response_model=List[ProductResponse])
def search_products(
    q: Optional[str] = Query(None, description="Search term matching name or aliases"),
    query: Optional[str] = Query(None, description="Alias for search query"),
    search: Optional[str] = Query(None, description="Alias for search query"),
    category: Optional[str] = Query(None, description="Filter by category"),
    active_only: Optional[bool] = Query(None, description="Filter active products only"),
    db: Session = Depends(get_db)
):
    """Search products by name, hindi_name, or spoken aliases."""
    return list_products(
        query=query,
        search=search,
        q=q,
        category=category,
        low_stock_only=False,
        include_inactive=False,
        active_only=active_only,
        db=db
    )


@router.get("/categories", response_model=List[str])
def list_categories(db: Session = Depends(get_db)):
    """Retrieve distinct product categories in the active catalog."""
    categories = (
        db.query(Product.category)
        .filter(Product.is_active == True)
        .distinct()
        .order_by(Product.category)
        .all()
    )
    return [c[0] for c in categories if c[0]]


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """Retrieve single product by ID."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found."
        )
    return _to_product_response(product)


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    """
    Create a new product in the catalog with server-side validation.
    Enforces non-empty name, non-negative price/stock, valid units, and uniqueness.
    """
    name_clean = payload.name.strip()
    if len(name_clean) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product name must be at least 2 characters long."
        )

    if payload.unit_price < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unit price cannot be negative."
        )

    if payload.stock_quantity < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stock quantity cannot be negative."
        )

    if payload.min_stock_threshold < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Min stock threshold cannot be negative."
        )

    # Check duplicate active product name
    existing = db.query(Product).filter(
        func.lower(Product.name) == name_clean.lower(),
        Product.is_active == True
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A product named '{existing.name}' already exists in category '{existing.category}'."
        )

    product = Product(
        name=name_clean,
        hindi_name=payload.hindi_name.strip() if payload.hindi_name else None,
        aliases=payload.aliases.strip() if payload.aliases else "",
        category=payload.category.strip(),
        unit=payload.unit.strip().lower(),
        unit_price=float(payload.unit_price),
        stock_quantity=float(payload.stock_quantity),
        min_stock_threshold=float(payload.min_stock_threshold),
        is_active=True
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return _to_product_response(product)


@router.put("/{product_id}", response_model=ProductResponse)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    """
    Update details of an existing product.
    Future bills will reflect the updated details and price; historical records remain untouched.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found."
        )

    update_data = payload.model_dump(exclude_unset=True)

    # Validate price and stock if provided
    if "unit_price" in update_data and update_data["unit_price"] is not None:
        if update_data["unit_price"] < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unit price cannot be negative."
            )

    if "stock_quantity" in update_data and update_data["stock_quantity"] is not None:
        if update_data["stock_quantity"] < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stock quantity cannot be negative."
            )

    if "name" in update_data and update_data["name"] is not None:
        new_name = update_data["name"].strip()
        if len(new_name) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product name must be at least 2 characters long."
            )
        # Check duplicate name on another product
        conflict = db.query(Product).filter(
            func.lower(Product.name) == new_name.lower(),
            Product.id != product_id,
            Product.is_active == True
        ).first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Another product with name '{conflict.name}' already exists (ID: {conflict.id})."
            )
        update_data["name"] = new_name

    for field, val in update_data.items():
        if val is not None:
            if isinstance(val, str):
                val = val.strip()
            setattr(product, field, val)

    db.commit()
    db.refresh(product)
    return _to_product_response(product)


@router.patch("/{product_id}/price", response_model=ProductResponse)
def update_product_price(product_id: int, payload: ProductPriceUpdate, db: Session = Depends(get_db)):
    """
    Dedicated endpoint to update current product price for future transactions.
    Historical sales and previous bills preserve their original transaction price.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found."
        )

    if payload.unit_price < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unit price cannot be negative."
        )

    product.unit_price = float(payload.unit_price)
    db.commit()
    db.refresh(product)
    return _to_product_response(product)


@router.post("/bulk-delete", status_code=status.HTTP_200_OK)
def bulk_delete_products(payload: BulkDeleteProductsRequest, db: Session = Depends(get_db)):
    """
    Bulk delete or archive multiple products from the catalog.
    Supports either an explicit list of product_ids or deleting all test products (name/category/alias containing 'test').
    When hard_delete=True, cleans up associated dependent test records and removes them permanently from the database.
    """
    if payload.delete_all_test_items:
        target_products = db.query(Product).filter(
            or_(
                func.lower(Product.name).like("%test%"),
                func.lower(Product.category).like("%test%"),
                func.lower(Product.aliases).like("%test%")
            )
        ).all()
    elif payload.product_ids:
        target_products = db.query(Product).filter(Product.id.in_(payload.product_ids)).all()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'product_ids' or 'delete_all_test_items: true' must be provided."
        )

    if not target_products:
        return {
            "status": "success",
            "message": "No matching products found to delete.",
            "deleted_count": 0,
            "product_ids": []
        }

    target_ids = [p.id for p in target_products]

    if payload.hard_delete:
        # Cascade dependent records for these products
        db.query(ProductForecast).filter(ProductForecast.product_id.in_(target_ids)).delete(synchronize_session=False)
        db.query(DailySalesSummary).filter(DailySalesSummary.product_id.in_(target_ids)).delete(synchronize_session=False)
        db.query(HistoricalSaleRecord).filter(HistoricalSaleRecord.product_id.in_(target_ids)).delete(synchronize_session=False)
        db.query(BillItem).filter(BillItem.product_id.in_(target_ids)).delete(synchronize_session=False)
        db.query(Product).filter(Product.id.in_(target_ids)).delete(synchronize_session=False)
        db.commit()
        return {
            "status": "success",
            "message": f"Successfully deleted {len(target_ids)} product(s) permanently from the database.",
            "deleted_count": len(target_ids),
            "product_ids": target_ids,
            "hard_deleted": True
        }
    else:
        # Safe soft-delete / archive
        for p in target_products:
            p.is_active = False
        db.commit()
        return {
            "status": "success",
            "message": f"Successfully archived {len(target_ids)} product(s).",
            "deleted_count": len(target_ids),
            "product_ids": target_ids,
            "hard_deleted": False
        }


@router.delete("/{product_id}", status_code=status.HTTP_200_OK)
def delete_product(product_id: int, hard_delete: bool = False, db: Session = Depends(get_db)):
    """
    Safely delete or archive a product from the catalog.
    If hard_delete is False (default):
        Safely soft-deletes (is_active = False) so foreign key constraints and historical
        financial integrity remain completely intact.
    If hard_delete is True:
        Permanently deletes the product from the backend database, safely cleaning
        up dependent records and foreign keys.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found."
        )

    # Check references across all dependent tables
    bill_refs = db.query(BillItem).filter(BillItem.product_id == product_id).count()
    hist_refs = db.query(HistoricalSaleRecord).filter(HistoricalSaleRecord.product_id == product_id).count()
    summary_refs = db.query(DailySalesSummary).filter(DailySalesSummary.product_id == product_id).count()
    total_refs = bill_refs + hist_refs + summary_refs

    if not hard_delete:
        # Safe soft-delete / archive
        product.is_active = False
        db.commit()
        return {
            "status": "success",
            "message": f"Product '{product.name}' has been safely archived. Historical sales and previous bills remain intact.",
            "soft_deleted": True,
            "is_active": False,
            "references_preserved": total_refs
        }
    else:
        # Permanent hard delete from backend database
        db.query(ProductForecast).filter(ProductForecast.product_id == product_id).delete(synchronize_session=False)
        db.query(DailySalesSummary).filter(DailySalesSummary.product_id == product_id).delete(synchronize_session=False)
        db.query(HistoricalSaleRecord).filter(HistoricalSaleRecord.product_id == product_id).delete(synchronize_session=False)
        db.query(BillItem).filter(BillItem.product_id == product_id).delete(synchronize_session=False)
        db.delete(product)
        db.commit()
        return {
            "status": "success",
            "message": f"Product '{product.name}' deleted permanently.",
            "soft_deleted": False,
            "is_active": False,
            "references_preserved": 0
        }


