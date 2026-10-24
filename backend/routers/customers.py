import io
import csv
import re
import secrets
from typing import List, Optional, Dict, Any, Tuple, Set
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Response
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from backend.database import get_db
from backend.models import Customer, FamilyMember, UdhaarTransaction, Bill, PhoneOTPVerification
from backend.schemas import (
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    CustomerDetailResponse,
    CustomerImportResponse,
    FamilyMemberCreate,
    FamilyMemberResponse,
    UdhaarTransactionResponse,
    UdhaarSettlementRequest,
    UdhaarSettlementResponse,
    FinalizedBillItemResponse,
    PhoneOTPRequest,
    PhoneOTPVerifyRequest,
    PhoneOTPResponse,
    DuplicateCustomerInfo,
    DuplicateGroupResponse,
    DuplicatesListResponse,
    DuplicateCleanupRequest,
    DuplicateCleanupResponse,
)

router = APIRouter(prefix="/api/v1/customers", tags=["Customer Accounts & Udhaar Ledger"])


def _format_customer_response(cust: Customer) -> CustomerResponse:
    """Helper to convert Customer ORM instance to CustomerResponse schema with computed fields."""
    available_credit = max(0.0, round(cust.credit_limit - cust.current_udhaar_balance, 2))
    members = [
        FamilyMemberResponse(
            id=m.id,
            primary_customer_id=m.primary_customer_id,
            full_name=m.full_name,
            relation_type=m.relation_type,
            phone=m.phone,
            allowed_spending_limit=m.allowed_spending_limit,
            is_active=m.is_active,
            is_phone_verified=getattr(m, "is_phone_verified", False),
            phone_verification_status=getattr(m, "phone_verification_status", "UNVERIFIED"),
            created_at=m.created_at
        )
        for m in cust.family_members
    ]

    if getattr(cust, "address_line", None):
        country_name = getattr(cust, "country", "India") or "India"
        addr = f"{cust.address_line}, {cust.city}, {cust.state} - {cust.pincode}, {country_name}"
    else:
        addr = cust.address

    return CustomerResponse(
        id=cust.id,
        customer_code=getattr(cust, "customer_code", None) or f"C-{cust.id:06d}",
        full_name=cust.full_name,
        phone=cust.phone,
        credit_limit=cust.credit_limit,
        current_udhaar_balance=cust.current_udhaar_balance,
        available_credit=available_credit,
        is_active=cust.is_active,
        is_phone_verified=getattr(cust, "is_phone_verified", False),
        phone_verification_status=getattr(cust, "phone_verification_status", "UNVERIFIED"),
        address_line=getattr(cust, "address_line", None),
        city=getattr(cust, "city", None),
        state=getattr(cust, "state", None),
        pincode=getattr(cust, "pincode", None),
        country=getattr(cust, "country", "India"),
        address=addr,
        created_at=cust.created_at,
        family_members=members
    )


def _format_transaction_response(t: UdhaarTransaction) -> UdhaarTransactionResponse:
    """Helper to convert UdhaarTransaction ORM instance to response schema, including bill line items."""
    items_list: List[FinalizedBillItemResponse] = []
    if t.bill and t.bill.items:
        for bi in t.bill.items:
            items_list.append(
                FinalizedBillItemResponse(
                    product_id=bi.product_id,
                    product_name=bi.product.name if bi.product else "Unknown Product",
                    quantity=bi.quantity,
                    unit=bi.unit,
                    unit_price=bi.unit_price,
                    line_total=bi.line_total
                )
            )

    cust_code = None
    if t.primary_customer:
        cust_code = getattr(t.primary_customer, "customer_code", None) or f"C-{t.primary_customer.id:06d}"

    return UdhaarTransactionResponse(
        id=t.id,
        customer_code=cust_code,
        primary_customer_id=t.primary_customer_id,
        primary_customer_name=t.primary_customer.full_name if t.primary_customer else None,
        family_member_id=t.family_member_id,
        family_member_name=t.family_member.full_name if t.family_member else None,
        bill_id=t.bill_id,
        bill_number=t.bill.bill_number if t.bill else None,
        amount=t.amount,
        transaction_type=t.transaction_type,
        balance_before=t.balance_before,
        balance_after=t.balance_after,
        verified_by=t.verified_by,
        notes=t.notes,
        created_at=t.created_at,
        items=items_list
    )


def resequence_customer_codes(db: Session):
    """
    Re-sequences customer_code for all active customers in strictly numerical gapless order
    starting from C-000001 (ordered alphabetically by full_name, id ASC).
    Uses a two-phase update to prevent SQLite UNIQUE constraint collisions.
    Clears customer_code on inactive accounts.
    """
    # 1. Clear codes on inactive accounts
    inactive = db.query(Customer).filter(Customer.is_active == False).all()
    for cust in inactive:
        cust.customer_code = None
    db.flush()

    # 2. Fetch all active customers ordered deterministically by full_name ASC, id ASC
    active_customers = (
        db.query(Customer)
        .filter(Customer.is_active == True)
        .order_by(func.lower(Customer.full_name).asc(), Customer.id.asc())
        .all()
    )

    # Phase 1: Temporary codes to avoid collisions
    for cust in active_customers:
        cust.customer_code = f"TMP-{cust.id}"
    db.flush()

    # Phase 2: Assign gapless C-00XXXX codes
    for idx, cust in enumerate(active_customers, start=1):
        cust.customer_code = f"C-{idx:06d}"
    db.flush()


