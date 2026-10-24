"""
Billing & POS Router (Phase 1: Draft Billing & Bill Finalization)
Connects NLP voice parsing to a real-time POS Draft Bill interface,
and finalizes sales transactions with atomic inventory deduction and idempotency.
"""
import uuid
import time
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Product, Bill, BillItem, Customer, FamilyMember
from backend.schemas import (
    DraftBillRequest, DraftBillRecalculateRequest, DraftBillResponse, DraftBillItem,
    FinalizeBillRequest, FinalizedBillResponse, FinalizedBillItemResponse, LowStockAlert
)
from backend.nlp.parser import VoiceBillingParser
from backend.services.sales_aggregation import aggregate_sales_for_date

router = APIRouter(prefix="/api/v1/billing", tags=["POS Billing Engine"])


def _generate_draft_id() -> str:
    """Generate a clean human-readable temporary draft identifier."""
    return f"DRAFT-{int(time.time()) % 100000:05d}-{uuid.uuid4().hex[:4].upper()}"


@router.post("/draft", response_model=DraftBillResponse, status_code=status.HTTP_200_OK)
def create_draft_bill(payload: DraftBillRequest, db: Session = Depends(get_db)):
    """
    Generate an in-memory Draft Bill from spoken or typed order text.
    Reuses the Step 4 NLP parser. Does NOT mutate database or deduct inventory.
    """
    draft_id = _generate_draft_id()
    draft_items: List[DraftBillItem] = []
    raw_text = payload.text.strip() if payload.text else ""

    if raw_text:
        parser = VoiceBillingParser(db)
        parsed_result = parser.parse(raw_text, language=payload.language or "hinglish")

        for item in parsed_result["items"]:
            draft_items.append(
                DraftBillItem(
                    product_id=item.get("product_id"),
                    product_name=item.get("product_name") or item.get("raw_item_name"),
                    raw_item_name=item.get("raw_item_name"),
                    quantity=item.get("quantity", 1.0),
                    unit=item.get("unit", "piece"),
                    unit_price=item.get("unit_price", 0.0),
                    line_total=item.get("line_total", 0.0),
                    status=item.get("status", "UNMATCHED"),
                    match_status=item.get("match_status", item.get("status", "UNMATCHED")),
                    unmatched_reason=item.get("unmatched_reason")
                )
            )
    elif payload.items:
        draft_items = payload.items

    # Calculate totals
    subtotal = round(sum(i.line_total for i in draft_items if i.status == "MATCHED"), 2)
    tax = 0.0
    total_amount = round(subtotal + tax, 2)
    matched_count = sum(1 for i in draft_items if i.status == "MATCHED")
    unmatched_count = len(draft_items) - matched_count

    return DraftBillResponse(
        draft_id=draft_id,
        raw_text=raw_text,
        items=draft_items,
        subtotal=subtotal,
        tax=tax,
        total_amount=total_amount,
        matched_items_count=matched_count,
        unmatched_items_count=unmatched_count,
        status="DRAFT"
    )


