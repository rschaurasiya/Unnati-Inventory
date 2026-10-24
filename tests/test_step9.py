"""
Step 9 Test Suite — Udhaar (Credit) Ledger & Family Account Management
Tests:
A. Primary account creation
B. Family member creation/linking
C. Customer search
D. Udhaar purchase within credit limit
E. Udhaar purchase exceeding credit limit
F. Primary-holder verification success
G. Primary-holder verification failure
H. Expired verification
I. Successful Udhaar balance update
J. Udhaar settlement/payment
K. Failed verification does not complete transaction
L. Failed transaction does not deduct inventory
M. Duplicate request does not duplicate Udhaar or stock deduction
N. Correct family member linked to the correct primary account
End-to-end complete Udhaar workflow.
"""
import time
import sys
import uuid
import secrets
from pathlib import Path
from datetime import datetime, timedelta

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product, Customer, FamilyMember, Bill, VerificationSession, UdhaarTransaction

client = TestClient(app)


@pytest.fixture(autouse=True)
def replenish_stock_for_tests():
    """Ensure catalog products have sufficient stock for repeatable testing."""
    db = SessionLocal()
    try:
        products = db.query(Product).all()
        for p in products:
            if p.stock_quantity < 10.0:
                p.stock_quantity = 50.0
        db.commit()
    finally:
        db.close()


def _random_phone(prefix: str = "98") -> str:
    """Generate a guaranteed distinct 10-digit phone number for tests."""
    rand_suffix = f"{secrets.randbelow(90000000) + 10000000}"
    return f"{prefix[:2]}{rand_suffix}"[:10]


DEFAULT_ADDRESS = {
    "address_line": "House No. 25, Main Road",
    "city": "Chandigarh",
    "state": "Chandigarh",
    "pincode": "160017",
    "country": "India"
}


def test_a_primary_account_creation():
    """Requirement A: Create and manage a primary account holder."""
    unique_phone = _random_phone("98")
    payload = {
        "full_name": "Kavita Sharma",
        "phone": unique_phone,
        "credit_limit": 4500.0,
        **DEFAULT_ADDRESS
    }
    res = client.post("/api/v1/customers", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["full_name"] == "Kavita Sharma"
    assert data["phone"] == unique_phone
    assert data["credit_limit"] == 4500.0
    assert data["current_udhaar_balance"] == 0.0
    assert data["available_credit"] == 4500.0
    assert data["is_active"] is True

    # Duplicate phone rejection
    dup_res = client.post("/api/v1/customers", json=payload)
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"].lower()


def test_b_family_member_creation_and_linking():
    """Requirement B: Add family members under the primary account."""
    unique_phone = _random_phone("97")
    cust_res = client.post("/api/v1/customers", json={
        "full_name": "Anil Gupta",
        "phone": unique_phone,
        "credit_limit": 5000.0,
        **DEFAULT_ADDRESS
    })
    assert cust_res.status_code == 201
    cust_id = cust_res.json()["id"]

    # Add Son
    member_res = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
        "full_name": "Rahul Gupta",
        "relation_type": "Son",
        "phone": _random_phone("96"),
        "allowed_spending_limit": 1500.0
    })
    assert member_res.status_code == 201
    member = member_res.json()
    assert member["full_name"] == "Rahul Gupta"
    assert member["relation_type"] == "Son"
    assert member["primary_customer_id"] == cust_id
    assert member["allowed_spending_limit"] == 1500.0

    # Add Wife
    member_res2 = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
        "full_name": "Sunita Gupta",
        "relation_type": "Wife"
    })
    assert member_res2.status_code == 201
    assert member_res2.json()["primary_customer_id"] == cust_id


