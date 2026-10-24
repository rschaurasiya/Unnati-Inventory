"""
Comprehensive Maintenance, Security & Integrity Test Suite
Kirana Shopkeeper Assistant (Steps 1–9 Hardening)

Covers:
- TEST GROUP 1: Payment Method Verification (CASH / UPI direct vs UDHAAR 2FA)
- TEST GROUP 2: Phone Format Validation (Customer & Family Member; explicit rejection of "1234")
- TEST GROUP 3: Phone Verification via OTP State Machine (Customer & Family Member)
- TEST GROUP 4: Controlled Udhaar Account Deletion & Data Preservation (Zero balance vs outstanding)
- TEST GROUP 5: SMS Mock Status & Receipt Preview Transparency
- SCENARIOS A through F: Realistic End-to-End Workflows
"""
import sys
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
from backend.models import (
    Product, Customer, FamilyMember, Bill, VerificationSession,
    UdhaarTransaction, PhoneOTPVerification
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def ensure_sufficient_stock():
    """Ensure catalog items have stock for repeatable test runs."""
    db = SessionLocal()
    try:
        products = db.query(Product).all()
        for p in products:
            if p.stock_quantity < 20.0:
                p.stock_quantity = 50.0
        db.commit()
    finally:
        db.close()


def _rand_phone() -> str:
    """Generate a guaranteed distinct 10-digit Indian phone number."""
    return f"9{secrets.randbelow(900000000) + 100000000}"[:10]


DEFAULT_ADDRESS = {
    "address_line": "Shop 12, Main Market",
    "city": "Chandigarh",
    "state": "Chandigarh",
    "pincode": "160017",
    "country": "India"
}


# ==============================================================================
# 🧪 TEST GROUP 1 — PAYMENT METHOD VERIFICATION
# ==============================================================================

def test_group1_cash_direct_finalization_no_2fa():
    """
    Test CASH:
    Draft Bill -> Select CASH -> Finalize Bill -> Inventory Deduction -> Bill Completed -> Receipt
    No customer 2FA required.
    """
    db = SessionLocal()
    try:
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        initial_stock = sugar.stock_quantity

        # Finalize CASH bill
        res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": sugar.id, "quantity": 2.0}],
            "payment_mode": "CASH",
            "notes": "Group 1 Normal Cash Sale"
        })
        assert res.status_code == 201
        data = res.json()
        assert data["payment_mode"] == "CASH"
        assert data["status"] == "COMPLETED"

        # Verify stock deducted exactly once
        db.expire_all()
        sugar_db = db.query(Product).filter(Product.id == sugar.id).first()
        assert sugar_db.stock_quantity == initial_stock - 2.0

        # Verify receipt works immediately without 2FA
        bill_id = data["id"]
        rcp_res = client.get(f"/api/v1/receipts/{bill_id}")
        assert rcp_res.status_code == 200
        rcp = rcp_res.json()
        assert rcp["is_verified"] is True
        assert rcp["payment_mode"] == "CASH"
        assert "COMPLETED (CASH SALE)" in rcp["formatted_text_receipt"]
    finally:
        db.close()


def test_group1_upi_direct_finalization_no_2fa():
    """
    Test UPI:
    Draft Bill -> Select UPI -> Finalize Bill -> Inventory Deduction -> Bill Completed -> Receipt
    No customer 2FA required.
    """
    db = SessionLocal()
    try:
        milk = db.query(Product).filter(Product.name.like("%Milk%")).first()
        initial_stock = milk.stock_quantity

        # Finalize UPI bill
        res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": milk.id, "quantity": 1.0}],
            "payment_mode": "UPI",
            "notes": "Group 1 Normal UPI Sale"
        })
        assert res.status_code == 201
        data = res.json()
        assert data["payment_mode"] == "UPI"
        assert data["status"] == "COMPLETED"

        # Verify stock deducted exactly once
        db.expire_all()
        milk_db = db.query(Product).filter(Product.id == milk.id).first()
        assert milk_db.stock_quantity == initial_stock - 1.0

        # Verify receipt works immediately without 2FA
        bill_id = data["id"]
        rcp_res = client.get(f"/api/v1/receipts/{bill_id}")
        assert rcp_res.status_code == 200
        rcp = rcp_res.json()
        assert rcp["is_verified"] is True
        assert rcp["payment_mode"] == "UPI"
        assert "COMPLETED (UPI SALE)" in rcp["formatted_text_receipt"]
    finally:
        db.close()


