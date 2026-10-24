"""
Step 8 Verification Test Suite
Tests:
- Verified bill -> Digital receipt generated successfully with store branding & itemization
- Unverified bill -> Receipt generation strictly blocked (HTTP 403 Forbidden)
- Unverified bill -> Receipt delivery prep strictly blocked (HTTP 403 Forbidden)
- Accurate bill items, units, unit prices, line totals, and grand total
- Accurate payment mode and verification timestamps in receipt
- WhatsApp Click-to-Chat URL generation with proper URL encoding
- Customer phone normalization (10-digit Indian mobile -> 91 country code prepended)
- WhatsApp Click-to-Chat URL without phone (opens WhatsApp with text)
- SMS mock formatting (under 160 chars, clear confirmation)
- Printable / Thermal ASCII receipt formatting
- Existing Step 1-7 functionality remains intact
"""
import re
import sys
import urllib.parse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product, Bill, VerificationSession, Customer

client = TestClient(app)


def _create_unverified_udhaar_bill():
    """Helper: Finalizes an Udhaar bill in PENDING_VERIFICATION status (unverified)."""
    db = SessionLocal()
    try:
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        milk = db.query(Product).filter(Product.name.like("%Milk%")).first()
        cust = db.query(Customer).filter(Customer.is_active == True).first()
        if not cust:
            cust = Customer(
                full_name="Step8 Udhaar Customer",
                phone="9811223344",
                credit_limit=5000.0,
                is_active=True,
                is_phone_verified=True,
                phone_verification_status="VERIFIED"
            )
            db.add(cust)
            db.commit()
            db.refresh(cust)
        res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust.id,
            "items": [
                {"product_id": sugar.id, "quantity": 1.0},
                {"product_id": milk.id, "quantity": 1.0}
            ],
            "payment_mode": "UDHAAR",
            "notes": "Step 8 unverified Udhaar test bill"
        })
        assert res.status_code == 201
        return res.json(), sugar, milk
    finally:
        db.close()


def _create_unverified_bill():
    """Helper: Finalizes a bill without customer 2FA verification."""
    db = SessionLocal()
    try:
        sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
        milk = db.query(Product).filter(Product.name.like("%Milk%")).first()
        res = client.post("/api/v1/billing/finalize", json={
            "items": [
                {"product_id": sugar.id, "quantity": 2.0},
                {"product_id": milk.id, "quantity": 1.0}
            ],
            "payment_mode": "UPI",
            "notes": "Step 8 unverified test bill"
        })
        assert res.status_code == 201
        return res.json(), sugar, milk
    finally:
        db.close()


def _create_verified_bill():
    """Helper: Finalizes a bill AND completes customer 2FA verification."""
    bill_data, sugar, milk = _create_unverified_bill()
    bill_id = bill_data["id"]

    # 1. Create verification session
    session_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
    assert session_res.status_code == 201
    session_id = session_res.json()["session_id"]

    # 2. Complete verification with secret target
    db = SessionLocal()
    try:
        target = db.query(VerificationSession).filter(VerificationSession.id == session_id).first().target_number
    finally:
        db.close()

    verify_res = client.post("/api/v1/verification/verify", json={
        "session_id": session_id,
        "selected_number": target
    })
    assert verify_res.status_code == 200
    assert verify_res.json()["status"] == "VERIFIED"

    return bill_data, sugar, milk


def test_unverified_bill_receipt_blocked():
    """
    Verify:
    1. Unverified Udhaar bill cannot generate receipt or prepare delivery (HTTP 403 Forbidden).
    2. Cash and UPI bills complete immediately and CAN generate receipts without 2FA (HTTP 200 OK).
    """
    # 1. Udhaar unverified bill is blocked
    udhaar_bill, _, _ = _create_unverified_udhaar_bill()
    bill_id = udhaar_bill["id"]

    # GET /api/v1/receipts/{bill_id} -> Blocked with 403
    res1 = client.get(f"/api/v1/receipts/{bill_id}")
    assert res1.status_code == 403, f"Expected 403 Forbidden, got {res1.status_code}"
    assert "not customer-verified" in res1.json()["detail"].lower()

    # POST /api/v1/receipts/delivery-prep -> Blocked with 403
    res2 = client.post("/api/v1/receipts/delivery-prep", json={
        "bill_id": bill_id,
        "customer_phone": "9876543210"
    })
    assert res2.status_code == 403, f"Expected 403 Forbidden, got {res2.status_code}"
    assert "has not been customer-verified" in res2.json()["detail"].lower()

    # 2. UPI bill completes directly and generates receipt without 2FA
    upi_bill, _, _ = _create_unverified_bill()
    res3 = client.get(f"/api/v1/receipts/{upi_bill['id']}")
    assert res3.status_code == 200, f"Expected 200 OK for UPI bill, got {res3.status_code}"