def test_c_customer_search():
    """Requirement C: Search/selecting the correct customer and family members."""
    # Seeded customer Ramesh Sharma
    res = client.get("/api/v1/customers?query=Ramesh")
    assert res.status_code == 200
    customers = res.json()
    assert len(customers) >= 1
    found = any("Ramesh" in c["full_name"] for c in customers)
    assert found is True

    # Search by phone (Ramesh's phone is 9876543210)
    res_phone = client.get("/api/v1/customers?query=9876543210")
    assert res_phone.status_code == 200
    assert len(res_phone.json()) >= 1
    assert res_phone.json()[0]["phone"] == "9876543210"

    # Detail includes family members
    cust_id = res_phone.json()[0]["id"]
    detail_res = client.get(f"/api/v1/customers/{cust_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert len(detail["family_members"]) >= 1
    assert "transactions" in detail


def test_n_cross_account_family_member_protection():
    """Requirement N: Prevent a family member from being incorrectly linked or used with another account."""
    db = SessionLocal()
    try:
        ramesh = db.query(Customer).filter(Customer.phone == "9876543210").first()
        vikram = db.query(Customer).filter(Customer.phone == "9823456789").first()
        assert ramesh is not None and vikram is not None

        # Aman belongs to Ramesh
        aman = db.query(FamilyMember).filter(FamilyMember.primary_customer_id == ramesh.id).first()
        assert aman is not None

        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()

        # Try to bill Vikram using Ramesh's family member Aman
        res = client.post("/api/v1/billing/finalize", json={
            "customer_id": vikram.id,
            "family_member_id": aman.id,
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        assert res.status_code == 400
        assert "does not belong" in res.json()["detail"].lower()
    finally:
        db.close()


def test_e_udhaar_purchase_exceeding_credit_limit():
    """Requirement E: Exceeding credit limit is rejected with clear explanation and zero mutations."""
    db = SessionLocal()
    try:
        # Create customer with small credit limit
        unique_phone = _random_phone("95")
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Low Limit Customer",
            "phone": unique_phone,
            "credit_limit": 100.0,  # Limit is only Rs. 100
            **DEFAULT_ADDRESS
        })
        assert cust_res.status_code == 201
        cust_id = cust_res.json()["id"]

        ghee = db.query(Product).filter(Product.name.like("%Ghee%")).first()
        assert ghee.unit_price > 100.0  # e.g. 550.0
        initial_ghee_stock = ghee.stock_quantity

        # Attempt to buy ghee on Udhaar
        res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": ghee.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        assert res.status_code == 400
        err_msg = res.json()["detail"]
        assert "credit limit exceeded" in err_msg.lower()
        assert "available credit" in err_msg.lower()

        # Verify stock and balance did NOT change
        db.expire_all()
        cust_db = db.query(Customer).filter(Customer.id == cust_id).first()
        assert cust_db.current_udhaar_balance == 0.0
        ghee_db = db.query(Product).filter(Product.id == ghee.id).first()
        assert ghee_db.stock_quantity == initial_ghee_stock
    finally:
        db.close()


def _create_udhaar_bill_pending():
    """Helper: Finalizes an Udhaar bill in PENDING_VERIFICATION status."""
    db = SessionLocal()
    try:
        unique_phone = _random_phone("94")
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Pooja Verma",
            "phone": unique_phone,
            "credit_limit": 3000.0,
            "is_phone_verified": True,
            **DEFAULT_ADDRESS
        })
        assert cust_res.status_code == 201
        cust_id = cust_res.json()["id"]

        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        initial_sugar_stock = sugar.stock_quantity

        # Finalize bill on Udhaar
        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": sugar.id, "quantity": 2.0}],
            "payment_mode": "UDHAAR",
            "notes": "Test within limit Udhaar bill"
        })
        assert bill_res.status_code == 201
        bill_data = bill_res.json()
        assert bill_data["status"] == "PENDING_VERIFICATION"
        assert bill_data["payment_mode"] == "UDHAAR"
        assert bill_data["customer_name"] == "Pooja Verma"
        assert bill_data["notification_message"] is not None
        assert "Pooja Verma" in bill_data["notification_message"]

        # CRITICAL: Verify stock is NOT yet deducted
        db.expire_all()
        sugar_db = db.query(Product).filter(Product.id == sugar.id).first()
        assert sugar_db.stock_quantity == initial_sugar_stock

        # Customer balance is NOT yet updated
        cust_db = db.query(Customer).filter(Customer.id == cust_id).first()
        assert cust_db.current_udhaar_balance == 0.0

        return bill_data["id"], cust_id, sugar.id, initial_sugar_stock, bill_data["total_amount"]
    finally:
        db.close()


