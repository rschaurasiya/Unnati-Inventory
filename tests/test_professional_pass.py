"""
Comprehensive Test Suite for Professional Improvement Pass (Steps 1–9 Hardening)
Kirana Shopkeeper Assistant

Tests Cover:
- TEST 1: Customer Structured Address Validation (Address Line, City, State, PIN [strictly 6 digits, rejection of letters/<6/>6/blank])
- TEST 2: Thermal Bill Printing for CASH, UPI, and UDHAAR (Direct receipt, 80mm layout, no 2FA for Cash/UPI, 2FA for Udhaar)
- TEST 3: Udhaar Purchase Items Details (Relational line items from Bill -> BillItem -> Product)
- TEST 4: Unique Sequential Customer ID (C-000001, distinct identity for same name/address)
- TEST 5: Family Member Removal/Deactivation (Relational safety, soft-deactivation when transactions exist)
- TEST 6: SMS Verification Channel (Target server-side, 3 candidate numbers, transparent DEMO/NOT_CONFIGURED status)
- TEST 7: WhatsApp Verification Channel (Transparent DEMO/NOT_CONFIGURED status)
- TEST 8: Verification Security (Attempt limit, expiration, single-use, session-bill association, zero mutations on failure)
- TEST 9: Payment Method Backend Enforcement (No 2FA for CASH/UPI, 2FA strictly enforced for UDHAAR)
- SCENARIOS A through F: Complete End-to-End Real-world Workflows
"""
import sys
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import (
    Product, Customer, FamilyMember, Bill, BillItem,
    VerificationSession, UdhaarTransaction
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def ensure_sufficient_stock():
    """Ensure catalog items have stock for repeatable test runs."""
    db = SessionLocal()
    try:
        products = db.query(Product).all()
        for p in products:
            if p.stock_quantity < 50.0:
                p.stock_quantity = 100.0
        db.commit()
    finally:
        db.close()


def _rand_phone() -> str:
    """Generate a unique 10-digit Indian mobile number."""
    return f"9{secrets.randbelow(900000000) + 100000000}"[:10]


VALID_ADDRESS = {
    "address_line": "House No. 25, Main Road",
    "city": "Chandigarh",
    "state": "Chandigarh",
    "pincode": "160017",
    "country": "India"
}


# ==============================================================================
# 🧪 TEST 1 — CUSTOMER ADDRESS VALIDATION
# ==============================================================================

def test_1_valid_customer_address_accepted():
    """Valid structured address must be accepted and persisted in DB."""
    phone = _rand_phone()
    res = client.post("/api/v1/customers", json={
        "full_name": "Valid Address Customer",
        "phone": phone,
        "credit_limit": 3000.0,
        **VALID_ADDRESS
    })
    assert res.status_code == 201
    data = res.json()
    assert data["address_line"] == VALID_ADDRESS["address_line"]
    assert data["city"] == VALID_ADDRESS["city"]
    assert data["state"] == VALID_ADDRESS["state"]
    assert data["pincode"] == "160017"
    assert data["country"] == "India"
    assert data["customer_code"].startswith("C-")

    # Verify DB persistence
    db = SessionLocal()
    try:
        cust = db.query(Customer).filter(Customer.id == data["id"]).first()
        assert cust.address_line == VALID_ADDRESS["address_line"]
        assert cust.city == "Chandigarh"
        assert cust.state == "Chandigarh"
        assert cust.pincode == "160017"
        assert cust.country == "India"
    finally:
        db.close()


def test_1_missing_address_fields_rejected():
    """Missing or empty required address fields must be rejected with 422."""
    phone_base = _rand_phone()

    # Missing address_line
    res1 = client.post("/api/v1/customers", json={
        "full_name": "Missing Address Line",
        "phone": _rand_phone(),
        "credit_limit": 2000.0,
        "city": "Chandigarh",
        "state": "Chandigarh",
        "pincode": "160017"
    })
    assert res1.status_code == 422

    # Blank/empty address_line
    res2 = client.post("/api/v1/customers", json={
        "full_name": "Empty Address Line",
        "phone": _rand_phone(),
        "credit_limit": 2000.0,
        "address_line": "   ",
        "city": "Chandigarh",
        "state": "Chandigarh",
        "pincode": "160017"
    })
    assert res2.status_code == 422

    # Missing city
    res3 = client.post("/api/v1/customers", json={
        "full_name": "Missing City",
        "phone": _rand_phone(),
        "credit_limit": 2000.0,
        "address_line": "House 25",
        "state": "Chandigarh",
        "pincode": "160017"
    })
    assert res3.status_code == 422

    # Blank city
    res4 = client.post("/api/v1/customers", json={
        "full_name": "Empty City",
        "phone": _rand_phone(),
        "credit_limit": 2000.0,
        "address_line": "House 25",
        "city": "",
        "state": "Chandigarh",
        "pincode": "160017"
    })
    assert res4.status_code == 422

    # Missing state
    res5 = client.post("/api/v1/customers", json={
        "full_name": "Missing State",
        "phone": _rand_phone(),
        "credit_limit": 2000.0,
        "address_line": "House 25",
        "city": "Chandigarh",
        "pincode": "160017"
    })
    assert res5.status_code == 422


def test_1_invalid_pincode_rejected():
    """PIN code must contain exactly 6 digits (numbers only, no alphabets/symbols, no <6, no >6)."""
    invalid_pins = [
        "123",        # fewer than 6 digits
        "12345",      # 5 digits
        "1234567",    # 7 digits
        "abc123",     # alphabetic characters
        "16001A",     # alphanumeric
        "16-001",     # symbols
        "      ",     # whitespace only
        ""            # empty
    ]

    for pin in invalid_pins:
        res = client.post("/api/v1/customers", json={
            "full_name": "Invalid PIN Customer",
            "phone": _rand_phone(),
            "credit_limit": 2000.0,
            "address_line": "House 25",
            "city": "Chandigarh",
            "state": "Chandigarh",
            "pincode": pin
        })
        assert res.status_code == 422, f"Expected 422 for PIN '{pin}', got {res.status_code}"


# ==============================================================================
# 🧪 TEST 2 — THERMAL RECEIPT FOR CASH, UPI, AND UDHAAR
# ==============================================================================

def test_2_thermal_receipt_cash_no_2fa():
    """CASH: Create -> Finalize -> Complete directly (NO 2FA) -> Receipt available."""
    db = SessionLocal()
    try:
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": sugar.id, "quantity": 1.5}],
            "payment_mode": "CASH"
        })
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "COMPLETED"
        assert data["payment_mode"] == "CASH"

        # Check receipt
        rcp_res = client.get(f"/api/v1/receipts/{data['id']}")
        assert rcp_res.status_code == 200
        rcp = rcp_res.json()
        assert rcp["payment_mode"] == "CASH"
        assert rcp["is_verified"] is True
        assert "APNA KIRANA STORE" in rcp["formatted_text_receipt"].upper()
        assert data["bill_number"] in rcp["formatted_text_receipt"]
        assert "CASH" in rcp["formatted_text_receipt"]
    finally:
        db.close()


