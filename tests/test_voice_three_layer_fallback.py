"""
Tests for 3-Layer Voice Fallback & Caching System
Validates:
  - Layer 1: SHA-256 Disk Audio Caching in .tts_cache/
  - Layer 2: Automatic edge-tts fallback on ElevenLabs quota/error/missing key
  - Layer 2: Language-aware neural voice detection (Hindi vs Indian English)
  - Layer 3: Offline Browser TTS fallback (signal 204 & frontend JavaScript handlers)
  - Configuration switch: VOICE_PROVIDER in .env (elevenlabs, edge-tts, browser)
"""

import sys
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

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
    detect_edge_voice,
    get_voice_provider,
    get_voice_status,
    _MEMORY_AUDIO_CACHE
)

client = TestClient(app)


def test_01_layer1_sha256_disk_caching_and_hit():
    """Verify Layer 1: SHA-256 local disk caching serves repeat requests with 0 API calls."""
    unique_phrase = "Testing Layer 1 SHA-256 disk caching verification for Apna Kirana."
    cache_key = compute_cache_key(unique_phrase, settings.ELEVENLABS_VOICE_ID, settings.ELEVENLABS_MODEL_ID)
    cache_file = settings.TTS_CACHE_DIR / f"{cache_key}.mp3"

    # Pre-populate dummy MP3 bytes in cache directory
    dummy_audio = b"\xff\xfb\x90\x00" + b"TEST_AUDIO_BYTES_CACHE_LAYER1" * 50
    settings.TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(dummy_audio)
    _MEMORY_AUDIO_CACHE.pop(cache_key, None)

    # Request should immediately hit disk cache (X-Audio-Cache: HIT)
    response = client.post("/api/voice/speak", json={"text": unique_phrase})
    assert response.status_code == 200
    assert response.headers.get("x-audio-cache") == "HIT"
    assert response.content == dummy_audio

    # Cleanup test cache file
    try:
        cache_file.unlink(missing_ok=True)
        _MEMORY_AUDIO_CACHE.pop(cache_key, None)
    except Exception:
        pass


def test_02_layer2_automatic_edge_tts_fallback_on_elevenlabs_quota_error():
    """Verify Layer 2: When ElevenLabs returns 429 quota exhausted, system auto-falls back to edge-tts."""
    phrase = "Total bill is ₹350. Thank you for your payment."
    cache_key = compute_cache_key(phrase, settings.ELEVENLABS_VOICE_ID, settings.ELEVENLABS_MODEL_ID)
    _MEMORY_AUDIO_CACHE.pop(cache_key, None)
    (settings.TTS_CACHE_DIR / f"{cache_key}.mp3").unlink(missing_ok=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.content = b'{"detail": {"status": "quota_exceeded"}}'

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        response = client.post("/api/voice/speak", json={"text": phrase})

    assert response.status_code == 200
    assert response.headers.get("x-audio-provider") == "edge-tts"
    assert response.headers.get("x-audio-fallback") == "true"
    assert len(response.content) > 500, "Should contain edge-tts generated MP3 audio bytes"

    # Subsequent call should now hit cache
    cached_resp = client.post("/api/voice/speak", json={"text": phrase})
    assert cached_resp.status_code == 200
    assert cached_resp.headers.get("x-audio-cache") == "HIT"


def test_03_layer2_edge_tts_language_detection():
    """Verify edge-tts voice selection accurately selects Hindi vs Indian English."""
    # Devanagari Hindi
    hindi_text = "नमस्ते! आपका स्वागत है हमारी दुकान में।"
    assert detect_edge_voice(hindi_text) == "hi-IN-SwaraNeural"

    # Hinglish retail phrases
    hinglish_text = "Ramesh ji ka udhaar khata clear ho gaya hai."
    assert detect_edge_voice(hinglish_text) == "hi-IN-SwaraNeural"

    # Indian English
    english_text = "Your total bill is four hundred rupees paid via UPI."
    assert detect_edge_voice(english_text) == "en-IN-PrabhatNeural"


def test_04_provider_switch_edge_tts_direct_mode():
    """Verify VOICE_PROVIDER=edge-tts generates speech via edge-tts directly without ElevenLabs."""
    with patch("backend.services.elevenlabs_service.get_voice_provider", return_value="edge-tts"):
        phrase = "Direct edge-tts speech generation test."
        cache_key = compute_cache_key(phrase, settings.ELEVENLABS_VOICE_ID, settings.ELEVENLABS_MODEL_ID)
        _MEMORY_AUDIO_CACHE.pop(cache_key, None)
        (settings.TTS_CACHE_DIR / f"{cache_key}.mp3").unlink(missing_ok=True)

        response = client.post("/api/voice/speak", json={"text": phrase})
        assert response.status_code == 200
        assert response.headers.get("x-audio-provider") == "edge-tts"
        assert len(response.content) > 500


def test_05_provider_switch_browser_fallback_mode():
    """Verify VOICE_PROVIDER=browser returns 204 No Content with X-Audio-Provider: browser."""
    with patch("backend.services.elevenlabs_service.get_voice_provider", return_value="browser"):
        response = client.post("/api/voice/speak", json={"text": "Browser fallback test phrase."})
        assert response.status_code == 204
        assert response.headers.get("x-audio-provider") == "browser"


def test_06_frontend_layer3_browser_tts_backup_script():
    """Verify frontend/js/shared/utils.js contains robust Layer 3 browser TTS fallback."""
    utils_path = ROOT_DIR / "frontend" / "js" / "shared" / "utils.js"
    assert utils_path.exists(), "frontend/js/shared/utils.js must exist"
    content = utils_path.read_text(encoding="utf-8")

    assert "speakBrowserTTS" in content, "Must implement speakBrowserTTS"
    assert "window.speechSynthesis" in content, "Must integrate window.speechSynthesis"
    assert "SpeechSynthesisUtterance" in content, "Must instantiate SpeechSynthesisUtterance"
    assert "hi-IN" in content and "en-IN" in content, "Must support both Hindi and Indian English"
    assert "x-audio-provider" in content, "Must check x-audio-provider header for fallback"


def test_07_voice_status_reports_multi_layer_health():
    """Verify GET /api/voice/status reflects provider, edge-tts availability, and cache statistics."""
    response = client.get("/api/voice/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert "provider" in data
    assert data["fallback_available"] is True
    assert data["edge_tts_available"] is True
    assert isinstance(data["cached_phrases"], int)