def test_d_udhaar_purchase_within_limit_draft_and_deferral():
    """Requirement D: Udhaar purchase within credit limit creates PENDING bill and defers stock deduction."""
    _create_udhaar_bill_pending()


def test_f_and_i_primary_holder_verification_success_and_balance_update():
    """Requirements F & I: Verification success deducts inventory, creates ledger, and updates balance."""
    bill_id, cust_id, sugar_id, initial_stock, bill_total = _create_udhaar_bill_pending()

    # 1. Create verification session
    session_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
    assert session_res.status_code == 201
    s_data = session_res.json()
    assert s_data["status"] == "PENDING"
    assert s_data["payment_mode"] == "UDHAAR"
    assert len(s_data["challenge_numbers"]) == 3
    assert s_data["notification_message"] is not None

    # Retrieve target number from db for testing
    db = SessionLocal()
    try:
        session_db = db.query(VerificationSession).filter(VerificationSession.id == s_data["session_id"]).first()
        target_num = session_db.target_number

        # 2. Submit correct verification number
        verify_res = client.post("/api/v1/verification/verify", json={
            "session_id": s_data["session_id"],
            "selected_number": target_num
        })
        assert verify_res.status_code == 200
        v_result = verify_res.json()
        assert v_result["success"] is True
        assert v_result["status"] == "VERIFIED"
        assert v_result["payment_mode"] == "UDHAAR"
        assert v_result["udhaar_balance_after"] == bill_total

        # 3. Verify database updates
        db.expire_all()
        bill_db = db.query(Bill).filter(Bill.id == bill_id).first()
        assert bill_db.status == "COMPLETED"

        sugar_db = db.query(Product).filter(Product.id == sugar_id).first()
        assert sugar_db.stock_quantity == round(initial_stock - 2.0, 3)

        cust_db = db.query(Customer).filter(Customer.id == cust_id).first()
        assert cust_db.current_udhaar_balance == bill_total

        # Immutable ledger record
        tx = db.query(UdhaarTransaction).filter(UdhaarTransaction.bill_id == bill_id).first()
        assert tx is not None
        assert tx.primary_customer_id == cust_id
        assert tx.amount == bill_total
        assert tx.transaction_type == "DEBIT_PURCHASE"
        assert tx.balance_before == 0.0
        assert tx.balance_after == bill_total
        assert tx.verified_by == "PRIMARY_2FA"
    finally:
        db.close()


def test_g_k_l_failed_verification_preserves_stock_and_balance():
    """Requirements G, K, L: Failed verification does not complete transaction or deduct inventory."""
    db = SessionLocal()
    try:
        unique_phone = _random_phone("93")
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Suresh Raina",
            "phone": unique_phone,
            "credit_limit": 2500.0,
            "is_phone_verified": True,
            **DEFAULT_ADDRESS
        })
        assert cust_res.status_code == 201
        cust_id = cust_res.json()["id"]

        milk = db.query(Product).filter(Product.name.like("%Milk%")).first()
        initial_milk_stock = milk.stock_quantity

        # Create Udhaar bill
        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": milk.id, "quantity": 3.0}],
            "payment_mode": "UDHAAR"
        })
        assert bill_res.status_code == 201
        bill_id = bill_res.json()["id"]

        # Create verification session
        session_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
        assert session_res.status_code == 201
        s_data = session_res.json()

        # Find a number from candidates that is NOT target_number
        session_db = db.query(VerificationSession).filter(VerificationSession.id == s_data["session_id"]).first()
        candidates = s_data["challenge_numbers"]
        wrong_num = [n for n in candidates if n != session_db.target_number][0]

        # Submit WRONG number
        verify_res = client.post("/api/v1/verification/verify", json={
            "session_id": s_data["session_id"],
            "selected_number": wrong_num
        })
        assert verify_res.status_code == 200
        v_result = verify_res.json()
        assert v_result["success"] is False
        assert v_result["status"] == "FAILED"

        # Check DB: Bill is STILL PENDING_VERIFICATION, stock is UNTOUCHED, balance is 0.0
        db.expire_all()
        bill_db = db.query(Bill).filter(Bill.id == bill_id).first()
        assert bill_db.status == "PENDING_VERIFICATION"

        milk_db = db.query(Product).filter(Product.id == milk.id).first()
        assert milk_db.stock_quantity == initial_milk_stock  # ZERO stock deduction

        cust_db = db.query(Customer).filter(Customer.id == cust_id).first()
        assert cust_db.current_udhaar_balance == 0.0  # ZERO balance change

        # No ledger record
        tx = db.query(UdhaarTransaction).filter(UdhaarTransaction.bill_id == bill_id).first()
        assert tx is None
    finally:
        db.close()


