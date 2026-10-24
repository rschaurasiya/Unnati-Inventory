"""
Step 7 Verification Test Suite
Tests:
- Verification session creation for finalized bills
- Exactly 3 distinct challenge numbers generated cryptographically
- Target number is kept secret (not exposed in API response)
- Correct-number verification marks session VERIFIED
- Incorrect-number verification marks session FAILED
- Expired session rejection (expiration logic)
- Already-verified session protection against reuse
- Non-existent bill handling (404)
- Non-existent verification session handling (404)
- Verification session linked to the correct bill
- ZERO inventory deduction during verification
- End-to-End flow:
  Voice/Draft -> Finalized Bill -> Verification Session -> Customer selects number -> VERIFIED
"""
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product, Bill, VerificationSession

client = TestClient(app)


def _create_test_finalized_bill():
    """Helper to finalize a quick test bill."""
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        if prod.stock_quantity < 5.0:
            prod.stock_quantity = 50.0
            db.commit()
            db.refresh(prod)
        payload = {
            "items": [{"product_id": prod.id, "quantity": 1.0}],
            "payment_mode": "UPI",
            "notes": "Step 7 test fixture bill"
        }
        res = client.post("/api/v1/billing/finalize", json=payload)
        assert res.status_code == 201, f"Failed to finalize test bill: {res.text}"
        return res.json()
    finally:
        db.close()


def test_verification_session_creation():
    """Verify: Session creates with exactly 3 challenge numbers, linked to bill, target hidden."""
    bill = _create_test_finalized_bill()
    bill_id = bill["id"]

    res = client.post("/api/v1/verification/sessions", json={
        "bill_id": bill_id,
        "expiry_seconds": 120
    })
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    data = res.json()

    # Assert session metadata
    assert data["bill_id"] == bill_id
    assert data["bill_number"] == bill["bill_number"]
    assert data["bill_total"] == bill["total_amount"]
    assert data["status"] == "PENDING"
    assert data["verification_type"] == "NUMBER_MATCHING"
    assert data["attempts"] == 0
    assert len(data["session_token"]) >= 32

    # Assert exactly 3 challenge numbers
    challenges = data["challenge_numbers"]
    assert len(challenges) == 3, f"Expected 3 challenge numbers, got {len(challenges)}"
    assert len(set(challenges)) == 3, "Challenge numbers must be distinct"
    for num in challenges:
        assert 10 <= num <= 99, f"Challenge number {num} should be 2-digit"

    # Assert target_number is NOT exposed in the API response!
    assert "target_number" not in data, "Security failure: secret target number was exposed in API response!"


def test_correct_number_verification():
    """Verify: Customer selecting the correct number marks session VERIFIED."""
    bill = _create_test_finalized_bill()
    bill_id = bill["id"]

    create_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
    assert create_res.status_code == 201
    session_data = create_res.json()
    session_id = session_data["session_id"]

    # Look up secret target from DB directly for testing
    db = SessionLocal()
    try:
        session_row = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
        target = session_row.target_number
        assert target in session_data["challenge_numbers"]
    finally:
        db.close()

    # Submit correct number
    verify_res = client.post("/api/v1/verification/verify", json={
        "session_id": session_id,
        "selected_number": target
    })
    assert verify_res.status_code == 200, f"Expected 200, got {verify_res.status_code}: {verify_res.text}"
    result = verify_res.json()

    assert result["success"] is True
    assert result["status"] == "VERIFIED"
    assert "successful" in result["message"].lower()
    assert result["bill_id"] == bill_id

    # Verify database state
    db = SessionLocal()
    try:
        db.expire_all()
        persisted = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
        assert persisted.status == "VERIFIED"
        assert persisted.verified_at is not None
        assert persisted.attempts == 1
    finally:
        db.close()


def test_incorrect_number_verification():
    """Verify: Customer selecting an incorrect challenge number marks session FAILED."""
    bill = _create_test_finalized_bill()
    bill_id = bill["id"]

    create_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
    assert create_res.status_code == 201
    session_data = create_res.json()
    session_id = session_data["session_id"]
    challenges = session_data["challenge_numbers"]

    # Find an incorrect candidate number
    db = SessionLocal()
    try:
        session_row = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
        target = session_row.target_number
        wrong_number = next(n for n in challenges if n != target)
    finally:
        db.close()

    # Submit wrong number
    verify_res = client.post("/api/v1/verification/verify", json={
        "session_id": session_id,
        "selected_number": wrong_number
    })
    assert verify_res.status_code == 200
    result = verify_res.json()

    assert result["success"] is False
    assert result["status"] == "FAILED"
    assert "failed" in result["message"].lower()

    # Verify session marked FAILED in DB
    db = SessionLocal()
    try:
        persisted = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
        assert persisted.status == "FAILED"
        assert persisted.verified_at is None
    finally:
        db.close()


