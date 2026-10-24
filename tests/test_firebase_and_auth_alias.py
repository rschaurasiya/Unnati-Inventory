"""
Test Suite for Firebase Configuration & Auth Router Aliases
Validates /api/auth alias routing, firebase-config endpoint,
and demo credentials auto-provisioning.
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import settings

client = TestClient(app)


def test_firebase_config_endpoint():
    """Verify /api/auth/firebase-config and /api/v1/auth/firebase-config return valid project configuration."""
    for path in ["/api/auth/firebase-config", "/api/v1/auth/firebase-config"]:
        res = client.get(path)
        assert res.status_code == 200, res.text
        data = res.json()
        assert "apiKey" in data
        assert "authDomain" in data
        assert "projectId" in data
        assert data["projectId"] == "unnati-03"
        assert data["apiKey"] == "AIzaSyDy8nIk6HW-gR6F3eM8B6mxPlxEiSGFoxM"
        assert data["isDummy"] is False


def test_auth_alias_login_demo_credentials():
    """Verify /api/auth/login succeeds with demo phone credentials."""
    res = client.post("/api/auth/login", json={
        "identifier": "9876543210",
        "password": "Password@123"
    })
    assert res.status_code == 200, res.text
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["phone"] == "9876543210"
    assert "shop_profile" in data["user"]


def test_auth_alias_login_demo_email():
    """Verify /api/auth/login succeeds with demo email credentials."""
    res = client.post("/api/auth/login", json={
        "identifier": "owner@apnakirana.com",
        "password": "Password@123"
    })
    assert res.status_code == 200, res.text
    data = res.json()
    assert "access_token" in data
    assert data["user"]["phone"] == "9876543210"


def test_auth_alias_me_endpoint():
    """Verify authenticated user can fetch profile via /api/auth/me."""
    login_res = client.post("/api/auth/login", json={
        "identifier": "9876543210",
        "password": "Password@123"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["phone"] == "9876543210"


def test_auth_alias_logout_endpoint():
    """Verify authenticated user can logout via /api/auth/logout."""
    login_res = client.post("/api/auth/login", json={
        "identifier": "9876543210",
        "password": "Password@123"
    })
    token = login_res.json()["access_token"]

    logout_res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_res.status_code == 200
    assert logout_res.json()["success"] is True


def test_firebase_sync_email_and_phone():
    """Verify syncing a Firebase user with email and phone creates/updates user in SQLite."""
    sync_res = client.post("/api/auth/firebase-sync", json={
        "firebase_uid": "fb_uid_test_phone_12345",
        "email": "9876500001@user.apnakirana.in",
        "phone": "9876500001",
        "display_name": "Ramesh Gupta",
        "photo_url": "https://example.com/avatar.jpg"
    })
    assert sync_res.status_code == 200, sync_res.text
    data = sync_res.json()
    assert "access_token" in data
    assert data["user"]["phone"] == "9876500001"
    assert data["user"]["full_name"] == "Ramesh Gupta"
    assert data["user"]["avatar_url"] == "https://example.com/avatar.jpg"
    assert "shop_profile" in data["user"]


def test_firebase_sync_google_account():
    """Verify syncing a Google sign-in Firebase user without phone auto-provisions user & shop."""
    sync_res = client.post("/api/auth/firebase-sync", json={
        "firebase_uid": "fb_uid_google_999888",
        "email": "shopowner.google@gmail.com",
        "display_name": "Sunil Sharma",
        "photo_url": "https://lh3.googleusercontent.com/photo.jpg"
    })
    assert sync_res.status_code == 200, sync_res.text
    data = sync_res.json()
    assert "access_token" in data
    assert data["user"]["email"] == "shopowner.google@gmail.com"
    assert data["user"]["full_name"] == "Sunil Sharma"
    assert len(data["user"]["phone"]) == 10
    assert data["user"]["shop_profile"]["shop_name"] == "Sunil Sharma's Kirana Store"