def test_h_expired_verification_handling():
    """Requirement H: Expired verification session rejects verification and preserves stock."""
    db = SessionLocal()
    try:
        unique_phone = _random_phone("92")
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Deepak Patel",
            "phone": unique_phone,
            "credit_limit": 2000.0,
            "is_phone_verified": True,
            **DEFAULT_ADDRESS
        })
        assert cust_res.status_code == 201
        cust_id = cust_res.json()["id"]

        salt = db.query(Product).filter(Product.name.like("%Salt%")).first()
        initial_salt_stock = salt.stock_quantity

        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": salt.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        bill_id = bill_res.json()["id"]

        # Create session with 30s expiry
        session_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id, "expiry_seconds": 30})
        session_id = session_res.json()["session_id"]

        # Force expire the session in DB
        session_db = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
        session_db.expires_at = datetime.utcnow() - timedelta(minutes=5)
        db.commit()

        # Submit attempt should fail with 400 Expired
        verify_res = client.post("/api/v1/verification/verify", json={
            "session_id": session_id,
            "selected_number": session_db.target_number
        })
        assert verify_res.status_code == 400
        assert "expired" in verify_res.json()["detail"].lower()

        # Verify stock and balance untouched
        db.expire_all()
        salt_db = db.query(Product).filter(Product.id == salt.id).first()
        assert salt_db.stock_quantity == initial_salt_stock
        cust_db = db.query(Customer).filter(Customer.id == cust_id).first()
        assert cust_db.current_udhaar_balance == 0.0
    finally:
        db.close()


def test_m_duplicate_request_idempotency():
    """Requirement M: Duplicate request does not duplicate Udhaar or stock deduction."""
    db = SessionLocal()
    try:
        unique_phone = _random_phone("91")
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Idempotent Customer",
            "phone": unique_phone,
            "credit_limit": 3000.0,
            **DEFAULT_ADDRESS
        })
        assert cust_res.status_code == 201
        cust_id = cust_res.json()["id"]

        rice = db.query(Product).filter(Product.name.like("%Rice%")).first()
        stock_before = rice.stock_quantity

        idemp_key = f"key-{uuid.uuid4()}"

        # 1. First finalize call (Cash or Udhaar)
        res1 = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": rice.id, "quantity": 1.0}],
            "payment_mode": "CASH",
            "idempotency_key": idemp_key
        })
        assert res1.status_code == 201
        data1 = res1.json()
        assert data1["is_duplicate_replay"] is False

        # 2. Second finalize call with identical idempotency_key
        res2 = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": rice.id, "quantity": 1.0}],
            "payment_mode": "CASH",
            "idempotency_key": idemp_key
        })
        assert res2.status_code == 200 or res2.status_code == 201
        data2 = res2.json()
        assert data2["is_duplicate_replay"] is True
        assert data2["id"] == data1["id"]

        # Verify stock deducted ONCE, not twice
        db.expire_all()
        rice_db = db.query(Product).filter(Product.id == rice.id).first()
        assert rice_db.stock_quantity == round(stock_before - 1.0, 3)
    finally:
        db.close()