def test_group1_udhaar_requires_2fa():
    """
    Test UDHAAR:
    Requires primary account holder 2FA before completion, stock deduction, and ledger update.
    """
    db = SessionLocal()
    try:
        phone = _rand_phone()
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Test Group 1 Udhaar User",
            "phone": phone,
            "credit_limit": 3000.0,
            "is_phone_verified": True,
            **DEFAULT_ADDRESS
        })
        assert cust_res.status_code == 201
        cust_id = cust_res.json()["id"]

        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        initial_stock = sugar.stock_quantity

        # 1. Finalize Udhaar Bill -> Must be PENDING_VERIFICATION
        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": sugar.id, "quantity": 2.0}],
            "payment_mode": "UDHAAR"
        })
        assert bill_res.status_code == 201
        bill_data = bill_res.json()
        bill_id = bill_data["id"]
        assert bill_data["status"] == "PENDING_VERIFICATION"

        # Stock is NOT deducted yet
        db.expire_all()
        sugar_db = db.query(Product).filter(Product.id == sugar.id).first()
        assert sugar_db.stock_quantity == initial_stock

        # Receipt is blocked
        rcp_blocked = client.get(f"/api/v1/receipts/{bill_id}")
        assert rcp_blocked.status_code == 403

        # 2. Start 2FA session
        sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
        assert sess_res.status_code == 201
        sess_id = sess_res.json()["session_id"]

        # Secret target
        target = db.query(VerificationSession).filter(VerificationSession.id == sess_id).first().target_number

        # 3. Submit correct number
        verify_res = client.post("/api/v1/verification/verify", json={
            "session_id": sess_id,
            "selected_number": target
        })
        assert verify_res.status_code == 200
        assert verify_res.json()["status"] == "VERIFIED"

        # 4. Stock deducted once
        db.expire_all()
        sugar_db = db.query(Product).filter(Product.id == sugar.id).first()
        assert sugar_db.stock_quantity == initial_stock - 2.0

        # Udhaar ledger updated
        cust_db = db.query(Customer).filter(Customer.id == cust_id).first()
        assert cust_db.current_udhaar_balance == bill_data["total_amount"]

        # Receipt now allowed
        rcp_ok = client.get(f"/api/v1/receipts/{bill_id}")
        assert rcp_ok.status_code == 200
    finally:
        db.close()


# ==============================================================================
# 🧪 TEST GROUP 2 — PHONE FORMAT VALIDATION
# ==============================================================================

def test_group2_customer_phone_validation():
    """Verify customer phone validation enforces exactly 10 digits."""
    # 1. Valid 10-digit number -> PASS
    valid_res = client.post("/api/v1/customers", json={
        "full_name": "Valid Phone Customer",
        "phone": _rand_phone(),
        "credit_limit": 2000.0,
        **DEFAULT_ADDRESS
    })
    assert valid_res.status_code == 201

    # 2. 4-digit number ("1234") -> FAIL (422)
    res_1234 = client.post("/api/v1/customers", json={
        "full_name": "Invalid Customer",
        "phone": "1234",
        "credit_limit": 2000.0,
        **DEFAULT_ADDRESS
    })
    assert res_1234.status_code == 422

    # 3. 9-digit number -> FAIL
    res_9 = client.post("/api/v1/customers", json={
        "full_name": "Invalid Customer",
        "phone": "987654321",
        "credit_limit": 2000.0,
        **DEFAULT_ADDRESS
    })
    assert res_9.status_code == 422

    # 4. 11-digit number -> FAIL
    res_11 = client.post("/api/v1/customers", json={
        "full_name": "Invalid Customer",
        "phone": "98765432101",
        "credit_limit": 2000.0,
        **DEFAULT_ADDRESS
    })
    assert res_11.status_code == 422

    # 5. Letters -> FAIL
    res_letters = client.post("/api/v1/customers", json={
        "full_name": "Invalid Customer",
        "phone": "98765abc10",
        "credit_limit": 2000.0,
        **DEFAULT_ADDRESS
    })
    assert res_letters.status_code == 422

    # 6. Special characters -> FAIL
    res_special = client.post("/api/v1/customers", json={
        "full_name": "Invalid Customer",
        "phone": "98765@#$10",
        "credit_limit": 2000.0,
        **DEFAULT_ADDRESS
    })
    assert res_special.status_code == 422

    # 7. Empty -> FAIL
    res_empty = client.post("/api/v1/customers", json={
        "full_name": "Invalid Customer",
        "phone": "",
        "credit_limit": 2000.0,
        **DEFAULT_ADDRESS
    })
    assert res_empty.status_code == 422