def test_2_thermal_receipt_upi_no_2fa():
    """UPI: Create -> Finalize -> Complete directly (NO 2FA) -> Receipt available."""
    db = SessionLocal()
    try:
        oil = db.query(Product).filter(Product.name.like("%Oil%")).first()
        res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": oil.id, "quantity": 1.0}],
            "payment_mode": "UPI"
        })
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "COMPLETED"
        assert data["payment_mode"] == "UPI"

        rcp_res = client.get(f"/api/v1/receipts/{data['id']}")
        assert rcp_res.status_code == 200
        rcp = rcp_res.json()
        assert rcp["payment_mode"] == "UPI"
        assert rcp["is_verified"] is True
        assert "UPI" in rcp["formatted_text_receipt"]
    finally:
        db.close()


def test_2_thermal_receipt_udhaar_requires_2fa():
    """UDHAAR: Create -> 2FA strictly required -> Receipt blocked until 2FA verified."""
    db = SessionLocal()
    try:
        # Create verified customer
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Receipt Test Customer",
            "phone": _rand_phone(),
            "credit_limit": 5000.0,
            "is_phone_verified": True,
            **VALID_ADDRESS
        })
        cust = cust_res.json()

        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust["id"],
            "items": [{"product_id": sugar.id, "quantity": 2.0}],
            "payment_mode": "UDHAAR"
        })
        assert bill_res.status_code == 201
        bill = bill_res.json()
        assert bill["status"] == "PENDING_VERIFICATION"

        # Receipt is blocked before 2FA
        blocked_rcp = client.get(f"/api/v1/receipts/{bill['id']}")
        assert blocked_rcp.status_code == 403

        # Start 2FA session
        sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill["id"]})
        assert sess_res.status_code == 201
        sess_id = sess_res.json()["session_id"]
        target = db.query(VerificationSession).filter(VerificationSession.id == sess_id).first().target_number

        # Complete 2FA
        verify_res = client.post("/api/v1/verification/verify", json={
            "session_id": sess_id,
            "selected_number": target
        })
        assert verify_res.status_code == 200

        # Receipt is now available and contains customer code and outstanding balance
        rcp_res = client.get(f"/api/v1/receipts/{bill['id']}")
        assert rcp_res.status_code == 200
        rcp = rcp_res.json()
        assert rcp["customer_code"] == cust["customer_code"]
        assert rcp["customer_name"] == cust["full_name"]
        assert "Outstanding Balance" in rcp["formatted_text_receipt"]
        assert "Customer ID:" in rcp["formatted_text_receipt"]
        # Sensitive target number and 2FA challenge info must NEVER appear on receipt
        assert "target_number" not in rcp["formatted_text_receipt"].lower()
        assert "challenge" not in rcp["formatted_text_receipt"].lower()
        assert f"target: {target}" not in rcp["formatted_text_receipt"].lower()
    finally:
        db.close()