@router.get("", response_model=List[CustomerResponse])
def list_customers(
    query: Optional[str] = Query(None, description="Search term matching customer name, phone, or customer ID"),
    active_only: bool = Query(True, description="Filter only active customers"),
    db: Session = Depends(get_db)
):
    """
    Lists all primary customers with real-time credit limit, current Udhaar balance, and family members.
    Supports searching by name, phone, and Customer ID (e.g. C-000001).
    Orders active accounts alphabetically and sequentially by Customer ID.
    """
    q = db.query(Customer)
    if active_only:
        q = q.filter(Customer.is_active == True)

    if query:
        search_term = f"%{query.strip().lower()}%"
        q = q.filter(
            or_(
                func.lower(Customer.full_name).like(search_term),
                Customer.phone.like(f"%{query.strip()}%"),
                func.lower(Customer.customer_code).like(search_term)
            )
        )

    customers = q.order_by(func.lower(Customer.full_name).asc(), Customer.id.asc()).all()
    return [_format_customer_response(c) for c in customers]


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    """
    Creates a new primary account holder with mandatory structured address and sequential Customer ID.
    """
    existing = db.query(Customer).filter(Customer.phone == payload.phone.strip()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Customer with phone '{payload.phone}' already exists ({existing.full_name})."
        )

    addr_str = payload.address
    if not addr_str:
        addr_str = f"{payload.address_line.strip()}, {payload.city.strip()}, {payload.state.strip()} - {payload.pincode.strip()}, {payload.country.strip()}"

    customer = Customer(
        full_name=payload.full_name.strip(),
        phone=payload.phone.strip(),
        credit_limit=payload.credit_limit,
        current_udhaar_balance=0.0,
        address_line=payload.address_line.strip(),
        city=payload.city.strip(),
        state=payload.state.strip(),
        pincode=payload.pincode.strip(),
        country=payload.country.strip(),
        address=addr_str,
        is_active=True,
        is_phone_verified=payload.is_phone_verified,
        phone_verification_status="VERIFIED" if payload.is_phone_verified else "UNVERIFIED"
    )
    db.add(customer)
    db.flush()

    # Generate sequential permanent Customer ID via gapless resequencing
    resequence_customer_codes(db)
    db.commit()
    db.refresh(customer)

    return _format_customer_response(customer)


# ==============================================================================
# Import Udhaar Customers Pipeline (CSV / Excel .xlsx / .xls)
# ==============================================================================

@router.get("/sample-template", summary="Download Sample Template for Udhaar Customer Import")
def download_sample_template():
    """
    Returns a downloadable CSV template with required column headers and sample data rows.
    Headers: Customer Name, Phone Number, Pending Balance, Address
    """
    csv_content = (
        "Customer Name,Phone Number,Pending Balance,Address\n"
        "Ramesh Kumar,9876543211,1500,Shop 12 Main Market\n"
        "Sunita Sharma,9876543212,0,House 45 Gandhi Nagar\n"
        "Amit Patel,9876543213,2500,Sector 14 Chandigarh\n"
        "Pooja Verma,9876543214,750,Model Town Delhi\n"
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="udhaar_customers_template.csv"'
        }
    )