def test_group2_family_member_phone_validation():
    """Verify family member phone validation rejects '1234' and non-10-digit numbers."""
    cust_res = client.post("/api/v1/customers", json={
        "full_name": "Family Head",
        "phone": _rand_phone(),
        "credit_limit": 2000.0,
        **DEFAULT_ADDRESS
    })
    cust_id = cust_res.json()["id"]

    # 1. 4-digit number ("1234") -> MUST FAIL (422)
    res_1234 = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
        "full_name": "Buggy Member",
        "relation_type": "Son",
        "phone": "1234"
    })
    assert res_1234.status_code == 422, f"Expected 422 for phone '1234', got {res_1234.status_code}"

    # 2. 9-digit -> FAIL
    res_9 = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
        "full_name": "Buggy Member",
        "relation_type": "Son",
        "phone": "987654321"
    })
    assert res_9.status_code == 422

    # 3. 11-digit -> FAIL
    res_11 = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
        "full_name": "Buggy Member",
        "relation_type": "Son",
        "phone": "98765432101"
    })
    assert res_11.status_code == 422

    # 4. Alphabetic -> FAIL
    res_alpha = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
        "full_name": "Buggy Member",
        "relation_type": "Son",
        "phone": "abcdefghij"
    })
    assert res_alpha.status_code == 422

    # 5. Valid 10-digit -> PASS
    res_valid = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
        "full_name": "Valid Member",
        "relation_type": "Son",
        "phone": _rand_phone()
    })
    assert res_valid.status_code == 201


# ==============================================================================
# 🧪 TEST GROUP 3 — PHONE VERIFICATION (OTP STATE MACHINE)
# ==============================================================================

def test_group3_customer_phone_verification_flow():
    """Test OTP creation, successful verification, incorrect OTP, max attempts, and expiration."""
    # 1. Create customer -> starts UNVERIFIED
    cust_res = client.post("/api/v1/customers", json={
        "full_name": "OTP Test Customer",
        "phone": _rand_phone(),
        "credit_limit": 2000.0,
        **DEFAULT_ADDRESS
    })
    assert cust_res.status_code == 201
    cust_id = cust_res.json()["id"]
    assert cust_res.json()["is_phone_verified"] is False
    assert cust_res.json()["phone_verification_status"] == "UNVERIFIED"

    # 2. Request OTP
    otp_req = client.post(f"/api/v1/customers/{cust_id}/request-phone-otp")
    assert otp_req.status_code == 200
    otp_data = otp_req.json()
    assert otp_data["status"] == "OTP_REQUESTED"
    assert otp_data["is_demo"] is True
    demo_otp = otp_data["demo_otp"]
    assert len(demo_otp) == 6

    # 3. Test Incorrect OTP -> Fails with remaining attempts
    bad_res = client.post(f"/api/v1/customers/{cust_id}/verify-phone-otp", json={
        "otp_code": "000000"
    })
    assert bad_res.status_code == 400
    assert "incorrect otp" in bad_res.json()["detail"].lower()
    assert "2 attempt(s) remaining" in bad_res.json()["detail"].lower()

    # 4. Test Correct OTP -> Succeeds and marks customer VERIFIED
    good_res = client.post(f"/api/v1/customers/{cust_id}/verify-phone-otp", json={
        "otp_code": demo_otp
    })
    assert good_res.status_code == 200
    assert good_res.json()["status"] == "VERIFIED"

    # Check database state
    db = SessionLocal()
    try:
        cust_db = db.query(Customer).filter(Customer.id == cust_id).first()
        assert cust_db.is_phone_verified is True
        assert cust_db.phone_verification_status == "VERIFIED"
    finally:
        db.close()

    # 5. Already verified number handles gracefully
    rep_res = client.post(f"/api/v1/customers/{cust_id}/request-phone-otp")
    assert rep_res.status_code == 200
    assert rep_res.json()["status"] == "VERIFIED"


