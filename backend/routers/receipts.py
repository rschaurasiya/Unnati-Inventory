"""
Digital Receipt & Delivery Preparation Router (Step 8)
Generates digital receipts for VERIFIED bills and prepares WhatsApp Click-to-Chat and SMS mock deliveries.
"""
import re
import urllib.parse
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models import Bill, VerificationSession, ShopProfile
from backend.schemas import (
    DigitalReceiptResponse,
    ReceiptItemResponse,
    ReceiptDeliveryRequest,
    ReceiptDeliveryResponse,
    WhatsAppDeliveryPreparation,
    SMSDeliveryPreparation
)

router = APIRouter(prefix="/api/v1/receipts", tags=["Digital Receipts & Delivery"])


def _clean_phone_number(raw_phone: Optional[str]) -> Optional[str]:
    """Cleans phone string into standard international format digits without symbols."""
    if not raw_phone:
        return None
    digits = re.sub(r"\D", "", raw_phone)
    if not digits:
        return None
    # If 10 digits (Standard Indian Mobile), prepend 91
    if len(digits) == 10:
        return f"91{digits}"
    return digits


def _get_shop_profile(db: Optional[Session]) -> Optional[ShopProfile]:
    """Retrieves authoritative active shop profile from database."""
    if db is None:
        return None
    try:
        return db.query(ShopProfile).first()
    except Exception:
        return None


import textwrap

LINE_WIDTH = 38

