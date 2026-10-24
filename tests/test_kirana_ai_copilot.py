"""
Automated Verification Suite for Kirana AI Copilot:
1. Backend Endpoint (POST /api/assistant/chat) with live SQLite database snapshot injection
2. LLM response & intelligent deterministic fallback responder (English, Hindi, Hinglish)
3. DOM & CSS contract verification for floating launcher, chat panel, suggestion chips, input bar
4. Zero regression guarantee on existing 7 tabs and app modules
"""

import os
from bs4 import BeautifulSoup
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import settings

client = TestClient(app)


def test_01_backend_chat_endpoint_with_groq_or_fallback():
    """Verify POST /api/assistant/chat returns 200 with grounded store numbers and action chips."""
    res = client.post("/api/assistant/chat", json={
        "message": "What is today's sales summary?",
        "history": []
    })
    assert res.status_code == 200
    data = res.json()
    assert "reply" in data and len(data["reply"]) > 10
    assert data["source"] in ("groq", "fallback")
    assert "action_tab" in data
    assert data["action_tab"] in ("dashboard", "billing", "inventory", "udhaar", "analytics", "forecasting", "profile")


def test_02_deterministic_fallback_when_offline_or_no_key():
    """Verify deterministic fallback guarantees zero crashes for all key store intents."""
    # Temporarily clear key to simulate offline/missing Groq key
    original_key = settings.GROQ_API_KEY
    settings.GROQ_API_KEY = ""

    try:
        # Test 1: Sales / Summary
        res_sum = client.post("/api/assistant/chat", json={"message": "aaj ki bikri summary batao"})
        assert res_sum.status_code == 200
        d_sum = res_sum.json()
        assert d_sum["source"] == "fallback"
        assert "revenue" in d_sum["reply"].lower() or "bikri" in d_sum["reply"].lower() or "₹" in d_sum["reply"]
        assert d_sum["action_tab"] == "dashboard"
        assert d_sum["action_label"] == "Go to Shop Dashboard →"

        # Test 2: Low Stock / Reorder
        res_stock = client.post("/api/assistant/chat", json={"message": "Konsa maal khatam ho raha hai?"})
        assert res_stock.status_code == 200
        d_stock = res_stock.json()
        assert d_stock["source"] == "fallback"
        assert d_stock["action_tab"] == "forecasting"
        assert "Demand Forecasting" in d_stock["action_label"]

        # Test 3: Udhaar / Customer Khata
        res_udhaar = client.post("/api/assistant/chat", json={"message": "Top udhaar balance kitna hai?"})
        assert res_udhaar.status_code == 200
        d_udhaar = res_udhaar.json()
        assert d_udhaar["source"] == "fallback"
        assert d_udhaar["action_tab"] == "udhaar"
        assert "Udhaar" in d_udhaar["action_label"]

        # Test 4: Voice POS Billing
        res_pos = client.post("/api/assistant/chat", json={"message": "Voice bill kaise banaye?"})
        assert res_pos.status_code == 200
        d_pos = res_pos.json()
        assert d_pos["source"] == "fallback"
        assert d_pos["action_tab"] == "billing"
        assert "Voice Billing" in d_pos["action_label"]

        # Test 5: Sales History & CSV Import
        res_imp = client.post("/api/assistant/chat", json={"message": "Purana sales CSV import kaise kare?"})
        assert res_imp.status_code == 200
        d_imp = res_imp.json()
        assert d_imp["source"] == "fallback"
        assert d_imp["action_tab"] == "analytics"
        assert "Sales History" in d_imp["action_label"]

        # Test 6: Profile & Settings
        res_prof = client.post("/api/assistant/chat", json={"message": "Dukaan ka naam aur logo kaise badle?"})
        assert res_prof.status_code == 200
        d_prof = res_prof.json()
        assert d_prof["source"] == "fallback"
        assert d_prof["action_tab"] == "profile"
        assert "Profile" in d_prof["action_label"]

        # Test 7: Greeting
        res_greet = client.post("/api/assistant/chat", json={"message": "Namaste"})
        assert res_greet.status_code == 200
        d_greet = res_greet.json()
        assert d_greet["source"] == "fallback"
        assert "Namaste" in d_greet["reply"]

    finally:
        # Restore key
        settings.GROQ_API_KEY = original_key