@router.post("/import", response_model=CustomerImportResponse, status_code=status.HTTP_200_OK, summary="Import Udhaar Customers via CSV / Excel")
async def import_customers(
    file: UploadFile = File(..., description="CSV or Excel file (.xlsx, .xls) containing customer records"),
    db: Session = Depends(get_db)
):
    """
    Migrates and bulk imports existing customer accounts and credit ledgers into the shopkeeper's isolated store database.
    - Parses CSV (built-in csv module) or Excel (pandas).
    - Validates required columns (Customer Name, Phone Number, Pending Balance).
    - Enforces 10-digit phone number validation and non-negative pending balances.
    - Skips duplicate phone numbers (both sheet-level and DB-level).
    - Assigns sequential C-00XXXX customer IDs.
    - Generates opening balance UdhaarTransaction entries for pending_balance > 0.
    - Commits all records atomically within a single transaction; rolls back on failure.
    """
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file uploaded or filename is missing."
        )

    filename_lower = file.filename.lower()
    allowed_exts = {".csv", ".xlsx", ".xls"}
    if not any(filename_lower.endswith(ext) for ext in allowed_exts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format for '{file.filename}'. Allowed formats: .csv, .xlsx, .xls"
        )

    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to read uploaded file: {str(e)}"
        )

    if not content or len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty (0 bytes)."
        )

    # 10 MB limit check
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The uploaded file exceeds the maximum 10 MB size limit."
        )

    raw_rows: List[Dict[str, Any]] = []

    try:
        if filename_lower.endswith(".csv"):
            # Attempt decoding utf-8-sig (handles Excel UTF-8 BOM), utf-8, latin1, cp1252
            decoded_text = None
            for encoding in ("utf-8-sig", "utf-8", "latin1", "cp1252"):
                try:
                    decoded_text = content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            if decoded_text is None:
                raise ValueError("Could not decode CSV file. Please ensure it is saved with UTF-8 encoding.")

            # Sniff delimiter
            sample = decoded_text[:2048]
            delimiter = ","
            try:
                sniffer = csv.Sniffer()
                dialect = sniffer.sniff(sample, delimiters=",;\t|")
                delimiter = dialect.delimiter
            except Exception:
                delimiter = ","

            reader = csv.DictReader(io.StringIO(decoded_text), delimiter=delimiter)
            if not reader.fieldnames:
                raise ValueError("CSV file has no header row.")
            raw_rows = list(reader)
        else:
            # Excel .xlsx or .xls via pandas
            df = pd.read_excel(io.BytesIO(content))
            if df.empty and len(df.columns) == 0:
                raise ValueError("Excel file has no data or columns.")
            df.columns = [str(col).strip() for col in df.columns]
            raw_rows = df.fillna("").to_dict(orient="records")

    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file format: {str(ve)}"
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error parsing file '{file.filename}': {str(exc)}. Please check file integrity."
        )

    if not raw_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file contains no data rows to import."
        )

    # Column detection & mapping
    sample_row = raw_rows[0]
    keys = list(sample_row.keys())

    def normalize_header(h: Any) -> str:
        s = str(h or "").strip().lower()
        return re.sub(r"[\s\-_]+", "_", s)

    norm_map = {normalize_header(k): k for k in keys}

    def find_col(candidates: List[str]) -> Optional[str]:
        for c in candidates:
            if c in norm_map:
                return norm_map[c]
        for norm_k, orig_k in norm_map.items():
            if any(c in norm_k for c in candidates):
                return orig_k
        return None

    name_col = find_col(["customer_name", "full_name", "name", "customer", "customername", "khatedar"])
    phone_col = find_col(["phone_number", "phone", "mobile", "mobile_number", "contact", "phonenumber", "mob"])
    balance_col = find_col(["pending_balance", "udhaar_balance", "opening_balance", "balance", "udhaar", "pendingbalance", "amount", "due_amount"])
    address_col = find_col(["address", "address_line", "street", "location", "city", "addr"])
    limit_col = find_col(["credit_limit", "limit", "max_limit"])

    missing_cols = []
    if not name_col:
        missing_cols.append("Customer Name")
    if not phone_col:
        missing_cols.append("Phone Number")
    if not balance_col:
        missing_cols.append("Pending Balance")

    if missing_cols:
        found_cols_str = ", ".join(f"'{k}'" for k in keys) if keys else "None"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Missing required columns in file: {', '.join(missing_cols)}. "
                f"Required column headers are: 'Customer Name', 'Phone Number', 'Pending Balance' (and optional 'Address'). "
                f"Found columns: [{found_cols_str}]."
            )
        )

    # Pre-fetch existing customer phone numbers in isolated DB
    existing_phone_records = db.query(Customer.phone).all()
    existing_phones: Set[str] = {p[0].strip() for p in existing_phone_records if p[0]}

    total_processed = 0
    skipped_duplicates = 0
    errors: List[str] = []
    seen_phones_in_batch: Set[str] = set()

    # Staged list for atomic insertion: (Customer, pending_balance, row_number)
    staged_customers: List[Tuple[Customer, float, int]] = []

    for idx, row in enumerate(raw_rows, start=2):  # row 1 is header
        total_processed += 1

        raw_name = row.get(name_col)
        name_str = str(raw_name or "").strip()
        if not name_str or name_str.lower() in ("nan", "none", "null"):
            errors.append(f"Row {idx}: Customer Name is missing or empty.")
            continue

        raw_phone = row.get(phone_col)
        phone_digits = re.sub(r"\D", "", str(raw_phone or "").strip())
        # If prefixed with 91 (India) and 12 digits, strip country code
        if len(phone_digits) == 12 and phone_digits.startswith("91"):
            phone_digits = phone_digits[2:]
        # If prefixed with 0 and 11 digits, strip leading 0
        elif len(phone_digits) == 11 and phone_digits.startswith("0"):
            phone_digits = phone_digits[1:]

        if len(phone_digits) != 10:
            errors.append(f"Row {idx} ({name_str}): Invalid phone number '{raw_phone}'. Must be exactly 10 digits.")
            continue

        # Duplicate check: DB check and sheet-level check
        if phone_digits in existing_phones:
            skipped_duplicates += 1
            errors.append(f"Row {idx} ({name_str}): Phone '{phone_digits}' already exists in store customer ledger (Duplicate skipped).")
            continue

        if phone_digits in seen_phones_in_batch:
            skipped_duplicates += 1
            errors.append(f"Row {idx} ({name_str}): Phone '{phone_digits}' is duplicated within this file (Duplicate skipped).")
            continue

        seen_phones_in_batch.add(phone_digits)

        # Pending balance parsing
        raw_bal = row.get(balance_col)
        pending_balance = 0.0
        if raw_bal is not None and str(raw_bal).strip() != "" and str(raw_bal).strip().lower() not in ("nan", "none", "null"):
            bal_str = str(raw_bal).replace(",", "").replace("₹", "").replace("$", "").replace("Rs.", "").replace("rs.", "").strip()
            try:
                pending_balance = round(float(bal_str), 2)
                if pending_balance < 0:
                    errors.append(f"Row {idx} ({name_str}): Pending balance cannot be negative (got '{bal_str}').")
                    continue
            except (ValueError, TypeError):
                errors.append(f"Row {idx} ({name_str}): Invalid pending balance '{raw_bal}'. Must be a valid numeric amount.")
                continue

        # Address parsing
        raw_addr = row.get(address_col) if address_col else ""
        addr_str = str(raw_addr or "").strip()
        if addr_str.lower() in ("nan", "none", "null"):
            addr_str = ""
        address_final = addr_str if addr_str else "Main Market"

        # Credit limit
        raw_lim = row.get(limit_col) if limit_col else None
        custom_limit = None
        if raw_lim is not None and str(raw_lim).strip() != "" and str(raw_lim).strip().lower() not in ("nan", "none", "null"):
            try:
                parsed_lim = float(str(raw_lim).replace(",", "").replace("₹", "").strip())
                if parsed_lim >= pending_balance:
                    custom_limit = parsed_lim
            except Exception:
                pass

        credit_limit = custom_limit if custom_limit is not None else max(3000.0, round(pending_balance * 1.5, 2))

        customer = Customer(
            full_name=name_str,
            phone=phone_digits,
            credit_limit=credit_limit,
            current_udhaar_balance=pending_balance,
            address_line=address_final[:255],
            city="Local",
            state="Local",
            pincode="",
            country="India",
            address=address_final[:255],
            is_active=True,
            is_phone_verified=True,
            phone_verification_status="VERIFIED",
            created_at=datetime.utcnow()
        )
        staged_customers.append((customer, pending_balance, idx))

    successfully_added = 0

    if staged_customers:
        try:
            # 1. Add customers
            for cust, bal, r_idx in staged_customers:
                db.add(cust)
            db.flush()

            # 2. Add opening balance ledger transactions for pending_balance > 0
            for cust, bal, r_idx in staged_customers:
                if bal > 0:
                    tx = UdhaarTransaction(
                        primary_customer_id=cust.id,
                        family_member_id=None,
                        bill_id=None,
                        amount=bal,
                        transaction_type="DEBIT_PURCHASE",
                        balance_before=0.0,
                        balance_after=bal,
                        verified_by="OPENING_BALANCE_IMPORT",
                        notes="Opening Balance from Import",
                        created_at=datetime.utcnow()
                    )
                    db.add(tx)

            # 3. Gapless resequencing of C-00XXXX IDs
            resequence_customer_codes(db)

            # 4. Commit atomic transaction
            db.commit()
            successfully_added = len(staged_customers)

        except Exception as db_exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database transaction error during customer import: {str(db_exc)}"
            )

    return CustomerImportResponse(
        status="success",
        total_processed=total_processed,
        successfully_added=successfully_added,
        skipped_duplicates=skipped_duplicates,
        errors=errors
    )