# ==============================================================================
# 🧪 TEST 3 — UDHAAR MUST SHOW WHAT WAS PURCHASED
# ==============================================================================

def test_3_udhaar_shows_purchased_items():
    """
    Create Udhaar bill with Sugar, Milk, Maggi.
    Verify Udhaar transaction details show all products, quantities, units, rates, and line totals
    sourced relationally from Bill -> BillItem -> Product without duplication.
    """
    db = SessionLocal()
    try:
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Item Detail Customer",
            "phone": _rand_phone(),
            "credit_limit": 5000.0,
            "is_phone_verified": True,
            **VALID_ADDRESS
        })
        cust_id = cust_res.json()["id"]

        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        milk = db.query(Product).filter(Product.name.like("%Milk%")).first()
        maggi = db.query(Product).filter(Product.name.like("%Maggi%")).first()

        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [
                {"product_id": sugar.id, "quantity": 2.0},
                {"product_id": milk.id, "quantity": 3.0},
                {"product_id": maggi.id, "quantity": 2.0}
            ],
            "payment_mode": "UDHAAR"
        })
        assert bill_res.status_code == 201
        bill = bill_res.json()

        # Complete 2FA
        sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill["id"]})
        sess_id = sess_res.json()["session_id"]
        target = db.query(VerificationSession).filter(VerificationSession.id == sess_id).first().target_number
        client.post("/api/v1/verification/verify", json={"session_id": sess_id, "selected_number": target})

        # Query customer ledger
        ledger_res = client.get(f"/api/v1/customers/{cust_id}/ledger")
        assert ledger_res.status_code == 200
        txs = ledger_res.json()
        assert len(txs) >= 1

        debit_tx = [t for t in txs if t["bill_id"] == bill["id"]][0]
        assert len(debit_tx["items"]) == 3

        item_names = [it["product_name"] for it in debit_tx["items"]]
        assert any("Sugar" in n for n in item_names)
        assert any("Milk" in n for n in item_names)
        assert any("Maggi" in n for n in item_names)

        # Verify quantities and rates
        for it in debit_tx["items"]:
            assert it["quantity"] > 0
            assert it["unit_price"] > 0
            assert it["line_total"] == round(it["quantity"] * it["unit_price"], 2)

        # Also check customer profile endpoint
        prof_res = client.get(f"/api/v1/customers/{cust_id}")
        assert prof_res.status_code == 200
        prof = prof_res.json()
        prof_tx = [t for t in prof["transactions"] if t["bill_id"] == bill["id"]][0]
        assert len(prof_tx["items"]) == 3
    finally:
        db.close()


