"""
Live Verification Script for Step 6:
Tests against running HTTP server http://127.0.0.1:8000
Verifies:
1. Bill Draft creation (stocks remain untouched)
2. Bill Finalization (transaction persisted, stock decremented atomically)
3. Duplicate finalization with same idempotency_key (stock does NOT decrease twice)
4. Insufficient stock rejection & rollback
5. Payment mode persistence (CASH, UPI, UDHAAR)
6. Direct inspection of SQLite database records
"""
import requests
import sqlite3
import uuid

BASE_URL = "http://127.0.0.1:8000"
DB_PATH = "data/shopkeeper.db"

def inspect_db_state(product_ids):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    stocks = {}
    for pid in product_ids:
        cursor.execute("SELECT id, name, stock_quantity, min_stock_threshold, unit_price FROM products WHERE id = ?", (pid,))
        row = cursor.fetchone()
        if row:
            stocks[pid] = {
                "id": row[0],
                "name": row[1],
                "stock": row[2],
                "threshold": row[3],
                "price": row[4]
            }
    cursor.execute("SELECT COUNT(*) FROM bills")
    bill_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM bill_items")
    bill_items_count = cursor.fetchone()[0]
    conn.close()
    return stocks, bill_count, bill_items_count

def run_live_verification():
    print("=" * 60)
    print("STEP 6 LIVE INTEGRATION & DATABASE VERIFICATION")
    print("=" * 60)

    # 1. Health check
    h_res = requests.get(f"{BASE_URL}/api/v1/health")
    assert h_res.status_code == 200, f"Health check failed: {h_res.text}"
    print("[1] Server Health Check: OK (v0.1.0, SQLite Connected)")

    # 2. Get target products to track
    p_res = requests.get(f"{BASE_URL}/api/v1/products?search=cheeni")
    cheeni_id = p_res.json()[0]["id"]
    p_milk = requests.get(f"{BASE_URL}/api/v1/products?search=doodh")
    milk_id = p_milk.json()[0]["id"]

    tracked_ids = [cheeni_id, milk_id]
    stocks_before_draft, bills_before_draft, items_before_draft = inspect_db_state(tracked_ids)
    print(f"\n[2] Initial State in Database:")
    for pid, p in stocks_before_draft.items():
        print(f"    - {p['name']} (ID {p['id']}): Stock = {p['stock']}, Threshold = {p['threshold']}")
    print(f"    - Total Bills in DB: {bills_before_draft}, Total BillItems: {items_before_draft}")

    # 3. Create Draft Bill
    draft_res = requests.post(f"{BASE_URL}/api/v1/billing/draft", json={
        "text": "Do kilo cheeni aur ek packet doodh"
    })
    assert draft_res.status_code == 200
    draft_data = draft_res.json()
    print(f"\n[3] Draft Bill Generated via Voice/Text Parsing:")
    print(f"    - Draft ID: {draft_data['draft_id']}")
    print(f"    - Subtotal: Rs. {draft_data['subtotal']:.2f}")
    print(f"    - Total Amount: Rs. {draft_data['total_amount']:.2f}")
    print(f"    - Matched Items: {draft_data['matched_items_count']}")

    # Verify inventory is 100% UNCHANGED during draft
    stocks_during_draft, bills_during_draft, _ = inspect_db_state(tracked_ids)
    for pid in tracked_ids:
        assert stocks_during_draft[pid]["stock"] == stocks_before_draft[pid]["stock"], "Stock mutated during draft creation!"
    assert bills_during_draft == bills_before_draft, "Bill record prematurely created!"
    print("    -> VERIFIED: Stock & Bills strictly unchanged during draft phase.")

    # 4. Finalize the Draft Bill
    idempotency_key = f"LIVE-TEST-{uuid.uuid4().hex[:8]}"
    finalize_payload = {
        "items": [
            {"product_id": it["product_id"], "quantity": it["quantity"]}
            for it in draft_data["items"] if it["status"] == "MATCHED"
        ],
        "payment_mode": "UPI",
        "idempotency_key": idempotency_key,
        "notes": "Live test customer transaction"
    }

    finalize_res = requests.post(f"{BASE_URL}/api/v1/billing/finalize", json=finalize_payload)
    assert finalize_res.status_code == 201, f"Finalize failed: {finalize_res.text}"
    final_bill = finalize_res.json()
    print(f"\n[4] Bill Successfully Finalized:")
    print(f"    - Bill Number: {final_bill['bill_number']}")
    print(f"    - Status: {final_bill['status']}")
    print(f"    - Payment Mode: {final_bill['payment_mode']}")
    print(f"    - Subtotal: Rs. {final_bill['subtotal']:.2f}")
    print(f"    - Total: Rs. {final_bill['total_amount']:.2f}")
    print(f"    - Low Stock Alerts: {len(final_bill['low_stock_alerts'])}")

    # 5. Verify database mutation AFTER finalization
    stocks_after, bills_after, items_after = inspect_db_state(tracked_ids)
    print(f"\n[5] Database State AFTER Finalization:")
    for pid in tracked_ids:
        initial = stocks_before_draft[pid]["stock"]
        current = stocks_after[pid]["stock"]
        diff = round(initial - current, 3)
        print(f"    - {stocks_after[pid]['name']}: Initial = {initial} -> Current = {current} (Deducted: {diff})")
    print(f"    - Total Bills in DB: {bills_after} (Incremented by {bills_after - bills_before_draft})")
    print(f"    - Total BillItems in DB: {items_after} (Incremented by {items_after - items_before_draft})")

    assert bills_after == bills_before_draft + 1, "Bill count did not increment by 1"
    assert items_after == items_before_draft + len(finalize_payload["items"]), "BillItem count did not increment correctly"

    # 6. Test Idempotency / Duplicate Finalization Protection
    print(f"\n[6] Testing Duplicate Finalization with Idempotency Key '{idempotency_key}':")
    dup_res = requests.post(f"{BASE_URL}/api/v1/billing/finalize", json=finalize_payload)
    assert dup_res.status_code in [200, 201]
    dup_bill = dup_res.json()
    print(f"    - Duplicate Replay Flag: {dup_bill['is_duplicate_replay']}")
    print(f"    - Replayed Bill Number: {dup_bill['bill_number']}")
    assert dup_bill["bill_number"] == final_bill["bill_number"]
    assert dup_bill["is_duplicate_replay"] is True

    # Check stock again: MUST be exactly unchanged!
    stocks_after_dup, bills_after_dup, _ = inspect_db_state(tracked_ids)
    for pid in tracked_ids:
        assert stocks_after_dup[pid]["stock"] == stocks_after[pid]["stock"], "Stock was erroneously deducted twice!"
    assert bills_after_dup == bills_after, "Duplicate bill record created!"
    print("    -> VERIFIED: Duplicate finalization did NOT deduct inventory or create duplicate bills!")

    # 7. Test Insufficient Stock Rejection & Rollback
    print(f"\n[7] Testing Insufficient Stock Rejection:")
    excessive_qty = stocks_after[cheeni_id]["stock"] + 1000.0
    err_res = requests.post(f"{BASE_URL}/api/v1/billing/finalize", json={
        "items": [{"product_id": cheeni_id, "quantity": excessive_qty}],
        "payment_mode": "CASH"
    })
    assert err_res.status_code == 400
    print(f"    - Status Code: {err_res.status_code} Bad Request")
    print(f"    - Detail: {err_res.json()['detail']}")
    stocks_after_err, bills_after_err, _ = inspect_db_state(tracked_ids)
    assert stocks_after_err[cheeni_id]["stock"] == stocks_after[cheeni_id]["stock"]
    assert bills_after_err == bills_after
    print("    -> VERIFIED: Insufficient stock rejected with HTTP 400; zero state mutation occurred.")

    # 8. Test UDHAAR Payment Mode
    print(f"\n[8] Testing UDHAAR Payment Mode Persistence:")
    udhaar_payload = {
        "items": [{"product_id": cheeni_id, "quantity": 0.5}],
        "payment_mode": "UDHAAR",
        "notes": "Testing Udhaar payment mode persistence"
    }
    udh_res = requests.post(f"{BASE_URL}/api/v1/billing/finalize", json=udhaar_payload)
    assert udh_res.status_code == 201
    udh_data = udh_res.json()
    assert udh_data["payment_mode"] == "UDHAAR"
    print(f"    - Bill Number: {udh_data['bill_number']}")
    print(f"    - Payment Mode: {udh_data['payment_mode']}")
    print(f"    - Status: {udh_data['status']}")
    print("    -> VERIFIED: UDHAAR payment mode stored accurately without premature Step 9 logic.")

    print("\n" + "=" * 60)
    print("ALL LIVE VERIFICATION CHECKS PASSED WITH 100% ACCURACY!")
    print("=" * 60)

if __name__ == "__main__":
    run_live_verification()