def test_group3_otp_max_attempts_and_expiration():
    """Verify maximum attempts lock and OTP expiration."""
    cust_res = client.post("/api/v1/customers", json={
        "full_name": "Attempt Lock Customer",
        "phone": _rand_phone(),
        "credit_limit": 2000.0,
        **DEFAULT_ADDRESS
    })
    cust_id = cust_res.json()["id"]

    # Request OTP
    client.post(f"/api/v1/customers/{cust_id}/request-phone-otp")

    # 3 bad attempts
    client.post(f"/api/v1/customers/{cust_id}/verify-phone-otp", json={"otp_code": "111111"})
    client.post(f"/api/v1/customers/{cust_id}/verify-phone-otp", json={"otp_code": "222222"})
    third_res = client.post(f"/api/v1/customers/{cust_id}/verify-phone-otp", json={"otp_code": "333333"})
    assert third_res.status_code == 400
    assert "maximum attempts" in third_res.json()["detail"].lower()

    # Further attempt rejected
    fourth_res = client.post(f"/api/v1/customers/{cust_id}/verify-phone-otp", json={"otp_code": "444444"})
    assert fourth_res.status_code == 400

    # Test Expiration
    db = SessionLocal()
    try:
        new_cust = Customer(
            full_name="Expired Customer",
            phone=_rand_phone(),
            credit_limit=2000.0,
            is_active=True
        )
        db.add(new_cust)
        db.commit()
        db.refresh(new_cust)

        expired_otp = PhoneOTPVerification(
            phone=new_cust.phone,
            otp_code="123456",
            entity_type="CUSTOMER",
            entity_id=new_cust.id,
            status="PENDING",
            attempts=0,
            max_attempts=3,
            expires_at=datetime.utcnow() - timedelta(minutes=10)
        )
        db.add(expired_otp)
        db.commit()

        exp_res = client.post(f"/api/v1/customers/{new_cust.id}/verify-phone-otp", json={
            "otp_code": "123456"
        })
        assert exp_res.status_code == 400
        assert "expired" in exp_res.json()["detail"].lower()
    finally:
        db.close()


def test_group3_family_member_phone_verification():
    """Verify family member phone OTP verification flow."""
    cust_res = client.post("/api/v1/customers", json={
        "full_name": "Family Head Verified",
        "phone": _rand_phone(),
        "credit_limit": 3000.0,
        **DEFAULT_ADDRESS
    })
    cust_id = cust_res.json()["id"]

    member_phone = _rand_phone()
    mem_res = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
        "full_name": "Daughter With Phone",
        "relation_type": "Daughter",
        "phone": member_phone
    })
    assert mem_res.status_code == 201
    member_id = mem_res.json()["id"]
    assert mem_res.json()["is_phone_verified"] is False

    # Request OTP for family member
    req_res = client.post(f"/api/v1/customers/{cust_id}/family-members/{member_id}/request-phone-otp")
    assert req_res.status_code == 200
    otp = req_res.json()["demo_otp"]

    # Verify OTP
    v_res = client.post(f"/api/v1/customers/{cust_id}/family-members/{member_id}/verify-phone-otp", json={
        "otp_code": otp
    })
    assert v_res.status_code == 200
    assert v_res.json()["status"] == "VERIFIED"

    # Database check
    db = SessionLocal()
    try:
        mem_db = db.query(FamilyMember).filter(FamilyMember.id == member_id).first()
        assert mem_db.is_phone_verified is True
        assert mem_db.phone_verification_status == "VERIFIED"
    finally:
        db.close()


# ==============================================================================
# 🧪 TEST GROUP 4 — CONTROLLED UDHAAR ACCOUNT DELETION & DATA SAFETY
# ==============================================================================