# ==============================================================================
# 🧪 TEST 4 — UNIQUE CUSTOMER ID
# ==============================================================================

def test_4_unique_customer_id_for_identical_names_and_addresses():
    """
    Two customers with the exact same name and address must have distinct, sequential
    Customer IDs (e.g. C-000001 != C-000002) and remain independently searchable.
    """
    phone1 = _rand_phone()
    phone2 = _rand_phone()

    cust1_res = client.post("/api/v1/customers", json={
        "full_name": "Rahul Kumar Singh",
        "phone": phone1,
        "credit_limit": 3000.0,
        **VALID_ADDRESS
    })
    assert cust1_res.status_code == 201
    c1 = cust1_res.json()

    cust2_res = client.post("/api/v1/customers", json={
        "full_name": "Rahul Kumar Singh",
        "phone": phone2,
        "credit_limit": 4000.0,
        **VALID_ADDRESS
    })
    assert cust2_res.status_code == 201
    c2 = cust2_res.json()

    # IDs must be unique
    assert c1["id"] != c2["id"]
    assert c1["customer_code"] != c2["customer_code"]
    assert c1["customer_code"].startswith("C-")
    assert c2["customer_code"].startswith("C-")

    # Search by Customer ID
    search1 = client.get(f"/api/v1/customers?query={c1['customer_code']}")
    assert search1.status_code == 200
    results1 = search1.json()
    assert len(results1) == 1
    assert results1[0]["id"] == c1["id"]

    search2 = client.get(f"/api/v1/customers?query={c2['customer_code']}")
    assert search2.status_code == 200
    results2 = search2.json()
    assert len(results2) == 1
    assert results2[0]["id"] == c2["id"]


# ==============================================================================
# 🧪 TEST 5 — FAMILY MEMBER REMOVAL / DEACTIVATION
# ==============================================================================

def test_5_family_member_safe_deletion_without_history():
    """Family member with NO transaction history can be deleted or removed safely."""
    cust_res = client.post("/api/v1/customers", json={
        "full_name": "Family Removal Head 1",
        "phone": _rand_phone(),
        "credit_limit": 3000.0,
        **VALID_ADDRESS
    })
    cust_id = cust_res.json()["id"]

    mem_res = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
        "full_name": "Temporary Member",
        "relation_type": "Cousin"
    })
    mem_id = mem_res.json()["id"]

    # Remove member
    del_res = client.delete(f"/api/v1/customers/{cust_id}/family-members/{mem_id}")
    assert del_res.status_code == 200

    # Verify not available in family members or marked inactive
    cust_check = client.get(f"/api/v1/customers/{cust_id}").json()
    active_mems = [m for m in cust_check.get("family_members", []) if m["id"] == mem_id and m.get("is_active", True)]
    assert len(active_mems) == 0


