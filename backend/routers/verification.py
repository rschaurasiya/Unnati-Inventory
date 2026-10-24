"""
Customer Verification & 2FA Router (Step 7 & Step 9)
Provides secure 3-number matching challenge sessions for bills.
For Udhaar transactions, enforces primary account holder 2FA before deducting inventory
and committing to the Udhaar ledger.
"""
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Bill, VerificationSession, Product, Customer, FamilyMember, UdhaarTransaction, ShopProfile
from backend.config import settings
from backend.schemas import (
    CreateVerificationSessionRequest,
    VerificationSessionResponse,
    SubmitVerificationRequest,
    VerificationResultResponse,
    LowStockAlert
)
from backend.services.sales_aggregation import aggregate_sales_for_date

router = APIRouter(prefix="/api/v1/verification", tags=["Customer Verification & 2FA"])


def _format_session_response(session: VerificationSession, bill: Bill, db: Optional[Session] = None) -> VerificationSessionResponse:
    """Helper to convert VerificationSession ORM model to response schema, hiding target_number."""
    now = datetime.utcnow()
    expires_in = max(0, int((session.expires_at - now).total_seconds()))

    # Parse candidate numbers from comma-separated string
    candidates = [int(n.strip()) for n in session.candidate_numbers.split(",") if n.strip().isdigit()]

    # Authoritative customer resolution
    cust = bill.customer
    if not cust and bill.customer_id and db is not None:
        cust = db.query(Customer).filter(Customer.id == bill.customer_id).first()

    customer_name = cust.full_name if cust else None
    buyer_name = bill.family_member.full_name if bill.family_member else customer_name
    notification_msg = None
    if bill.payment_mode == "UDHAAR" and cust:
        buyer_str = buyer_name or "Family member"
        notification_msg = f"{buyer_str} purchased Rs. {bill.total_amount:.2f} on Udhaar from your family account. Confirm matching challenge number."

    cust_code = None
    cust_phone_masked = None
    is_phone_verif = None
    if cust:
        cust_code = getattr(cust, "customer_code", None) or f"C-{cust.id:06d}"
        is_phone_verif = bool(getattr(cust, "is_phone_verified", False))
        if is_phone_verif:
            raw_p = cust.phone
            if raw_p:
                clean_digits = "".join(filter(str.isdigit, raw_p))
                last10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
                if len(last10) >= 4:
                    cust_phone_masked = f"{last10[:2]}******{last10[-2:]}"
                else:
                    cust_phone_masked = last10
        else:
            cust_phone_masked = None

    # Dynamic Shop Name Resolution
    shop = None
    if db is not None:
        try:
            shop = db.query(ShopProfile).first()
        except Exception:
            pass
    shop_name = (shop.shop_name if shop and shop.shop_name else settings.SHOP_NAME).strip()

    channel = getattr(session, "delivery_channel", "SMS")
    is_otp = (session.verification_type == "OTP")
    del_status = getattr(session, "delivery_status", "SIMULATED" if is_otp else "NOT_CONFIGURED")

    if is_otp:
        channel_note = f"{channel} Verification (Simulated/Mock Delivery - Demo Request Prepared)"
        otp_display = session.otp_code or f"{session.target_number:04d}"
        expiry_mins = max(1, expires_in // 60 + (1 if expires_in % 60 else 0))
        delivery_message_preview = (
            f"[SIMULATED {channel} DELIVERY]\n"
            f"{shop_name}: Your 4-digit verification OTP for Udhaar bill {bill.bill_number} "
            f"(Amount: Rs. {bill.total_amount:.2f}) is {otp_display}. "
            f"Valid for {expiry_mins} min(s). Please provide this OTP to the shopkeeper to confirm your Udhaar purchase."
        )
        if bill.payment_mode == "UDHAAR" and cust:
            buyer_str = buyer_name or "Family member"
            notification_msg = f"{buyer_str} requested Rs. {bill.total_amount:.2f} on Udhaar. 4-digit verification OTP prepared via {channel}."
    else:
        channel_note = f"{channel} Verification — Demo/Not Configured"
        delivery_message_preview = (
            f"{shop_name} verification for Udhaar bill {bill.bill_number}.\n\n"
            f"Choose the number shown by the shopkeeper:\n" +
            "\n".join([f"{i+1}. {c}" for i, c in enumerate(candidates)]) +
            f"\n\nReply/confirm the correct number through the supported verification flow."
        )

    demo_otp = None
    if is_otp and (settings.DEBUG or getattr(settings, "APP_ENV", "") == "development"):
        demo_otp = session.otp_code or f"{session.target_number:04d}"

    return VerificationSessionResponse(
        session_id=session.id,
        session_token=session.session_token,
        bill_id=bill.id,
        bill_number=bill.bill_number,
        bill_total=bill.total_amount,
        verification_type=session.verification_type,
        status=session.status,
        challenge_numbers=candidates,
        otp_length=4,
        demo_otp=demo_otp,
        attempts=session.attempts,
        expires_at=session.expires_at,
        expires_in_seconds=expires_in,
        created_at=session.created_at,
        verified_at=session.verified_at,
        payment_mode=bill.payment_mode,
        customer_id=cust.id if cust else bill.customer_id,
        customer_code=cust_code,
        customer_name=customer_name,
        customer_phone_masked=cust_phone_masked,
        is_phone_verified=is_phone_verif,
        family_member_id=bill.family_member_id,
        buyer_name=buyer_name,
        notification_message=notification_msg,
        delivery_channel=channel,
        delivery_status=del_status,
        channel_status_note=channel_note,
        delivery_message_preview=delivery_message_preview
    )


@router.post("/sessions", response_model=VerificationSessionResponse, status_code=status.HTTP_201_CREATED)
def create_verification_session(payload: CreateVerificationSessionRequest, db: Session = Depends(get_db)):
    """
    Creates or regenerates a 3-number matching verification challenge for a bill.
    ENFORCES:
    - If Udhaar bill, primary customer phone number must be verified before sending challenge.
    - Generates 3 distinct 2-digit numbers cryptographically and securely stores the target.
    - Selects communication delivery channel (SMS or WHATSAPP).
    """
    bill = db.query(Bill).filter(Bill.id == payload.bill_id).first()
    if not bill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bill with ID {payload.bill_id} not found."
        )

    if bill.status not in ["COMPLETED", "PENDING_VERIFICATION"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot create verification session for bill in '{bill.status}' status."
        )

    # 5E: Enforce customer phone verification for Udhaar bills before generating/sending 2FA challenge
    if bill.payment_mode == "UDHAAR" and bill.customer:
        if not bill.customer.is_phone_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Customer phone number is not verified. Verify the customer's phone number before using SMS/WhatsApp verification."
            )

    # Check existing session
    existing = db.query(VerificationSession).filter(VerificationSession.bill_id == bill.id).first()
    if existing and existing.status == "VERIFIED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bill '{bill.bill_number}' has already been verified on {existing.verified_at}."
        )

    # Udhaar transactions use OTP verification by default
    is_udhaar = (bill.payment_mode == "UDHAAR")
    verif_type = "OTP" if is_udhaar else (payload.verification_type or "NUMBER_MATCHING")

    secure_rng = secrets.SystemRandom()
    if verif_type == "OTP":
        # Generate cryptographically secure random 4-digit OTP server-side (0000 - 9999)
        otp_int = secrets.randbelow(10000)
        otp_code = f"{otp_int:04d}"
        target_number = otp_int
        # Generate two distractor 4-digit options for candidate list (used by legacy challenge APIs/tests)
        alt1 = (otp_int + secure_rng.randint(100, 999)) % 10000
        alt2 = (otp_int + secure_rng.randint(1001, 8999)) % 10000
        cand_list = [otp_int, alt1, alt2]
        secure_rng.shuffle(cand_list)
        candidate_str = ",".join(str(c) for c in cand_list)
        del_status = "SIMULATED"
    else:
        # Legacy number matching: 3 distinct 2-digit numbers
        challenge_numbers = secure_rng.sample(range(10, 100), 3)
        target_number = secrets.choice(challenge_numbers)
        otp_code = None
        candidate_str = ", ".join(str(n) for n in challenge_numbers)
        del_status = "NOT_CONFIGURED"

    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=payload.expiry_seconds)
    session_token = secrets.token_hex(24)

    channel = payload.delivery_channel if payload.delivery_channel in ["SMS", "WHATSAPP"] else "SMS"

    if existing:
        # Regenerate / reset existing unverified or expired/failed session
        existing.session_token = session_token
        existing.target_number = target_number
        existing.candidate_numbers = candidate_str
        existing.otp_code = otp_code
        existing.verification_type = verif_type
        existing.delivery_channel = channel
        existing.delivery_status = del_status
        existing.status = "PENDING"
        existing.attempts = 0
        existing.created_at = now
        existing.expires_at = expires_at
        existing.verified_at = None
        session = existing
    else:
        session = VerificationSession(
            bill_id=bill.id,
            session_token=session_token,
            target_number=target_number,
            candidate_numbers=candidate_str,
            otp_code=otp_code,
            verification_type=verif_type,
            delivery_channel=channel,
            delivery_status=del_status,
            status="PENDING",
            attempts=0,
            max_attempts=3,
            created_at=now,
            expires_at=expires_at,
            verified_at=None
        )
        db.add(session)

    db.commit()
    db.refresh(session)

    return _format_session_response(session, bill, db)


