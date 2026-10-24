"""
Test Suite for Issue 1 (Udhaar 2FA Customer Details) and Issue 2 (Thermal Print Flow)
"""
import random
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Customer, Product, Bill, VerificationSession, ShopProfile

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_shop_name_for_issue2():
    db = SessionLocal()
    shop = db.query(ShopProfile).first()
    if shop:
        shop.shop_name = "Apna Kirana Store"
        db.commit()
    db.close()
    yield

VALID_ADDRESS = {
    "address_line": "Shop 42, Market Complex",
    "city": "Chandigarh",
    "state": "Chandigarh",
    "pincode": "160017",
    "country": "India"
}


def _rand_phone():
    return f"9{random.randint(100000000, 999999999)}"


# ==============================================================================
# 🔐 ISSUE 1: UDHAAR 2FA CUSTOMER DETAILS TESTS
# ==============================================================================

def test_issue1_udhaar_2fa_customer_details_flow():
    """
    Test Complete Flow for Issue 1:
    1. Create Udhaar customer with name, customer ID, valid phone, verified status.
    2. Create Udhaar bill for that customer.
    3. Finalize returns authoritative customer details.
    4. Create verification session.
    5. API response contains correct customer_id, customer_code, customer_name, customer_phone_masked, is_phone_verified.
    6. Masked phone follows format (e.g. 98******10).
    7. Secret target number is NOT exposed.
    """
    phone = _rand_phone()
    cust_res = client.post("/api/v1/customers", json={
        "full_name": "Rahul Kumar Singh",
        "phone": phone,
        "credit_limit": 5000.0,
        "is_phone_verified": True,
        **VALID_ADDRESS
    })
    assert cust_res.status_code == 201
    cust = cust_res.json()
    cust_id = cust["id"]
    cust_code = cust["customer_code"]

    products = client.get("/api/v1/products").json()
    prod = products[0]

    # Finalize bill on Udhaar
    bill_res = client.post("/api/v1/billing/finalize", json={
        "customer_id": cust_id,
        "items": [{"product_id": prod["id"], "quantity": 1}],
        "payment_mode": "UDHAAR"
    })
    assert bill_res.status_code == 201
    bill = bill_res.json()

    # Authoritative customer data in bill response
    assert bill["customer_id"] == cust_id
    assert bill["customer_code"] == cust_code
    assert bill["customer_name"] == "Rahul Kumar Singh"
    assert bill["is_phone_verified"] is True
    expected_mask = f"{phone[:2]}******{phone[-2:]}"
    assert bill["customer_phone_masked"] == expected_mask

    # Create verification session
    sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill["id"]})
    assert sess_res.status_code == 201
    session = sess_res.json()

    # Authoritative customer data in verification session response
    assert session["customer_id"] == cust_id
    assert session["customer_code"] == cust_code
    assert session["customer_name"] == "Rahul Kumar Singh"
    assert session["is_phone_verified"] is True
    assert session["customer_phone_masked"] == expected_mask

    # Security check: secret target is NOT exposed
    assert "target_number" not in session
    assert len(session["challenge_numbers"]) == 3


def test_issue1_similar_names_cross_account_isolation():
    """
    Create two different customers with the exact same name 'Rahul Kumar Singh'.
    Create verification for Customer B.
    Ensure Customer B's customer_id, customer_code, and masked phone appear.
    Ensure Customer A's details do NOT appear accidentally.
    """
    phone_a = _rand_phone()
    phone_b = _rand_phone()

    cust_a = client.post("/api/v1/customers", json={
        "full_name": "Rahul Kumar Singh",
        "phone": phone_a,
        "credit_limit": 4000.0,
        "is_phone_verified": True,
        **VALID_ADDRESS
    }).json()

    cust_b = client.post("/api/v1/customers", json={
        "full_name": "Rahul Kumar Singh",
        "phone": phone_b,
        "credit_limit": 6000.0,
        "is_phone_verified": True,
        **VALID_ADDRESS
    }).json()

    assert cust_a["id"] != cust_b["id"]
    assert cust_a["customer_code"] != cust_b["customer_code"]

    products = client.get("/api/v1/products").json()
    prod = products[0]

    # Create bill for Customer B
    bill_b = client.post("/api/v1/billing/finalize", json={
        "customer_id": cust_b["id"],
        "items": [{"product_id": prod["id"], "quantity": 1}],
        "payment_mode": "UDHAAR"
    }).json()

    # Create verification session for Customer B
    sess_b = client.post("/api/v1/verification/sessions", json={"bill_id": bill_b["id"]}).json()

    # Strictly verify Customer B's attributes are returned
    assert sess_b["customer_id"] == cust_b["id"]
    assert sess_b["customer_code"] == cust_b["customer_code"]
    assert sess_b["customer_phone_masked"] == f"{phone_b[:2]}******{phone_b[-2:]}"

    # Verify Customer A's details do NOT leak
    assert sess_b["customer_id"] != cust_a["id"]
    assert sess_b["customer_code"] != cust_a["customer_code"]
    assert sess_b["customer_phone_masked"] != f"{phone_a[:2]}******{phone_a[-2:]}"


