"""
End-to-End Live Verification Script for Historical Sales Import Pipeline
Tests all live endpoints on http://127.0.0.1:8000.
"""
import requests
import json
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"

def run_live_verification():
    print("=== STARTING LIVE END-TO-END VERIFICATION ===")

    # 1. Health check
    res_health = requests.get(f"{BASE_URL}/api/v1/health")
    assert res_health.status_code == 200, f"Health check failed: {res_health.text}"
    print("[PASS] Health Check Passed:", res_health.json()["status"])

    # 2. Get initial stock of Sugar to prove inventory safety
    res_prods = requests.get(f"{BASE_URL}/api/v1/products")
    prods = res_prods.json()
    sugar_prod = next(p for p in prods if "Sugar" in p["name"])
    initial_stock = sugar_prod["stock_quantity"]
    print(f"[PASS] Initial stock of {sugar_prod['name']}: {initial_stock} {sugar_prod['unit']}")

    # 3. Upload File A (Standard CSV)
    file_a_path = Path("data/test_import_files/file_a_standard.csv")
    with open(file_a_path, "rb") as f:
        res_upload = requests.post(
            f"{BASE_URL}/api/v1/analytics/import/upload",
            files={"file": ("file_a_standard.csv", f, "text/csv")}
        )
    assert res_upload.status_code == 200, f"Upload failed: {res_upload.text}"
    analysis = res_upload.json()
    assert analysis["status"] == "READY"
    assert analysis["validation_summary"]["valid_rows"] == 3
    import_id = analysis["import_id"]
    print(f"[PASS] File A Upload & Analysis Passed. Import ID: {import_id}, Valid Rows: 3")

    # 4. Confirm Import
    res_confirm = requests.post(
        f"{BASE_URL}/api/v1/analytics/import/confirm",
        json={"import_id": import_id, "import_mode": "SKIP_INVALID"}
    )
    assert res_confirm.status_code == 201, f"Confirm failed: {res_confirm.text}"
    confirm_data = res_confirm.json()
    print(f"[PASS] Confirm Import Passed: {confirm_data['imported_records_count']} records imported, status: {confirm_data['forecasting_status']}")

    # 5. Check Daily Sales on 2026-09-01 includes the imported Sugar sale (5 kg)
    res_daily = requests.get(f"{BASE_URL}/api/v1/analytics/sales/daily?date=2026-09-01")
    assert res_daily.status_code == 200
    daily_data = res_daily.json()
    sugar_daily = next((it for it in daily_data["items"] if "Sugar" in it["product_name"]), None)
    assert sugar_daily is not None
    assert sugar_daily["total_quantity_sold"] >= 5.0
    print(f"[PASS] Daily Sales Verified on 2026-09-01: {sugar_daily['product_name']} sold = {sugar_daily['total_quantity_sold']}")

    # 6. Verify Stock was NOT modified
    res_prods_after = requests.get(f"{BASE_URL}/api/v1/products")
    sugar_after = next(p for p in res_prods_after.json() if p["id"] == sugar_prod["id"])
    assert sugar_after["stock_quantity"] == initial_stock, "INVENTORY LEAK: Stock was modified by historical import!"
    print(f"[PASS] Inventory Safety Verified: Stock remained exactly {initial_stock} {sugar_prod['unit']}")

    # 7. Check Audit Batches
    res_batches = requests.get(f"{BASE_URL}/api/v1/analytics/import/batches")
    assert res_batches.status_code == 200
    batches = res_batches.json()
    batch_item = next((b for b in batches if b["import_id"] == import_id), None)
    assert batch_item is not None
    print(f"[PASS] Import Audit Batch Verified in DB: status = {batch_item['status']}")

    # 8. Test Rollback
    res_rb = requests.post(f"{BASE_URL}/api/v1/analytics/import/rollback/{import_id}")
    assert res_rb.status_code == 200
    rb_data = res_rb.json()
    print(f"[PASS] Batch Rollback Verified: {rb_data['records_deactivated_count']} records deactivated")

    # 9. Verify Problematic File diagnostics
    file_prob_path = Path("data/test_import_files/file_problematic.csv")
    with open(file_prob_path, "rb") as f:
        res_prob = requests.post(
            f"{BASE_URL}/api/v1/analytics/import/upload",
            files={"file": ("file_problematic.csv", f, "text/csv")}
        )
    assert res_prob.status_code == 200
    prob_data = res_prob.json()
    assert prob_data["validation_summary"]["invalid_rows"] == 6
    assert "Phone" in prob_data["ignored_columns"]
    assert "Address" in prob_data["ignored_columns"]
    print("[PASS] Problematic File Handled Safely: 6 invalid rows flagged, Phone & Address privacy-ignored.")

    print("\nALL LIVE VERIFICATION CHECKS PASSED 100%!")

if __name__ == "__main__":
    run_live_verification()