@router.get("/sessions/{session_id}", response_model=VerificationSessionResponse)
def get_verification_session(session_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the verification session by session ID.
    Checks and marks expiration automatically if elapsed.
    """
    session = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification session with ID {session_id} not found."
        )

    # Check expiration dynamically
    now = datetime.utcnow()
    if session.status == "PENDING" and now > session.expires_at:
        session.status = "EXPIRED"
        db.commit()
        db.refresh(session)

    return _format_session_response(session, session.bill, db)


@router.get("/sessions/token/{session_token}", response_model=VerificationSessionResponse)
def get_verification_session_by_token(session_token: str, db: Session = Depends(get_db)):
    """
    Retrieves verification session by unique cryptographic session token.
    Useful for customer-facing mobile/kiosk screens.
    """
    session = db.query(VerificationSession).filter(VerificationSession.session_token == session_token).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification session not found."
        )

    now = datetime.utcnow()
    if session.status == "PENDING" and now > session.expires_at:
        session.status = "EXPIRED"
        db.commit()
        db.refresh(session)

    return _format_session_response(session, session.bill, db)


@router.get("/bill/{bill_id}", response_model=VerificationSessionResponse)
def get_verification_session_by_bill(bill_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the verification session associated with a specific bill ID.
    """
    session = db.query(VerificationSession).filter(VerificationSession.bill_id == bill_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No verification session found for bill ID {bill_id}."
        )

    now = datetime.utcnow()
    if session.status == "PENDING" and now > session.expires_at:
        session.status = "EXPIRED"
        db.commit()
        db.refresh(session)

    return _format_session_response(session, session.bill, db)


@router.post("/verify", response_model=VerificationResultResponse)
def submit_verification(payload: SubmitVerificationRequest, db: Session = Depends(get_db)):
    """
    Submits the customer's selected number against the active verification challenge.
    Enforces expiration, single-attempt/state validation.
    For Udhaar transactions, atomically deducts product inventory, records an immutable
    Udhaar ledger transaction, updates the customer's credit balance, and marks the bill COMPLETED.
    If verification fails, inventory and balances remain completely untouched!
    """
    if not payload.session_id and not payload.session_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either session_id or session_token must be provided."
        )

    query = db.query(VerificationSession)
    if payload.session_id:
        session = query.filter(VerificationSession.id == payload.session_id).first()
    else:
        session = query.filter(VerificationSession.session_token == payload.session_token).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification session not found."
        )

    bill = session.bill
    if not bill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Linked bill for this session was not found."
        )

    # Check bill/session association if bill_id was provided
    if payload.bill_id and session.bill_id != payload.bill_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Verification session {session.id} does not match bill ID {payload.bill_id}."
        )

    # Check customer binding if customer_id provided
    if payload.customer_id and bill.customer_id != payload.customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification session does not belong to the specified customer."
        )

    now = datetime.utcnow()

    # 1. Check if already verified
    if session.status == "VERIFIED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This verification session has already been completed on {session.verified_at} and cannot be reused."
        )

    # 2. Check if expired
    if session.status == "EXPIRED" or now > session.expires_at:
        session.status = "EXPIRED"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification session has expired. Please ask the shopkeeper to regenerate the challenge."
        )

    # 3. Check if already failed or maximum attempts exceeded
    max_att = getattr(session, "max_attempts", 3)
    if session.status == "FAILED" or session.attempts >= max_att:
        session.status = "FAILED"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum verification attempts exceeded. Session failed. Please regenerate a new challenge."
        )

    # 4. Evaluate matching based on verification_type
    is_otp_session = (session.verification_type == "OTP")
    raw_otp = payload.otp if payload.otp is not None else (payload.otp_code if payload.otp_code is not None else None)

    if is_otp_session:
        if raw_otp is not None:
            entered_code = str(raw_otp).strip()
        elif payload.selected_number is not None:
            entered_code = f"{payload.selected_number:04d}" if payload.selected_number < 10000 else str(payload.selected_number)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="4-digit verification OTP is required."
            )

        if len(entered_code) != 4 or not entered_code.isdigit():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP format. OTP must be exactly 4 numeric digits."
            )

        expected_otp = session.otp_code or f"{session.target_number:04d}"
        is_match = (entered_code == expected_otp)
    else:
        # Legacy number matching
        candidates = [int(n.strip()) for n in session.candidate_numbers.split(",") if n.strip().isdigit()]
        if payload.selected_number not in candidates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Selected number {payload.selected_number} is not one of the displayed challenge options."
            )
        is_match = (payload.selected_number == session.target_number)

    # Increment attempts
    session.attempts += 1

    # 5. Process result
    if is_match:
        low_stock_alerts: List[LowStockAlert] = []
        balance_after: Optional[float] = None

        try:
            # Atomic Udhaar finalization & inventory deduction if bill is pending Udhaar
            if bill.payment_mode == "UDHAAR" and bill.status == "PENDING_VERIFICATION":
                cust = bill.customer
                if not cust or not cust.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Customer account associated with this Udhaar bill is invalid or inactive."
                    )

                # Re-verify credit limit at verification time
                if cust.current_udhaar_balance + bill.total_amount > cust.credit_limit:
                    avail = max(0.0, round(cust.credit_limit - cust.current_udhaar_balance, 2))
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Credit limit exceeded for '{cust.full_name}'. Limit: Rs.{cust.credit_limit:.2f}, "
                            f"Current: Rs.{cust.current_udhaar_balance:.2f}, Bill: Rs.{bill.total_amount:.2f}. "
                            f"Available credit is Rs.{avail:.2f}."
                        )
                    )

                # Atomic stock check and deduction for each line item
                for it in bill.items:
                    prod = it.product
                    if not prod or prod.stock_quantity < it.quantity:
                        prod_name = prod.name if prod else f"ID {it.product_id}"
                        prod_stock = prod.stock_quantity if prod else 0
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Insufficient inventory for '{prod_name}'. Available: {prod_stock}, Required: {it.quantity}."
                        )
                    new_stock = round(prod.stock_quantity - it.quantity, 3)
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

                # Update customer balance
                balance_before = cust.current_udhaar_balance
                balance_after = round(balance_before + bill.total_amount, 2)
                cust.current_udhaar_balance = balance_after

                # Record immutable Udhaar ledger transaction
                buyer_label = bill.family_member.full_name if bill.family_member else cust.full_name
                udhaar_tx = UdhaarTransaction(
                    primary_customer_id=cust.id,
                    family_member_id=bill.family_member_id,
                    bill_id=bill.id,
                    amount=bill.total_amount,
                    transaction_type="DEBIT_PURCHASE",
                    balance_before=balance_before,
                    balance_after=balance_after,
                    verified_by="PRIMARY_2FA",
                    notes=f"Udhaar purchase via Bill {bill.bill_number} ({buyer_label}) (OTP Verified)",
                    created_at=now
                )
                db.add(udhaar_tx)

                # Mark bill as COMPLETED
                bill.status = "COMPLETED"

            session.status = "VERIFIED"
            session.verified_at = now

            # Append audit note to bill
            if is_otp_session:
                verif_channel_str = getattr(session, "delivery_channel", "SMS")
                verification_tag = f"[Customer Verified: 4-digit OTP via {verif_channel_str} on {now.strftime('%Y-%m-%d %H:%M:%S')}]"
            else:
                verification_tag = f"[Customer Verified: 2FA-Match on {now.strftime('%Y-%m-%d %H:%M:%S')}]"

            if bill.notes:
                bill.notes = f"{bill.notes} {verification_tag}".strip()
            else:
                bill.notes = verification_tag

            db.flush()
            if bill.status == "COMPLETED":
                aggregate_sales_for_date(db, bill.created_at.date())

            db.commit()
            try:
                from backend.services.forecasting import invalidate_forecast_cache
                invalidate_forecast_cache()
            except Exception:
                pass
            db.refresh(session)

        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Verification completion failed and was rolled back: {str(exc)}"
            )

        success_msg = (
            f"Customer verification successful! 4-digit OTP verified via {session.delivery_channel}. Udhaar transaction approved and inventory deducted."
            if bill.payment_mode == "UDHAAR"
            else "Customer verification successful! Transaction confirmed."
        )

        return VerificationResultResponse(
            session_id=session.id,
            bill_id=bill.id,
            bill_number=bill.bill_number,
            success=True,
            status="VERIFIED",
            message=success_msg,
            verified_at=session.verified_at,
            payment_mode=bill.payment_mode,
            udhaar_balance_after=balance_after,
            low_stock_alerts=low_stock_alerts
        )
    else:
        is_legacy_submit = (payload.selected_number is not None and payload.otp is None and payload.otp_code is None)
        if is_otp_session and not is_legacy_submit:
            if session.attempts >= max_att:
                session.status = "FAILED"
            else:
                session.status = "PENDING"
        else:
            session.status = "FAILED"

        db.commit()
        db.refresh(session)

        fail_msg = (
            f"Incorrect 4-digit OTP. Customer verification failed. Attempt {session.attempts} of {max_att}."
            if is_otp_session
            else "Incorrect number selected. Customer verification failed. Please regenerate challenge."
        )

        return VerificationResultResponse(
            session_id=session.id,
            bill_id=bill.id,
            bill_number=bill.bill_number,
            success=False,
            status="FAILED",
            message=fail_msg,
            verified_at=None,
            payment_mode=bill.payment_mode,
            udhaar_balance_after=None,
            low_stock_alerts=[]
        )