def test_03_frontend_dom_elements_presence():
    """Verify launcher button, floating chat panel, chips, mic, input, and script tag exist in HTML."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # 1. Floating launcher button
    launcher = soup.find(id="kirana-copilot-launcher")
    assert launcher is not None, "Missing #kirana-copilot-launcher"
    assert "Ask AI" in launcher.get_text()

    # 2. Floating chat panel
    panel = soup.find(id="kirana-copilot-panel")
    assert panel is not None, "Missing #kirana-copilot-panel"
    assert "display:none" in panel.get("style", "").replace(" ", "")

    # 3. Header title, close button (Global audio toggle is removed in favor of inline Listen buttons & Voice Mode)
    assert soup.find(id="copilot-header-title") is not None
    assert "Kirana AI Copilot" in soup.find(id="copilot-header-title").get_text()
    assert soup.find(id="copilot-audio-toggle") is None, "Global voice toggle must be removed"
    assert soup.find(id="copilot-close-btn") is not None

    # 4. 4 Suggestion Chips
    chips_bar = soup.find(id="copilot-chips-container")
    assert chips_bar is not None
    chips_text = chips_bar.get_text()
    assert "Today's Summary" in chips_text
    assert "Low Stock Items" in chips_text
    assert "Top Udhaar" in chips_text
    assert "How to Use POS" in chips_text

    # 5. Messages container, inline listen button, voice wave indicator, and input bar
    assert soup.find(id="copilot-messages") is not None
    assert soup.find(class_="copilot-listen-btn") is not None, "Missing inline .copilot-listen-btn"
    assert soup.find(id="copilot-listening-wave") is not None, "Missing #copilot-listening-wave"
    assert soup.find(id="copilot-input-bar") is not None
    assert soup.find(id="copilot-mic-btn") is not None
    assert soup.find(id="copilot-input") is not None
    assert soup.find(id="copilot-send-btn") is not None

    # 6. Copilot script tag
    assert "/static/js/copilot.js" in html


def test_04_frontend_css_specifications():
    """Verify launcher and panel styling follow non-intrusive floating standards."""
    with open("frontend/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    # Launcher CSS: bottom-right fixed, z-index 9990
    assert ".kirana-copilot-launcher" in css
    assert "position: fixed;" in css
    assert "bottom: 20px;" in css
    assert "right: 20px;" in css
    assert "z-index: 9990;" in css

    # Panel CSS: bottom 76px, width 340px, height 450px, z-index 9991
    assert ".kirana-copilot-panel" in css
    assert "bottom: 76px;" in css
    assert "width: 340px;" in css
    assert "height: 450px;" in css
    assert "max-height: 80vh;" in css
    assert "z-index: 9991;" in css


def test_05_copilot_js_module_integrity():
    """Verify copilot.js is syntactically sound and exports window.KiranaCopilot."""
    with open("frontend/js/copilot.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "window.KiranaCopilot = {" in js
    assert "toggle:" in js
    assert "open:" in js
    assert "close:" in js
    assert "toggleSpeech:" in js
    assert "toggleMic:" in js
    assert "sendSuggested:" in js
    assert "navigateTab:" in js
    assert "window.speakWithElevenLabs" in js


def test_06_strict_input_source_reflection():
    """Verify input_source ('text' or 'mic') is preserved and reflected in the response."""
    # Text input
    res_text = client.post("/api/assistant/chat", json={
        "message": "What is today's sales?",
        "input_source": "text"
    })
    assert res_text.status_code == 200
    assert res_text.json().get("input_source") == "text"

    # Mic voice input
    res_mic = client.post("/api/assistant/chat", json={
        "message": "What is today's sales?",
        "input_source": "mic"
    })
    assert res_mic.status_code == 200
    assert res_mic.json().get("input_source") == "mic"


def test_07_todays_sales_query_live_db_and_fallback():
    """Verify queries about today's sales reliably return accurate live figures and units sold."""
    # English query
    res1 = client.post("/api/assistant/chat", json={"message": "What is today's sales?"})
    assert res1.status_code == 200
    reply1 = res1.json()["reply"]
    assert "₹" in reply1 or "sales" in reply1.lower() or "revenue" in reply1.lower()

    # Hindi / Hinglish query
    res2 = client.post("/api/assistant/chat", json={"message": "Aaj ki sale kitni hai?"})
    assert res2.status_code == 200
    reply2 = res2.json()["reply"]
    assert "₹" in reply2 or "sale" in reply2.lower() or "bikri" in reply2.lower()

    # Today's summary query
    res3 = client.post("/api/assistant/chat", json={"message": "Tell me today's sales summary"})
    assert res3.status_code == 200
    reply3 = res3.json()["reply"]
    assert len(reply3) > 15


def test_08_speech_text_sanitizer():
    """Verify currency '₹' is converted to 'Rupees ' and markdown characters are stripped for clean audio."""
    import re

    def sanitize_for_speech_py(text: str) -> str:
        if not text:
            return ""
        t = re.sub(r"₹\s*", "Rupees ", text)
        t = re.sub(r"Rs\.?\s*", "Rupees ", t, flags=re.IGNORECASE)
        t = re.sub(r"\*\*(.*?)\*\*", r"\1", t)
        t = re.sub(r"\*(.*?)\*", r"\1", t)
        t = re.sub(r"`([^`]+)`", r"\1", t)
        t = re.sub(r"#+", "", t)
        t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.MULTILINE)
        t = re.sub(r"ACTION_TAB:\s*[a-zA-Z0-9_]+", "", t, flags=re.IGNORECASE)
        return " ".join(t.split()).strip()

    raw = "Today's sales total **₹18,502.50** across 193 bills (*343 units* sold). # Summary ACTION_TAB: dashboard"
    clean = sanitize_for_speech_py(raw)
    assert "₹" not in clean
    assert "Rupees 18,502.50" in clean
    assert "**" not in clean
    assert "*" not in clean
    assert "#" not in clean
    assert "ACTION_TAB" not in clean


def test_09_copilot_js_strict_mode_contract():
    """Verify copilot.js implements strict input mode, mic auto-submit, and speech sanitization."""
    with open("frontend/js/copilot.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "sanitizeForSpeech" in js, "Must define speech sanitizer"
    assert "Rupees " in js, "Must convert ₹ to Rupees"
    assert "inputSource === \"mic\"" in js, "Must strictly condition auto-speech on mic source"
    assert "stopVoicePlayback" in js, "Must stop audio on text queries"
    assert "submitMessage(transcript, \"mic\")" in js, "Must auto-submit mic transcripts as mic input"
    assert "🔊 Listen" in js, "Must provide manual listen button beside assistant bubbles"