def test_group4_delete_blocked_when_outstanding_balance_remains():
    """
    Test: Customer balance = Rs. 500
    -> Delete request MUST FAIL (HTTP 400)
    -> Account remains, ledger remains intact.
    Then settle to 0 -> Delete SUCCEEDS (soft deactivation).
    """
    db = SessionLocal()
    try:
        cust = Customer(
            full_name="Debtor Customer",
            phone=_rand_phone(),
            credit_limit=2000.0,
            current_udhaar_balance=500.0,
            is_active=True,
            is_phone_verified=True
        )
        db.add(cust)
        db.commit()
        db.refresh(cust)

        # Attempt deletion while balance is Rs. 500
        del_res = client.delete(f"/api/v1/customers/{cust.id}")
        assert del_res.status_code == 400
        assert "cannot be deleted because outstanding udhaar remains" in del_res.json()["detail"].lower()

        # Verify customer still active
        db.expire_all()
        cust_db = db.query(Customer).filter(Customer.id == cust.id).first()
        assert cust_db.is_active is True
        assert cust_db.current_udhaar_balance == 500.0

        # Now settle debt to Rs. 0
        settle_res = client.post(f"/api/v1/customers/{cust.id}/settle", json={
            "amount": 500.0,
            "payment_mode": "CASH",
            "notes": "Full settlement before account closure"
        })
        assert settle_res.status_code == 200
        assert settle_res.json()["new_balance"] == 0.0

        # Now delete account -> MUST SUCCEED
        del_res_ok = client.delete(f"/api/v1/customers/{cust.id}")
        assert del_res_ok.status_code == 200
        assert del_res_ok.json()["success"] is True

        # Verify soft deactivation and audit preservation
        db.expire_all()
        cust_deactivated = db.query(Customer).filter(Customer.id == cust.id).first()
        assert cust_deactivated is not None
        assert cust_deactivated.is_active is False
        assert cust_deactivated.current_udhaar_balance == 0.0

        # Historical settlement ledger transaction remains intact!
        txs = db.query(UdhaarTransaction).filter(UdhaarTransaction.primary_customer_id == cust.id).all()
        assert len(txs) >= 1
    finally:
        db.close()


def test_group4_foreign_key_and_ledger_integrity_after_deactivation():
    """Verify that completed bills and ledger entries are not orphaned or corrupted."""
    db = SessionLocal()
    try:
        phone = _rand_phone()
        cust = Customer(
            full_name="Historical Audit Customer",
            phone=phone,
            credit_limit=5000.0,
            current_udhaar_balance=0.0,
            is_active=True,
            is_phone_verified=True
        )
        db.add(cust)
        db.commit()
        db.refresh(cust)

        member = FamilyMember(
            primary_customer_id=cust.id,
            full_name="Audit Family Member",
            relation_type="Son",
            is_active=True
        )
        db.add(member)
        db.commit()
        db.refresh(member)

        # Create a bill and ledger record
        bill = Bill(
            bill_number=f"BILL-{secrets.token_hex(4).upper()}",
            customer_id=cust.id,
            family_member_id=member.id,
            subtotal=100.0,
            total_amount=100.0,
            payment_mode="UDHAAR",
            status="COMPLETED"
        )
        db.add(bill)
        db.commit()
        db.refresh(bill)

        tx = UdhaarTransaction(
            primary_customer_id=cust.id,
            family_member_id=member.id,
            bill_id=bill.id,
            amount=100.0,
            transaction_type="DEBIT_PURCHASE",
            balance_before=0.0,
            balance_after=100.0,
            verified_by="PRIMARY_2FA"
        )
        db.add(tx)
        cust.current_udhaar_balance = 100.0
        db.commit()

        # Cannot delete with balance 100
        assert client.delete(f"/api/v1/customers/{cust.id}").status_code == 400

        # Settle
        client.post(f"/api/v1/customers/{cust.id}/settle", json={"amount": 100.0, "payment_mode": "UPI"})

        # Delete (soft deactivation)
        assert client.delete(f"/api/v1/customers/{cust.id}").status_code == 200

        # Verify bills and ledger are safely preserved
        db.expire_all()
        persisted_bill = db.query(Bill).filter(Bill.id == bill.id).first()
        assert persisted_bill is not None
        assert persisted_bill.customer_id == cust.id

        persisted_tx = db.query(UdhaarTransaction).filter(UdhaarTransaction.id == tx.id).first()
        assert persisted_tx is not None
        assert persisted_tx.primary_customer_id == cust.id
        assert persisted_tx.family_member_id == member.id
    finally:
        db.close()


# ==============================================================================
# 🧪 TEST GROUP 5 — SMS MOCK PREVIEW TRANSPARENCY
# ==============================================================================

