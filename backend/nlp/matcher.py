"""
Product Catalog Matcher using RapidFuzz
Performs tolerant phonetic and token-based similarity matching between
spoken/transcribed item phrases and the store's active product inventory.
"""
from typing import Optional, Dict, Any, List
from rapidfuzz import fuzz
from sqlalchemy.orm import Session
from backend.models import Product


class ProductMatcher:
    """Matches raw spoken product names against the database product catalog."""

    def __init__(self, db: Session):
        self.db = db
        self.products: List[Product] = self.db.query(Product).all()

    def refresh_catalog(self):
        """Refreshes product list from database."""
        self.products = self.db.query(Product).all()

    def match(
        self,
        raw_query: str,
        spoken_unit: Optional[str] = None,
        language: Optional[str] = "hinglish"
    ) -> Dict[str, Any]:
        """
        Match a raw spoken item string (e.g. 'cheeni', 'sarson tel', 'maggi') to the catalog
        using a 3-step tiered language matching pipeline:
          Step 1: Primary Selected Language Search (english -> name, hinglish -> aliases, hindi -> hindi_name)
          Step 2: Remaining Two Languages Fallback (if primary score < 78.0)
          Step 3: Product Not Available State (UNMATCHED if score < 72.0)
        """
        clean_query = raw_query.strip().lower()

        if not clean_query:
            return {
                "product_id": None,
                "product_name": raw_query,
                "matched_alias": None,
                "confidence": 0.0,
                "status": "UNMATCHED",
                "match_status": "UNMATCHED",
                "unit_price": 0.0,
                "catalog_unit": None,
                "stock_quantity": 0.0,
                "min_stock_threshold": 0.0,
                "unmatched_reason": "Product Not Available: Empty product query."
            }

        query_tokens = set(clean_query.split())

        # Normalize target language selection
        lang = (language or "hinglish").strip().lower()
        if lang in ["hi", "hindi", "devanagari"]:
            lang = "hindi"
        elif lang in ["en", "english"]:
            lang = "english"
        else:
            lang = "hinglish"

        def _score_cand(cand: str) -> float:
            cand_clean = cand.strip().lower()
            if not cand_clean:
                return 0.0
            if clean_query == cand_clean:
                return 100.0
            cand_tokens = set(cand_clean.split())
            if cand_tokens and cand_tokens.issubset(query_tokens):
                return 100.0
            score_sort = fuzz.token_sort_ratio(clean_query, cand_clean)
            score_set = fuzz.token_set_ratio(clean_query, cand_clean)
            return float(max(score_sort, score_set * 0.9))

        best_product: Optional[Product] = None
        best_score: float = 0.0
        best_alias: Optional[str] = None

        # -------------------------------------------------------------
        # STEP 1: Primary Selected Language Search
        # -------------------------------------------------------------
        for p in self.products:
            primary_cands: List[str] = []
            if lang == "english":
                if p.name:
                    primary_cands.append(p.name.lower())
            elif lang == "hindi":
                if p.hindi_name:
                    primary_cands.append(p.hindi_name.lower())
            else:  # hinglish
                if p.aliases:
                    primary_cands.extend([a.strip().lower() for a in p.aliases.split(",") if a.strip()])

            for cand in primary_cands:
                cand_score = _score_cand(cand)
                if cand_score > best_score:
                    best_score = cand_score
                    best_product = p
                    best_alias = cand

        # -------------------------------------------------------------
        # STEP 2: Remaining Two Languages Fallback
        # If no match meets the confidence threshold (78.0) in primary,
        # search across the remaining two language fields.
        # -------------------------------------------------------------
        if best_score < 78.0:
            for p in self.products:
                fallback_cands: List[str] = []
                if lang == "english":
                    if p.aliases:
                        fallback_cands.extend([a.strip().lower() for a in p.aliases.split(",") if a.strip()])
                    if p.hindi_name:
                        fallback_cands.append(p.hindi_name.lower())
                elif lang == "hindi":
                    if p.name:
                        fallback_cands.append(p.name.lower())
                    if p.aliases:
                        fallback_cands.extend([a.strip().lower() for a in p.aliases.split(",") if a.strip()])
                else:  # hinglish
                    if p.name:
                        fallback_cands.append(p.name.lower())
                    if p.hindi_name:
                        fallback_cands.append(p.hindi_name.lower())

                for cand in fallback_cands:
                    cand_score = _score_cand(cand)
                    if cand_score > best_score:
                        best_score = cand_score
                        best_product = p
                        best_alias = cand

        confidence = round(best_score / 100.0, 2)

        # -------------------------------------------------------------
        # STEP 3: Classification / Product Not Available State
        # -------------------------------------------------------------
        if best_product and best_score >= 78.0:
            return {
                "product_id": best_product.id,
                "product_name": best_product.name,
                "matched_alias": best_alias,
                "confidence": confidence,
                "status": "MATCHED",
                "match_status": "MATCHED",
                "unit_price": best_product.unit_price,
                "catalog_unit": best_product.unit,
                "stock_quantity": best_product.stock_quantity,
                "min_stock_threshold": best_product.min_stock_threshold,
                "unmatched_reason": None
            }
        elif best_product and best_score >= 72.0:
            return {
                "product_id": best_product.id,
                "product_name": best_product.name,
                "matched_alias": best_alias,
                "confidence": confidence,
                "status": "AMBIGUOUS",
                "match_status": "AMBIGUOUS",
                "unit_price": best_product.unit_price,
                "catalog_unit": best_product.unit,
                "stock_quantity": best_product.stock_quantity,
                "min_stock_threshold": best_product.min_stock_threshold,
                "unmatched_reason": f"Low match confidence ({confidence * 100:.0f}%). Closest item: '{best_product.name}'."
            }
        else:
            return {
                "product_id": None,
                "product_name": raw_query,
                "matched_alias": None,
                "confidence": confidence,
                "status": "UNMATCHED",
                "match_status": "UNMATCHED",
                "unit_price": 0.0,
                "catalog_unit": None,
                "stock_quantity": 0.0,
                "min_stock_threshold": 0.0,
                "unmatched_reason": f"Product Not Available: No product in catalog matches '{raw_query}' (Best similarity: {confidence * 100:.0f}%)."
            }