@router.get("/charts", status_code=status.HTTP_200_OK)
def get_customer_udhaar_charts(
    days: int = Query(30, ge=1, le=365, description="Period window for credit vs collections"),
    db: Session = Depends(get_db)
):
    """
    Returns aggregated series for Udhaar & Customer visualizations (Phase 2):
    1. Highest Outstanding Balances (Top 10 indebted customers with masked phones for privacy)
    2. Credit vs Collections (Grouped time series comparing credit issued vs debt settled)
    3. Outstanding Balance Status
    """
    # 1. Highest Outstanding Balances (Sensitive: restricted to authorized session, phone masked)
    top_custs = (
        db.query(Customer)
        .filter(Customer.is_active == True, Customer.current_udhaar_balance > 0)
        .order_by(Customer.current_udhaar_balance.desc())
        .limit(10)
        .all()
    )
    highest_outstanding = []
    for c in top_custs:
        raw_ph = c.phone or ""
        masked_ph = f"{raw_ph[:5]}****{raw_ph[-1]}" if len(raw_ph) >= 6 else "****"
        highest_outstanding.append({
            "id": c.id,
            "name": c.full_name,
            "phone_masked": masked_ph,
            "balance": round(c.current_udhaar_balance, 2),
            "credit_limit": round(c.credit_limit, 2)
        })

    # 2. Credit vs Collections
    today = datetime.utcnow().date()
    d_start = today - timedelta(days=days - 1)
    d_end = today
    dt_start = datetime.combine(d_start, datetime.min.time())
    dt_end = datetime.combine(d_end, datetime.max.time())

    txns = (
        db.query(UdhaarTransaction)
        .filter(
            UdhaarTransaction.created_at >= dt_start,
            UdhaarTransaction.created_at <= dt_end
        )
        .order_by(UdhaarTransaction.created_at.asc())
        .all()
    )

    # Date mapping
    date_map = {}
    curr = d_start
    while curr <= d_end:
        date_map[curr] = {"credit_added": 0.0, "collections": 0.0}
        curr += timedelta(days=1)

    total_credit_added = 0.0
    total_collections = 0.0
    for t in txns:
        t_date = t.created_at.date()
        amt = round(float(t.amount or 0.0), 2)
        if t_date in date_map:
            if t.transaction_type == "DEBIT_PURCHASE":
                date_map[t_date]["credit_added"] += amt
                total_credit_added += amt
            elif t.transaction_type == "CREDIT_PAYMENT":
                date_map[t_date]["collections"] += amt
                total_collections += amt

    credit_vs_collections_series = []
    for d, info in sorted(date_map.items()):
        credit_vs_collections_series.append({
            "date": d.isoformat(),
            "label": d.strftime("%d %b"),
            "credit_added": round(info["credit_added"], 2),
            "collections": round(info["collections"], 2)
        })

    total_outstanding_sum = (
        db.query(func.sum(Customer.current_udhaar_balance))
        .filter(Customer.is_active == True)
        .scalar()
    ) or 0.0

    indebted_count = (
        db.query(Customer)
        .filter(Customer.is_active == True, Customer.current_udhaar_balance > 0)
        .count()
    )

    return {
        "days": days,
        "start_date": d_start.isoformat(),
        "end_date": d_end.isoformat(),
        "total_outstanding_balance": round(float(total_outstanding_sum), 2),
        "customers_with_balance_count": indebted_count,
        "period_credit_added": round(total_credit_added, 2),
        "period_collections": round(total_collections, 2),
        "highest_outstanding": highest_outstanding,
        "credit_vs_collections": credit_vs_collections_series,
        "historical_trend_supported": False,
        "historical_trend_disclosure": "Historical balance trend reconstruction is not stored as a distinct point-in-time snapshot. Real-time outstanding balances and period transactions are displayed."
    }


@router.get("/{customer_id}", response_model=CustomerDetailResponse)
def get_customer_details(customer_id: int, db: Session = Depends(get_db)):
    """
    Retrieves full customer account profile, family members, and complete Udhaar ledger transactions with line items.
    """
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if not cust:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer with ID {customer_id} not found."
        )

    base_resp = _format_customer_response(cust)
    transactions = (
        db.query(UdhaarTransaction)
        .filter(UdhaarTransaction.primary_customer_id == customer_id)
        .order_by(UdhaarTransaction.created_at.desc(), UdhaarTransaction.id.desc())
        .all()
    )

    return CustomerDetailResponse(
        **base_resp.model_dump(),
        transactions=[_format_transaction_response(t) for t in transactions]
    )