def test_group5_sms_mock_preview_and_metrics():
    """Verify SMS preview formatting, NOT_CONFIGURED status, and metrics."""
    db = SessionLocal()
    try:
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()

        # Create Cash bill
        bill_res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "CASH"
        })
        bill = bill_res.json()
        bill_id = bill["id"]

        # Call delivery prep
        prep_res = client.post("/api/v1/receipts/delivery-prep", json={
            "bill_id": bill_id,
            "customer_phone": "9876543210"
        })
        assert prep_res.status_code == 200
        sms = prep_res.json()["sms"]

        # 1. Delivery status indicates NOT_CONFIGURED
        assert sms["delivery_status"] == "NOT_CONFIGURED"
        assert sms["is_mock"] is True
        assert "no external sms gateway configured" in sms["note"].lower()

        # 2. Information accuracy
        assert bill["bill_number"] in sms["sms_text"]
        assert f"{bill['total_amount']:.2f}" in sms["sms_text"]
        assert "CASH" in sms["sms_text"]
        assert "1 item(s)" in sms["sms_text"]

        # 3. Message length within 160 chars
        assert sms["char_count"] <= 160

        # 4. Missing phone handled cleanly
        no_phone_res = client.post("/api/v1/receipts/delivery-prep", json={
            "bill_id": bill_id,
            "customer_phone": None
        })
        assert no_phone_res.status_code == 200
        assert no_phone_res.json()["sms"]["customer_phone"] is None
    finally:
        db.close()


# ==============================================================================
# 🌟 FINAL END-TO-END SCENARIO TESTS (SCENARIOS A – F)
# ==============================================================================

def test_scenario_a_cash_purchase_no_2fa():
    """
    SCENARIO A — CASH:
    Customer enters normal purchase -> CASH -> No 2FA -> Bill completed -> Inventory deducted -> Receipt generated.
    """
    db = SessionLocal()
    try:
        tea = db.query(Product).filter(Product.name.like("%Tea%")).first()
        if not tea:
            tea = db.query(Product).first()
        init_stock = tea.stock_quantity

        # Finalize CASH
        res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": tea.id, "quantity": 1.0}],
            "payment_mode": "CASH"
        })
        assert res.status_code == 201
        bill = res.json()
        assert bill["status"] == "COMPLETED"

        # Stock deducted
        db.expire_all()
        tea_db = db.query(Product).filter(Product.id == tea.id).first()
        assert tea_db.stock_quantity == init_stock - 1.0

        # Receipt generated directly
        rcp = client.get(f"/api/v1/receipts/{bill['id']}")
        assert rcp.status_code == 200
        assert rcp.json()["is_verified"] is True
    finally:
        db.close()


def test_scenario_b_upi_purchase_no_2fa():
    """
    SCENARIO B — UPI:
    Customer enters normal purchase -> UPI -> No 2FA -> Bill completed -> Inventory deducted -> Receipt generated.
    """
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        init_stock = prod.stock_quantity

        # Finalize UPI
        res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": prod.id, "quantity": 1.0}],
            "payment_mode": "UPI"
        })
        assert res.status_code == 201
        bill = res.json()
        assert bill["status"] == "COMPLETED"

        # Stock deducted
        db.expire_all()
        prod_db = db.query(Product).filter(Product.id == prod.id).first()
        assert prod_db.stock_quantity == init_stock - 1.0

        # Receipt generated directly
        rcp = client.get(f"/api/v1/receipts/{bill['id']}")
        assert rcp.status_code == 200
        assert rcp.json()["is_verified"] is True
    finally:
        db.close()


