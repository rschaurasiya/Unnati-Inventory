"""
Verification Test for Live Firebase Configuration and HTML Integration
"""
import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_firebase_config_endpoint_live():
    res = client.get("/api/auth/firebase-config")
    assert res.status_code == 200
    cfg = res.json()
    assert cfg["projectId"] == "unnati-03"
    assert cfg["apiKey"] == "AIzaSyDy8nIk6HW-gR6F3eM8B6mxPlxEiSGFoxM"
    assert cfg["isDummy"] is False


def test_index_html_has_firebase_module_and_google_btn():
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert 'type="module" src="/static/js/firebase-config.js' in html
    assert 'id="google-login-btn"' in html
    assert 'Continue with Google' in html
    assert 'id="welcome-greeting-modal"' in html
    assert 'Continue to Profile &amp; Settings &rarr;' in html
    assert 'id="welcome-continue-btn"' in html


def test_firebase_config_js_static_content():
    res = client.get("/static/js/firebase-config.js")
    assert res.status_code == 200
    js = res.text
    assert "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js" in js
    assert "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js" in js
    assert "unnati-03" in js
    assert "KiranaAuthService" in js
    assert "@user.apnakirana.in" in js


def test_compact_login_layout_and_autofill():
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert 'clickable-demo-box' in html
    assert 'autoFillDemoCredentials()' in html
    assert 'Demo Account —' in html
    assert 'width="28" height="28"' in html

    css_res = client.get("/static/css/style.css")
    assert css_res.status_code == 200
    css = css_res.text
    assert "width: min(430px, 94vw)" in css
    assert "overflow-y: auto" in css
    assert "padding: 12px 16px" in css


def test_index_html_has_account_not_registered_modal():
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert 'id="account-not-registered-modal"' in html
    assert 'Account Not Registered' in html
    assert 'No store account was found for these credentials' in html
    assert 'id="go-to-register-btn"' in html
    assert 'Go to Register New Store &rarr;' in html


def test_consistent_token_response_structure_on_login():
    res = client.post("/api/auth/login", json={
        "identifier": "9876543210",
        "password": "Password@123"
    })
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "success"
    assert "token" in data and len(data["token"]) > 0
    assert "access_token" in data and data["access_token"] == data["token"]
    assert "data" in data and isinstance(data["data"], dict)
    assert data["data"].get("token") == data["token"]
    assert "user" in data
    assert data["user"]["phone"] == "9876543210"