@router.put("/{customer_id}", response_model=CustomerResponse)
@router.patch("/{customer_id}", response_model=CustomerResponse)
def update_customer(customer_id: int, payload: CustomerUpdate, db: Session = Depends(get_db)):
    """
    Updates customer details or adjusts credit limit and structured address.
    """
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if not cust:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer with ID {customer_id} not found."
        )

    if payload.full_name is not None:
        cust.full_name = payload.full_name.strip()
    if payload.phone is not None:
        dup = db.query(Customer).filter(Customer.phone == payload.phone.strip(), Customer.id != customer_id).first()
        if dup:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Phone number '{payload.phone}' already in use by {dup.full_name}."
            )
        cust.phone = payload.phone.strip()
    if payload.credit_limit is not None:
        cust.credit_limit = payload.credit_limit
    if payload.address_line is not None:
        cust.address_line = payload.address_line.strip()
    if payload.city is not None:
        cust.city = payload.city.strip()
    if payload.state is not None:
        cust.state = payload.state.strip()
    if payload.pincode is not None:
        cust.pincode = payload.pincode.strip()
    if payload.country is not None:
        cust.country = payload.country.strip()
    if payload.address is not None:
        cust.address = payload.address.strip()
    elif any(x is not None for x in [payload.address_line, payload.city, payload.state, payload.pincode, payload.country]):
        cust.address = f"{cust.address_line or ''}, {cust.city or ''}, {cust.state or ''} - {cust.pincode or ''}, {cust.country or 'India'}"

    if payload.is_active is not None:
        cust.is_active = payload.is_active

    db.commit()
    db.refresh(cust)

    return _format_customer_response(cust)


@router.post("/{customer_id}/family-members", response_model=FamilyMemberResponse, status_code=status.HTTP_201_CREATED)
def add_family_member(customer_id: int, payload: FamilyMemberCreate, db: Session = Depends(get_db)):
    """
    Adds an authorized family member linked to the primary account.
    """
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if not cust:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Primary customer with ID {customer_id} not found."
        )

    # Determine initial phone verification status
    is_verified = False
    verif_status = "UNVERIFIED"
    if not payload.phone:
        # If no personal phone provided, inherit primary customer's phone verification
        if cust.is_phone_verified:
            is_verified = True
            verif_status = "INHERITED"

    member = FamilyMember(
        primary_customer_id=cust.id,
        full_name=payload.full_name.strip(),
        relation_type=payload.relation_type.strip(),
        phone=payload.phone.strip() if payload.phone else None,
        allowed_spending_limit=payload.allowed_spending_limit,
        is_active=True,
        is_phone_verified=is_verified,
        phone_verification_status=verif_status
    )
    db.add(member)
    db.commit()
    db.refresh(member)

    return FamilyMemberResponse(
        id=member.id,
        primary_customer_id=member.primary_customer_id,
        full_name=member.full_name,
        relation_type=member.relation_type,
        phone=member.phone,
        allowed_spending_limit=member.allowed_spending_limit,
        is_active=member.is_active,
        is_phone_verified=member.is_phone_verified,
        phone_verification_status=member.phone_verification_status,
        created_at=member.created_at
    )


@router.delete("/{customer_id}/family-members/{member_id}", status_code=status.HTTP_200_OK)
def remove_family_member(customer_id: int, member_id: int, db: Session = Depends(get_db)):
    """
    Deactivates/removes a family member from the primary account.
    Enforces relational integrity: prevents cross-account deletion.
    FINANCIAL SAFETY RULE:
    If historical financial records exist (Bills or Udhaar ledger transactions),
    uses soft deactivation (is_active = False) so historical records, receipts,
    and audit trails remain intact while preventing future Udhaar purchases.
    If the member has never participated in any transaction, hard deletion is safe and allowed.
    """
    member = db.query(FamilyMember).filter(FamilyMember.id == member_id).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Family member with ID {member_id} not found."
        )

    if member.primary_customer_id != customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Family member '{member.full_name}' does not belong to customer ID {customer_id}."
        )

    has_history = (
        db.query(UdhaarTransaction).filter(UdhaarTransaction.family_member_id == member_id).first() is not None or
        db.query(Bill).filter(Bill.family_member_id == member_id).first() is not None
    )

    if has_history:
        member.is_active = False
        db.commit()
        return {
            "success": True,
            "action": "DEACTIVATED",
            "message": f"Family member '{member.full_name}' has historical transactions and was safely deactivated. Historical records preserved."
        }
    else:
        db.delete(member)
        db.commit()
        return {
            "success": True,
            "action": "DELETED",
            "message": f"Family member '{member.full_name}' had no historical transactions and was safely removed."
        }


@router.delete("/{customer_id}", status_code=status.HTTP_200_OK)
def delete_customer(customer_id: int, hard_delete: bool = Query(False), db: Session = Depends(get_db)):
    """
    Controlled deletion/deactivation of an Udhaar customer account.
    Enforces:
    1. Outstanding Udhaar balance must be exactly zero.
       If balance > 0: Strictly rejected with HTTP 400.
    2. If balance == 0: Soft deactivates account and linked family members,
       preserving all historical bills, payments, and immutable ledger transactions.
       If hard_delete=True: Permanently deletes record.
    3. Automatically re-sequences remaining active Customer IDs (C-00XXXX) gaplessly.
    """
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if not cust:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer with ID {customer_id} not found."
        )

    if cust.current_udhaar_balance > 0.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Account cannot be deleted because outstanding Udhaar remains (Rs. {cust.current_udhaar_balance:.2f}). "
                f"Please settle outstanding balance before deleting the account."
            )
        )

    name = cust.full_name
    if hard_delete:
        db.delete(cust)
    else:
        cust.is_active = False
        cust.customer_code = None
        for m in cust.family_members:
            m.is_active = False

    db.flush()
    resequence_customer_codes(db)
    db.commit()

    return {
        "success": True,
        "message": f"Customer account '{name}' successfully deleted. Remaining customer accounts re-sequenced.",
        "deleted_id": customer_id
    }


# ==============================================================================
# Duplicate Customer Cleanup
# ==============================================================================