@router.post("/draft/recalculate", response_model=DraftBillResponse, status_code=status.HTTP_200_OK)
def recalculate_draft_bill(payload: DraftBillRecalculateRequest, db: Session = Depends(get_db)):
    """
    Recalculates an in-memory draft bill when the shopkeeper edits quantities,
    removes items, or assigns catalog products to unmatched lines.
    Re-verifies prices against the active database catalog.
    """
    draft_id = _generate_draft_id()
    updated_items: List[DraftBillItem] = []

    for item in payload.items:
        if item.quantity <= 0:
            continue  # Drop items with 0 or negative quantity

        unit_price = item.unit_price
        product_name = item.product_name
        unit = item.unit
        status_val = item.status
        reason = item.unmatched_reason

        # If product_id is provided, verify against catalog
        if item.product_id:
            db_product = db.query(Product).filter(Product.id == item.product_id).first()
            if db_product:
                unit_price = db_product.unit_price
                product_name = db_product.name
                unit = db_product.unit
                status_val = "MATCHED"
                reason = None

        line_total = round(item.quantity * unit_price, 2) if status_val == "MATCHED" else 0.0

        updated_items.append(
            DraftBillItem(
                product_id=item.product_id,
                product_name=product_name,
                raw_item_name=item.raw_item_name,
                quantity=item.quantity,
                unit=unit,
                unit_price=unit_price,
                line_total=line_total,
                status=status_val,
                match_status=status_val,
                unmatched_reason=reason
            )
        )

    subtotal = round(sum(i.line_total for i in updated_items if i.status == "MATCHED"), 2)
    tax = 0.0
    total_amount = round(subtotal + tax, 2)
    matched_count = sum(1 for i in updated_items if i.status == "MATCHED")
    unmatched_count = len(updated_items) - matched_count

    return DraftBillResponse(
        draft_id=draft_id,
        items=updated_items,
        subtotal=subtotal,
        tax=tax,
        total_amount=total_amount,
        matched_items_count=matched_count,
        unmatched_items_count=unmatched_count,
        status="DRAFT"
    )