def test_issue1_unverified_customer_phone_display_and_blocked():
    """
    If customer phone is not verified:
    - Finalized bill response shows is_phone_verified=False and customer_phone_masked=None.
    - Verification session creation is blocked with 400 Bad Request.
    """
    phone = _rand_phone()
    cust = client.post("/api/v1/customers", json={
        "full_name": "Unverified Cust",
        "phone": phone,
        "credit_limit": 3000.0,
        "is_phone_verified": False,
        **VALID_ADDRESS
    }).json()

    products = client.get("/api/v1/products").json()
    prod = products[0]

    bill = client.post("/api/v1/billing/finalize", json={
        "customer_id": cust["id"],
        "items": [{"product_id": prod["id"], "quantity": 1}],
        "payment_mode": "UDHAAR"
    }).json()

    assert bill["customer_id"] == cust["id"]
    assert bill["is_phone_verified"] is False
    assert bill["customer_phone_masked"] is None

    # Verification session creation must fail with 400 Bad Request
    sess_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill["id"]})
    assert sess_res.status_code == 400
    assert "phone number is not verified" in sess_res.json()["detail"].lower()


def test_issue1_step7_verification_success_failure_cycle():
    """Existing Step 7 number-matching verification success and failure behavior still works."""
    phone = _rand_phone()
    cust = client.post("/api/v1/customers", json={
        "full_name": "Step7 Test Cust",
        "phone": phone,
        "credit_limit": 5000.0,
        "is_phone_verified": True,
        **VALID_ADDRESS
    }).json()

    products = client.get("/api/v1/products").json()
    prod = products[0]

    bill = client.post("/api/v1/billing/finalize", json={
        "customer_id": cust["id"],
        "items": [{"product_id": prod["id"], "quantity": 1}],
        "payment_mode": "UDHAAR"
    }).json()

    sess = client.post("/api/v1/verification/sessions", json={"bill_id": bill["id"]}).json()
    session_id = sess["session_id"]
    candidates = sess["challenge_numbers"]

    # Get secret target from DB
    db = SessionLocal()
    target = db.query(VerificationSession).filter(VerificationSession.id == session_id).first().target_number
    db.close()

    # Wrong number submission
    wrong_num = next(n for n in candidates if n != target)
    fail_res = client.post("/api/v1/verification/verify", json={
        "session_id": session_id,
        "selected_number": wrong_num
    })
    assert fail_res.status_code == 200
    assert fail_res.json()["success"] is False
    assert fail_res.json()["status"] == "FAILED"

    # Regenerate session and verify with correct number
    new_sess = client.post("/api/v1/verification/sessions", json={"bill_id": bill["id"]}).json()
    db = SessionLocal()
    new_target = db.query(VerificationSession).filter(VerificationSession.id == new_sess["session_id"]).first().target_number
    db.close()

    success_res = client.post("/api/v1/verification/verify", json={
        "session_id": new_sess["session_id"],
        "selected_number": new_target
    })
    assert success_res.status_code == 200
    assert success_res.json()["success"] is True
    assert success_res.json()["status"] == "VERIFIED"


# ==============================================================================
# 🖨️ ISSUE 2: THERMAL PRINT FLOW TESTS
# ==============================================================================

def test_issue2_cash_thermal_receipt_workflow():
    """
    CASH bill:
    - Finalizes immediately with COMPLETED status (no 2FA).
    - Thermal receipt can be retrieved via delivery-prep immediately.
    - Receipt formatted for thermal printing contains store header, bill number, items, and totals.
    - No 2FA candidate numbers or targets appear in receipt.
    """
    products = client.get("/api/v1/products").json()
    prod = products[0]

    bill = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod["id"], "quantity": 2}],
        "payment_mode": "CASH"
    }).json()

    assert bill["status"] == "COMPLETED"
    assert bill["payment_mode"] == "CASH"

    prep_res = client.post("/api/v1/receipts/delivery-prep", json={"bill_id": bill["id"]})
    assert prep_res.status_code == 200
    prep_data = prep_res.json()

    assert "receipt" in prep_data
    receipt_text = prep_data["receipt"]["formatted_text_receipt"]

    assert "APNA KIRANA STORE" in receipt_text
    assert bill["bill_number"] in receipt_text
    assert "Payment:    CASH" in receipt_text
    assert ("GRAND TOTAL:" in receipt_text and f"Rs. {bill['total_amount']:.2f}" in receipt_text)
    assert "target_number" not in receipt_text
    assert "challenge_numbers" not in receipt_text


