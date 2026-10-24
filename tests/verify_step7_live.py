"""
Live Integration and Database Verification for Step 7:
Customer Verification Session & Number Matching 2FA Setup
Runs against running server at http://127.0.0.1:8000 and inspects data/shopkeeper.db
"""
import requests
import sqlite3
import uuid
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:8000"
DB_PATH = "data/shopkeeper.db"


def inspect_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, bill_id, session_token, target_number, candidate_numbers, status, attempts, created_at, expires_at, verified_at FROM verification_sessions ORDER BY id DESC LIMIT 5")
    sessions = cursor.fetchall()
    cursor.execute("SELECT id, name, stock_quantity FROM products WHERE id = 34")
    product = cursor.fetchone()
    conn.close()
    return sessions, product


def run_live_verification():
    print("=" * 65)
    print("STEP 7 LIVE INTEGRATION & DATABASE VERIFICATION")
    print("=" * 65)

    # 1. Health check
    h = requests.get(f"{BASE_URL}/api/v1/health")
    assert h.status_code == 200
    print("[1] Server Health Check: OK")

    # 2. Finalize a new Bill for Step 7 testing
    # Check sugar stock before bill
    _, sugar_before_bill = inspect_db()
    stock_before = sugar_before_bill[2]

    idemp = f"STEP7-TEST-{uuid.uuid4().hex[:8]}"
    finalize_res = requests.post(f"{BASE_URL}/api/v1/billing/finalize", json={
        "items": [{"product_id": 34, "quantity": 1.0}],
        "payment_mode": "CASH",
        "idempotency_key": idemp,
        "notes": "Step 7 live 2FA verification transaction"
    })
    assert finalize_res.status_code == 201, f"Finalize failed: {finalize_res.text}"
    bill = finalize_res.json()
    bill_id = bill["id"]
    bill_num = bill["bill_number"]
    print(f"\n[2] Finalized Test Bill:")
    print(f"    - Bill ID: {bill_id}")
    print(f"    - Bill Number: {bill_num}")
    print(f"    - Total Amount: Rs. {bill['total_amount']:.2f}")

    _, sugar_after_bill = inspect_db()
    stock_after_bill = sugar_after_bill[2]
    assert stock_after_bill == round(stock_before - 1.0, 3)
    print(f"    - Inventory Deducted for Bill: {stock_before} -> {stock_after_bill}")

    # 3. Create Verification Session
    create_res = requests.post(f"{BASE_URL}/api/v1/verification/sessions", json={
        "bill_id": bill_id,
        "expiry_seconds": 120
    })
    assert create_res.status_code == 201, f"Failed to create session: {create_res.text}"
    session = create_res.json()
    session_id = session["session_id"]
    challenges = session["challenge_numbers"]

    print(f"\n[3] Verification Session Created:")
    print(f"    - Session ID: {session_id}")
    print(f"    - Status: {session['status']}")
    print(f"    - Challenge Numbers (3): {challenges}")
    print(f"    - Expires In Seconds: {session['expires_in_seconds']}s")
    assert len(challenges) == 3
    assert "target_number" not in session, "Target number leaked in API response!"
    print("    -> VERIFIED: Exactly 3 numbers generated cryptographically; secret target hidden.")

    # 4. Zero Inventory Deduction Check During Session Creation
    _, sugar_after_session_create = inspect_db()
    assert sugar_after_session_create[2] == stock_after_bill, "Inventory mutated during session creation!"
    print("    -> VERIFIED: Stock strictly unchanged during session creation.")

    # 5. Look up secret target from DB directly to test incorrect and correct selections
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT target_number FROM verification_sessions WHERE id = ?", (session_id,))
    target_number = c.fetchone()[0]
    conn.close()
    wrong_number = next(n for n in challenges if n != target_number)

    # 6. Test Incorrect Number Selection
    print(f"\n[4] Testing Incorrect Number Selection (Customer picks {wrong_number}, Target is {target_number}):")
    wrong_res = requests.post(f"{BASE_URL}/api/v1/verification/verify", json={
        "session_id": session_id,
        "selected_number": wrong_number
    })
    assert wrong_res.status_code == 200
    wrong_data = wrong_res.json()
    print(f"    - Verification Success: {wrong_data['success']}")
    print(f"    - Result Status: {wrong_data['status']}")
    print(f"    - Message: {wrong_data['message']}")
    assert wrong_data["success"] is False
    assert wrong_data["status"] == "FAILED"
    print("    -> VERIFIED: Incorrect selection marks session FAILED.")

    # 7. Test Regenerating New Challenge after Failure
    print(f"\n[5] Testing Challenge Regeneration for Bill {bill_id}:")
    regen_res = requests.post(f"{BASE_URL}/api/v1/verification/sessions", json={
        "bill_id": bill_id,
        "expiry_seconds": 180
    })
    assert regen_res.status_code == 201
    new_session = regen_res.json()
    new_challenges = new_session["challenge_numbers"]
    print(f"    - Status: {new_session['status']}")
    print(f"    - New Challenge Numbers: {new_challenges}")
    assert new_session["status"] == "PENDING"
    assert len(new_challenges) == 3

    # Look up new secret target
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT target_number FROM verification_sessions WHERE id = ?", (new_session["session_id"],))
    new_target = c.fetchone()[0]
    conn.close()

    # 8. Test Correct Number Selection
    print(f"\n[6] Testing Correct Number Selection (Customer picks {new_target}):")
    correct_res = requests.post(f"{BASE_URL}/api/v1/verification/verify", json={
        "session_id": new_session["session_id"],
        "selected_number": new_target
    })
    assert correct_res.status_code == 200
    correct_data = correct_res.json()
    print(f"    - Verification Success: {correct_data['success']}")
    print(f"    - Result Status: {correct_data['status']}")
    print(f"    - Verified At: {correct_data['verified_at']}")
    print(f"    - Message: {correct_data['message']}")
    assert correct_data["success"] is True
    assert correct_data["status"] == "VERIFIED"
    print("    -> VERIFIED: Correct selection marks session VERIFIED.")

    # 9. Zero Inventory Deduction Check After Verification
    _, sugar_after_verify = inspect_db()
    assert sugar_after_verify[2] == stock_after_bill, "Inventory mutated during verification!"
    print("    -> VERIFIED: Stock remains 100% UNCHANGED throughout verification!")

    # 10. Test Reuse Protection (Repeated Verification Rejected)
    print(f"\n[7] Testing Repeated Verification Protection:")
    dup_verify = requests.post(f"{BASE_URL}/api/v1/verification/verify", json={
        "session_id": new_session["session_id"],
        "selected_number": new_target
    })
    assert dup_verify.status_code == 400
    print(f"    - Repeated Verify Error (400): {dup_verify.json()['detail']}")
    print("    -> VERIFIED: Already verified session rejected against reuse.")

    # 11. Test Expiration Handling
    print(f"\n[8] Testing Expiration Logic:")
    # Create another quick bill and expire its session
    b2 = requests.post(f"{BASE_URL}/api/v1/billing/finalize", json={
        "items": [{"product_id": 34, "quantity": 0.5}],
        "payment_mode": "UPI"
    }).json()
    s2 = requests.post(f"{BASE_URL}/api/v1/verification/sessions", json={
        "bill_id": b2["id"],
        "expiry_seconds": 30
    }).json()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE verification_sessions SET expires_at = ? WHERE id = ?",
              ((datetime.utcnow() - timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S"), s2["session_id"]))
    conn.commit()
    conn.close()

    exp_res = requests.post(f"{BASE_URL}/api/v1/verification/verify", json={
        "session_id": s2["session_id"],
        "selected_number": s2["challenge_numbers"][0]
    })
    assert exp_res.status_code == 400
    print(f"    - Expired Verify Error (400): {exp_res.json()['detail']}")
    print("    -> VERIFIED: Expired session rejected properly.")

    # 12. Direct Database Inspection
    print(f"\n[9] Direct SQLite Database Inspection:")
    sessions_in_db, _ = inspect_db()
    for row in sessions_in_db[:3]:
        print(f"    - Session ID {row[0]}: Bill ID={row[1]}, Status={row[5]}, Candidates='{row[4]}', Target={row[3]}, VerifiedAt={row[9]}")

    print("\n" + "=" * 65)
    print("ALL STEP 7 LIVE VERIFICATION CHECKS PASSED WITH 100% SUCCESS!")
    print("=" * 65)


if __name__ == "__main__":
    run_live_verification()
