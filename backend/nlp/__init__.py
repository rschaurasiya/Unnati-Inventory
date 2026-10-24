"""
NLP Parsing Package for Shopkeeper Voice Billing
Supports Hindi, Hinglish, and English sentence parsing, quantity word resolution,
unit normalization, and fuzzy product matching against the store catalog.
"""
from backend.nlp.parser import VoiceBillingParser

__all__ = ["VoiceBillingParser"]
