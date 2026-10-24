import urllib.request
import json

def post(url, body):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get(url):
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    print("--- 1. Searching Customer Ramesh ---")
    customers = get("http://127.0.0.1:8000/api/v1/customers?query=Ramesh")
    assert len(customers) > 0, "No customer found"
    ramesh = customers[0]
    cid = ramesh["id"]
    print(f"Customer: {ramesh['full_name']}, Balance: {ramesh['current_udhaar_balance']}, Credit Limit: {ramesh['credit_limit']}")

    print("\n--- 2. Fetching Customer Details & Family Members ---")
    detail = get(f"http://127.0.0.1:8000/api/v1/customers/{cid}")
    assert len(detail["family_members"]) > 0, "No family members found"
    aman = detail["family_members"][0]
    print(f"Family Member: {aman['full_name']} ({aman.get('relation_type', 'Member')})")

    print("\n--- 3. Finalizing Udhaar Draft Bill ---")
    prods = get("http://127.0.0.1:8000/api/v1/products?limit=2")
    p1 = prods[0]
    initial_stock = p1["stock_quantity"]
    
    bill_req = {
        "items": [{
            "product_id": p1["id"],
            "product_name": p1["name"],
            "quantity": 1.0,
            "unit": p1["unit"],
            "unit_price": p1["unit_price"],
            "line_total": p1["unit_price"]
        }],
        "payment_mode": "UDHAAR",
        "customer_id": cid,
        "family_member_id": aman["id"],
        "notes": "Live test Udhaar purchase"
    }
    bill = post("http://127.0.0.1:8000/api/v1/bills/finalize", bill_req)
    assert bill["status"] == "PENDING_VERIFICATION", f"Expected PENDING_VERIFICATION, got {bill['status']}"
    print(f"Bill created: {bill['bill_number']}, Status: {bill['status']}")
    print(f"Mock Notification: {bill.get('notification_message')}")

    print("\n--- 4. Checking Inventory Before Verification ---")
    # Verify stock has NOT yet been deducted!
    prod_check = get(f"http://127.0.0.1:8000/api/v1/products/{p1['id']}")
    assert prod_check["stock_quantity"] == initial_stock, "Stock was prematurely deducted!"
    print(f"Stock before verification: {prod_check['stock_quantity']} (Preserved safely)")

    print("\n--- 5. Creating 2FA Verification Session ---")
    session = post("http://127.0.0.1:8000/api/v1/verification/sessions", {"bill_id": bill["id"]})
    sid = session["session_id"]
    challenges = session["challenge_numbers"]
    print(f"Session: {sid}, Challenges: {challenges}")

    print("\n--- 6. Submitting Correct Challenge Number ---")
    # One of the challenge numbers is correct
    verified_res = None
    for num in challenges:
        try:
            res = post(f"http://127.0.0.1:8000/api/v1/verification/verify", {"session_id": sid, "selected_number": num})
            if res.get("success"):
                verified_res = res
                break
        except Exception:
            pass

    assert verified_res is not None and verified_res["success"], "Verification failed to match target number"
    print(f"Verification Success! Bill status: {verified_res['status']}")

    print("\n--- 7. Checking Stock Deduction & Ledger Update After Verification ---")
    prod_after = get(f"http://127.0.0.1:8000/api/v1/products/{p1['id']}")
    assert prod_after["stock_quantity"] == initial_stock - 1.0, "Stock was not deducted exactly once!"
    print(f"Stock after verification: {prod_after['stock_quantity']} (Deducted exactly 1)")

    ledger = get(f"http://127.0.0.1:8000/api/v1/customers/{cid}/ledger")
    latest_tx = ledger[0]
    assert latest_tx["transaction_type"] == "DEBIT_PURCHASE"
    assert latest_tx["bill_id"] == bill["id"]
    print(f"Ledger record verified: {latest_tx['transaction_type']} of Rs. {latest_tx['amount']}, New Balance: Rs. {latest_tx['balance_after']}")

    print("\n--- 8. Testing Udhaar Settlement ---")
    settle_res = post(f"http://127.0.0.1:8000/api/v1/customers/{cid}/settle", {
        "amount": p1["unit_price"],
        "payment_mode": "CASH",
        "notes": "Full test repayment"
    })
    print(f"Settled: Rs. {settle_res['settled_amount']}, Previous: Rs. {settle_res['previous_balance']}, New: Rs. {settle_res['new_balance']}")

    ledger_after_settle = get(f"http://127.0.0.1:8000/api/v1/customers/{cid}/ledger")
    assert ledger_after_settle[0]["transaction_type"] == "CREDIT_PAYMENT"
    print(f"Settlement ledger recorded: {ledger_after_settle[0]['transaction_type']} of Rs. {ledger_after_settle[0]['amount']}")

    print("\n==========================================")
    print("ALL LIVE SERVER INTEGRATION CHECKS PASSED!")
    print("==========================================")

if __name__ == "__main__":
    main()