@router.post("/finalize", response_model=FinalizedBillResponse, status_code=status.HTTP_201_CREATED)
def finalize_bill(payload: FinalizeBillRequest, db: Session = Depends(get_db)):
    """
    Finalizes a validated bill, records permanent Bill & BillItem rows,
    and atomically deducts product stock within a single ACID transaction.
    Guarantees idempotency (repeating same idempotency_key returns existing bill without double-deduction).
    """
    if not payload.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot finalize an empty bill. At least one valid item is required."
        )

    # 1. Idempotency Check
    if payload.idempotency_key:
        idemp_tag = f"idempotency:{payload.idempotency_key.strip()}"
        existing_bill = db.query(Bill).filter(
            Bill.notes.like(f"%{idemp_tag}%"),
            Bill.status == "COMPLETED"
        ).first()

        if existing_bill:
            # Replay existing bill without touching inventory
            bill_items_resp = [
                FinalizedBillItemResponse(
                    product_id=bi.product_id,
                    product_name=bi.product.name if bi.product else "Unknown",
                    quantity=bi.quantity,
                    unit=bi.unit,
                    unit_price=bi.unit_price,
                    line_total=bi.line_total
                )
                for bi in existing_bill.items
            ]
            return FinalizedBillResponse(
                id=existing_bill.id,
                bill_number=existing_bill.bill_number,
                subtotal=existing_bill.subtotal,
                discount=existing_bill.discount,
                tax=existing_bill.tax,
                total_amount=existing_bill.total_amount,
                payment_mode=existing_bill.payment_mode,
                status=existing_bill.status,
                created_at=existing_bill.created_at,
                items=bill_items_resp,
                low_stock_alerts=[],
                is_duplicate_replay=True
            )

    # 2. Udhaar Customer & Family Member Pre-validation (Step 9)
    cust = None
    family_member = None
    buyer_name = None
    notification_msg = None
    is_udhaar = (payload.payment_mode == "UDHAAR")

    if is_udhaar:
        if not payload.customer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Primary customer must be selected for Udhaar (credit) transactions."
            )
        cust = db.query(Customer).filter(Customer.id == payload.customer_id).first()
        if not cust or not cust.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected customer account is invalid or inactive."
            )

        if payload.family_member_id:
            family_member = db.query(FamilyMember).filter(FamilyMember.id == payload.family_member_id).first()
            if not family_member or family_member.primary_customer_id != cust.id or not family_member.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Family member does not belong to customer '{cust.full_name}' or is inactive."
                )

    # 3. Strict Pre-validation of products, quantities, and available inventory
    product_map = {}
    estimated_subtotal = 0.0
    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid quantity {item.quantity} for product ID {item.product_id}. Quantity must be positive."
            )

        prod = db.query(Product).filter(Product.id == item.product_id).first()
        if not prod:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product with ID {item.product_id} does not exist in store catalog."
            )

        # Accumulate requested quantity in case product appears multiple times
        total_requested = product_map.get(prod.id, 0.0) + item.quantity
        if prod.stock_quantity < total_requested:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Insufficient stock for '{prod.name}'. Current stock: {prod.stock_quantity} {prod.unit}, "
                    f"requested: {total_requested} {prod.unit}."
                )
            )
        product_map[prod.id] = total_requested
        estimated_subtotal += round(item.quantity * prod.unit_price, 2)

    estimated_total = round(estimated_subtotal, 2)

    # 4. Credit Limit Checks for Udhaar
    if is_udhaar:

        # A. Primary Holder Credit Limit Check
        if cust.current_udhaar_balance + estimated_total > cust.credit_limit:
            avail = max(0.0, round(cust.credit_limit - cust.current_udhaar_balance, 2))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Credit limit exceeded for '{cust.full_name}'. Limit: Rs.{cust.credit_limit:.2f}, "
                    f"Current Balance: Rs.{cust.current_udhaar_balance:.2f}, Bill Total: Rs.{estimated_total:.2f}. "
                    f"Available credit is only Rs.{avail:.2f}."
                )
            )

        # B. Family Member Spending Limit Check
        if family_member and family_member.allowed_spending_limit is not None:
            if estimated_total > family_member.allowed_spending_limit:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Spending limit exceeded for family member '{family_member.full_name}'. "
                        f"Member Limit: Rs.{family_member.allowed_spending_limit:.2f}, Bill Total: Rs.{estimated_total:.2f}."
                    )
                )

        buyer_name = family_member.full_name if family_member else cust.full_name
        notification_msg = f"{buyer_name} requested Rs. {estimated_total:.2f} on Udhaar from your family account. Confirm matching challenge number."

    # 4. Atomic Database Transaction
    now = datetime.utcnow()
    bill_number = f"BILL-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

    subtotal = 0.0
    discount = 0.0
    tax = 0.0
    bill_items_data: List[FinalizedBillItemResponse] = []
    low_stock_alerts: List[LowStockAlert] = []

    try:
        bill_notes = payload.notes or ""
        if payload.idempotency_key:
            idemp_tag = f"idempotency:{payload.idempotency_key.strip()}"
            bill_notes = f"{bill_notes} [{idemp_tag}]".strip()

        # For Udhaar: Bill is PENDING_VERIFICATION until Primary Holder verifies 2FA
        bill_status = "PENDING_VERIFICATION" if is_udhaar else "COMPLETED"

        bill = Bill(
            bill_number=bill_number,
            customer_id=payload.customer_id,
            family_member_id=payload.family_member_id if is_udhaar else None,
            subtotal=0.0,
            discount=discount,
            tax=tax,
            total_amount=0.0,
            payment_mode=payload.payment_mode,
            status=bill_status,
            notes=bill_notes,
            created_at=now
        )
        db.add(bill)
        db.flush()  # Generate bill.id

        for item in payload.items:
            prod = db.query(Product).filter(Product.id == item.product_id).first()
            unit_price = prod.unit_price
            line_total = round(item.quantity * unit_price, 2)
            subtotal += line_total

            # For CASH and UPI, stock is deducted immediately.
            # For UDHAAR, stock is safely deferred until Primary Holder 2FA verification succeeds!
            if not is_udhaar:
                new_stock = round(prod.stock_quantity - item.quantity, 3)
                prod.stock_quantity = new_stock

                if new_stock <= prod.min_stock_threshold:
                    low_stock_alerts.append(
                        LowStockAlert(
                            product_id=prod.id,
                            product_name=prod.name,
                            current_stock=new_stock,
                            min_stock_threshold=prod.min_stock_threshold,
                            unit=prod.unit
                        )
                    )

            bill_item = BillItem(
                bill_id=bill.id,
                product_id=prod.id,
                quantity=item.quantity,
                unit=prod.unit,
                unit_price=unit_price,
                line_total=line_total
            )
            db.add(bill_item)
            bill_items_data.append(
                FinalizedBillItemResponse(
                    product_id=prod.id,
                    product_name=prod.name,
                    quantity=item.quantity,
                    unit=prod.unit,
                    unit_price=unit_price,
                    line_total=line_total
                )
            )

        total_amount = round(subtotal - discount + tax, 2)
        bill.subtotal = round(subtotal, 2)
        bill.total_amount = total_amount

        db.flush()
        if bill.status == "COMPLETED":
            aggregate_sales_for_date(db, bill.created_at.date())

        # Commit everything in single transaction
        db.commit()
        if bill.status == "COMPLETED":
            try:
                from backend.services.forecasting import invalidate_forecast_cache
                invalidate_forecast_cache()
            except Exception:
                pass
        db.refresh(bill)

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transaction failed and was rolled back: {str(exc)}"
        )

    # Populate customer details for response
    is_phone_verif = bool(getattr(cust, "is_phone_verified", False)) if cust else None
    cust_code = (getattr(cust, "customer_code", None) or f"C-{cust.id:06d}") if cust else None
    cust_phone_masked = None
    if cust and cust.phone and is_phone_verif:
        clean_digits = "".join(filter(str.isdigit, cust.phone))
        last10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
        if len(last10) >= 4:
            cust_phone_masked = f"{last10[:2]}******{last10[-2:]}"
        else:
            cust_phone_masked = last10

    return FinalizedBillResponse(
        id=bill.id,
        bill_number=bill.bill_number,
        subtotal=bill.subtotal,
        discount=bill.discount,
        tax=bill.tax,
        total_amount=bill.total_amount,
        payment_mode=bill.payment_mode,
        status=bill.status,
        created_at=bill.created_at,
        items=bill_items_data,
        low_stock_alerts=low_stock_alerts,
        is_duplicate_replay=False,
        customer_id=cust.id if cust else None,
        customer_code=cust_code,
        customer_name=cust.full_name if cust else None,
        customer_phone_masked=cust_phone_masked,
        is_phone_verified=is_phone_verif,
        family_member_id=family_member.id if family_member else None,
        buyer_name=buyer_name if is_udhaar else None,
        notification_message=notification_msg if is_udhaar else None
    )


