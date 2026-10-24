import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product
from backend.nlp.dictionary import (
    DEVANAGARI_DIGITS,
    QUANTITY_WORDS,
    UNIT_MAP,
    normalize_devanagari_digits,
)
from backend.nlp.parser import VoiceBillingParser
from backend.nlp.matcher import ProductMatcher

client = TestClient(app)


def test_devanagari_dictionary_definitions():
    """Verify Devanagari numerals, fractions, units and normalization."""
    # Test normalization of devanagari numerals
    assert normalize_devanagari_digits("२ किलो") == "2 किलो"
    assert normalize_devanagari_digits("५०० ग्राम") == "500 ग्राम"

    # Test dictionary definitions
    assert "दो" in QUANTITY_WORDS and QUANTITY_WORDS["दो"] == 2.0
    assert "तीन" in QUANTITY_WORDS and QUANTITY_WORDS["तीन"] == 3.0
    assert "आधा" in QUANTITY_WORDS and QUANTITY_WORDS["आधा"] == 0.5
    assert "ढाई" in QUANTITY_WORDS and QUANTITY_WORDS["ढाई"] == 2.5
    assert "किलो" in UNIT_MAP and UNIT_MAP["किलो"] == "kg"
    assert "पैकेट" in UNIT_MAP and UNIT_MAP["पैकेट"] == "packet"
    assert "०" in DEVANAGARI_DIGITS and DEVANAGARI_DIGITS["९"] == "9"


def test_hindi_devanagari_parsing_and_matching():
    """Verify parser extracts items correctly from Hindi Devanagari speech."""
    db = SessionLocal()
    try:
        parser = VoiceBillingParser(db)
        res = parser.parse("दो किलो चीनी और एक पैकेट दूध", language="hindi")
        assert len(res["items"]) == 2
        assert res["matched_count"] == 2

        sugar = res["items"][0]
        assert sugar["quantity"] == 2.0
        assert sugar["unit"] == "kg"
        assert sugar["status"] == "MATCHED"
        assert sugar["match_status"] == "MATCHED"

        milk = res["items"][1]
        assert milk["quantity"] == 1.0
        assert milk["unit"] == "packet"
        assert milk["status"] == "MATCHED"
        assert milk["match_status"] == "MATCHED"
    finally:
        db.close()


def test_colloquial_devanagari_fractions_and_fillers():
    """Verify Devanagari fractions (ढाई, आधा) and filler words removal."""
    db = SessionLocal()
    try:
        parser = VoiceBillingParser(db)
        # With filler "भैया" and "दे दो"
        res = parser.parse("भैया ढाई किलो चावल और आधा किलो सरसों तेल दे दो", language="hindi")
        assert len(res["items"]) == 2
        assert res["matched_count"] == 2

        rice = res["items"][0]
        assert rice["quantity"] == 2.5
        assert rice["unit"] == "kg"
        assert rice["status"] == "MATCHED"

        oil = res["items"][1]
        assert oil["quantity"] == 0.5
        assert oil["unit"] in ["kg", "bottle", "liter", "packet", "pouch"]
        assert oil["status"] == "MATCHED"
    finally:
        db.close()


def test_tiered_matching_cross_language_fallback():
    """Verify 3-step tiered matching algorithm."""
    db = SessionLocal()
    try:
        matcher = ProductMatcher(db)

        # Step 1: English primary match on name
        res_en = matcher.match("sugar", spoken_unit="kg", language="english")
        assert res_en["status"] == "MATCHED"
        assert res_en["match_status"] == "MATCHED"

        # Step 1: Hinglish primary match on aliases
        res_hi_alias = matcher.match("cheeni", spoken_unit="kg", language="hinglish")
        assert res_hi_alias["status"] == "MATCHED"
        assert res_hi_alias["match_status"] == "MATCHED"

        # Step 1: Hindi primary match on hindi_name
        res_dev = matcher.match("चीनी", spoken_unit="kg", language="hindi")
        assert res_dev["status"] == "MATCHED"
        assert res_dev["match_status"] == "MATCHED"

        # Step 2: Cross-language fallback (selected language is Hindi, but user says English "mustard oil")
        res_fallback = matcher.match("mustard oil", spoken_unit="liter", language="hindi")
        assert res_fallback["status"] == "MATCHED"
        assert res_fallback["match_status"] == "MATCHED"

        # Step 3: Product Not Available State (unmatched item)
        res_unm = matcher.match("dragonfruit exotic", spoken_unit="kg", language="hinglish")
        assert res_unm["status"] == "UNMATCHED"
        assert res_unm["match_status"] == "UNMATCHED"
        assert "Product Not Available" in res_unm["unmatched_reason"]
    finally:
        db.close()


def test_api_draft_bill_with_language_parameter():
    """Verify /api/v1/billing/draft endpoint with language parameter."""
    payload_hindi = {
        "text": "दो किलो चीनी और एक पैकेट दूध",
        "language": "hindi"
    }
    res = client.post("/api/v1/billing/draft", json=payload_hindi)
    assert res.status_code == 200
    data = res.json()
    assert "draft_id" in data
    assert "items" in data
    assert len(data["items"]) == 2
    assert all(it["status"] == "MATCHED" for it in data["items"])

    payload_english = {
        "text": "2 kg sugar and 1 packet milk",
        "language": "english"
    }
    res_en = client.post("/api/v1/billing/draft", json=payload_english)
    assert res_en.status_code == 200
    data_en = res_en.json()
    assert len(data_en["items"]) == 2

    # Test unknown item in draft
    payload_unmatched = {
        "text": "1 kg dragonfruit",
        "language": "english"
    }
    res_unm = client.post("/api/v1/billing/draft", json=payload_unmatched)
    assert res_unm.status_code == 200
    data_unm = res_unm.json()
    assert data_unm["unmatched_items_count"] >= 1
    unmatched_item = [it for it in data_unm["items"] if it["status"] == "UNMATCHED"][0]
    assert unmatched_item["match_status"] == "UNMATCHED"
    assert "Product Not Available" in unmatched_item["unmatched_reason"]


def test_unmatched_items_cannot_be_finalized():
    """Verify that unmatched items without valid catalog product ID fail on finalize."""
    invalid_finalize_payload = {
        "items": [
            {"product_id": 999999, "quantity": 1.0}
        ],
        "payment_mode": "CASH"
    }
    res = client.post("/api/v1/billing/finalize", json=invalid_finalize_payload)
    assert res.status_code == 400
    assert "does not exist" in res.json()["detail"].lower()
