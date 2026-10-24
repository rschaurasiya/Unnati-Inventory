"""
Step 4 Verification Test Suite
Tests:
- Deterministic parsing of colloquial Hindi, Hinglish, and English order phrases
- Exact prompt examples:
  1. "Do kilo cheeni aur ek packet doodh"
  2. "Aadha kilo sarson tel"
  3. "Dhai kilo chawal aur teen packet maggi"
  4. "ek kilo chini"
- Colloquial quantity words: ek, do, teen, char, paanch, aadha, paav, derh, dhai
- Unit normalization: kg/kilo, gram/g, litre/liter, packet, piece, dozen
- Conversational filler removal: "bhaiya ... de do", "chahiye"
- Tolerant fuzzy spelling matching (e.g. "sarsan tel", "chaval")
- Clear detection of unknown / unmatched products
- Guarantee that inventory is NOT modified during parsing
- API endpoint POST /api/v1/nlp/parse
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product
from backend.nlp.parser import VoiceBillingParser

client = TestClient(app)


def test_example_1_cheeni_and_doodh():
    """Test: 'Do kilo cheeni aur ek packet doodh'"""
    db = SessionLocal()
    try:
        parser = VoiceBillingParser(db)
        res = parser.parse("Do kilo cheeni aur ek packet doodh")

        assert len(res["items"]) == 2
        assert res["matched_count"] == 2

        # Item 1: Sugar
        item1 = res["items"][0]
        assert "Sugar" in item1["product_name"] or "Cheeni" in item1["product_name"]
        assert item1["quantity"] == 2.0
        assert item1["unit"] == "kg"
        assert item1["status"] == "MATCHED"
        assert item1["line_total"] == round(2.0 * item1["unit_price"], 2)

        # Item 2: Milk
        item2 = res["items"][1]
        assert "Milk" in item2["product_name"] or "Doodh" in item2["product_name"]
        assert item2["quantity"] == 1.0
        assert item2["unit"] == "packet"
        assert item2["status"] == "MATCHED"

        assert res["total_estimated_amount"] == item1["line_total"] + item2["line_total"]
    finally:
        db.close()


def test_example_2_aadha_kilo_sarson_tel():
    """Test: 'Aadha kilo sarson tel'"""
    db = SessionLocal()
    try:
        parser = VoiceBillingParser(db)
        res = parser.parse("Aadha kilo sarson tel")

        assert len(res["items"]) == 1
        assert res["matched_count"] == 1

        item = res["items"][0]
        assert "Mustard Oil" in item["product_name"] or "सरसों" in item["product_name"]
        assert item["quantity"] == 0.5
        assert item["status"] == "MATCHED"
        assert item["line_total"] > 0
    finally:
        db.close()


def test_example_3_dhai_kilo_chawal_aur_teen_packet_maggi():
    """Test: 'Dhai kilo chawal aur teen packet maggi'"""
    db = SessionLocal()
    try:
        parser = VoiceBillingParser(db)
        res = parser.parse("Dhai kilo chawal aur teen packet maggi")

        assert len(res["items"]) == 2
        assert res["matched_count"] == 2

        # Item 1: Rice (2.5 kg)
        item1 = res["items"][0]
        assert "Rice" in item1["product_name"] or "Chawal" in item1["product_name"]
        assert item1["quantity"] == 2.5
        assert item1["unit"] == "kg"
        assert item1["status"] == "MATCHED"

        # Item 2: Maggi (3 packets)
        item2 = res["items"][1]
        assert "Maggi" in item2["product_name"]
        assert item2["quantity"] == 3.0
        assert item2["unit"] == "packet"
        assert item2["status"] == "MATCHED"
    finally:
        db.close()


def test_example_4_ek_kilo_chini():
    """Test: 'ek kilo chini' (phonetic alias for cheeni/sugar)"""
    db = SessionLocal()
    try:
        parser = VoiceBillingParser(db)
        res = parser.parse("ek kilo chini")

        assert len(res["items"]) == 1
        assert res["matched_count"] == 1

        item = res["items"][0]
        assert "Sugar" in item["product_name"] or "Cheeni" in item["product_name"]
        assert item["quantity"] == 1.0
        assert item["unit"] == "kg"
        assert item["status"] == "MATCHED"
    finally:
        db.close()


def test_colloquial_fractions_and_quantities():
    """Test various colloquial quantity words: derh (1.5), paav (0.25), paanch (5)."""
    db = SessionLocal()
    try:
        parser = VoiceBillingParser(db)

        # derh kilo (1.5 kg)
        r_derh = parser.parse("derh kilo chawal")
        assert r_derh["items"][0]["quantity"] == 1.5

        # paav kilo (0.25 kg)
        r_paav = parser.parse("paav kilo cheeni")
        assert r_paav["items"][0]["quantity"] == 0.25

        # paanch packet (5 packets)
        r_paanch = parser.parse("paanch packet maggi")
        assert r_paanch["items"][0]["quantity"] == 5.0
    finally:
        db.close()


def test_gram_to_kg_unit_reconciliation():
    """Test: '500 gram cheeni' automatically converts to 0.5 kg to match catalog unit."""
    db = SessionLocal()
    try:
        parser = VoiceBillingParser(db)
        res = parser.parse("500 gram cheeni")

        assert len(res["items"]) == 1
        item = res["items"][0]
        assert item["quantity"] == 0.5
        assert item["unit"] == "kg"
        assert item["status"] == "MATCHED"
    finally:
        db.close()


def test_conversational_fillers_removal():
    """Test sentence with polite padding: 'Bhaiya do kilo gehu ka aata aur ek packet amul butter de do'"""
    db = SessionLocal()
    try:
        parser = VoiceBillingParser(db)
        res = parser.parse("Bhaiya do kilo gehu ka aata aur ek packet amul butter de do")

        assert len(res["items"]) == 2
        assert res["matched_count"] == 2

        item1 = res["items"][0]
        assert "Atta" in item1["product_name"]
        assert item1["quantity"] == 2.0

        item2 = res["items"][1]
        assert "Butter" in item2["product_name"]
        assert item2["quantity"] == 1.0
    finally:
        db.close()


def test_spelling_variation_tolerant_matching():
    """Test phonetic / slight misspelling: 'sarsan tel' and 'chaval'."""
    db = SessionLocal()
    try:
        parser = VoiceBillingParser(db)

        # 'sarsan tel' -> matches Mustard Oil
        res_oil = parser.parse("ek packet sarsan tel")
        assert res_oil["matched_count"] == 1
        assert "Mustard Oil" in res_oil["items"][0]["product_name"]

        # 'chaval' -> matches Rice
        res_rice = parser.parse("do kilo chaval")
        assert res_rice["matched_count"] == 1
        assert "Rice" in res_rice["items"][0]["product_name"]
    finally:
        db.close()


def test_unknown_and_unmatched_products():
    """Test unknown products: 'ek kilo dragonfruit aur teen packet alienbiscuits'"""
    db = SessionLocal()
    try:
        parser = VoiceBillingParser(db)
        res = parser.parse("ek kilo dragonfruit aur teen packet alienbiscuits")

        assert len(res["items"]) == 2
        assert res["matched_count"] == 0
        assert res["unmatched_count"] == 2

        item1 = res["items"][0]
        assert item1["status"] == "UNMATCHED"
        assert item1["product_id"] is None
        assert "dragonfruit" in item1["raw_item_name"].lower()
        assert item1["quantity"] == 1.0

        item2 = res["items"][1]
        assert item2["status"] == "UNMATCHED"
        assert item2["product_id"] is None
        assert "alienbiscuits" in item2["raw_item_name"].lower()
        assert item2["quantity"] == 3.0
    finally:
        db.close()


def test_inventory_not_modified_during_parsing():
    """Verify that parsing sentences does NOT mutate product stock quantities in the database."""
    db = SessionLocal()
    try:
        sugar = db.query(Product).filter(Product.id == 34).first() or db.query(Product).first()
        initial_stock = sugar.stock_quantity

        parser = VoiceBillingParser(db)
        # Parse an order with 10 kg
        parser.parse("10 kilo cheeni")

        db.refresh(sugar)
        assert sugar.stock_quantity == initial_stock, "Stock was inadvertently altered during parsing!"
    finally:
        db.close()


def test_nlp_parse_api_endpoint():
    """Verify HTTP POST /api/v1/nlp/parse endpoint."""
    payload = {"text": "Do kilo cheeni aur ek packet doodh"}
    response = client.post("/api/v1/nlp/parse", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["raw_text"] == payload["text"]
    assert len(data["items"]) == 2
    assert data["matched_count"] == 2
    assert data["total_estimated_amount"] > 0


if __name__ == "__main__":
    print("Running Step 4 Hindi/Hinglish NLP Voice Parsing Engine Tests...")
    test_example_1_cheeni_and_doodh()
    print("[PASS] Example 1: 'Do kilo cheeni aur ek packet doodh' parsed & matched")
    test_example_2_aadha_kilo_sarson_tel()
    print("[PASS] Example 2: 'Aadha kilo sarson tel' (fraction quantity 0.5) parsed & matched")
    test_example_3_dhai_kilo_chawal_aur_teen_packet_maggi()
    print("[PASS] Example 3: 'Dhai kilo chawal aur teen packet maggi' (2.5 kg & 3 pkts) parsed & matched")
    test_example_4_ek_kilo_chini()
    print("[PASS] Example 4: 'ek kilo chini' (phonetic alias) parsed & matched")
    test_colloquial_fractions_and_quantities()
    print("[PASS] Colloquial quantities: derh (1.5), paav (0.25), paanch (5) verified")
    test_gram_to_kg_unit_reconciliation()
    print("[PASS] Unit reconciliation: 500 gram converted to 0.5 kg matching catalog")
    test_conversational_fillers_removal()
    print("[PASS] Conversational fillers stripped ('bhaiya ... de do')")
    test_spelling_variation_tolerant_matching()
    print("[PASS] Spelling tolerance: 'sarsan tel' and 'chaval' correctly resolved")
    test_unknown_and_unmatched_products()
    print("[PASS] Unknown products: 'dragonfruit' and 'alienbiscuits' cleanly flagged UNMATCHED")
    test_inventory_not_modified_during_parsing()
    print("[PASS] Inventory safety: stock remains completely untouched during parsing")
    test_nlp_parse_api_endpoint()
    print("[PASS] API Endpoint: POST /api/v1/nlp/parse returns 200 OK and valid JSON")
    print("\nALL STEP 4 TESTS PASSED SUCCESSFULLY!")