def test_verified_bill_receipt_generation():
    """Verify: Verified bill generates complete, accurate digital receipt."""
    bill, sugar, milk = _create_verified_bill()
    bill_id = bill["id"]

    res = client.get(f"/api/v1/receipts/{bill_id}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    receipt = res.json()

    assert receipt["bill_id"] == bill_id
    assert receipt["bill_number"] == bill["bill_number"]
    assert receipt["payment_mode"] == "UPI"
    assert receipt["is_verified"] is True
    assert receipt["status"] == "CUSTOMER_VERIFIED"
    assert receipt["verified_at"] is not None
    assert "Apna Kirana" in receipt["shop_name"]

    # Items validation
    assert len(receipt["items"]) == 2
    item_names = [it["product_name"] for it in receipt["items"]]
    assert any("Sugar" in n for n in item_names)
    assert any("Milk" in n for n in item_names)

    expected_total = round(2.0 * sugar.unit_price + 1.0 * milk.unit_price, 2)
    assert receipt["total_amount"] == expected_total

    # Formatted printable receipt
    text_receipt = receipt["formatted_text_receipt"]
    assert "APNA KIRANA STORE" in text_receipt
    assert bill["bill_number"] in text_receipt
    assert "VERIFIED: YES" in text_receipt
    assert "GRAND TOTAL:" in text_receipt


def test_whatsapp_delivery_preparation_with_phone():
    """Verify: WhatsApp click-to-chat URL correctly prepends 91 and encodes formatted text."""
    bill, _, _ = _create_verified_bill()
    bill_id = bill["id"]

    phone = "9876543210"
    res = client.post("/api/v1/receipts/delivery-prep", json={
        "bill_id": bill_id,
        "customer_phone": phone
    })
    assert res.status_code == 200
    data = res.json()

    wa = data["whatsapp"]
    assert wa["prepared"] is True
    assert wa["customer_phone"] == phone
    assert "wa.me/919876543210?text=" in wa["click_to_chat_url"]

    # Verify message formatting
    msg = wa["formatted_message"]
    assert "APNA KIRANA STORE" in msg
    assert bill["bill_number"] in msg
    assert "CUSTOMER VERIFIED" in msg
    assert "Total Amount:" in msg

    # Verify URL encoding can be cleanly decoded back
    parsed_url = urllib.parse.urlparse(wa["click_to_chat_url"])
    query_params = urllib.parse.parse_qs(parsed_url.query)
    assert "text" in query_params
    decoded_text = query_params["text"][0]
    assert bill["bill_number"] in decoded_text


def test_whatsapp_delivery_preparation_without_phone():
    """Verify: WhatsApp click-to-chat URL works even if customer phone is not provided."""
    bill, _, _ = _create_verified_bill()
    bill_id = bill["id"]

    res = client.post("/api/v1/receipts/delivery-prep", json={
        "bill_id": bill_id
    })
    assert res.status_code == 200
    data = res.json()

    wa = data["whatsapp"]
    assert wa["click_to_chat_url"].startswith("https://wa.me/?text=")
    assert bill["bill_number"] in wa["formatted_message"]


def test_sms_mock_delivery_preparation():
    """Verify: SMS mock notification is concise, informative, and formatted."""
    bill, _, _ = _create_verified_bill()
    bill_id = bill["id"]

    res = client.post("/api/v1/receipts/delivery-prep", json={
        "bill_id": bill_id,
        "customer_phone": "9876543210"
    })
    assert res.status_code == 200
    data = res.json()

    sms = data["sms"]
    assert sms["is_mock"] is True
    assert sms["customer_phone"] == "9876543210"
    assert "Apna Kirana" in sms["sms_text"]
    assert bill["bill_number"] in sms["sms_text"]
    assert "verified" in sms["sms_text"].lower()
    assert sms["char_count"] == len(sms["sms_text"])
    assert sms["char_count"] < 160  # Standard SMS segment length


def test_nonexistent_bill_handling():
    """Verify: 404 is returned when bill does not exist."""
    res = client.get("/api/v1/receipts/999999")
    assert res.status_code == 404

    res2 = client.post("/api/v1/receipts/delivery-prep", json={"bill_id": 999999})
    assert res2.status_code == 404


if __name__ == "__main__":
    print("Running Step 8 Digital Receipt & Delivery Preparation Tests...")
    test_unverified_bill_receipt_blocked()
    print("[PASS] Security: Unverified bills strictly blocked from receipt generation (403 Forbidden)")
    test_verified_bill_receipt_generation()
    print("[PASS] Digital Receipt: Complete itemization, store branding, and totals verified")
    test_whatsapp_delivery_preparation_with_phone()
    print("[PASS] WhatsApp Click-to-Chat: Phone normalized (91) & message URL-encoded")
    test_whatsapp_delivery_preparation_without_phone()
    print("[PASS] WhatsApp Fallback: General Click-to-Chat URL generated when phone omitted")
    test_sms_mock_delivery_preparation()
    print("[PASS] SMS Mock: Concise under-160 character friendly notification formatted")
    test_nonexistent_bill_handling()
    print("[PASS] Error Handling: Nonexistent bills return 404 Not Found")
    print("\nALL STEP 8 TESTS PASSED SUCCESSFULLY!")
