"""
Live Integration and Database Verification for Step 8:
Digital Receipt Generation & Delivery Preparation (WhatsApp/SMS Mock)
Runs against live server at http://127.0.0.1:8000 and inspects data/shopkeeper.db
"""
import requests
import sqlite3
import urllib.parse
import uuid

BASE_URL = "http://127.0.0.1:8000"
DB_PATH = "data/shopkeeper.db"


def run_live_verification():
    print("=" * 68)
    print("STEP 8 LIVE INTEGRATION & DATABASE VERIFICATION")
    print("=" * 68)

    # 1. Health check
    h = requests.get(f"{BASE_URL}/api/v1/health")
    assert h.status_code == 200
    print("[1] Server Health Check: OK")

    # 2. Finalize a new Bill for Step 8 testing
    idemp = f"STEP8-LIVE-{uuid.uuid4().hex[:8]}"
    finalize_res = requests.post(f"{BASE_URL}/api/v1/billing/finalize", json={
        "items": [
            {"product_id": 34, "quantity": 2.0},  # Sugar
            {"product_id": 18, "quantity": 1.0}   # Amul Milk
        ],
        "payment_mode": "UPI",
        "idempotency_key": idemp,
        "notes": "Step 8 live receipt verification"
    })
    assert finalize_res.status_code == 201
    bill = finalize_res.json()
    bill_id = bill["id"]
    bill_num = bill["bill_number"]
    total = bill["total_amount"]
    print(f"\n[2] Finalized Test Bill (Unverified Initial State):")
    print(f"    - Bill ID: {bill_id}")
    print(f"    - Bill Number: {bill_num}")
    print(f"    - Total Amount: Rs. {total:.2f}")
    print(f"    - Status: {bill['status']}")

    # 3. Security Check: Verify Unverified Bill CANNOT Generate Receipt
    print("\n[3] Security Check — Unverified Bill Receipt Protection:")
    unverified_receipt = requests.get(f"{BASE_URL}/api/v1/receipts/{bill_id}")
    assert unverified_receipt.status_code == 403, f"Expected 403, got {unverified_receipt.status_code}"
    print(f"    - GET /api/v1/receipts/{bill_id} -> HTTP 403 Forbidden")
    print(f"    - Error Detail: {unverified_receipt.json()['detail']}")

    unverified_prep = requests.post(f"{BASE_URL}/api/v1/receipts/delivery-prep", json={
        "bill_id": bill_id,
        "customer_phone": "9876543210"
    })
    assert unverified_prep.status_code == 403
    print(f"    - POST /api/v1/receipts/delivery-prep -> HTTP 403 Forbidden")
    print("    -> VERIFIED: Unverified bills are strictly blocked from digital receipt delivery!")

    # 4. Perform Customer 2FA Verification
    print(f"\n[4] Performing Customer 2FA Verification for Bill {bill_id}:")
    session_res = requests.post(f"{BASE_URL}/api/v1/verification/sessions", json={"bill_id": bill_id})
    assert session_res.status_code == 201
    session_data = session_res.json()
    session_id = session_data["session_id"]

    # Look up secret target
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT target_number FROM verification_sessions WHERE id = ?", (session_id,))
    target_number = c.fetchone()[0]
    conn.close()

    verify_res = requests.post(f"{BASE_URL}/api/v1/verification/verify", json={
        "session_id": session_id,
        "selected_number": target_number
    })
    assert verify_res.status_code == 200
    assert verify_res.json()["status"] == "VERIFIED"
    print(f"    - Customer 2FA Verified with Target Number: {target_number}")
    print("    - Status: VERIFIED")

    # 5. Retrieve Digital Receipt for Verified Bill
    print(f"\n[5] Generating Digital Receipt for Verified Bill:")
    receipt_res = requests.get(f"{BASE_URL}/api/v1/receipts/{bill_id}")
    assert receipt_res.status_code == 200
    receipt = receipt_res.json()

    print(f"    - Receipt ID: {receipt['receipt_id']}")
    print(f"    - Store: {receipt['shop_name']}")
    print(f"    - Address: {receipt['shop_address']}")
    print(f"    - Verified: {receipt['is_verified']} (Status: {receipt['status']})")
    print(f"    - Total Amount: Rs. {receipt['total_amount']:.2f}")
    print(f"    - Line Items ({len(receipt['items'])}):")
    for it in receipt["items"]:
        print(f"      • {it['product_name']}: {it['quantity']} {it['unit']} @ Rs.{it['unit_price']:.2f} = Rs.{it['line_total']:.2f}")
    assert receipt["total_amount"] == total
    print("    -> VERIFIED: Digital receipt successfully generated with complete itemized breakdown.")

    # 6. Test WhatsApp Click-to-Chat Delivery Preparation
    print("\n[6] Testing WhatsApp Click-to-Chat Delivery Preparation:")
    delivery_res = requests.post(f"{BASE_URL}/api/v1/receipts/delivery-prep", json={
        "bill_id": bill_id,
        "customer_phone": "9876543210"
    })
    assert delivery_res.status_code == 200
    delivery = delivery_res.json()

    wa = delivery["whatsapp"]
    print(f"    - Customer Phone: {wa['customer_phone']}")
    print(f"    - Click-to-Chat URL: {wa['click_to_chat_url'][:60]}...[TRUNCATED]")
    assert "wa.me/919876543210?text=" in wa["click_to_chat_url"]

    # Verify WhatsApp message contains store name, bill number, items, and verification seal
    parsed = urllib.parse.urlparse(wa["click_to_chat_url"])
    decoded_text = urllib.parse.parse_qs(parsed.query)["text"][0]
    assert "APNA KIRANA STORE" in decoded_text
    assert bill_num in decoded_text
    assert "CUSTOMER VERIFIED" in decoded_text
    print("    -> VERIFIED: WhatsApp URL encoded with phone prefix (91) and verified receipt details.")

    # 7. Test SMS Mock Notification Preview
    print("\n[7] Testing SMS Mock Notification:")
    sms = delivery["sms"]
    print(f"    - SMS Text: \"{sms['sms_text']}\"")
    print(f"    - Character Count: {sms['char_count']} (Max: 160)")
    assert sms["char_count"] <= 160
    assert "Apna Kirana" in sms["sms_text"]
    assert bill_num in sms["sms_text"]
    print("    -> VERIFIED: Concise SMS formatted under standard 160-char SMS limit.")

    # 8. Test Thermal / Printable Receipt Formatting
    print("\n[8] Testing Thermal / Printable Receipt Output:")
    thermal_text = receipt["formatted_text_receipt"]
    print(f"--- Thermal Receipt Preview ({len(thermal_text.splitlines())} lines) ---")
    for line in thermal_text.splitlines()[:10]:
        print(f"    {line}")
    print("    ...")
    assert "GRAND TOTAL:" in thermal_text
    assert "THANK YOU" in thermal_text
    print("    -> VERIFIED: Printable thermal format verified.")

    # 9. Verify Zero Side Effects on Database
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT total_amount, payment_mode, status FROM bills WHERE id = ?", (bill_id,))
    bill_row = c.fetchone()
    conn.close()
    assert bill_row[0] == total
    assert bill_row[1] == "UPI"
    assert bill_row[2] == "COMPLETED"
    print("\n[9] Database Integrity: Bill record in SQLite remained 100% stable.")

    print("\n" + "=" * 68)
    print("ALL STEP 8 LIVE VERIFICATION CHECKS PASSED WITH 100% SUCCESS!")
    print("=" * 68)


if __name__ == "__main__":
    run_live_verification()
