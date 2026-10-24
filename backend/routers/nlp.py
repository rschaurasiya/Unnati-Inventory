"""
NLP Voice Parsing API Router
Provides endpoints to parse natural spoken or typed Hindi/Hinglish order phrases into structured line items.
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas import VoiceParseRequest, VoiceParseResponse
from backend.nlp.parser import VoiceBillingParser

router = APIRouter(prefix="/api/v1/nlp", tags=["NLP Voice Parsing"])


@router.post("/parse", response_model=VoiceParseResponse, status_code=status.HTTP_200_OK)
def parse_voice_order(payload: VoiceParseRequest, db: Session = Depends(get_db)):
    """
    Parses a natural Hindi, Hinglish, or English order sentence into structured items with catalog matching.
    Does NOT modify inventory or create permanent bills.
    """
    parser = VoiceBillingParser(db)
    result = parser.parse(payload.text, language=payload.language or "hinglish")
    return result