def test_expired_session_rejection():
    """Verify: Submitting a verification request after expiration is rejected."""
    bill = _create_test_finalized_bill()
    bill_id = bill["id"]

    create_res = client.post("/api/v1/verification/sessions", json={
        "bill_id": bill_id,
        "expiry_seconds": 30
    })
    session_id = create_res.json()["session_id"]

    # Manually expire the session in the DB
    db = SessionLocal()
    try:
        session_row = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
        session_row.expires_at = datetime.utcnow() - timedelta(seconds=10)
        target = session_row.target_number
        db.commit()
    finally:
        db.close()

    # Attempt to verify after expiration
    verify_res = client.post("/api/v1/verification/verify", json={
        "session_id": session_id,
        "selected_number": target
    })
    assert verify_res.status_code == 400
    assert "expired" in verify_res.json()["detail"].lower()

    # Verify GET session reflects EXPIRED status
    get_res = client.get(f"/api/v1/verification/sessions/{session_id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "EXPIRED"


def test_already_verified_session_reuse_protection():
    """Verify: An already verified session cannot be re-verified or reused."""
    bill = _create_test_finalized_bill()
    bill_id = bill["id"]

    create_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
    session_id = create_res.json()["session_id"]

    db = SessionLocal()
    try:
        session_row = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
        target = session_row.target_number
    finally:
        db.close()

    # 1. First verification: Succeeds
    v1 = client.post("/api/v1/verification/verify", json={
        "session_id": session_id,
        "selected_number": target
    })
    assert v1.status_code == 200
    assert v1.json()["status"] == "VERIFIED"

    # 2. Repeated verification: Must be rejected!
    v2 = client.post("/api/v1/verification/verify", json={
        "session_id": session_id,
        "selected_number": target
    })
    assert v2.status_code == 400
    assert "already been completed" in v2.json()["detail"].lower()

    # 3. Attempting to create a new session for an already verified bill must be rejected
    re_create = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
    assert re_create.status_code == 400
    assert "already been verified" in re_create.json()["detail"].lower()


def test_nonexistent_bill_and_session_handling():
    """Verify: 404 is returned when querying non-existent bills or sessions."""
    # 1. Nonexistent bill ID
    res1 = client.post("/api/v1/verification/sessions", json={"bill_id": 999999})
    assert res1.status_code == 404
    assert "not found" in res1.json()["detail"].lower()

    # 2. Nonexistent session ID
    res2 = client.get("/api/v1/verification/sessions/999999")
    assert res2.status_code == 404

    # 3. Nonexistent session verify
    res3 = client.post("/api/v1/verification/verify", json={
        "session_id": 999999,
        "selected_number": 55
    })
    assert res3.status_code == 404


def test_zero_inventory_deduction_during_verification():
    """
    CRITICAL INVENTORY SAFETY TEST:
    Verify: Verification NEVER mutates inventory or deducts stock a second time.
    """
    db = SessionLocal()
    try:
        prod = db.query(Product).first()
        if prod.stock_quantity < 5.0:
            prod.stock_quantity = 50.0
            db.commit()
            db.refresh(prod)
        stock_before_bill = prod.stock_quantity

        # Finalize bill: stock decreases by 2.0
        finalize_res = client.post("/api/v1/billing/finalize", json={
            "items": [{"product_id": prod.id, "quantity": 2.0}],
            "payment_mode": "CASH"
        })
        assert finalize_res.status_code == 201
        bill_data = finalize_res.json()
        bill_id = bill_data["id"]

        db.refresh(prod)
        stock_after_finalize = prod.stock_quantity
        assert stock_after_finalize == round(stock_before_bill - 2.0, 3)

        # Step 1: Create verification session -> Stock must NOT change
        create_res = client.post("/api/v1/verification/sessions", json={"bill_id": bill_id})
        assert create_res.status_code == 201
        session_id = create_res.json()["session_id"]

        db.refresh(prod)
        assert prod.stock_quantity == stock_after_finalize, "Stock mutated during session creation!"

        # Step 2: Customer verifies number -> Stock must NOT change
        session_row = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
        target = session_row.target_number

        verify_res = client.post("/api/v1/verification/verify", json={
            "session_id": session_id,
            "selected_number": target
        })
        assert verify_res.status_code == 200

        db.refresh(prod)
        assert prod.stock_quantity == stock_after_finalize, "Stock mutated during verification submission!"

    finally:
        db.close()


def test_end_to_end_verification_flow():
    """
    Full End-to-End Workflow:
    Voice/Text -> NLP Draft Bill -> Finalize Bill -> Create Verification Session ->
    Customer Selects Number -> Verified -> Linked to original transaction.
    """
    # 1. Voice Draft
    draft_res = client.post("/api/v1/billing/draft", json={
        "text": "ek packet doodh"
    })
    assert draft_res.status_code == 200
    draft_items = [
        {"product_id": it["product_id"], "quantity": it["quantity"]}
        for it in draft_res.json()["items"] if it["status"] == "MATCHED"
    ]
    assert len(draft_items) >= 1

    # 2. Finalize Bill
    finalize_res = client.post("/api/v1/billing/finalize", json={
        "items": draft_items,
        "payment_mode": "UPI",
        "notes": "E2E Step 7 verification test"
    })
    assert finalize_res.status_code == 201
    final_bill = finalize_res.json()
    bill_id = final_bill["id"]
    bill_num = final_bill["bill_number"]

    # 3. Verification Session Created for Bill
    session_res = client.post("/api/v1/verification/sessions", json={
        "bill_id": bill_id,
        "expiry_seconds": 180
    })
    assert session_res.status_code == 201
    session = session_res.json()
    session_id = session["session_id"]

    assert session["bill_number"] == bill_num
    assert len(session["challenge_numbers"]) == 3

    # 4. Fetch session by Bill ID
    by_bill_res = client.get(f"/api/v1/verification/bill/{bill_id}")
    assert by_bill_res.status_code == 200
    assert by_bill_res.json()["session_id"] == session_id

    # 5. Customer Completes Verification
    db = SessionLocal()
    try:
        target = db.query(VerificationSession).filter(VerificationSession.id == session_id).first().target_number
    finally:
        db.close()

    result_res = client.post("/api/v1/verification/verify", json={
        "session_id": session_id,
        "selected_number": target
    })
    assert result_res.status_code == 200
    result = result_res.json()

    assert result["success"] is True
    assert result["status"] == "VERIFIED"
    assert result["bill_number"] == bill_num

    # 6. Verify Bill is linked and notes contain verification record
    db = SessionLocal()
    try:
        bill_in_db = db.query(Bill).filter(Bill.id == bill_id).first()
        assert bill_in_db is not None
        assert "Customer Verified: 2FA-Match" in (bill_in_db.notes or "")
        assert bill_in_db.verification_session is not None
        assert bill_in_db.verification_session.status == "VERIFIED"
    finally:
        db.close()


if __name__ == "__main__":
    print("Running Step 7 Customer Verification & Number Matching 2FA Tests...")
    test_verification_session_creation()
    print("[PASS] Session Creation: Exactly 3 challenge numbers generated; secret target hidden")
    test_correct_number_verification()
    print("[PASS] Correct Match: Customer selection verified successfully")
    test_incorrect_number_verification()
    print("[PASS] Incorrect Match: Wrong number selection fails cleanly")
    test_expired_session_rejection()
    print("[PASS] Expiry Protection: Expired sessions rejected with HTTP 400")
    test_already_verified_session_reuse_protection()
    print("[PASS] Reuse Protection: Already verified sessions cannot be reused")
    test_nonexistent_bill_and_session_handling()
    print("[PASS] Error Handling: Nonexistent bills and sessions return 404")
    test_zero_inventory_deduction_during_verification()
    print("[PASS] Inventory Safety: Zero stock deduction during verification")
    test_end_to_end_verification_flow()
    print("[PASS] End-to-End: Finalized Bill -> Verification Session -> Customer Verified")
    print("\nALL STEP 7 TESTS PASSED SUCCESSFULLY!")