def test_5_family_member_soft_deactivation_with_history():
    """
    Family member with historical Udhaar transactions must be soft-deactivated (is_active=False).
    Historical transactions must remain intact and inactive member cannot make new purchases.
    """
    db = SessionLocal()
    try:
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Family Removal Head 2",
            "phone": _rand_phone(),
            "credit_limit": 5000.0,
            "is_phone_verified": True,
            **VALID_ADDRESS
        })
        cust_id = cust_res.json()["id"]

        mem_res = client.post(f"/api/v1/customers/{cust_id}/family-members", json={
            "full_name": "Historical Member",
            "relation_type": "Son"
        })
        mem_id = mem_res.json()["id"]

        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()

        # Create historical transaction
        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "family_member_id": mem_id,
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        bill_id = bill_res.json()["id"]

        # Complete 2FA
        sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
        sess_id = sess_res.json()["session_id"]
        target = db.query(VerificationSession).filter(VerificationSession.id == sess_id).first().target_number
        client.post("/api/v1/verification/verify", json={"session_id": sess_id, "selected_number": target})

        # Now remove/deactivate the member
        del_res = client.delete(f"/api/v1/customers/{cust_id}/family-members/{mem_id}")
        assert del_res.status_code == 200
        del_data = del_res.json()
        assert del_data["action"] == "DEACTIVATED"

        # Check member in DB: is_active is False
        db.expire_all()
        mem_db = db.query(FamilyMember).filter(FamilyMember.id == mem_id).first()
        assert mem_db is not None
        assert mem_db.is_active is False

        # Historical bill and ledger record remain intact
        bill_db = db.query(Bill).filter(Bill.id == bill_id).first()
        assert bill_db.family_member_id == mem_id
        tx = db.query(UdhaarTransaction).filter(UdhaarTransaction.bill_id == bill_id).first()
        assert tx is not None
        assert tx.family_member_id == mem_id

        # Inactive member cannot make new Udhaar purchases
        new_buy = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "family_member_id": mem_id,
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        assert new_buy.status_code == 400
        assert "inactive" in new_buy.json()["detail"].lower()
    finally:
        db.close()


# ==============================================================================
# 🧪 TEST 6 — SMS VERIFICATION FLOW
# ==============================================================================

def test_6_sms_verification_flow():
    """
    SMS Verification:
    - Session created with delivery_channel = 'SMS'
    - 3 candidate numbers generated
    - Target number kept server-side
    - Customer name, customer_code, masked phone returned
    - Delivery status clearly indicates DEMO / NOT CONFIGURED
    """
    db = SessionLocal()
    try:
        phone = _rand_phone()
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "SMS Verification User",
            "phone": phone,
            "credit_limit": 4000.0,
            "is_phone_verified": True,
            **VALID_ADDRESS
        })
        cust = cust_res.json()

        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust["id"],
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        bill_id = bill_res.json()["id"]

        # Request SMS verification challenge
        sess_res = client.post("/api/v1/verification/sessions", json={
            "bill_id": bill_id,
            "delivery_channel": "SMS"
        })
        assert sess_res.status_code == 201
        data = sess_res.json()

        assert data["delivery_channel"] == "SMS"
        assert data["delivery_status"] in ["NOT_CONFIGURED", "DEMO_NOT_CONFIGURED", "SIMULATED", "READY"]
        assert "demo" in data["channel_status_note"].lower() or "not configured" in data["channel_status_note"].lower()
        assert data["customer_code"] == cust["customer_code"]
        assert data["customer_name"] == cust["full_name"]
        assert len(data["challenge_numbers"]) == 3
        # Target number must NOT be in the client response
        assert "target_number" not in data

        # Message preview contains OTP (for OTP verification) or candidate numbers (for matching challenge)
        assert data["delivery_message_preview"] is not None
        if data.get("verification_type") == "OTP":
            assert str(data.get("demo_otp") or "") in data["delivery_message_preview"]
        else:
            for n in data["challenge_numbers"]:
                assert str(n) in data["delivery_message_preview"]
    finally:
        db.close()


# ==============================================================================
# 🧪 TEST 7 — WHATSAPP VERIFICATION FLOW
# ==============================================================================

def test_7_whatsapp_verification_flow():
    """
    WhatsApp Verification:
    - Session created with delivery_channel = 'WHATSAPP'
    - Delivery status indicates DEMO / NOT CONFIGURED
    - Customer details returned with preview message
    """
    db = SessionLocal()
    try:
        phone = _rand_phone()
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "WhatsApp Verification User",
            "phone": phone,
            "credit_limit": 4000.0,
            "is_phone_verified": True,
            **VALID_ADDRESS
        })
        cust = cust_res.json()

        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust["id"],
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        bill_id = bill_res.json()["id"]

        sess_res = client.post("/api/v1/verification/sessions", json={
            "bill_id": bill_id,
            "delivery_channel": "WHATSAPP"
        })
        assert sess_res.status_code == 201
        data = sess_res.json()

        assert data["delivery_channel"] == "WHATSAPP"
        assert "whatsapp" in data["channel_status_note"].lower()
        assert len(data["challenge_numbers"]) == 3
        assert "target_number" not in data
    finally:
        db.close()


