"""
ElevenLabs & Multi-Layer Text-to-Speech (TTS) Service
Provides bulletproof 3-layer voice fallback and caching:
  Layer 1: SHA-256 local disk audio caching (.tts_cache/<hash>.mp3) + memory cache.
  Layer 2: ElevenLabs Flash v2.5 with automatic fallback to edge-tts (en-IN-PrabhatNeural / hi-IN-SwaraNeural).
  Layer 3: Browser offline speech synthesis signal when client-side fallback is required.
"""

import os
import re
import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict
import httpx
from fastapi import HTTPException, status

from backend.config import settings

logger = logging.getLogger("elevenlabs_service")

# In-memory audio byte cache for sub-millisecond repeated playback
_MEMORY_AUDIO_CACHE: Dict[str, bytes] = {}


def get_api_key() -> str:
    """Retrieves ElevenLabs API key from settings or environment."""
    key = settings.ELEVENLABS_API_KEY or os.getenv("ELEVENLABS_API_KEY", "")
    return key.strip()


def get_default_voice_id() -> str:
    """Retrieves default ElevenLabs Voice ID from settings or environment."""
    voice_id = settings.ELEVENLABS_VOICE_ID or os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    return voice_id.strip() or "JBFqnCBsd6RMkjVDRZzb"


def get_model_id() -> str:
    """Retrieves ElevenLabs Model ID (defaulting to eleven_flash_v2_5)."""
    return (settings.ELEVENLABS_MODEL_ID or "eleven_flash_v2_5").strip()


def get_voice_provider() -> str:
    """Retrieves configured voice provider: 'elevenlabs', 'edge-tts', or 'browser'."""
    prov = getattr(settings, "VOICE_PROVIDER", "elevenlabs") or os.getenv("VOICE_PROVIDER", "elevenlabs")
    return prov.strip().lower()


def compute_cache_key(text: str, voice_id: str, model_id: str) -> str:
    """Generates a deterministic SHA-256 hash for audio caching."""
    normalized_text = " ".join(text.strip().split())
    raw_key = f"{voice_id}:{model_id}:{normalized_text}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def count_cached_phrases() -> int:
    """Counts total cached MP3 phrases in disk cache directory."""
    try:
        if settings.TTS_CACHE_DIR.exists():
            return len(list(settings.TTS_CACHE_DIR.glob("*.mp3")))
    except Exception as e:
        logger.warning(f"Failed to count cached phrases: {e}")
    return len(_MEMORY_AUDIO_CACHE)


def detect_edge_voice(text: str) -> str:
    """
    Selects the most natural edge-tts neural voice:
    - Hindi (hi-IN-SwaraNeural) if Devanagari script or Hinglish retail keywords detected.
    - Indian English (en-IN-PrabhatNeural) otherwise.
    """
    # 1. Check for Devanagari Unicode range
    if re.search(r"[\u0900-\u097F]", text):
        return getattr(settings, "EDGE_TTS_VOICE_HI", "hi-IN-SwaraNeural")

    # 2. Check for common Hinglish retail phrases
    hinglish_keywords = {
        "namaste", "dhanyawad", "shukriya", "udhaar", "khata", "maal",
        "khatam", "paisa", "rupaye", "kaise", "karein", "batao", "kitna",
        "hai", "hain", "aapse", "aapka", "bhai", "dukaan", "kirana",
        "grahak", "customer", "bacha", "bhejo", "jama"
    }
    words = set(re.findall(r"\w+", text.lower()))
    if len(words.intersection(hinglish_keywords)) >= 2:
        return getattr(settings, "EDGE_TTS_VOICE_HI", "hi-IN-SwaraNeural")

    return getattr(settings, "EDGE_TTS_VOICE_EN", "en-IN-PrabhatNeural")


async def synthesize_edge_tts(text: str, voice: Optional[str] = None) -> bytes:
    """
    Synthesizes speech using edge-tts (Layer 2 unlimited free fallback).
    """
    try:
        import edge_tts
    except ImportError as e:
        logger.error(f"edge-tts package is not available: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="edge-tts package is not installed on the server."
        )

    clean_text = text.strip()
    selected_voice = voice or detect_edge_voice(clean_text)
    communicate = edge_tts.Communicate(clean_text, selected_voice)

    audio_buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            audio_buffer.extend(chunk.get("data", b""))

    if not audio_buffer:
        raise ValueError("edge-tts stream completed with empty audio buffer.")

    return bytes(audio_buffer)