def test_scenario_c_udhaar_full_workflow():
    """
    SCENARIO C — UDHAAR:
    Customer -> Verified phone -> Family member -> Verified phone -> Purchase -> UDHAAR
    -> Credit-limit check -> Primary-holder 2FA -> Bill completed -> Inventory deducted -> Ledger updated -> Receipt.
    """
    db = SessionLocal()
    try:
        # 1. Customer with verified phone
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Scenario C Primary",
            "phone": _rand_phone(),
            "credit_limit": 5000.0,
            **DEFAULT_ADDRESS
        })
        cust_id = cust_res.json()["id"]

        otp_req = client.post(f"/api/v1/customers/{cust_id}/request-phone-otp")
        client.post(f"/api/v1/customers/{cust_id}/verify-phone-otp", json={"otp_code": otp_req.json()["demo_otp"]})

        # 2. Family member with verified phone
        mem_res = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
            "full_name": "Scenario C Son",
            "relation_type": "Son",
            "phone": _rand_phone(),
            "allowed_spending_limit": 2000.0
        })
        mem_id = mem_res.json()["id"]

        mem_otp_req = client.post(f"/api/v1/customers/{cust_id}/family-members/{mem_id}/request-phone-otp")
        client.post(f"/api/v1/customers/{cust_id}/family-members/{mem_id}/verify-phone-otp", json={
            "otp_code": mem_otp_req.json()["demo_otp"]
        })

        # 3. Purchase on Udhaar
        prod = db.query(Product).first()
        init_stock = prod.stock_quantity

        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "family_member_id": mem_id,
            "items": [{"product_id": prod.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        assert bill_res.status_code == 201
        bill = bill_res.json()
        assert bill["status"] == "PENDING_VERIFICATION"

        # Stock not deducted
        db.expire_all()
        assert db.query(Product).filter(Product.id == prod.id).first().stock_quantity == init_stock

        # 4. 2FA challenge
        sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill["id"]})
        sess_id = sess_res.json()["session_id"]
        target = db.query(VerificationSession).filter(VerificationSession.id == sess_id).first().target_number

        # 5. Complete 2FA
        v_res = client.post("/api/v1/verification/verify", json={
            "session_id": sess_id,
            "selected_number": target
        })
        assert v_res.status_code == 200
        assert v_res.json()["status"] == "VERIFIED"

        # 6. Stock deducted & ledger updated
        db.expire_all()
        assert db.query(Product).filter(Product.id == prod.id).first().stock_quantity == init_stock - 1.0
        cust_db = db.query(Customer).filter(Customer.id == cust_id).first()
        assert cust_db.current_udhaar_balance == bill["total_amount"]

        # 7. Receipt ready
        rcp = client.get(f"/api/v1/receipts/{bill['id']}")
        assert rcp.status_code == 200
        assert rcp.json()["is_verified"] is True
    finally:
        db.close()


def test_scenario_d_invalid_phone_rejected():
    """
    SCENARIO D — INVALID PHONE:
    Create family member -> Enter "1234" -> Backend rejects -> Record is NOT created.
    """
    cust_res = client.post("/api/v1/customers", json={
        "full_name": "Scenario D Head",
        "phone": _rand_phone(),
        "credit_limit": 2000.0,
        **DEFAULT_ADDRESS
    })
    cust_id = cust_res.json()["id"]

    res = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
        "full_name": "Invalid Member",
        "relation_type": "Brother",
        "phone": "1234"
    })
    assert res.status_code == 422, f"Expected 422, got {res.status_code}"

    # Confirm member was not created
    db = SessionLocal()
    try:
        members = db.query(FamilyMember).filter(FamilyMember.primary_customer_id == cust_id).all()
        assert len(members) == 0
    finally:
        db.close()


def test_scenario_e_outstanding_udhaar_delete_rejected():
    """
    SCENARIO E — OUTSTANDING UDHAAR DELETE:
    Customer has Rs. 500 outstanding -> Delete account -> Request rejected -> Account and ledger remain intact.
    """
    db = SessionLocal()
    try:
        cust = Customer(
            full_name="Scenario E Customer",
            phone=_rand_phone(),
            credit_limit=2000.0,
            current_udhaar_balance=500.0,
            is_active=True,
            is_phone_verified=True
        )
        db.add(cust)
        db.commit()
        db.refresh(cust)

        del_res = client.delete(f"/api/v1/customers/{cust.id}")
        assert del_res.status_code == 400
        assert "cannot be deleted because outstanding udhaar remains" in del_res.json()["detail"].lower()

        db.expire_all()
        cust_db = db.query(Customer).filter(Customer.id == cust.id).first()
        assert cust_db.is_active is True
        assert cust_db.current_udhaar_balance == 500.0
    finally:
        db.close()


def test_scenario_f_cleared_udhaar_delete_allowed():
    """
    SCENARIO F — CLEARED UDHAAR DELETE:
    Customer outstanding balance = Rs. 0 -> Delete/deactivate -> Allowed -> Historical financial records remain safe.
    """
    db = SessionLocal()
    try:
        cust = Customer(
            full_name="Scenario F Customer",
            phone=_rand_phone(),
            credit_limit=2000.0,
            current_udhaar_balance=0.0,
            is_active=True,
            is_phone_verified=True
        )
        db.add(cust)
        db.commit()
        db.refresh(cust)

        del_res = client.delete(f"/api/v1/customers/{cust.id}")
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True

        db.expire_all()
        cust_db = db.query(Customer).filter(Customer.id == cust.id).first()
        assert cust_db.is_active is False
    finally:
        db.close()