def _generate_text_receipt(
    bill: Bill,
    is_verified: bool,
    verified_at: Optional[datetime],
    shop: Optional[ShopProfile] = None
) -> str:
    """Renders a clean thermal/printable ASCII receipt strictly 38 characters wide."""
    date_str = bill.created_at.strftime("%d-%b-%Y %I:%M %p")

    # Payment and Status lines according to payment mode
    if bill.payment_mode == "CASH":
        payment_line = "Payment:    CASH"
        status_line = "Status:     COMPLETED (CASH SALE)"
    elif bill.payment_mode == "UPI":
        payment_line = "Payment:    UPI / QR"
        status_line = "Status:     COMPLETED (UPI SALE)"
    elif bill.payment_mode == "UDHAAR":
        payment_line = "Payment:    UDHAAR (CREDIT)"
        if is_verified:
            status_line = "Status:     VERIFIED: YES"
        else:
            status_line = "Status:     VERIFIED: NO"
    else:
        payment_line = f"Payment:    {bill.payment_mode}"
        status_line = "Status:     COMPLETED"

    if is_verified and verified_at:
        status_line = "Status:     VERIFIED: YES"

    cust_name = bill.customer.full_name if bill.customer else None
    buyer_name = bill.family_member.full_name if bill.family_member else cust_name

    cust_code = None
    cust_phone_masked = None
    if bill.customer:
        cust_code = getattr(bill.customer, "customer_code", None) or f"C-{bill.customer.id:06d}"
        raw_p = bill.customer.phone
        if raw_p:
            clean_p = "".join(filter(str.isdigit, raw_p))
            if len(clean_p) >= 4:
                cust_phone_masked = f"{clean_p[:2]}******{clean_p[-2:]}"
            else:
                cust_phone_masked = clean_p

    shop_name = (shop.shop_name if shop and shop.shop_name else settings.SHOP_NAME).strip().upper()
    shop_address = (shop.shop_address if shop and shop.shop_address else settings.SHOP_ADDRESS).strip()
    shop_phone = (shop.shop_phone if shop and shop.shop_phone else settings.SHOP_PHONE).strip()
    gstin = shop.gstin.strip().upper() if (shop and shop.gstin) else None
    footer = (shop.invoice_footer if shop and shop.invoice_footer else "THANK YOU FOR SHOPPING!").strip()

    lines = [
        "=" * LINE_WIDTH,
    ]
    # Word-wrap and center store name and address cleanly within 38 characters
    for s_line in textwrap.wrap(shop_name, width=LINE_WIDTH):
        lines.append(s_line.center(LINE_WIDTH))
    for a_line in textwrap.wrap(shop_address, width=LINE_WIDTH):
        lines.append(a_line.center(LINE_WIDTH))
    lines.append(f"Phone: {shop_phone}".center(LINE_WIDTH))
    if gstin:
        lines.append(f"GSTIN: {gstin}".center(LINE_WIDTH))

    lines.extend([
        "=" * LINE_WIDTH,
        f"Bill No:    {bill.bill_number}",
        f"Date:       {date_str}",
        payment_line,
    ])

    if cust_code:
        lines.append(f"Customer ID:{cust_code}")
    if cust_name:
        for c_line in textwrap.wrap(f"Customer:   {cust_name}", width=LINE_WIDTH):
            lines.append(c_line)
    elif bill.payment_mode in ["CASH", "UPI"]:
        lines.append("Customer:   Walk-in Customer")
    if cust_phone_masked:
        lines.append(f"Phone:      {cust_phone_masked}")
    if bill.family_member:
        for b_line in textwrap.wrap(f"Buyer:      {bill.family_member.full_name} ({bill.family_member.relation_type})", width=LINE_WIDTH):
            lines.append(b_line)

    lines.extend([
        status_line,
        "-" * LINE_WIDTH,
        f"{'Product':<18}{'Qty':<6}{'Rate':<7}{'Total':>7}",
        "-" * LINE_WIDTH,
    ])

    for it in bill.items:
        prod_name = (it.product.name if it.product else "Unknown Product").strip()
        qty_val = f"{it.quantity:g}" if hasattr(it.quantity, "is_integer") and it.quantity.is_integer() else f"{it.quantity:.1f}"
        unit_val = (it.unit or "").strip()
        qty_str = f"{qty_val}{unit_val}"[:6]
        rate_str = f"{it.unit_price:.2f}"[:7]
        total_str = f"{it.line_total:.2f}"[:7]

        # Never truncate product names with '..'! Wrap cleanly at LINE_WIDTH
        if len(prod_name) <= 17:
            lines.append(f"{prod_name:<18}{qty_str:<6}{rate_str:<7}{total_str:>7}")
        else:
            for p_line in textwrap.wrap(prod_name, width=LINE_WIDTH):
                lines.append(p_line)
            lines.append(f"{'':<18}{qty_str:<6}{rate_str:<7}{total_str:>7}")

    lines.extend([
        "-" * LINE_WIDTH,
        f"{'Subtotal:':<22}{f'Rs. {bill.subtotal:.2f}':>16}",
        f"{'Tax / VAT:':<22}{f'Rs. {bill.tax:.2f}':>16}",
        f"{'Discount:':<22}{f'-Rs. {bill.discount:.2f}':>16}",
        "=" * LINE_WIDTH,
        f"{'GRAND TOTAL:':<22}{f'Rs. {bill.total_amount:.2f}':>16}",
        "=" * LINE_WIDTH,
    ])

    if bill.payment_mode == "UDHAAR" and bill.customer:
        if bill.udhaar_transaction:
            lines.append(f"{'Udhaar TX:':<22}{f'TX-{bill.udhaar_transaction.id:05d}':>16}")
        lines.append(f"{'Outstanding Balance:':<22}{f'Rs. {bill.customer.current_udhaar_balance:.2f}':>16}")
        lines.append("=" * LINE_WIDTH)

    lines.append("=" * LINE_WIDTH)
    for f_line in textwrap.wrap(footer, width=LINE_WIDTH):
        lines.append(f_line.center(LINE_WIDTH))
    lines.append("Please Visit Again Soon".center(LINE_WIDTH))
    lines.append("=" * LINE_WIDTH)

    return "\n".join(lines)


def _generate_whatsapp_message(bill: Bill, is_verified: bool, shop: Optional[ShopProfile] = None) -> str:
    """Formats an attractive, clean WhatsApp receipt text without emojis."""
    date_str = bill.created_at.strftime("%d-%b-%Y, %I:%M %p")
    if is_verified:
        status_str = "CUSTOMER VERIFIED (2FA Match)"
    elif bill.payment_mode in ["CASH", "UPI"]:
        status_str = f"COMPLETED ({bill.payment_mode} SALE)"
    else:
        status_str = "UNVERIFIED"

    item_lines = []
    for it in bill.items:
        prod_name = it.product.name if it.product else "Item"
        item_lines.append(f"• *{prod_name}*\n  {it.quantity} {it.unit} × ₹{it.unit_price:.2f} = *₹{it.line_total:.2f}*")

    items_block = "\n".join(item_lines)

    cust_info = ""
    if bill.customer:
        cust_info += f"*Account:* {bill.customer.full_name}\n"
    if bill.family_member:
        cust_info += f"*Buyer:* {bill.family_member.full_name} ({bill.family_member.relation_type})\n"

    shop_name = (shop.shop_name if shop and shop.shop_name else settings.SHOP_NAME).strip().upper()
    shop_address = (shop.shop_address if shop and shop.shop_address else settings.SHOP_ADDRESS).strip()
    shop_phone = (shop.shop_phone if shop and shop.shop_phone else settings.SHOP_PHONE).strip()
    footer = (shop.invoice_footer if shop and shop.invoice_footer else "Thank you for your visit!").strip()
    gstin_line = f"*GSTIN:* `{shop.gstin}`\n" if (shop and shop.gstin) else ""

    msg = (
        f"*{shop_name}*\n"
        f"_{shop_address}_\n"
        f"{shop_phone}\n"
        f"{gstin_line}"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Bill No:* `{bill.bill_number}`\n"
        f"*Date:* {date_str}\n"
        f"*Status:* {status_str}\n"
        f"{cust_info}"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"*PURCHASED ITEMS:*\n"
        f"{items_block}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Total Amount:* *₹{bill.total_amount:.2f}*\n"
        f"*Payment Mode:* {bill.payment_mode}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"*{footer}*\n"
        f"_This digital receipt is recorded in store ledger._"
    )
    return msg