async def synthesize_speech(
    text: str,
    voice_id: Optional[str] = None
) -> Tuple[bytes, bool, str]:
    """
    Synthesizes speech using the 3-Layer bulletproof architecture:
      Layer 1: SHA-256 Memory & Local Disk Caching (.tts_cache/<hash>.mp3).
      Layer 2: ElevenLabs Flash v2.5 with automatic fallback to edge-tts on quota/error.
      Layer 3: Browser TTS signal if provider='browser' or if offline.

    Returns:
        Tuple[bytes, bool, str]: (audio_bytes, was_cached, provider_name)
    """
    if not text or not text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Speech text cannot be empty."
        )

    clean_text = text.strip()
    active_voice_id = (voice_id or get_default_voice_id()).strip()
    model_id = get_model_id()
    cache_key = compute_cache_key(clean_text, active_voice_id, model_id)
    provider_config = get_voice_provider()

    # Browser-only override mode
    if provider_config == "browser":
        return b"", False, "browser"

    # =========================================================================
    # LAYER 1: SHA-256 Memory & Local Disk Caching (0 API calls, 0 credits)
    # =========================================================================
    if cache_key in _MEMORY_AUDIO_CACHE:
        logger.debug(f"TTS Memory Cache HIT for text '{clean_text[:30]}...' [key={cache_key[:8]}]")
        return _MEMORY_AUDIO_CACHE[cache_key], True, "cache"

    cache_file = settings.TTS_CACHE_DIR / f"{cache_key}.mp3"
    if cache_file.exists():
        try:
            audio_bytes = cache_file.read_bytes()
            if len(audio_bytes) > 0:
                _MEMORY_AUDIO_CACHE[cache_key] = audio_bytes
                logger.debug(f"TTS Disk Cache HIT for text '{clean_text[:30]}...' [key={cache_key[:8]}]")
                return audio_bytes, True, "cache"
        except Exception as read_err:
            logger.warning(f"Failed to read disk cache file {cache_file}: {read_err}")

    # =========================================================================
    # Direct edge-tts provider mode (skips ElevenLabs entirely to save credits)
    # =========================================================================
    if provider_config in ["edge-tts", "edge_tts"]:
        try:
            audio_bytes = await synthesize_edge_tts(clean_text)
            _save_to_cache(cache_key, cache_file, audio_bytes)
            logger.info(f"Synthesized via edge-tts ({len(audio_bytes)} bytes) [key={cache_key[:8]}]")
            return audio_bytes, False, "edge-tts"
        except Exception as edge_err:
            logger.error(f"edge-tts synthesis failed: {edge_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"edge-tts synthesis failed: {edge_err}"
            )

    # =========================================================================
    # LAYER 2: ElevenLabs with Automatic edge-tts Fallback on Quota/API Error
    # =========================================================================
    api_key = get_api_key()

    # If ElevenLabs API key is missing or blank, seamlessly fall back to edge-tts
    if not api_key:
        logger.warning("ELEVENLABS_API_KEY is not configured. Falling back to Layer 2: edge-tts.")
        try:
            audio_bytes = await synthesize_edge_tts(clean_text)
            _save_to_cache(cache_key, cache_file, audio_bytes)
            return audio_bytes, False, "edge-tts"
        except Exception as edge_err:
            logger.error(f"edge-tts fallback failed: {edge_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Speech synthesis failed across ElevenLabs and edge-tts: {edge_err}"
            )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{active_voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }
    payload = {
        "text": clean_text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.55,
            "similarity_boost": 0.75
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=payload)

        # Successful ElevenLabs generation
        if response.status_code == 200 and response.content:
            audio_bytes = response.content
            _save_to_cache(cache_key, cache_file, audio_bytes)
            logger.info(f"Synthesized via ElevenLabs ({len(audio_bytes)} bytes) [key={cache_key[:8]}]")
            return audio_bytes, False, "elevenlabs"

        # Quota/API Error (401, 402, 403, 429) -> Auto Fallback to edge-tts
        logger.warning(
            f"ElevenLabs API returned {response.status_code}. Automatically falling back to Layer 2: edge-tts."
        )
        audio_bytes = await synthesize_edge_tts(clean_text)
        _save_to_cache(cache_key, cache_file, audio_bytes)
        return audio_bytes, False, "edge-tts"

    except Exception as exc:
        logger.warning(
            f"ElevenLabs request error ({exc}). Automatically falling back to Layer 2: edge-tts."
        )
        try:
            audio_bytes = await synthesize_edge_tts(clean_text)
            _save_to_cache(cache_key, cache_file, audio_bytes)
            return audio_bytes, False, "edge-tts"
        except Exception as edge_err:
            logger.error(f"Layer 2 edge-tts also failed: {edge_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Both ElevenLabs and edge-tts failed: {edge_err}"
            )


def _save_to_cache(cache_key: str, cache_file: Path, audio_bytes: bytes) -> None:
    """Helper to store audio in memory and disk cache."""
    try:
        settings.TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(audio_bytes)
    except Exception as write_err:
        logger.warning(f"Failed to write TTS disk cache: {write_err}")

    _MEMORY_AUDIO_CACHE[cache_key] = audio_bytes


def get_voice_status() -> dict:
    """Returns current voice engine configuration, active provider, and cache status."""
    api_key = get_api_key()
    is_configured = bool(api_key and len(api_key) >= 10)
    cached_count = count_cached_phrases()
    provider = get_voice_provider()

    has_edge_tts = False
    try:
        import edge_tts
        has_edge_tts = True
    except ImportError:
        pass

    return {
        "status": "active" if (is_configured or has_edge_tts) else "unconfigured",
        "configured": is_configured,
        "voice_id": get_default_voice_id(),
        "model_id": get_model_id(),
        "cached_phrases": cached_count,
        "provider": provider,
        "fallback_available": has_edge_tts,
        "edge_tts_available": has_edge_tts
    }
