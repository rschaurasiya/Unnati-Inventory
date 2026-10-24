"""
Deterministic Hindi / Hinglish Voice Billing NLP Parser
Extracts quantities, units, and product names from natural shopkeeper speech
and matches them against the active store inventory catalog.
"""
import re
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from backend.nlp.dictionary import (
    QUANTITY_WORDS, UNIT_MAP, ITEM_CONJUNCTIONS, FILLER_WORDS,
    normalize_devanagari_digits
)
from backend.nlp.matcher import ProductMatcher


class VoiceBillingParser:
    """Parses natural Hindi/Hinglish/English speech into structured line items with catalog matches."""

    def __init__(self, db: Session):
        self.db = db
        self.matcher = ProductMatcher(db)

    def parse(self, transcript: str, language: Optional[str] = "hinglish") -> Dict[str, Any]:
        """
        Main entry point: parses raw speech transcript into structured line items.
        Returns parsed items, counts, and estimated total.
        """
        raw_text = transcript.strip()
        if not raw_text:
            return {
                "raw_text": "",
                "items": [],
                "matched_count": 0,
                "unmatched_count": 0,
                "ambiguous_count": 0,
                "total_estimated_amount": 0.0
            }

        # Normalize any Devanagari digits (०-९ -> 0-9)
        normalized_text = normalize_devanagari_digits(raw_text)

        # 1. Clean conversational filler words
        cleaned_text = self._clean_fillers(normalized_text)

        # 2. Split into individual item phrases
        item_phrases = self._split_into_item_phrases(cleaned_text)

        # 3. Parse each phrase into (quantity, unit, product_query)
        parsed_items: List[Dict[str, Any]] = []
        total_amount = 0.0
        matched_count = 0
        unmatched_count = 0
        ambiguous_count = 0

        for phrase in item_phrases:
            phrase = phrase.strip()
            if not phrase:
                continue

            extracted = self._extract_item_components(phrase)
            if not extracted:
                continue

            raw_qty = extracted["quantity"]
            raw_unit = extracted["unit"]
            raw_item_name = extracted["item_name"]

            # Match with database catalog using tiered matching
            match_res = self.matcher.match(raw_item_name, spoken_unit=raw_unit, language=language)

            # Reconcile units and quantities
            final_qty, final_unit = self._reconcile_unit_and_quantity(
                raw_qty, raw_unit, match_res.get("catalog_unit")
            )

            unit_price = match_res.get("unit_price", 0.0)
            line_total = round(final_qty * unit_price, 2) if match_res["status"] == "MATCHED" else 0.0

            item_entry = {
                "product_id": match_res.get("product_id"),
                "product_name": match_res.get("product_name"),
                "matched_alias": match_res.get("matched_alias"),
                "raw_input_phrase": phrase,
                "raw_item_name": raw_item_name,
                "quantity": final_qty,
                "unit": final_unit,
                "unit_price": unit_price,
                "line_total": line_total,
                "confidence": match_res.get("confidence", 0.0),
                "status": match_res["status"],
                "match_status": match_res.get("match_status", match_res["status"]),
                "unmatched_reason": match_res.get("unmatched_reason")
            }

            parsed_items.append(item_entry)

            if match_res["status"] == "MATCHED":
                matched_count += 1
                total_amount += line_total
            elif match_res["status"] == "AMBIGUOUS":
                ambiguous_count += 1
                total_amount += line_total
            else:
                unmatched_count += 1

        return {
            "raw_text": raw_text,
            "items": parsed_items,
            "matched_count": matched_count,
            "unmatched_count": unmatched_count,
            "ambiguous_count": ambiguous_count,
            "total_estimated_amount": round(total_amount, 2)
        }

    def _clean_fillers(self, text: str) -> str:
        """Removes conversational filler phrases like 'bhaiya', 'de do', 'chahiye', 'कृपया'."""
        cleaned = text.lower()
        # Sort fillers by length descending so longer phrases match first
        for filler in sorted(FILLER_WORDS, key=len, reverse=True):
            # Support word boundary or whitespace for both Latin and Devanagari
            pattern = r'(?:\b|^|\s)' + re.escape(filler.lower()) + r'(?:\b|$|\s)'
            cleaned = re.sub(pattern, ' ', cleaned)
        return re.sub(r'\s+', ' ', cleaned).strip()

    def _split_into_item_phrases(self, text: str) -> List[str]:
        """
        Splits a compound sentence into separate item phrases.
        Handles conjunctions ('aur', 'and', ',', 'और') and boundary detection on new quantity words.
        """
        # First, normalize conjunctions to a unified delimiter '|'
        delimited = text
        for conj in sorted(ITEM_CONJUNCTIONS, key=len, reverse=True):
            if conj in [",", "&", "+"]:
                delimited = delimited.replace(conj, " | ")
            else:
                pattern = r'(?:\b|^|\s)' + re.escape(conj.lower()) + r'(?:\b|$|\s)'
                delimited = re.sub(pattern, ' | ', delimited)

        # Split on the delimiter
        raw_splits = [p.strip() for p in delimited.split("|") if p.strip()]

        # Secondary pass: if a phrase contains multiple quantity + unit patterns without conjunctions,
        # e.g. "do kilo cheeni ek packet doodh"
        final_phrases: List[str] = []
        qty_pattern = r'(?:\b|^|\s)(' + '|'.join(re.escape(k) for k in QUANTITY_WORDS.keys()) + r'|\d+(?:\.\d+)?)(?:\b|$|\s)'

        for segment in raw_splits:
            matches = list(re.finditer(qty_pattern, segment))
            if len(matches) <= 1:
                final_phrases.append(segment)
            else:
                # Split at second and subsequent quantity match positions
                prev_idx = 0
                for i in range(1, len(matches)):
                    start = matches[i].start()
                    sub_phrase = segment[prev_idx:start].strip()
                    if sub_phrase:
                        final_phrases.append(sub_phrase)
                    prev_idx = start
                remainder = segment[prev_idx:].strip()
                if remainder:
                    final_phrases.append(remainder)

        return [p for p in final_phrases if p]

    def _extract_item_components(self, phrase: str) -> Optional[Dict[str, Any]]:
        """
        Extracts (quantity, unit, product_name) from a single item phrase.
        Handles numeric digits (e.g. '2.5', '2') and words (e.g. 'do', 'aadha', 'dhai').
        """
        tokens = phrase.split()
        if not tokens:
            return None

        quantity: float = 1.0
        unit: Optional[str] = None
        item_tokens: List[str] = []

        i = 0
        qty_found = False

        while i < len(tokens):
            token = tokens[i].lower()

            # 1. Check if token is a quantity (digit or word)
            if not qty_found:
                # Check direct numeric digit: e.g. "2", "2.5", "500"
                if re.match(r'^\d+(\.\d+)?$', token):
                    quantity = float(token)
                    qty_found = True
                    i += 1
                    continue
                # Check Hindi/English quantity word: e.g. "do", "aadha", "dhai", "ek"
                elif token in QUANTITY_WORDS:
                    quantity = QUANTITY_WORDS[token]
                    qty_found = True
                    i += 1
                    continue

            # 2. Check if token is a unit: e.g. "kilo", "kg", "packet", "litre", "gram"
            if unit is None and token in UNIT_MAP:
                unit = UNIT_MAP[token]
                i += 1
                continue

            # 3. Check for multi-word unit combinations: e.g. "pao kilo" -> handled as fraction + kg
            if token in ["kilo", "kg"] and unit is None:
                unit = "kg"
                i += 1
                continue

            # 4. Otherwise, token belongs to the product name
            item_tokens.append(tokens[i])
            i += 1

        product_name = " ".join(item_tokens).strip()

        # If no product name was extracted but the phrase had content, treat the phrase as product
        if not product_name:
            product_name = phrase

        # Default unit to 'piece' or 'unit' if none mentioned
        if unit is None:
            unit = "piece"

        return {
            "quantity": quantity,
            "unit": unit,
            "item_name": product_name
        }

    def _reconcile_unit_and_quantity(
        self,
        spoken_qty: float,
        spoken_unit: str,
        catalog_unit: Optional[str]
    ) -> (float, str):
        """
        Converts units/quantities to match the catalog representation.
        Example: If customer says '500 gram cheeni' and catalog is in 'kg',
        reconciles to 0.5 kg.
        """
        if not catalog_unit:
            return spoken_qty, spoken_unit

        c_unit = catalog_unit.lower()
        s_unit = spoken_unit.lower()

        # Weight conversion: gram -> kg
        if c_unit == "kg" and s_unit == "gram":
            return round(spoken_qty / 1000.0, 3), "kg"

        # Volume conversion: ml -> litre
        if c_unit == "litre" and s_unit == "ml":
            return round(spoken_qty / 1000.0, 3), "litre"

        # If catalog is packet/piece and user said kg or vice versa, adhere to catalog unit
        if s_unit == "piece" and c_unit in ["packet", "piece"]:
            return spoken_qty, c_unit

        return spoken_qty, c_unit if c_unit else spoken_unit
