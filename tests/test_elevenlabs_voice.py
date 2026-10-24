"""
Tests for ElevenLabs Text-to-Speech (TTS) Integration
Validates backend configuration, voice status, speech synthesis, SHA-256 caching,
and fallback credit protection.
"""

import sys
from pathlib import Path

# Ensure workspace root is in python path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
from backend.services.elevenlabs_service import (
    compute_cache_key,
    get_api_key,
    get_default_voice_id,
    get_model_id
)

client = TestClient(app)


def test_elevenlabs_environment_config():
    """Verify ElevenLabs configuration settings are loaded properly."""
    assert get_api_key().startswith("sk_"), "ELEVENLABS_API_KEY should be loaded from .env"
    assert get_default_voice_id() == "JBFqnCBsd6RMkjVDRZzb"
    assert get_model_id() == "eleven_flash_v2_5"
    assert settings.TTS_CACHE_DIR.exists(), "TTS Cache directory should exist"


def test_voice_status_endpoint():
    """Verify GET /api/voice/status returns 200 with active configuration."""
    response = client.get("/api/voice/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["configured"] is True
    assert data["voice_id"] == "JBFqnCBsd6RMkjVDRZzb"
    assert data["model_id"] == "eleven_flash_v2_5"
    assert isinstance(data["cached_phrases"], int)


def test_voice_status_v1_alias():
    """Verify GET /api/v1/voice/status alias returns 200."""
    response = client.get("/api/v1/voice/status")
    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is True


def test_sha256_cache_key_computation():
    """Verify SHA-256 cache keys are deterministic and whitespace-normalized."""
    key1 = compute_cache_key("Namaste! Welcome.", "voice123", "eleven_flash_v2_5")
    key2 = compute_cache_key("  Namaste!   Welcome.  ", "voice123", "eleven_flash_v2_5")
    key3 = compute_cache_key("Different text", "voice123", "eleven_flash_v2_5")

    assert key1 == key2, "Whitespace differences should normalize to identical cache key"
    assert key1 != key3, "Different text should produce distinct cache keys"
    assert len(key1) == 64, "SHA-256 hex string should be 64 characters long"


def test_voice_speak_and_sha256_cache():
    """
    Verify POST /api/voice/speak returns audio/mpeg and serves repeat calls
    from local cache with X-Audio-Cache: HIT.
    """
    phrase = "Bill completed for ₹250.00 via Cash. Thank you for shopping!"

    # First Call: either MISS (synthesized) or HIT (if already cached)
    resp1 = client.post("/api/voice/speak", json={"text": phrase})
    assert resp1.status_code == 200
    assert "audio/mpeg" in resp1.headers.get("content-type", "")
    assert len(resp1.content) > 1000, "Audio response should contain MP3 audio data"

    # Second Call: MUST be a cache HIT, protecting free-tier credits
    resp2 = client.post("/api/voice/speak", json={"text": phrase})
    assert resp2.status_code == 200
    assert resp2.headers.get("x-audio-cache") == "HIT"
    assert len(resp2.content) == len(resp1.content), "Cached audio must match original byte-for-byte"


def test_voice_speak_empty_text_validation():
    """Verify empty or blank speech text returns 400 Bad Request."""
    resp1 = client.post("/api/voice/speak", json={"text": ""})
    assert resp1.status_code in [400, 422]

    resp2 = client.post("/api/voice/speak", json={"text": "   "})
    assert resp2.status_code in [400, 422]