def test_j_udhaar_settlement_payment():
    """Requirement J: Udhaar settlement / repayment updates balance and adds CREDIT_PAYMENT ledger record."""
    # First, setup customer with balance
    db = SessionLocal()
    try:
        unique_phone = _random_phone("90")
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Settlement Customer",
            "phone": unique_phone,
            "credit_limit": 5000.0,
            **DEFAULT_ADDRESS
        })
        assert cust_res.status_code == 201
        cust_id = cust_res.json()["id"]

        # Manually set a balance to settle
        cust_db = db.query(Customer).filter(Customer.id == cust_id).first()
        cust_db.current_udhaar_balance = 1200.0
        db.commit()

        # 1. Overpayment rejection check
        overpay_res = client.post(f"/api/v1/customers/{cust_id}/settle", json={
            "amount": 1500.0,
            "payment_mode": "CASH",
            "notes": "Attempt overpayment"
        })
        assert overpay_res.status_code == 400
        assert "exceeds" in overpay_res.json()["detail"].lower() and "outstanding balance" in overpay_res.json()["detail"].lower()

        # 2. Partial settlement of Rs. 500
        settle_res = client.post(f"/api/v1/customers/{cust_id}/settle", json={
            "amount": 500.0,
            "payment_mode": "UPI",
            "notes": "Partial repayment"
        })
        assert settle_res.status_code == 200
        s_data = settle_res.json()
        assert s_data["settled_amount"] == 500.0
        assert s_data["previous_balance"] == 1200.0
        assert s_data["new_balance"] == 700.0

        # Check customer credit
        cust_after_res = client.get(f"/api/v1/customers/{cust_id}")
        assert cust_after_res.status_code == 200
        assert cust_after_res.json()["available_credit"] == 4300.0

        # Check ledger
        ledger_res = client.get(f"/api/v1/customers/{cust_id}/ledger")
        assert ledger_res.status_code == 200
        txs = ledger_res.json()
        assert len(txs) >= 1
        payment_tx = txs[0]
        assert payment_tx["transaction_type"] == "CREDIT_PAYMENT"
        assert payment_tx["amount"] == 500.0
        assert payment_tx["balance_after"] == 700.0

        # 3. Full settlement of remaining Rs. 700
        settle_full = client.post(f"/api/v1/customers/{cust_id}/settle", json={
            "amount": 700.0,
            "payment_mode": "CASH",
            "notes": "Full settlement"
        })
        assert settle_full.status_code == 200
        assert settle_full.json()["new_balance"] == 0.0

        cust_final_res = client.get(f"/api/v1/customers/{cust_id}")
        assert cust_final_res.status_code == 200
        assert cust_final_res.json()["available_credit"] == 5000.0
    finally:
        db.close()