def _generate_sms_text(bill: Bill, is_verified: bool = False, shop: Optional[ShopProfile] = None) -> str:
    """Formats a concise 160-character friendly SMS notification."""
    shop_name = (shop.shop_name if shop and shop.shop_name else settings.SHOP_NAME).strip()
    status_tag = "verified & paid" if (is_verified or bill.payment_mode in ["CASH", "UPI"]) else "pending"
    return (
        f"{shop_name}: Bill {bill.bill_number} of Rs.{bill.total_amount:.2f} "
        f"{status_tag} via {bill.payment_mode}. {len(bill.items)} item(s). Thank you! Visit again."
    )


def _build_digital_receipt(bill: Bill, db: Optional[Session] = None) -> DigitalReceiptResponse:
    """Builds the DigitalReceiptResponse schema from Bill model using active ShopProfile."""
    shop = _get_shop_profile(db) if db is not None else None
    verification = bill.verification_session
    is_verified = bool(verification and verification.status == "VERIFIED")
    verified_at = verification.verified_at if verification else None

    # For Cash and UPI, the transaction is immediately verified/completed upon payment
    if bill.payment_mode in ["CASH", "UPI"] and bill.status == "COMPLETED":
        effective_verified = True
        status_val = "CUSTOMER_VERIFIED" if is_verified else "COMPLETED"
    else:
        effective_verified = is_verified
        status_val = "CUSTOMER_VERIFIED" if is_verified else bill.status

    cust_name = bill.customer.full_name if bill.customer else None
    buyer_name = bill.family_member.full_name if bill.family_member else cust_name

    cust_code = None
    cust_phone_masked = None
    outstanding_bal = None
    if bill.customer:
        cust_code = getattr(bill.customer, "customer_code", None) or f"C-{bill.customer.id:06d}"
        outstanding_bal = bill.customer.current_udhaar_balance
        raw_p = bill.customer.phone
        if raw_p:
            clean_p = "".join(filter(str.isdigit, raw_p))
            if len(clean_p) >= 4:
                cust_phone_masked = f"{clean_p[:2]}******{clean_p[-2:]}"
            else:
                cust_phone_masked = clean_p

    items = [
        ReceiptItemResponse(
            product_id=it.product_id,
            product_name=it.product.name if it.product else "Unknown Product",
            quantity=it.quantity,
            unit=it.unit,
            unit_price=it.unit_price,
            line_total=it.line_total
        )
        for it in bill.items
    ]

    formatted_text = _generate_text_receipt(bill, is_verified, verified_at, shop=shop)

    shop_name = (shop.shop_name if shop and shop.shop_name else settings.SHOP_NAME).strip()
    shop_address = (shop.shop_address if shop and shop.shop_address else settings.SHOP_ADDRESS).strip()
    shop_phone = (shop.shop_phone if shop and shop.shop_phone else settings.SHOP_PHONE).strip()
    shop_logo_url = shop.shop_logo_url if shop else None
    gstin = shop.gstin if shop else None
    invoice_footer = shop.invoice_footer if shop and shop.invoice_footer else None
    currency = shop.currency if shop and shop.currency else "₹"

    return DigitalReceiptResponse(
        receipt_id=f"RCP-{bill.bill_number}",
        shop_name=shop_name,
        shop_address=shop_address,
        shop_phone=shop_phone,
        shop_logo_url=shop_logo_url,
        gstin=gstin,
        invoice_footer=invoice_footer,
        currency=currency,
        bill_id=bill.id,
        bill_number=bill.bill_number,
        created_at=bill.created_at,
        payment_mode=bill.payment_mode,
        status=status_val,
        is_verified=effective_verified,
        verified_at=verified_at or (bill.created_at if bill.payment_mode in ["CASH", "UPI"] else None),
        items=items,
        subtotal=bill.subtotal,
        discount=bill.discount,
        tax=bill.tax,
        total_amount=bill.total_amount,
        formatted_text_receipt=formatted_text,
        customer_id=bill.customer_id,
        customer_code=cust_code,
        customer_name=cust_name,
        customer_phone_masked=cust_phone_masked,
        buyer_name=buyer_name,
        outstanding_balance=outstanding_bal,
        udhaar_transaction_id=bill.udhaar_transaction.id if bill.udhaar_transaction else None
    )