def _build_duplicate_customer_info(cust: Customer, db: Session) -> DuplicateCustomerInfo:
    """Build a DuplicateCustomerInfo DTO, checking for bills and udhaar history."""
    has_bills = db.query(Bill).filter(Bill.customer_id == cust.id).first() is not None
    has_udhaar = db.query(UdhaarTransaction).filter(UdhaarTransaction.primary_customer_id == cust.id).first() is not None
    return DuplicateCustomerInfo(
        id=cust.id,
        customer_code=getattr(cust, "customer_code", None) or f"C-{cust.id:06d}",
        full_name=cust.full_name,
        phone=cust.phone,
        credit_limit=cust.credit_limit,
        current_udhaar_balance=cust.current_udhaar_balance,
        is_active=cust.is_active,
        is_phone_verified=getattr(cust, "is_phone_verified", False),
        has_bills=has_bills,
        has_udhaar_transactions=has_udhaar,
        created_at=cust.created_at,
    )


@router.get("/duplicates", response_model=DuplicatesListResponse)
def get_duplicate_customers(db: Session = Depends(get_db)):
    """
    Scans all customer accounts for duplicate full names (case-insensitive).

    For each duplicate group the oldest record (lowest ID) is designated as
    the canonical account to keep.  All newer accounts in the group are then
    individually assessed:
      - **Safe to delete** – zero outstanding udhaar balance, no bills, and
        no udhaar ledger transactions.
      - **Unsafe to delete** – has a positive balance, or historical records;
        flagged for manual review only.

    Returns full group metadata so the frontend can show a rich preview before
    any deletion is committed.
    """
    # Find all lower-cased names that appear more than once
    dup_names_q = (
        db.query(func.lower(Customer.full_name).label("lower_name"))
        .group_by(func.lower(Customer.full_name))
        .having(func.count(Customer.id) > 1)
        .all()
    )

    groups: list[DuplicateGroupResponse] = []
    total_accounts = 0
    total_safe = 0

    for row in dup_names_q:
        lower_name = row.lower_name
        members_orm = (
            db.query(Customer)
            .filter(func.lower(Customer.full_name) == lower_name)
            .order_by(Customer.id.asc())
            .all()
        )

        keep_id = members_orm[0].id  # oldest = canonical
        safe_ids: list[int] = []
        members_info: list[DuplicateCustomerInfo] = []

        for cust in members_orm:
            info = _build_duplicate_customer_info(cust, db)
            members_info.append(info)

            if cust.id == keep_id:
                continue  # never delete the oldest record

            is_safe = (
                cust.current_udhaar_balance == 0.0
                and not info.has_bills
                and not info.has_udhaar_transactions
            )
            if is_safe:
                safe_ids.append(cust.id)

        groups.append(DuplicateGroupResponse(
            duplicate_name=members_orm[0].full_name,
            count=len(members_orm),
            safe_to_delete_ids=safe_ids,
            keep_id=keep_id,
            members=members_info,
        ))
        total_accounts += len(members_orm)
        total_safe += len(safe_ids)

    return DuplicatesListResponse(
        total_duplicate_groups=len(groups),
        total_duplicate_accounts=total_accounts,
        safe_to_delete_count=total_safe,
        groups=groups,
    )


@router.post("/bulk-delete-duplicates", response_model=DuplicateCleanupResponse)
def bulk_delete_duplicate_customers(
    payload: DuplicateCleanupRequest,
    db: Session = Depends(get_db)
):
    """
    Hard-deletes safe duplicate customer accounts in bulk.

    Safety rules enforced for **every** ID supplied (or auto-discovered):
      1. Customer must have zero outstanding udhaar balance.
      2. Customer must have no linked Bills.
      3. Customer must have no Udhaar ledger transactions.
      4. The oldest account in each duplicate group is never deleted
         (protected as the canonical account).

    If *dry_run* is ``true``, the endpoint performs all safety checks and
    returns what *would* be deleted without touching the database.
    """
    # ---- 1. Gather the universe of candidate IDs ----
    if payload.customer_ids:
        # Caller explicitly listed which IDs to delete
        candidate_ids = list(set(payload.customer_ids))
    else:
        # Auto-discover all safe-to-delete duplicates
        dup_names_q = (
            db.query(func.lower(Customer.full_name).label("lower_name"))
            .group_by(func.lower(Customer.full_name))
            .having(func.count(Customer.id) > 1)
            .all()
        )
        candidate_ids = []
        for row in dup_names_q:
            members = (
                db.query(Customer.id)
                .filter(func.lower(Customer.full_name) == row.lower_name)
                .order_by(Customer.id.asc())
                .all()
            )
            # Skip the first (oldest) record, collect the rest
            candidate_ids.extend(m.id for m in members[1:])

    # ---- 2. Evaluate each candidate against safety rules ----
    deleted_ids: list[int] = []
    skipped_ids: list[int] = []
    skipped_reasons: dict[str, str] = {}

    for cust_id in candidate_ids:
        cust = db.query(Customer).filter(Customer.id == cust_id).first()
        if not cust:
            skipped_ids.append(cust_id)
            skipped_reasons[str(cust_id)] = "Customer not found."
            continue

        # Check balance
        if cust.current_udhaar_balance > 0.0:
            skipped_ids.append(cust_id)
            skipped_reasons[str(cust_id)] = (
                f"Outstanding balance of ₹{cust.current_udhaar_balance:.2f}; settle before deleting."
            )
            continue

        # Check bills
        has_bills = db.query(Bill).filter(Bill.customer_id == cust_id).first() is not None
        if has_bills:
            skipped_ids.append(cust_id)
            skipped_reasons[str(cust_id)] = "Has linked bill records; cannot safely hard-delete."
            continue

        # Check udhaar transactions
        has_udhaar = (
            db.query(UdhaarTransaction)
            .filter(UdhaarTransaction.primary_customer_id == cust_id)
            .first() is not None
        )
        if has_udhaar:
            skipped_ids.append(cust_id)
            skipped_reasons[str(cust_id)] = "Has udhaar ledger history; cannot safely hard-delete."
            continue

        # Guard: never delete the oldest account in its name-group
        oldest = (
            db.query(Customer.id)
            .filter(func.lower(Customer.full_name) == func.lower(cust.full_name))
            .order_by(Customer.id.asc())
            .first()
        )
        if oldest and oldest.id == cust_id:
            skipped_ids.append(cust_id)
            skipped_reasons[str(cust_id)] = (
                "Oldest account in the duplicate group; retained as canonical record."
            )
            continue

        # All checks passed — safe to delete
        if not payload.dry_run:
            # Remove family members first (they cascade, but we're explicit)
            for m in cust.family_members:
                db.delete(m)
            db.delete(cust)
        deleted_ids.append(cust_id)

    if not payload.dry_run:
        db.commit()

    action_verb = "Would delete" if payload.dry_run else "Deleted"
    return DuplicateCleanupResponse(
        success=True,
        dry_run=payload.dry_run,
        deleted_count=len(deleted_ids),
        skipped_count=len(skipped_ids),
        deleted_ids=deleted_ids,
        skipped_ids=skipped_ids,
        skipped_reasons=skipped_reasons,
        message=(
            f"{action_verb} {len(deleted_ids)} duplicate account(s). "
            f"{len(skipped_ids)} skipped due to active history or safety constraints."
        ),
    )