def test_end_to_end_udhaar_workflow():
    """
    End-to-End Workflow:
    Primary Account Holder -> Family Member -> Udhaar Bill -> Credit Limit Check
    -> Notification -> 2FA Verification -> Stock Deducted -> Udhaar Ledger Recorded -> Receipt Generated.
    """
    db = SessionLocal()
    try:
        # 1. Primary Account Holder
        cust_phone = _random_phone("99")
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Mahesh Chandra",
            "phone": cust_phone,
            "credit_limit": 4000.0,
            "is_phone_verified": True,
            **DEFAULT_ADDRESS
        })
        assert cust_res.status_code == 201
        cust = cust_res.json()
        cust_id = cust["id"]

        # 2. Add Family Member (Son)
        member_res = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
            "full_name": "Vikas Chandra",
            "relation_type": "Son",
            "phone": _random_phone("88"),
            "allowed_spending_limit": 2000.0
        })
        assert member_res.status_code == 201
        member = member_res.json()
        member_id = member["id"]

        # Check products & initial stock
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        oil = db.query(Product).filter(Product.name.like("%Oil%")).first()
        initial_sugar_stock = sugar.stock_quantity
        initial_oil_stock = oil.stock_quantity

        # 3. Create Draft Bill via POS items
        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "family_member_id": member_id,
            "items": [
                {"product_id": sugar.id, "quantity": 2.0},
                {"product_id": oil.id, "quantity": 1.0}
            ],
            "payment_mode": "UDHAAR",
            "notes": "Family purchase for Vikas"
        })
        assert bill_res.status_code == 201
        bill_data = bill_res.json()
        bill_id = bill_data["id"]
        total_amount = bill_data["total_amount"]
        assert bill_data["status"] == "PENDING_VERIFICATION"
        assert bill_data["buyer_name"] == "Vikas Chandra"
        assert "Vikas Chandra" in bill_data["notification_message"]

        # Verify stock NOT deducted yet
        db.expire_all()
        assert db.query(Product).filter(Product.id == sugar.id).first().stock_quantity == initial_sugar_stock
        assert db.query(Product).filter(Product.id == oil.id).first().stock_quantity == initial_oil_stock

        # 4. Generate Verification Session
        session_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
        assert session_res.status_code == 201
        s_data = session_res.json()
        assert s_data["payment_mode"] == "UDHAAR"
        assert s_data["buyer_name"] == "Vikas Chandra"
        assert s_data["customer_name"] == "Mahesh Chandra"
        assert len(s_data["challenge_numbers"]) == 3

        # 5. Primary Holder approves by matching number
        session_db = db.query(VerificationSession).filter(VerificationSession.id == s_data["session_id"]).first()
        target_num = session_db.target_number

        verify_res = client.post("/api/v1/verification/verify", json={
            "session_id": s_data["session_id"],
            "selected_number": target_num
        })
        assert verify_res.status_code == 200
        v_res = verify_res.json()
        assert v_res["success"] is True
        assert v_res["status"] == "VERIFIED"
        assert v_res["udhaar_balance_after"] == total_amount

        # 6. Verify inventory deducted exactly once
        db.expire_all()
        assert db.query(Product).filter(Product.id == sugar.id).first().stock_quantity == round(initial_sugar_stock - 2.0, 3)
        assert db.query(Product).filter(Product.id == oil.id).first().stock_quantity == round(initial_oil_stock - 1.0, 3)

        # 7. Verify Udhaar ledger updated
        ledger_res = client.get(f"/api/v1/customers/{cust_id}/ledger")
        assert ledger_res.status_code == 200
        ledger = ledger_res.json()
        assert len(ledger) >= 1
        tx = ledger[0]
        assert tx["bill_id"] == bill_id
        assert tx["amount"] == total_amount
        assert tx["family_member_name"] == "Vikas Chandra"
        assert tx["transaction_type"] == "DEBIT_PURCHASE"

        # 8. Verify digital receipt can now be generated with customer & buyer info
        receipt_res = client.get(f"/api/v1/receipts/{bill_id}")
        assert receipt_res.status_code == 200
        receipt = receipt_res.json()
        assert receipt["customer_name"] == "Mahesh Chandra"
        assert receipt["buyer_name"] == "Vikas Chandra"
        assert receipt["payment_mode"] == "UDHAAR"
        assert "Mahesh Chandra" in receipt["formatted_text_receipt"]
        assert "Vikas Chandra" in receipt["formatted_text_receipt"]
    finally:
        db.close()


def test_exact_credit_limit_boundary_and_reconstruction():
    """
    Phase 4 / Step 9D:
    Test purchase exactly at credit limit, then test rejection when limit reached,
    and verify ledger reconstruction: sum(debits) - sum(credits) == balance.
    """
    db = SessionLocal()
    try:
        # Create customer with credit limit exactly equal to product price * 2
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        sugar_price = sugar.unit_price
        exact_limit = round(sugar_price * 2.0, 2)

        unique_phone = _random_phone("89")
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Boundary Test Customer",
            "phone": unique_phone,
            "credit_limit": exact_limit,
            "is_phone_verified": True,
            **DEFAULT_ADDRESS
        })
        assert cust_res.status_code == 201
        cust_id = cust_res.json()["id"]

        # 1. Purchase exactly at credit limit (2 * sugar_price == exact_limit)
        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": sugar.id, "quantity": 2.0}],
            "payment_mode": "UDHAAR"
        })
        assert bill_res.status_code == 201
        bill = bill_res.json()
        assert bill["total_amount"] == exact_limit

        # Complete 2FA verification
        sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill["id"]})
        assert sess_res.status_code == 201
        sess_id = sess_res.json()["session_id"]

        sess_db = db.query(VerificationSession).filter(VerificationSession.id == sess_id).first()
        verify_res = client.post("/api/v1/verification/verify", json={
            "session_id": sess_id,
            "selected_number": sess_db.target_number
        })
        assert verify_res.status_code == 200
        assert verify_res.json()["udhaar_balance_after"] == exact_limit

        # 2. Limit is now completely exhausted. Next purchase (even 0.5 kg) must be rejected
        exhausted_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": sugar.id, "quantity": 0.5}],
            "payment_mode": "UDHAAR"
        })
        assert exhausted_res.status_code == 400
        assert "credit limit exceeded" in exhausted_res.json()["detail"].lower()

        # 3. Partial settlement of 1 * sugar_price
        settle_res = client.post(f"/api/v1/customers/{cust_id}/settle", json={
            "amount": sugar_price,
            "payment_mode": "CASH"
        })
        assert settle_res.status_code == 200

        # 4. Verify ledger auditability: reconstruct balance from ledger
        ledger_res = client.get(f"/api/v1/customers/{cust_id}/ledger")
        assert ledger_res.status_code == 200
        txs = ledger_res.json()

        total_debits = sum(t["amount"] for t in txs if t["transaction_type"] == "DEBIT_PURCHASE")
        total_credits = sum(t["amount"] for t in txs if t["transaction_type"] == "CREDIT_PAYMENT")
        reconstructed_balance = round(total_debits - total_credits, 2)

        cust_check = client.get(f"/api/v1/customers/{cust_id}").json()
        assert cust_check["current_udhaar_balance"] == reconstructed_balance
    finally:
        db.close()


