"""
Step 5 Verification Test Suite
Tests:
- Voice & Typed POS Draft Bill generation endpoint: POST /api/v1/billing/draft
- Required prompt examples:
  1. "Do kilo cheeni aur ek packet doodh"
  2. "Aadha kilo sarson tel"
  3. "Dhai kilo chawal aur teen packet maggi"
  4. "ek kilo chini"
- Unmatched product detection in draft: "ek kilo dragonfruit"
- Spelling tolerance in draft generation: "sarsan tel"
- In-memory draft recalculation: POST /api/v1/billing/draft/recalculate
- Inline quantity modification and item deletion
- CRITICAL INVENTORY SAFETY TEST:
  Guarantees that database inventory stock and bill tables are 100% UNCHANGED during draft creation.
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product, Bill, BillItem

client = TestClient(app)


def test_draft_example_1_cheeni_and_doodh():
    """Verify: 'Do kilo cheeni aur ek packet doodh' produces accurate draft bill."""
    payload = {"text": "Do kilo cheeni aur ek packet doodh"}
    res = client.post("/api/v1/billing/draft", json=payload)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    draft = res.json()

    assert draft["status"] == "DRAFT"
    assert draft["draft_id"].startswith("DRAFT-")
    assert len(draft["items"]) == 2
    assert draft["matched_items_count"] == 2
    assert draft["unmatched_items_count"] == 0

    item1 = draft["items"][0]
    assert "Sugar" in item1["product_name"] or "Cheeni" in item1["product_name"]
    assert item1["quantity"] == 2.0
    assert item1["unit"] == "kg"
    assert item1["unit_price"] == 44.0
    assert item1["line_total"] == 88.0

    item2 = draft["items"][1]
    assert "Milk" in item2["product_name"] or "Doodh" in item2["product_name"]
    assert item2["quantity"] == 1.0
    assert item2["unit"] == "packet"

    expected_total = item1["line_total"] + item2["line_total"]
    assert draft["total_amount"] == expected_total


def test_draft_example_2_sarson_tel():
    """Verify: 'Aadha kilo sarson tel' produces 0.5 quantity draft line."""
    payload = {"text": "Aadha kilo sarson tel"}
    res = client.post("/api/v1/billing/draft", json=payload)
    assert res.status_code == 200
    draft = res.json()

    assert len(draft["items"]) == 1
    assert draft["matched_items_count"] == 1
    item = draft["items"][0]
    assert "Mustard Oil" in item["product_name"]
    assert item["quantity"] == 0.5
    assert item["line_total"] == round(0.5 * item["unit_price"], 2)


def test_draft_example_3_chawal_and_maggi():
    """Verify: 'Dhai kilo chawal aur teen packet maggi'."""
    payload = {"text": "Dhai kilo chawal aur teen packet maggi"}
    res = client.post("/api/v1/billing/draft", json=payload)
    assert res.status_code == 200
    draft = res.json()

    assert len(draft["items"]) == 2
    assert draft["matched_items_count"] == 2

    # Chawal: 2.5 kg
    item1 = draft["items"][0]
    assert "Rice" in item1["product_name"]
    assert item1["quantity"] == 2.5

    # Maggi: 3 packets
    item2 = draft["items"][1]
    assert "Maggi" in item2["product_name"]
    assert item2["quantity"] == 3.0


def test_draft_example_4_ek_kilo_chini():
    """Verify: 'ek kilo chini' uses alias and creates 1 kg draft line."""
    payload = {"text": "ek kilo chini"}
    res = client.post("/api/v1/billing/draft", json=payload)
    assert res.status_code == 200
    draft = res.json()

    assert len(draft["items"]) == 1
    item = draft["items"][0]
    assert "Sugar" in item["product_name"] or "Cheeni" in item["product_name"]
    assert item["quantity"] == 1.0
    assert item["line_total"] == 44.0


def test_draft_unmatched_product():
    """Verify unknown product 'ek kilo dragonfruit' is reported as UNMATCHED without breaking."""
    payload = {"text": "ek kilo dragonfruit"}
    res = client.post("/api/v1/billing/draft", json=payload)
    assert res.status_code == 200
    draft = res.json()

    assert len(draft["items"]) == 1
    assert draft["matched_items_count"] == 0
    assert draft["unmatched_items_count"] == 1

    item = draft["items"][0]
    assert item["status"] == "UNMATCHED"
    assert item["product_id"] is None
    assert "dragonfruit" in item["product_name"].lower()
    assert item["line_total"] == 0.0
    assert draft["total_amount"] == 0.0


def test_draft_spelling_variation():
    """Verify misspelled product 'do packet sarsan tel' matches Mustard oil."""
    payload = {"text": "do packet sarsan tel"}
    res = client.post("/api/v1/billing/draft", json=payload)
    assert res.status_code == 200
    draft = res.json()

    assert draft["matched_items_count"] == 1
    assert "Mustard Oil" in draft["items"][0]["product_name"]
    assert draft["items"][0]["quantity"] == 2.0


def test_draft_recalculation_on_edit_and_delete():
    """Verify POST /api/v1/billing/draft/recalculate updates subtotal and total."""
    # Start with initial draft
    initial = client.post("/api/v1/billing/draft", json={"text": "Do kilo cheeni aur ek packet doodh"}).json()
    items = initial["items"]
    assert len(items) == 2

    # 1. Edit quantity of first item from 2.0 to 5.0
    items[0]["quantity"] = 5.0
    res_recalc = client.post("/api/v1/billing/draft/recalculate", json={"items": items})
    assert res_recalc.status_code == 200
    recalculated = res_recalc.json()

    assert recalculated["items"][0]["quantity"] == 5.0
    assert recalculated["items"][0]["line_total"] == round(5.0 * items[0]["unit_price"], 2)
    assert recalculated["total_amount"] == recalculated["items"][0]["line_total"] + recalculated["items"][1]["line_total"]

    # 2. Delete second item (milk)
    items_after_delete = [items[0]]
    res_delete = client.post("/api/v1/billing/draft/recalculate", json={"items": items_after_delete})
    assert res_delete.status_code == 200
    deleted_data = res_delete.json()

    assert len(deleted_data["items"]) == 1
    assert deleted_data["total_amount"] == recalculated["items"][0]["line_total"]


def test_inventory_strictly_unchanged():
    """
    CRITICAL SAFETY REQUIREMENT:
    Verify that generating drafts and recalculating drafts causes ZERO inventory deductions
    and ZERO new rows in bills or bill_items tables.
    """
    db = SessionLocal()
    try:
        # Capture pre-test inventory snapshots
        pre_products = {p.id: p.stock_quantity for p in db.query(Product).all()}
        pre_bills_count = db.query(Bill).count()
        pre_bill_items_count = db.query(BillItem).count()

        # Execute multiple draft operations
        client.post("/api/v1/billing/draft", json={"text": "100 kilo cheeni aur 50 packet doodh"})
        client.post("/api/v1/billing/draft", json={"text": "Aadha kilo sarson tel"})
        client.post("/api/v1/billing/draft", json={"text": "Dhai kilo chawal aur teen packet maggi"})
        client.post("/api/v1/billing/draft/recalculate", json={
            "items": [
                {"product_id": 1, "product_name": "Atta", "quantity": 20.0, "unit": "packet", "unit_price": 225.0, "line_total": 4500.0, "status": "MATCHED"}
            ]
        })

        # Capture post-test database state
        post_products = {p.id: p.stock_quantity for p in db.query(Product).all()}
        post_bills_count = db.query(Bill).count()
        post_bill_items_count = db.query(BillItem).count()

        # Assert zero change
        assert pre_products == post_products, "Product stock was altered during draft billing!"
        assert pre_bills_count == post_bills_count, "Bills table was modified during draft billing!"
        assert pre_bill_items_count == post_bill_items_count, "Bill items were inserted during draft billing!"
    finally:
        db.close()


if __name__ == "__main__":
    print("Running Step 5 Voice Billing Integration & POS Draft Bill Tests...")
    test_draft_example_1_cheeni_and_doodh()
    print("[PASS] Example 1: 'Do kilo cheeni aur ek packet doodh' -> Accurate draft bill")
    test_draft_example_2_sarson_tel()
    print("[PASS] Example 2: 'Aadha kilo sarson tel' -> 0.5 qty draft line")
    test_draft_example_3_chawal_and_maggi()
    print("[PASS] Example 3: 'Dhai kilo chawal aur teen packet maggi' -> 2 items parsed & priced")
    test_draft_example_4_ek_kilo_chini()
    print("[PASS] Example 4: 'ek kilo chini' -> Sugar alias resolved in draft")
    test_draft_unmatched_product()
    print("[PASS] Unmatched handling: 'dragonfruit' flagged UNMATCHED without crashing")
    test_draft_spelling_variation()
    print("[PASS] Spelling tolerance: 'sarsan tel' resolved to Mustard Oil")
    test_draft_recalculation_on_edit_and_delete()
    print("[PASS] Recalculate: Inline quantity edits and line deletion update total dynamically")
    test_inventory_strictly_unchanged()
    print("[PASS] INVENTORY SAFETY: Stock quantities and Bill tables remained 100% untouched")
    print("\nALL STEP 5 TESTS PASSED SUCCESSFULLY!")