# ==============================================================================
# Phone OTP Verification (Customer & Family Member)
# ==============================================================================

@router.post("/{customer_id}/request-phone-otp", response_model=PhoneOTPResponse, status_code=status.HTTP_200_OK)
def request_customer_phone_otp(customer_id: int, payload: Optional[PhoneOTPRequest] = None, db: Session = Depends(get_db)):
    """
    Initiates Demo/Mock phone OTP verification for a primary customer account.
    """
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if not cust:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer with ID {customer_id} not found.")

    if cust.is_phone_verified:
        return PhoneOTPResponse(
            success=True,
            phone=cust.phone,
            status="VERIFIED",
            message=f"Phone number '{cust.phone}' is already verified for {cust.full_name}.",
            is_demo=True,
            demo_otp=None
        )

    otp_code = f"{secrets.randbelow(900000) + 100000}"
    now = datetime.utcnow()
    expires_at = now + timedelta(minutes=5)

    otp_rec = PhoneOTPVerification(
        phone=cust.phone,
        otp_code=otp_code,
        entity_type="CUSTOMER",
        entity_id=cust.id,
        status="PENDING",
        attempts=0,
        max_attempts=3,
        created_at=now,
        expires_at=expires_at
    )
    cust.phone_verification_status = "OTP_REQUESTED"
    db.add(otp_rec)
    db.commit()
    db.refresh(otp_rec)

    return PhoneOTPResponse(
        success=True,
        phone=cust.phone,
        status="OTP_REQUESTED",
        message=f"[DEMO/MOCK] OTP sent to {cust.phone}. Valid for 5 minutes (no external SMS gateway configured).",
        is_demo=True,
        demo_otp=otp_code,
        expires_in_seconds=300,
        attempts_remaining=3
    )