def test_reused_verification_session_rejection():
    """Phase 4: Attempting to verify an already VERIFIED session must fail."""
    db = SessionLocal()
    try:
        unique_phone = _random_phone("88")
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Reuse Test Customer",
            "phone": unique_phone,
            "credit_limit": 5000.0,
            "is_phone_verified": True,
            **DEFAULT_ADDRESS
        })
        cust_id = cust_res.json()["id"]

        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        bill_id = bill_res.json()["id"]

        sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
        sess_id = sess_res.json()["session_id"]
        sess_db = db.query(VerificationSession).filter(VerificationSession.id == sess_id).first()
        target = sess_db.target_number

        # First verification succeeds
        v1 = client.post("/api/v1/verification/verify", json={"session_id": sess_id, "selected_number": target})
        assert v1.status_code == 200
        assert v1.json()["success"] is True

        # Second verification attempt on same session must be rejected with 400
        v2 = client.post("/api/v1/verification/verify", json={"session_id": sess_id, "selected_number": target})
        assert v2.status_code == 400
        assert "already been completed" in v2.json()["detail"].lower()
    finally:
        db.close()


def test_family_member_deactivation_and_cross_account_delete_protection():
    """Requirement B & N: Deactivation works, cross-account deletion rejected, deactivated member cannot buy."""
    db = SessionLocal()
    try:
        cust1_res = client.post("/api/v1/customers", json={
            "full_name": "Account One",
            "phone": _random_phone("87"),
            "credit_limit": 3000.0,
            **DEFAULT_ADDRESS
        })
        cust1_id = cust1_res.json()["id"]

        cust2_res = client.post("/api/v1/customers", json={
            "full_name": "Account Two",
            "phone": _random_phone("86"),
            "credit_limit": 3000.0,
            **DEFAULT_ADDRESS
        })
        cust2_id = cust2_res.json()["id"]

        # Add member to Account One
        mem_res = client.post(f"/api/v1/customers/{cust1_id}/family-members", json={
            "full_name": "Member One",
            "relation_type": "Brother"
        })
        mem_id = mem_res.json()["id"]

        # 1. Attempt to delete member under Account Two (cross-account attack) -> must fail
        cross_del = client.delete(f"/api/v1/customers/{cust2_id}/family-members/{mem_id}")
        assert cross_del.status_code == 400
        assert "does not belong" in cross_del.json()["detail"].lower()

        # 2. Deactivate member properly under Account One -> must succeed
        del_res = client.delete(f"/api/v1/customers/{cust1_id}/family-members/{mem_id}")
        assert del_res.status_code == 200

        # 3. Attempt to use deactivated family member on Udhaar bill -> must fail
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        if sugar.stock_quantity < 10.0:
            sugar.stock_quantity = 50.0
            db.commit()
        buy_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust1_id,
            "family_member_id": mem_id,
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        assert buy_res.status_code == 400
        assert "inactive" in buy_res.json()["detail"].lower() or "does not belong" in buy_res.json()["detail"].lower()
    finally:
        db.close()