@router.get("/{bill_id}", response_model=DigitalReceiptResponse)
def get_digital_receipt(bill_id: int, db: Session = Depends(get_db)):
    """
    Generates and returns the digital receipt for a bill.
    ENFORCES:
    - Normal CASH and UPI transactions complete immediately and do NOT require 2FA.
    - UDHAAR credit transactions strictly require customer 2FA verification.
    """
    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bill with ID {bill_id} not found."
        )

    verification = bill.verification_session
    is_verified = bool(verification and verification.status == "VERIFIED")

    # ENFORCE: Only UDHAAR requires 2FA verification
    if bill.payment_mode == "UDHAAR" and not is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Receipt generation blocked: Udhaar bill '{bill.bill_number}' is not customer-verified. "
                f"Primary account holder must complete 2FA number matching challenge first."
            )
        )

    return _build_digital_receipt(bill, db=db)


@router.post("/delivery-prep", response_model=ReceiptDeliveryResponse)
def prepare_receipt_delivery(payload: ReceiptDeliveryRequest, db: Session = Depends(get_db)):
    """
    Prepares digital receipt delivery through WhatsApp Click-to-Chat URL and SMS mock.
    ENFORCES:
    - Normal CASH and UPI transactions complete immediately and do NOT require 2FA.
    - UDHAAR transactions require 2FA verification before delivery preparation.
    """
    bill = db.query(Bill).filter(Bill.id == payload.bill_id).first()
    if not bill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bill with ID {payload.bill_id} not found."
        )

    verification = bill.verification_session
    is_verified = bool(verification and verification.status == "VERIFIED")

    # ENFORCE: Only UDHAAR requires 2FA verification
    if bill.payment_mode == "UDHAAR" and not is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Receipt delivery blocked: Udhaar bill '{bill.bill_number}' has not been customer-verified. "
                f"Primary account holder must complete 2FA verification before preparing receipt delivery."
            )
        )

    shop = _get_shop_profile(db)
    receipt = _build_digital_receipt(bill, db=db)
    clean_phone = _clean_phone_number(payload.customer_phone)

    # 1. WhatsApp Preparation
    whatsapp_msg = _generate_whatsapp_message(
        bill,
        is_verified=is_verified or bill.payment_mode in ["CASH", "UPI"],
        shop=shop
    )
    encoded_text = urllib.parse.quote(whatsapp_msg)

    if clean_phone:
        whatsapp_url = f"https://wa.me/{clean_phone}?text={encoded_text}"
    else:
        whatsapp_url = f"https://wa.me/?text={encoded_text}"

    whatsapp_prep = WhatsAppDeliveryPreparation(
        customer_phone=payload.customer_phone,
        formatted_message=whatsapp_msg,
        click_to_chat_url=whatsapp_url,
        prepared=True
    )

    # 2. SMS Preparation (Mock Preview - Clearly specifies NOT_CONFIGURED status)
    sms_text = _generate_sms_text(bill, is_verified=is_verified, shop=shop)
    sms_prep = SMSDeliveryPreparation(
        customer_phone=payload.customer_phone,
        sms_text=sms_text,
        char_count=len(sms_text),
        is_mock=True,
        delivery_status="NOT_CONFIGURED",
        note="SMS Preview / Simulation - No external SMS gateway configured."
    )

    return ReceiptDeliveryResponse(
        receipt=receipt,
        whatsapp=whatsapp_prep,
        sms=sms_prep
    )
