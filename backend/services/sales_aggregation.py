"""
Sales Aggregation & Historical Data Foundation Service (Step 10)
Provides deterministic, idempotent daily product-level sales aggregation,
reconciliation/rebuild from completed bills, data sufficiency evaluation,
and inventory-safe historical demo data seeding.
"""
import random
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import Bill, BillItem, DailySalesSummary, Product, HistoricalSaleRecord


def aggregate_sales_for_date(db: Session, target_date: date) -> int:
    """
    Idempotently aggregates sales for a specific date from completed bills AND
    active imported historical sales records.
    Updates existing DailySalesSummary rows or inserts new ones.
    Removes stale summaries if items for that date were removed or cancelled.
    Sources of truth:
      1. Bill.status == 'COMPLETED' and its BillItems.
      2. HistoricalSaleRecord.is_active == True (source_type == 'IMPORTED').
    """
    start_dt = datetime.combine(target_date, time.min)
    end_dt = datetime.combine(target_date, time.max)

    # 1. Query aggregated sales directly from completed bills and items
    aggregated_bill_rows = (
        db.query(
            BillItem.product_id,
            func.sum(BillItem.quantity).label("total_qty"),
            func.sum(BillItem.line_total).label("total_rev"),
            func.count(func.distinct(Bill.id)).label("tx_count")
        )
        .join(Bill, BillItem.bill_id == Bill.id)
        .filter(
            Bill.status == "COMPLETED",
            Bill.created_at >= start_dt,
            Bill.created_at <= end_dt
        )
        .group_by(BillItem.product_id)
        .all()
    )

    # 2. Query aggregated sales from active imported historical records
    imported_rows = (
        db.query(
            HistoricalSaleRecord.product_id,
            func.sum(HistoricalSaleRecord.quantity).label("total_qty"),
            func.sum(HistoricalSaleRecord.total_amount).label("total_rev"),
            func.count(HistoricalSaleRecord.id).label("tx_count")
        )
        .filter(
            HistoricalSaleRecord.sale_date == target_date,
            HistoricalSaleRecord.is_active == True,
            HistoricalSaleRecord.source_type == "IMPORTED"
        )
        .group_by(HistoricalSaleRecord.product_id)
        .all()
    )

    # 3. Combine totals by product_id
    product_totals: Dict[int, Dict[str, float]] = {}

    for row in aggregated_bill_rows:
        pid = row.product_id
        product_totals[pid] = {
            "qty": float(row.total_qty or 0.0),
            "rev": float(row.total_rev or 0.0),
            "tx_count": int(row.tx_count or 0)
        }

    for row in imported_rows:
        pid = row.product_id
        if pid not in product_totals:
            product_totals[pid] = {
                "qty": float(row.total_qty or 0.0),
                "rev": float(row.total_rev or 0.0),
                "tx_count": int(row.tx_count or 0)
            }
        else:
            product_totals[pid]["qty"] += float(row.total_qty or 0.0)
            product_totals[pid]["rev"] += float(row.total_rev or 0.0)
            product_totals[pid]["tx_count"] += int(row.tx_count or 0)

    # 4. Existing summary records for target_date
    existing_summaries: Dict[int, DailySalesSummary] = {
        s.product_id: s
        for s in db.query(DailySalesSummary).filter(DailySalesSummary.sale_date == target_date).all()
    }

    count_processed = 0
    now = datetime.utcnow()

    # 5. Upsert aggregation results
    for pid, data in product_totals.items():
        qty = round(data["qty"], 3)
        rev = round(data["rev"], 2)
        txs = int(data["tx_count"])

        if pid in existing_summaries:
            summary = existing_summaries.pop(pid)
            summary.total_quantity_sold = qty
            summary.total_revenue = rev
            summary.transaction_count = txs
            summary.updated_at = now
        else:
            summary = DailySalesSummary(
                product_id=pid,
                sale_date=target_date,
                total_quantity_sold=qty,
                total_revenue=rev,
                transaction_count=txs,
                updated_at=now
            )
            db.add(summary)
        count_processed += 1

    # 6. Remove orphan records that no longer have completed or imported sales on this date
    for orphan in existing_summaries.values():
        db.delete(orphan)

    db.flush()
    return count_processed