@router.get("/bills", response_model=List[FinalizedBillResponse])
def list_completed_bills(limit: int = 20, db: Session = Depends(get_db)):
    """List recently completed transactions."""
    bills = db.query(Bill).filter(Bill.status == "COMPLETED").order_by(Bill.created_at.desc()).limit(limit).all()
    results = []
    for b in bills:
        items_resp = [
            FinalizedBillItemResponse(
                product_id=bi.product_id,
                product_name=bi.product.name if bi.product else "Unknown",
                quantity=bi.quantity,
                unit=bi.unit,
                unit_price=bi.unit_price,
                line_total=bi.line_total
            )
            for bi in b.items
        ]
        cust = b.customer
        results.append(
            FinalizedBillResponse(
                id=b.id,
                bill_number=b.bill_number,
                subtotal=b.subtotal,
                discount=b.discount,
                tax=b.tax,
                total_amount=b.total_amount,
                payment_mode=b.payment_mode,
                status=b.status,
                created_at=b.created_at,
                items=items_resp,
                low_stock_alerts=[],
                is_duplicate_replay=False,
                customer_id=cust.id if cust else None,
                customer_code=getattr(cust, "customer_code", None) or (f"C-{cust.id:06d}" if cust else None),
                customer_name=cust.full_name if cust else None,
                buyer_name=getattr(b, "buyer_name", None)
            )
        )
    return results