# ==============================================================================
# 🧪 TEST 8 — VERIFICATION SECURITY
# ==============================================================================

def test_8_verification_unverified_phone_blocked():
    """Udhaar 2FA session must be rejected if primary customer phone is not verified."""
    db = SessionLocal()
    try:
        # Create UNVERIFIED customer
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Unverified Phone Cust",
            "phone": _rand_phone(),
            "credit_limit": 3000.0,
            "is_phone_verified": False,
            **VALID_ADDRESS
        })
        cust_id = cust_res.json()["id"]

        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        bill_id = bill_res.json()["id"]

        # Attempt to create verification challenge
        sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
        assert sess_res.status_code == 400
        assert "phone number is not verified" in sess_res.json()["detail"].lower()
    finally:
        db.close()


def test_8_verification_attempts_and_bill_mismatch():
    """Test attempt limits, wrong bill association, and failed verification integrity."""
    db = SessionLocal()
    try:
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Security Test Cust",
            "phone": _rand_phone(),
            "credit_limit": 3000.0,
            "is_phone_verified": True,
            **VALID_ADDRESS
        })
        cust_id = cust_res.json()["id"]

        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        init_stock = sugar.stock_quantity

        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": sugar.id, "quantity": 2.0}],
            "payment_mode": "UDHAAR"
        })
        bill_id = bill_res.json()["id"]

        sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
        s_data = sess_res.json()
        sess_id = s_data["session_id"]

        session_db = db.query(VerificationSession).filter(VerificationSession.id == sess_id).first()
        wrong_num = [n for n in s_data["challenge_numbers"] if n != session_db.target_number][0]

        # 1. Wrong bill_id association check
        mismatch_res = client.post("/api/v1/verification/verify", json={
            "session_id": sess_id,
            "selected_number": session_db.target_number,
            "bill_id": 999999
        })
        assert mismatch_res.status_code == 400
        assert "does not match" in mismatch_res.json()["detail"].lower()

        # 2. Wrong candidate number submission fails cleanly
        v1 = client.post("/api/v1/verification/verify", json={"session_id": sess_id, "selected_number": wrong_num})
        assert v1.status_code == 200
        assert v1.json()["success"] is False
        assert v1.json()["status"] == "FAILED"

        # 3. Subsequent attempt on now-failed session is rejected with 400
        v2 = client.post("/api/v1/verification/verify", json={"session_id": sess_id, "selected_number": wrong_num})
        assert v2.status_code == 400
        assert "session failed" in v2.json()["detail"].lower() or "maximum" in v2.json()["detail"].lower()

        # 4. Attempt with correct target on failed session is also rejected
        v3 = client.post("/api/v1/verification/verify", json={"session_id": sess_id, "selected_number": session_db.target_number})
        assert v3.status_code == 400

        # 5. Confirm zero mutations
        db.expire_all()
        assert db.query(Product).filter(Product.id == sugar.id).first().stock_quantity == init_stock
        assert db.query(Customer).filter(Customer.id == cust_id).first().current_udhaar_balance == 0.0
    finally:
        db.close()


# ==============================================================================
# 🧪 TEST 9 — PAYMENT METHOD BACKEND ENFORCEMENT
# ==============================================================================

def test_9_payment_method_backend_enforcement():
    """Verify backend enforcement: CASH & UPI complete immediately; UDHAAR requires 2FA."""
    db = SessionLocal()
    try:
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()

        # CASH -> COMPLETED
        cash_res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "CASH"
        })
        assert cash_res.status_code == 201
        assert cash_res.json()["status"] == "COMPLETED"

        # UPI -> COMPLETED
        upi_res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "UPI"
        })
        assert upi_res.status_code == 201
        assert upi_res.json()["status"] == "COMPLETED"

        # UDHAAR -> PENDING_VERIFICATION
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Payment Mode Enforce Cust",
            "phone": _rand_phone(),
            "credit_limit": 3000.0,
            "is_phone_verified": True,
            **VALID_ADDRESS
        })
        cust_id = cust_res.json()["id"]

        udh_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": sugar.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        assert udh_res.status_code == 201
        assert udh_res.json()["status"] == "PENDING_VERIFICATION"
    finally:
        db.close()