def test_issue2_upi_thermal_receipt_workflow():
    """
    UPI bill:
    - Finalizes immediately with COMPLETED status (no 2FA).
    - Thermal receipt can be retrieved via delivery-prep immediately.
    - Receipt formatted for thermal printing contains store header, bill number, items, and totals.
    """
    products = client.get("/api/v1/products").json()
    prod = products[0]

    bill = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod["id"], "quantity": 1}],
        "payment_mode": "UPI"
    }).json()

    assert bill["status"] == "COMPLETED"
    assert bill["payment_mode"] == "UPI"

    prep_res = client.post("/api/v1/receipts/delivery-prep", json={"bill_id": bill["id"]})
    assert prep_res.status_code == 200
    prep_data = prep_res.json()

    assert "receipt" in prep_data
    receipt_text = prep_data["receipt"]["formatted_text_receipt"]

    assert "APNA KIRANA STORE" in receipt_text
    assert bill["bill_number"] in receipt_text
    assert "Payment:    UPI" in receipt_text
    assert ("GRAND TOTAL:" in receipt_text and f"Rs. {bill['total_amount']:.2f}" in receipt_text)


def test_issue2_udhaar_thermal_receipt_after_verification():
    """
    UDHAAR bill:
    - Blocked from receipt preparation before 2FA verification (403 Forbidden).
    - Verification completed -> Receipt preparation succeeds.
    - Receipt includes customer name, customer ID, masked phone, Udhaar balance.
    """
    phone = _rand_phone()
    cust = client.post("/api/v1/customers", json={
        "full_name": "Deepak Mehta",
        "phone": phone,
        "credit_limit": 8000.0,
        "is_phone_verified": True,
        **VALID_ADDRESS
    }).json()

    products = client.get("/api/v1/products").json()
    prod = products[0]

    bill = client.post("/api/v1/billing/finalize", json={
        "customer_id": cust["id"],
        "items": [{"product_id": prod["id"], "quantity": 1}],
        "payment_mode": "UDHAAR"
    }).json()

    assert bill["status"] == "PENDING_VERIFICATION"

    # Pre-verification receipt access blocked
    blocked_res = client.post("/api/v1/receipts/delivery-prep", json={"bill_id": bill["id"]})
    assert blocked_res.status_code == 403

    # Create verification session and verify
    sess = client.post("/api/v1/verification/sessions", json={"bill_id": bill["id"]}).json()
    db = SessionLocal()
    target = db.query(VerificationSession).filter(VerificationSession.id == sess["session_id"]).first().target_number
    db.close()

    v_res = client.post("/api/v1/verification/verify", json={
        "session_id": sess["session_id"],
        "selected_number": target
    })
    assert v_res.status_code == 200
    assert v_res.json()["success"] is True

    # Post-verification receipt access succeeds
    prep_res = client.post("/api/v1/receipts/delivery-prep", json={"bill_id": bill["id"]})
    assert prep_res.status_code == 200
    prep_data = prep_res.json()

    receipt_text = prep_data["receipt"]["formatted_text_receipt"]
    assert "APNA KIRANA STORE" in receipt_text
    assert bill["bill_number"] in receipt_text
    assert "Payment:    UDHAAR" in receipt_text
    assert f"Customer ID:{cust['customer_code']}" in receipt_text
    assert f"Customer:   {cust['full_name']}" in receipt_text
    assert f"Phone:      {phone[:2]}******{phone[-2:]}" in receipt_text
    assert "Outstanding Balance:" in receipt_text
    assert "target_number" not in receipt_text


def test_issue2_frontend_wiring_and_print_workflow():
    """
    Verify the frontend HTML, JavaScript, and CSS contain all elements and wiring
    for customer 2FA display and thermal print execution.
    """
    try:
        import urllib.request
        index_html = urllib.request.urlopen("http://127.0.0.1:8000/", timeout=1).read().decode("utf-8")
        app_js = urllib.request.urlopen("http://127.0.0.1:8000/static/js/app.js?v=2.1", timeout=1).read().decode("utf-8")
        style_css = urllib.request.urlopen("http://127.0.0.1:8000/static/css/style.css", timeout=1).read().decode("utf-8")
    except Exception:
        index_html = client.get("/").text
        app_js = client.get("/static/js/app.js?v=2.1").text
        style_css = client.get("/static/css/style.css").text

    # 1. Verification customer labels and values in index.html
    assert 'id="udhaar-verif-customer-name"' in index_html
    assert 'id="udhaar-verif-customer-code"' in index_html
    assert 'id="udhaar-verif-customer-phone"' in index_html
    assert 'id="udhaar-verif-phone-label"' in index_html

    # 2. Thermal Print button in index.html
    assert 'id="btn-thermal-print-direct"' in index_html
    assert 'onclick="printThermalReceipt()"' in index_html

    # 3. JavaScript app.js wiring
    assert 'updateVerificationCustomerDisplay' in app_js
    assert 'udhaar-verif-customer-name' in app_js
    assert 'udhaar-verif-customer-code' in app_js
    assert 'udhaar-verif-customer-phone' in app_js
    assert 'window.printThermalReceipt' in app_js
    assert 'btn-thermal-print-direct' in app_js
    assert 'prepareDigitalReceiptDelivery' in app_js

    # 4. Print CSS in style.css
    assert '@media print' in style_css
    assert '#thermal-receipt-container' in style_css
    assert '80mm' in style_css