@router.post("/{customer_id}/verify-phone-otp", response_model=PhoneOTPResponse, status_code=status.HTTP_200_OK)
def verify_customer_phone_otp(customer_id: int, payload: PhoneOTPVerifyRequest, db: Session = Depends(get_db)):
    """
    Verifies submitted OTP code for customer phone verification.
    """
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if not cust:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer with ID {customer_id} not found.")

    otp_rec = (
        db.query(PhoneOTPVerification)
        .filter(PhoneOTPVerification.entity_type == "CUSTOMER", PhoneOTPVerification.entity_id == customer_id)
        .order_by(PhoneOTPVerification.created_at.desc())
        .first()
    )

    if not otp_rec or otp_rec.status == "VERIFIED":
        if cust.is_phone_verified:
            return PhoneOTPResponse(
                success=True,
                phone=cust.phone,
                status="VERIFIED",
                message=f"Phone number '{cust.phone}' is already verified.",
                is_demo=True
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active OTP verification session found. Please request a new OTP.")

    now = datetime.utcnow()
    if otp_rec.status == "EXPIRED" or now > otp_rec.expires_at:
        otp_rec.status = "EXPIRED"
        cust.phone_verification_status = "EXPIRED"
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP has expired. Please request a new OTP.")

    if otp_rec.status == "FAILED" or otp_rec.attempts >= otp_rec.max_attempts:
        otp_rec.status = "FAILED"
        cust.phone_verification_status = "FAILED"
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum verification attempts exceeded. Please request a new OTP.")

    otp_rec.attempts += 1

    if payload.otp_code.strip() == otp_rec.otp_code:
        otp_rec.status = "VERIFIED"
        otp_rec.verified_at = now
        cust.is_phone_verified = True
        cust.phone_verification_status = "VERIFIED"
        db.commit()
        return PhoneOTPResponse(
            success=True,
            phone=cust.phone,
            status="VERIFIED",
            message=f"Phone number '{cust.phone}' successfully verified.",
            is_demo=True,
            attempts_remaining=0
        )
    else:
        remaining = max(0, otp_rec.max_attempts - otp_rec.attempts)
        if remaining == 0:
            otp_rec.status = "FAILED"
            cust.phone_verification_status = "FAILED"
            db.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect OTP. Maximum attempts reached. Session failed.")
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Incorrect OTP. {remaining} attempt(s) remaining.")


@router.post("/{customer_id}/family-members/{member_id}/request-phone-otp", response_model=PhoneOTPResponse, status_code=status.HTTP_200_OK)
def request_family_member_phone_otp(customer_id: int, member_id: int, payload: Optional[PhoneOTPRequest] = None, db: Session = Depends(get_db)):
    """
    Initiates Demo/Mock phone OTP verification for a family member.
    """
    member = db.query(FamilyMember).filter(FamilyMember.id == member_id).first()
    if not member or member.primary_customer_id != customer_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Family member with ID {member_id} not found.")

    if not member.phone:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Family member has no personal phone number configured.")

    if member.is_phone_verified:
        return PhoneOTPResponse(
            success=True,
            phone=member.phone,
            status="VERIFIED",
            message=f"Phone number '{member.phone}' is already verified for {member.full_name}.",
            is_demo=True,
            demo_otp=None
        )

    otp_code = f"{secrets.randbelow(900000) + 100000}"
    now = datetime.utcnow()
    expires_at = now + timedelta(minutes=5)

    otp_rec = PhoneOTPVerification(
        phone=member.phone,
        otp_code=otp_code,
        entity_type="FAMILY_MEMBER",
        entity_id=member.id,
        status="PENDING",
        attempts=0,
        max_attempts=3,
        created_at=now,
        expires_at=expires_at
    )
    member.phone_verification_status = "OTP_REQUESTED"
    db.add(otp_rec)
    db.commit()
    db.refresh(otp_rec)

    return PhoneOTPResponse(
        success=True,
        phone=member.phone,
        status="OTP_REQUESTED",
        message=f"[DEMO/MOCK] OTP sent to {member.phone}. Valid for 5 minutes (no external SMS gateway configured).",
        is_demo=True,
        demo_otp=otp_code,
        expires_in_seconds=300,
        attempts_remaining=3
    )


@router.post("/{customer_id}/family-members/{member_id}/verify-phone-otp", response_model=PhoneOTPResponse, status_code=status.HTTP_200_OK)
def verify_family_member_phone_otp(customer_id: int, member_id: int, payload: PhoneOTPVerifyRequest, db: Session = Depends(get_db)):
    """
    Verifies submitted OTP code for family member phone verification.
    """
    member = db.query(FamilyMember).filter(FamilyMember.id == member_id).first()
    if not member or member.primary_customer_id != customer_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Family member with ID {member_id} not found.")

    otp_rec = (
        db.query(PhoneOTPVerification)
        .filter(PhoneOTPVerification.entity_type == "FAMILY_MEMBER", PhoneOTPVerification.entity_id == member_id)
        .order_by(PhoneOTPVerification.created_at.desc())
        .first()
    )

    if not otp_rec or otp_rec.status == "VERIFIED":
        if member.is_phone_verified:
            return PhoneOTPResponse(
                success=True,
                phone=member.phone or "",
                status="VERIFIED",
                message=f"Phone number for '{member.full_name}' is already verified.",
                is_demo=True
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active OTP verification session found. Please request a new OTP.")

    now = datetime.utcnow()
    if otp_rec.status == "EXPIRED" or now > otp_rec.expires_at:
        otp_rec.status = "EXPIRED"
        member.phone_verification_status = "EXPIRED"
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP has expired. Please request a new OTP.")

    if otp_rec.status == "FAILED" or otp_rec.attempts >= otp_rec.max_attempts:
        otp_rec.status = "FAILED"
        member.phone_verification_status = "FAILED"
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum verification attempts exceeded. Please request a new OTP.")

    otp_rec.attempts += 1

    if payload.otp_code.strip() == otp_rec.otp_code:
        otp_rec.status = "VERIFIED"
        otp_rec.verified_at = now
        member.is_phone_verified = True
        member.phone_verification_status = "VERIFIED"
        db.commit()
        return PhoneOTPResponse(
            success=True,
            phone=member.phone or "",
            status="VERIFIED",
            message=f"Phone number '{member.phone}' successfully verified.",
            is_demo=True,
            attempts_remaining=0
        )
    else:
        remaining = max(0, otp_rec.max_attempts - otp_rec.attempts)
        if remaining == 0:
            otp_rec.status = "FAILED"
            member.phone_verification_status = "FAILED"
            db.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect OTP. Maximum attempts reached. Session failed.")
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Incorrect OTP. {remaining} attempt(s) remaining.")



@router.get("/{customer_id}/ledger", response_model=List[UdhaarTransactionResponse])
def get_customer_ledger(customer_id: int, db: Session = Depends(get_db)):
    """
    Retrieves the complete immutable Udhaar ledger history for a customer account.
    """
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if not cust:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer with ID {customer_id} not found."
        )

    transactions = (
        db.query(UdhaarTransaction)
        .filter(UdhaarTransaction.primary_customer_id == customer_id)
        .order_by(UdhaarTransaction.created_at.desc())
        .all()
    )
    return [_format_transaction_response(t) for t in transactions]


@router.post("/{customer_id}/settle", response_model=UdhaarSettlementResponse)
def settle_udhaar(customer_id: int, payload: UdhaarSettlementRequest, db: Session = Depends(get_db)):
    """
    Processes an Udhaar debt settlement/payment.
    Decrements outstanding balance and appends an immutable CREDIT_PAYMENT ledger entry.
    """
    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if not cust:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer with ID {customer_id} not found."
        )

    if payload.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Settlement amount must be greater than zero."
        )

    if payload.amount > cust.current_udhaar_balance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Settlement amount (Rs.{payload.amount:.2f}) exceeds current outstanding balance "
                f"(Rs.{cust.current_udhaar_balance:.2f}) for '{cust.full_name}'."
            )
        )

    balance_before = cust.current_udhaar_balance
    balance_after = round(balance_before - payload.amount, 2)
    cust.current_udhaar_balance = balance_after

    transaction = UdhaarTransaction(
        primary_customer_id=cust.id,
        amount=payload.amount,
        transaction_type="CREDIT_PAYMENT",
        balance_before=balance_before,
        balance_after=balance_after,
        verified_by=f"SETTLEMENT_{payload.payment_mode}",
        notes=payload.notes or f"Udhaar settled via {payload.payment_mode}"
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    return UdhaarSettlementResponse(
        success=True,
        customer_id=cust.id,
        customer_name=cust.full_name,
        settled_amount=payload.amount,
        previous_balance=balance_before,
        new_balance=balance_after,
        transaction=_format_transaction_response(transaction),
        message=f"Successfully settled Rs.{payload.amount:.2f} via {payload.payment_mode}. New balance: Rs.{balance_after:.2f}."
    )