# ==============================================================================
# 🧪 FINAL END-TO-END SCENARIOS A THROUGH F
# ==============================================================================

def test_scenario_a_cash():
    """Scenario A: Create bill -> CASH -> Finalize -> Completed -> Stock deducted once -> Thermal receipt."""
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        init_stock = prod.stock_quantity

        res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": prod.id, "quantity": 2.0}],
            "payment_mode": "CASH"
        })
        assert res.status_code == 201
        bill = res.json()
        assert bill["status"] == "COMPLETED"

        db.expire_all()
        assert db.query(Product).filter(Product.id == prod.id).first().stock_quantity == round(init_stock - 2.0, 3)

        rcp = client.get(f"/api/v1/receipts/{bill['id']}").json()
        assert rcp["payment_mode"] == "CASH"
        assert rcp["is_verified"] is True
    finally:
        db.close()


def test_scenario_b_upi():
    """Scenario B: Create bill -> UPI -> Finalize -> Completed -> Stock deducted once -> Thermal receipt."""
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        init_stock = prod.stock_quantity

        res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": prod.id, "quantity": 1.5}],
            "payment_mode": "UPI"
        })
        assert res.status_code == 201
        bill = res.json()
        assert bill["status"] == "COMPLETED"

        db.expire_all()
        assert db.query(Product).filter(Product.id == prod.id).first().stock_quantity == round(init_stock - 1.5, 3)

        rcp = client.get(f"/api/v1/receipts/{bill['id']}").json()
        assert rcp["payment_mode"] == "UPI"
        assert rcp["is_verified"] is True
    finally:
        db.close()


def test_scenario_c_udhaar_sms():
    """Scenario C: Verified customer & phone -> UDHAAR -> Credit limit check -> Finalize -> SMS challenge -> Customer verifies -> Completed -> Stock deducted once -> Ledger updated -> Receipt available."""
    db = SessionLocal()
    try:
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Scenario C Customer",
            "phone": _rand_phone(),
            "credit_limit": 5000.0,
            "is_phone_verified": True,
            **VALID_ADDRESS
        })
        cust = cust_res.json()

        prod = db.query(Product).first()
        init_stock = prod.stock_quantity

        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust["id"],
            "items": [{"product_id": prod.id, "quantity": 2.0}],
            "payment_mode": "UDHAAR"
        })
        assert bill_res.status_code == 201
        bill = bill_res.json()
        assert bill["status"] == "PENDING_VERIFICATION"

        # Stock not deducted
        db.expire_all()
        assert db.query(Product).filter(Product.id == prod.id).first().stock_quantity == init_stock

        # Choose SMS verification
        sess_res = client.post("/api/v1/verification/sessions", json={
            "bill_id": bill["id"],
            "delivery_channel": "SMS"
        })
        assert sess_res.status_code == 201
        s_data = sess_res.json()
        assert s_data["delivery_channel"] == "SMS"

        # Verify target
        target = db.query(VerificationSession).filter(VerificationSession.id == s_data["session_id"]).first().target_number
        v_res = client.post("/api/v1/verification/verify", json={
            "session_id": s_data["session_id"],
            "selected_number": target,
            "bill_id": bill["id"]
        })
        assert v_res.status_code == 200
        assert v_res.json()["success"] is True

        # Stock deducted once & ledger updated
        db.expire_all()
        assert db.query(Product).filter(Product.id == prod.id).first().stock_quantity == round(init_stock - 2.0, 3)
        assert db.query(Customer).filter(Customer.id == cust["id"]).first().current_udhaar_balance == bill["total_amount"]

        # Receipt available
        rcp = client.get(f"/api/v1/receipts/{bill['id']}").json()
        assert rcp["is_verified"] is True
        assert rcp["customer_code"] == cust["customer_code"]
    finally:
        db.close()