def rebuild_all_sales_summaries(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> Tuple[int, int]:
    """
    Deterministically rebuilds all DailySalesSummary rows from completed bills AND
    active imported historical sales records.
    Safe to rerun repeatedly. Completely eliminates duplicates and stale entries.
    """
    bill_query = db.query(Bill.created_at).filter(Bill.status == "COMPLETED")
    if start_date:
        bill_query = bill_query.filter(Bill.created_at >= datetime.combine(start_date, time.min))
    if end_date:
        bill_query = bill_query.filter(Bill.created_at <= datetime.combine(end_date, time.max))

    all_completed_bills = bill_query.all()
    distinct_dates = {b[0].date() for b in all_completed_bills if b[0]}

    # Include distinct dates from imported historical sales records
    hist_query = db.query(HistoricalSaleRecord.sale_date).filter(HistoricalSaleRecord.is_active == True)
    if start_date:
        hist_query = hist_query.filter(HistoricalSaleRecord.sale_date >= start_date)
    if end_date:
        hist_query = hist_query.filter(HistoricalSaleRecord.sale_date <= end_date)

    all_hist_records = hist_query.all()
    for h in all_hist_records:
        if h[0]:
            distinct_dates.add(h[0])

    sorted_dates = sorted(distinct_dates)

    # Clean existing summary records in the target scope
    del_query = db.query(DailySalesSummary)
    if start_date:
        del_query = del_query.filter(DailySalesSummary.sale_date >= start_date)
    if end_date:
        del_query = del_query.filter(DailySalesSummary.sale_date <= end_date)
    del_query.delete(synchronize_session=False)
    db.flush()

    total_summaries = 0
    for d in sorted_dates:
        count = aggregate_sales_for_date(db, d)
        total_summaries += count

    db.commit()
    try:
        from backend.services.forecasting import invalidate_forecast_cache
        invalidate_forecast_cache()
    except Exception:
        pass
    return len(sorted_dates), total_summaries


def check_data_sufficiency(db: Session, product_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Evaluates whether historical sales data meets the threshold for forecasting eligibility.
    Rule:
      < 7 usable days with sales -> INSUFFICIENT_DATA
      >= 7 usable days with sales -> SUFFICIENT_DATA
    Evaluates both store-wide and product-level readiness.
    """
    # 1. Store-wide usable days
    sales_rows = (
        db.query(DailySalesSummary)
        .filter(DailySalesSummary.total_quantity_sold > 0)
        .all()
    )

    all_dates = {s.sale_date for s in sales_rows}
    usable_days_count = len(all_dates)
    overall_status = "SUFFICIENT_DATA" if usable_days_count >= 7 else "INSUFFICIENT_DATA"

    earliest_date = min(all_dates).isoformat() if all_dates else None
    latest_date = max(all_dates).isoformat() if all_dates else None

    # 2. Product-level breakdown
    active_products = (
        db.query(Product)
        .order_by(Product.name.asc())
        .all()
    )

    # Map product_id to list of summaries with sales
    product_summaries_map: Dict[int, List[DailySalesSummary]] = {}
    for s in sales_rows:
        product_summaries_map.setdefault(s.product_id, []).append(s)

    product_details = []
    sufficient_count = 0
    insufficient_count = 0

    for prod in active_products:
        p_summaries = product_summaries_map.get(prod.id, [])
        p_dates = {s.sale_date for s in p_summaries}
        p_days = len(p_dates)
        p_status = "SUFFICIENT_DATA" if p_days >= 7 else "INSUFFICIENT_DATA"

        if p_status == "SUFFICIENT_DATA":
            sufficient_count += 1
        else:
            insufficient_count += 1

        p_earliest = min(p_dates).isoformat() if p_dates else None
        p_latest = max(p_dates).isoformat() if p_dates else None
        total_qty = round(sum(s.total_quantity_sold for s in p_summaries), 2)
        total_rev = round(sum(s.total_revenue for s in p_summaries), 2)

        product_details.append({
            "product_id": prod.id,
            "product_name": prod.name,
            "category": prod.category,
            "unit": prod.unit,
            "usable_days_count": p_days,
            "status": p_status,
            "earliest_date": p_earliest,
            "latest_date": p_latest,
            "total_quantity_sold": total_qty,
            "total_sales_amount": total_rev
        })

    # If specific product_id is requested, place it first or filter
    if product_id:
        matched = [p for p in product_details if p["product_id"] == product_id]
        if not matched:
            target_prod = db.query(Product).filter(Product.id == product_id).first()
            if target_prod:
                matched = [{
                    "product_id": target_prod.id,
                    "product_name": target_prod.name,
                    "category": target_prod.category,
                    "unit": target_prod.unit,
                    "usable_days_count": 0,
                    "status": "INSUFFICIENT_DATA",
                    "earliest_date": None,
                    "latest_date": None,
                    "total_quantity_sold": 0.0,
                    "total_sales_amount": 0.0
                }]

    message = (
        f"Store has {usable_days_count} usable days of sales history (threshold: 7 days). "
        f"{sufficient_count} active products have sufficient historical depth."
    )

    return {
        "status": overall_status,
        "usable_days_count": usable_days_count,
        "min_days_required": 7,
        "earliest_date": earliest_date,
        "latest_date": latest_date,
        "total_active_products": len(active_products),
        "sufficient_products_count": sufficient_count,
        "insufficient_products_count": insufficient_count,
        "message": message,
        "products": product_details
    }


def seed_demo_historical_sales(
    db: Session,
    days: int = 60,
    seed: int = 42
) -> Dict[str, Any]:
    """
    Generates approximately 60 days of realistic, deterministic historical completed bills.
    Incorporates:
      - Daily variation
      - Product-level variation (staples sell daily, niche sell less)
      - Day-of-week variation (weekend demand multiplier)
      - Isolated demo tag without corrupting current inventory stock.
    Guarantees:
      - Product.stock_quantity is completely untouched!
      - Idempotent and deterministic when using a fixed seed.
    """
    rng = random.Random(seed)

    # 1. Take snapshot of current stock quantities to guarantee inventory safety
    products = db.query(Product).all()
    if not products:
        return {
            "status": "ERROR",
            "message": "No active products found to seed demo history.",
            "days_seeded": 0,
            "bills_created": 0,
            "items_created": 0,
            "inventory_unaltered": True,
            "earliest_date": "",
            "latest_date": ""
        }

    initial_stock_snapshot = {p.id: p.stock_quantity for p in products}

    # 2. Clean existing demo bills and demo summaries
    existing_demo_bills = db.query(Bill).filter(Bill.notes.like("%[DEMO_HISTORICAL_DATA]%")).all()
    for b in existing_demo_bills:
        db.delete(b)
    db.flush()

    # Re-fetch active products
    prod_lookup = {p.id: p for p in products}
    all_prod_ids = [p.id for p in products]

    # Split products into demand tiers
    # Staples: sell frequently every day
    staple_keywords = ["sugar", "atta", "milk", "rice", "dal", "tea", "oil", "maggi", "salt", "bread", "soap"]
    staple_ids = [
        p.id for p in products
        if any(kw in p.name.lower() or kw in p.aliases.lower() for kw in staple_keywords)
    ]
    if not staple_ids:
        staple_ids = all_prod_ids[:max(5, len(all_prod_ids) // 3)]

    regular_ids = [pid for pid in all_prod_ids if pid not in staple_ids]
    if not regular_ids:
        regular_ids = all_prod_ids

    # Designate 1 product as 'new/recent' with only 2 days of demo sales
    new_product_id = regular_ids[-1] if len(regular_ids) > 1 else None

    today = date.today()
    bills_created = 0
    items_created = 0
    seeded_dates = []

    for day_offset in range(days, 0, -1):
        target_date = today - timedelta(days=day_offset)
        seeded_dates.append(target_date)

        # Day-of-week factor: Friday (4), Saturday (5), Sunday (6) have higher traffic
        weekday = target_date.weekday()
        if weekday in (4, 5, 6):
            demand_multiplier = rng.uniform(1.3, 1.55)
            num_bills = rng.randint(5, 9)
        else:
            demand_multiplier = rng.uniform(0.85, 1.15)
            num_bills = rng.randint(3, 6)

        for bill_idx in range(num_bills):
            bill_time = time(
                hour=rng.randint(8, 20),
                minute=rng.randint(0, 59),
                second=rng.randint(0, 59)
            )
            created_at = datetime.combine(target_date, bill_time)

            payment_mode = rng.choices(["CASH", "UPI", "UDHAAR"], weights=[0.60, 0.30, 0.10])[0]
            bill_num = f"DEMO-BILL-{target_date.strftime('%Y%m%d')}-{bill_idx+1:03d}-{rng.randint(100, 999)}"

            bill = Bill(
                bill_number=bill_num,
                customer_id=None,
                family_member_id=None,
                subtotal=0.0,
                discount=0.0,
                tax=0.0,
                total_amount=0.0,
                payment_mode=payment_mode,
                status="COMPLETED",
                notes="[DEMO_HISTORICAL_DATA] Seeded historical foundation for sales analytics",
                created_at=created_at
            )
            db.add(bill)
            db.flush()

            # Select 2 to 6 items per bill
            num_items = rng.randint(2, 5)
            selected_pids = set()

            # At least 1 staple in each bill
            if staple_ids:
                selected_pids.add(rng.choice(staple_ids))

            # Pick remaining products
            candidate_pool = [pid for pid in all_prod_ids if pid != new_product_id]
            while len(selected_pids) < num_items and candidate_pool:
                selected_pids.add(rng.choice(candidate_pool))

            # If within last 2 days of demo range, include the new product occasionally
            if new_product_id and day_offset <= 2 and rng.random() < 0.6:
                selected_pids.add(new_product_id)

            bill_subtotal = 0.0
            for pid in selected_pids:
                prod = prod_lookup[pid]
                # Vary quantity based on unit
                if prod.unit.lower() in ["kg", "litre"]:
                    base_qty = rng.choice([0.5, 1.0, 1.5, 2.0, 3.0, 5.0])
                elif prod.unit.lower() in ["packet", "piece"]:
                    base_qty = float(rng.randint(1, 4))
                elif prod.unit.lower() == "dozen":
                    base_qty = float(rng.choice([0.5, 1.0, 2.0]))
                else:
                    base_qty = float(rng.randint(1, 3))

                qty = round(base_qty * (1.2 if weekday in (5, 6) else 1.0), 2)
                line_total = round(qty * prod.unit_price, 2)
                bill_subtotal += line_total

                bill_item = BillItem(
                    bill_id=bill.id,
                    product_id=prod.id,
                    quantity=qty,
                    unit=prod.unit,
                    unit_price=prod.unit_price,
                    line_total=line_total
                )
                db.add(bill_item)
                items_created += 1

            bill.subtotal = round(bill_subtotal, 2)
            bill.total_amount = round(bill_subtotal, 2)
            bills_created += 1

        # Aggregate daily sales for this target date
        aggregate_sales_for_date(db, target_date)

    # 3. VERIFY INVENTORY SAFETY: Stock quantities MUST NOT have changed
    for prod in products:
        current_stock = prod.stock_quantity
        expected_stock = initial_stock_snapshot[prod.id]
        if current_stock != expected_stock:
            # Revert any unexpected mutation
            prod.stock_quantity = expected_stock

    db.commit()
    try:
        from backend.services.forecasting import invalidate_forecast_cache
        invalidate_forecast_cache()
    except Exception:
        pass

    earliest_str = seeded_dates[0].isoformat() if seeded_dates else ""
    latest_str = seeded_dates[-1].isoformat() if seeded_dates else ""

    return {
        "status": "SUCCESS",
        "message": f"Successfully seeded {days} days of deterministic historical sales data.",
        "days_seeded": len(seeded_dates),
        "bills_created": bills_created,
        "items_created": items_created,
        "inventory_unaltered": True,
        "earliest_date": earliest_str,
        "latest_date": latest_str
    }


def query_sales_by_date(db: Session, target_date: date) -> Dict[str, Any]:
    """
    Returns aggregated daily sales per product for a specific date.
    """
    summaries = (
        db.query(DailySalesSummary)
        .filter(DailySalesSummary.sale_date == target_date)
        .all()
    )

    items = []
    total_rev = 0.0
    total_qty = 0.0
    total_tx = 0

    for s in summaries:
        prod = s.product
        item_qty = round(s.total_quantity_sold, 3)
        item_rev = round(s.total_revenue, 2)
        total_rev += item_rev
        total_qty += item_qty
        total_tx += s.transaction_count

        items.append({
            "product_id": s.product_id,
            "product_name": prod.name if prod else f"Product #{s.product_id}",
            "category": prod.category if prod else None,
            "unit": prod.unit if prod else "unit",
            "unit_price": prod.unit_price if prod else 0.0,
            "total_quantity_sold": item_qty,
            "total_sales_amount": item_rev,
            "transaction_count": s.transaction_count
        })

    # Sort by sales amount descending
    items.sort(key=lambda x: x["total_sales_amount"], reverse=True)

    return {
        "sale_date": target_date.isoformat(),
        "total_revenue": round(total_rev, 2),
        "total_quantity_sold": round(total_qty, 3),
        "transaction_count": total_tx,
        "items": items
    }


def query_sales_by_range(
    db: Session,
    start_date: date,
    end_date: date,
    product_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Queries aggregated sales across a date range with optional product filter.
    """
    query = (
        db.query(DailySalesSummary)
        .filter(
            DailySalesSummary.sale_date >= start_date,
            DailySalesSummary.sale_date <= end_date
        )
    )
    if product_id:
        query = query.filter(DailySalesSummary.product_id == product_id)

    all_rows = query.order_by(DailySalesSummary.sale_date.asc()).all()

    # Group by date
    by_date: Dict[date, List[DailySalesSummary]] = {}
    distinct_products = set()
    total_rev = 0.0
    total_qty = 0.0
    total_tx = 0

    for r in all_rows:
        by_date.setdefault(r.sale_date, []).append(r)
        distinct_products.add(r.product_id)
        total_rev += r.total_revenue
        total_qty += r.total_quantity_sold
        total_tx += r.transaction_count

    daily_summaries = []
    for d, rows in sorted(by_date.items(), key=lambda x: x[0]):
        d_items = []
        d_rev = 0.0
        d_qty = 0.0
        d_tx = 0
        for s in rows:
            prod = s.product
            d_rev += s.total_revenue
            d_qty += s.total_quantity_sold
            d_tx += s.transaction_count
            d_items.append({
                "product_id": s.product_id,
                "product_name": prod.name if prod else f"Product #{s.product_id}",
                "category": prod.category if prod else None,
                "unit": prod.unit if prod else "unit",
                "unit_price": prod.unit_price if prod else 0.0,
                "total_quantity_sold": round(s.total_quantity_sold, 3),
                "total_sales_amount": round(s.total_revenue, 2),
                "transaction_count": s.transaction_count
            })
        d_items.sort(key=lambda x: x["total_sales_amount"], reverse=True)
        daily_summaries.append({
            "sale_date": d.isoformat(),
            "total_revenue": round(d_rev, 2),
            "total_quantity_sold": round(d_qty, 3),
            "transaction_count": d_tx,
            "items": d_items
        })

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_revenue": round(total_rev, 2),
        "total_quantity_sold": round(total_qty, 3),
        "total_transactions": total_tx,
        "distinct_products_count": len(distinct_products),
        "usable_days_count": len(by_date),
        "daily_summaries": daily_summaries
    }


def query_product_sales_history(
    db: Session,
    product: Product,
    start_date: date,
    end_date: date
) -> Dict[str, Any]:
    """
    Returns historical daily sales time-series for a single product.
    """
    rows = (
        db.query(DailySalesSummary)
        .filter(
            DailySalesSummary.product_id == product.id,
            DailySalesSummary.sale_date >= start_date,
            DailySalesSummary.sale_date <= end_date
        )
        .order_by(DailySalesSummary.sale_date.asc())
        .all()
    )

    history_points = []
    total_qty = 0.0
    total_rev = 0.0
    total_tx = 0

    for r in rows:
        total_qty += r.total_quantity_sold
        total_rev += r.total_revenue
        total_tx += r.transaction_count
        history_points.append({
            "sale_date": r.sale_date.isoformat(),
            "quantity_sold": round(r.total_quantity_sold, 3),
            "sales_amount": round(r.total_revenue, 2),
            "transaction_count": r.transaction_count
        })

    days_count = len(history_points)
    avg_qty = round(total_qty / days_count, 2) if days_count > 0 else 0.0

    return {
        "product_id": product.id,
        "product_name": product.name,
        "category": product.category,
        "unit": product.unit,
        "unit_price": product.unit_price,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_quantity_sold": round(total_qty, 3),
        "total_sales_amount": round(total_rev, 2),
        "total_transactions": total_tx,
        "active_days_count": days_count,
        "average_daily_quantity": avg_qty,
        "history": history_points
    }


def query_completed_sale_items(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    product_id: Optional[int] = None,
    category: Optional[str] = None,
    payment_mode: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Returns completed bill line items with billing context, plus active imported
    historical sale records.
    Omits all customer personal identification (phone, address, verification data).
    """
    # 1. Query completed POS bills
    bill_query = (
        db.query(BillItem, Bill)
        .join(Bill, BillItem.bill_id == Bill.id)
        .filter(Bill.status == "COMPLETED")
    )

    if start_date:
        bill_query = bill_query.filter(Bill.created_at >= datetime.combine(start_date, time.min))
    if end_date:
        bill_query = bill_query.filter(Bill.created_at <= datetime.combine(end_date, time.max))
    if product_id:
        bill_query = bill_query.filter(BillItem.product_id == product_id)
    if payment_mode and payment_mode.strip() and payment_mode.upper() != "ALL":
        bill_query = bill_query.filter(Bill.payment_mode == payment_mode.strip().upper())
    if category and category.strip() and category.upper() != "ALL":
        bill_query = bill_query.join(Product, BillItem.product_id == Product.id).filter(Product.category == category.strip())

    bill_records = bill_query.order_by(Bill.created_at.desc()).limit(limit).all()

    results = []
    for item, bill in bill_records:
        prod = item.product
        results.append({
            "bill_id": bill.id,
            "bill_number": bill.bill_number,
            "product_id": item.product_id,
            "product_name": prod.name if prod else f"Product #{item.product_id}",
            "category": prod.category if prod else "General",
            "quantity": item.quantity,
            "unit": item.unit,
            "unit_price": item.unit_price,
            "line_total": item.line_total,
            "payment_mode": bill.payment_mode,
            "status": "Completed",
            "created_at": bill.created_at
        })

    # 2. Query active imported historical sales
    include_hist = True
    if payment_mode and payment_mode.strip() and payment_mode.upper() != "ALL":
        pm_upper = payment_mode.strip().upper()
        # Imported records count under generic CASH/IMPORTED or when ALL is selected
        if pm_upper not in ["IMPORTED", "CASH"]:
            include_hist = False

    if include_hist:
        hist_query = (
            db.query(HistoricalSaleRecord)
            .filter(HistoricalSaleRecord.is_active == True)
        )
        if start_date:
            hist_query = hist_query.filter(HistoricalSaleRecord.sale_date >= start_date)
        if end_date:
            hist_query = hist_query.filter(HistoricalSaleRecord.sale_date <= end_date)
        if product_id:
            hist_query = hist_query.filter(HistoricalSaleRecord.product_id == product_id)
        if category and category.strip() and category.upper() != "ALL":
            hist_query = hist_query.join(Product, HistoricalSaleRecord.product_id == Product.id).filter(Product.category == category.strip())

        hist_records = hist_query.order_by(HistoricalSaleRecord.sale_date.desc(), HistoricalSaleRecord.id.desc()).limit(limit).all()

        for h in hist_records:
            prod = h.product
            rec_time = h.sale_time or time(12, 0)
            rec_datetime = datetime.combine(h.sale_date, rec_time)
            results.append({
                "bill_id": h.id,
                "bill_number": h.external_transaction_id or f"HIST-{h.id:05d}",
                "product_id": h.product_id,
                "product_name": prod.name if prod else (h.raw_product_name or f"Product #{h.product_id}"),
                "category": prod.category if prod else "General",
                "quantity": h.quantity,
                "unit": h.unit or (prod.unit if prod else "unit"),
                "unit_price": h.unit_price,
                "line_total": h.total_amount,
                "payment_mode": "IMPORTED",
                "status": "Completed",
                "created_at": rec_datetime
            })

    # Sort merged records by date descending and respect limit
    results.sort(key=lambda r: r["created_at"], reverse=True)
    return results[:limit]