def test_scenario_d_udhaar_whatsapp():
    """Scenario D: Same flow using WhatsApp verification."""
    db = SessionLocal()
    try:
        cust_res = client.post("/api/v1/customers", json={
            "full_name": "Scenario D Customer",
            "phone": _rand_phone(),
            "credit_limit": 5000.0,
            "is_phone_verified": True,
            **VALID_ADDRESS
        })
        cust = cust_res.json()

        prod = db.query(Product).first()
        init_stock = prod.stock_quantity

        bill_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust["id"],
            "items": [{"product_id": prod.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        bill = bill_res.json()

        sess_res = client.post("/api/v1/verification/sessions", json={
            "bill_id": bill["id"],
            "delivery_channel": "WHATSAPP"
        })
        assert sess_res.status_code == 201
        s_data = sess_res.json()
        assert s_data["delivery_channel"] == "WHATSAPP"

        target = db.query(VerificationSession).filter(VerificationSession.id == s_data["session_id"]).first().target_number
        v_res = client.post("/api/v1/verification/verify", json={
            "session_id": s_data["session_id"],
            "selected_number": target,
            "bill_id": bill["id"]
        })
        assert v_res.status_code == 200

        db.expire_all()
        assert db.query(Product).filter(Product.id == prod.id).first().stock_quantity == round(init_stock - 1.0, 3)
    finally:
        db.close()


def test_scenario_e_same_customer_details():
    """Scenario E: Two customers with identical name and address -> separate Customer IDs & accounts."""
    c1 = client.post("/api/v1/customers", json={
        "full_name": "Amit Singhal",
        "phone": _rand_phone(),
        "credit_limit": 3000.0,
        **VALID_ADDRESS
    }).json()

    c2 = client.post("/api/v1/customers", json={
        "full_name": "Amit Singhal",
        "phone": _rand_phone(),
        "credit_limit": 4000.0,
        **VALID_ADDRESS
    }).json()

    assert c1["id"] != c2["id"]
    assert c1["customer_code"] != c2["customer_code"]
    assert c1["credit_limit"] == 3000.0
    assert c2["credit_limit"] == 4000.0


def test_scenario_f_family_member_removal_lifecycle():
    """Scenario F: Add family member -> make purchase -> deactivate -> unavailable for new purchases -> history safe."""
    db = SessionLocal()
    try:
        cust = client.post("/api/v1/customers", json={
            "full_name": "Scenario F Head",
            "phone": _rand_phone(),
            "credit_limit": 5000.0,
            "is_phone_verified": True,
            **VALID_ADDRESS
        }).json()

        mem = client.post(f"/api/v1/customers/{cust['id']}/family-members", json={
            "full_name": "Scenario F Daughter",
            "relation_type": "Daughter"
        }).json()

        prod = db.query(Product).first()

        # 1. Successful purchase by daughter
        b_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust["id"],
            "family_member_id": mem["id"],
            "items": [{"product_id": prod.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        b_id = b_res.json()["id"]

        sess_id = client.post("/api/v1/verification/sessions", json={"bill_id": b_id}).json()["session_id"]
        target = db.query(VerificationSession).filter(VerificationSession.id == sess_id).first().target_number
        client.post("/api/v1/verification/verify", json={"session_id": sess_id, "selected_number": target})

        # 2. Deactivate daughter
        client.delete(f"/api/v1/customers/{cust['id']}/family-members/{mem['id']}")

        # 3. Daughter cannot make new purchase
        rej_res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust["id"],
            "family_member_id": mem["id"],
            "items": [{"product_id": prod.id, "quantity": 1.0}],
            "payment_mode": "UDHAAR"
        })
        assert rej_res.status_code == 400

        # 4. Historical transaction remains intact in ledger
        ledger = client.get(f"/api/v1/customers/{cust['id']}/ledger").json()
        assert any(t["family_member_name"] == "Scenario F Daughter" for t in ledger)
    finally:
        db.close()
