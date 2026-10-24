"""
Authentication, Profile & Settings Automated Test Suite
Tests registration, login, token authentication, profile management,
business details, password change, forgot/reset password flow, and user isolation.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import ShopkeeperUser, ShopProfile, PasswordResetToken
from backend.security import verify_password

client = TestClient(app)


def _unique_phone() -> str:
    """Generates a random unique 10-digit Indian mobile number."""
    return f"9{uuid.uuid4().int % 1000000000:09d}"


def _unique_email() -> str:
    """Generates a unique email address."""
    return f"test_{uuid.uuid4().hex[:8]}@kirana.test"


def test_01_user_registration_success():
    """Verify new shopkeeper registration creates user, shop profile, and returns valid token."""
    phone = _unique_phone()
    email = _unique_email()
    res = client.post("/api/v1/auth/register", json={
        "full_name": "Ramesh Kumar",
        "phone": phone,
        "email": email,
        "password": "SecurePassword@123",
        "confirm_password": "SecurePassword@123",
        "shop_name": "Ramesh Grocery Store",
        "role": "Shop Owner"
    })
    assert res.status_code == 201, res.text
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["full_name"] == "Ramesh Kumar"
    assert data["user"]["phone"] == phone
    assert data["user"]["email"] == email
    assert data["user"]["shop_profile"]["shop_name"] == ""

    # Verify password was hashed and NOT stored in plaintext
    db = SessionLocal()
    try:
        user = db.query(ShopkeeperUser).filter(ShopkeeperUser.phone == phone).first()
        assert user is not None
        assert user.hashed_password != "SecurePassword@123"
        assert verify_password("SecurePassword@123", user.hashed_password) is True
    finally:
        db.close()


def test_02_registration_duplicate_phone_rejected():
    """Verify duplicate phone registration is rejected with 400 Bad Request."""
    phone = _unique_phone()
    res1 = client.post("/api/v1/auth/register", json={
        "full_name": "User One",
        "phone": phone,
        "password": "Password@123",
        "confirm_password": "Password@123"
    })
    assert res1.status_code == 201

    res2 = client.post("/api/v1/auth/register", json={
        "full_name": "User Two",
        "phone": phone,
        "password": "Password@123",
        "confirm_password": "Password@123"
    })
    assert res2.status_code == 400
    assert "already exists" in res2.json()["detail"].lower()


def test_03_registration_duplicate_email_rejected():
    """Verify duplicate email registration is rejected with 400 Bad Request."""
    email = _unique_email()
    res1 = client.post("/api/v1/auth/register", json={
        "full_name": "User A",
        "phone": _unique_phone(),
        "email": email,
        "password": "Password@123",
        "confirm_password": "Password@123"
    })
    assert res1.status_code == 201

    res2 = client.post("/api/v1/auth/register", json={
        "full_name": "User B",
        "phone": _unique_phone(),
        "email": email,
        "password": "Password@123",
        "confirm_password": "Password@123"
    })
    assert res2.status_code == 400
    assert "email" in res2.json()["detail"].lower() and "already exists" in res2.json()["detail"].lower()


def test_04_registration_password_mismatch_and_length():
    """Verify password confirmation check and length requirements."""
    # Mismatch
    res_mismatch = client.post("/api/v1/auth/register", json={
        "full_name": "Test User",
        "phone": _unique_phone(),
        "password": "Password@123",
        "confirm_password": "DifferentPassword@123"
    })
    assert res_mismatch.status_code == 400
    assert "match" in res_mismatch.json()["detail"].lower()

    # Short password
    res_short = client.post("/api/v1/auth/register", json={
        "full_name": "Test User",
        "phone": _unique_phone(),
        "password": "123",
        "confirm_password": "123"
    })
    assert res_short.status_code == 400
    assert "6 characters" in res_short.json()["detail"].lower()


def test_05_login_success_by_phone_and_email():
    """Verify login works with both phone number and email identifier."""
    phone = _unique_phone()
    email = _unique_email()
    reg = client.post("/api/v1/auth/register", json={
        "full_name": "Suresh Raina",
        "phone": phone,
        "email": email,
        "password": "MyLoginPassword@99",
        "confirm_password": "MyLoginPassword@99",
        "shop_name": "Raina Supermart"
    })
    assert reg.status_code == 201

    # Login by phone
    login_phone = client.post("/api/v1/auth/login", json={
        "identifier": phone,
        "password": "MyLoginPassword@99"
    })
    assert login_phone.status_code == 200
    assert "access_token" in login_phone.json()
    assert login_phone.json()["user"]["phone"] == phone

    # Login by email
    login_email = client.post("/api/v1/auth/login", json={
        "identifier": email,
        "password": "MyLoginPassword@99"
    })
    assert login_email.status_code == 200
    assert "access_token" in login_email.json()
    assert login_email.json()["user"]["email"] == email


def test_06_login_invalid_credentials():
    """Verify login rejects invalid password or non-existent user."""
    # Non-existent user
    res1 = client.post("/api/v1/auth/login", json={
        "identifier": "0000000000",
        "password": "AnyPassword@123"
    })
    assert res1.status_code == 401
    assert "invalid" in res1.json()["detail"].lower()

    # Wrong password
    phone = _unique_phone()
    client.post("/api/v1/auth/register", json={
        "full_name": "Wrong Pwd User",
        "phone": phone,
        "password": "CorrectPassword@1",
        "confirm_password": "CorrectPassword@1"
    })
    res2 = client.post("/api/v1/auth/login", json={
        "identifier": phone,
        "password": "IncorrectPassword@2"
    })
    assert res2.status_code == 401
    assert "invalid" in res2.json()["detail"].lower()


def test_07_protected_me_endpoint():
    """Verify /api/v1/auth/me requires valid token and returns correct profile."""
    # Without token
    res_no_auth = client.get("/api/v1/auth/me")
    assert res_no_auth.status_code == 401

    # With invalid token
    res_bad_auth = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer fake.invalid.token"})
    assert res_bad_auth.status_code == 401

    # With valid token
    phone = _unique_phone()
    reg = client.post("/api/v1/auth/register", json={
        "full_name": "Token Tester",
        "phone": phone,
        "password": "Password@123",
        "confirm_password": "Password@123"
    })
    token = reg.json()["access_token"]

    res_auth = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res_auth.status_code == 200
    data = res_auth.json()
    assert data["full_name"] == "Token Tester"
    assert data["phone"] == phone


def test_08_update_personal_and_shop_profile():
    """Verify updating personal profile and store business details persists in database."""
    phone = _unique_phone()
    reg = client.post("/api/v1/auth/register", json={
        "full_name": "Initial Name",
        "phone": phone,
        "password": "Password@123",
        "confirm_password": "Password@123",
        "shop_name": "Initial Shop"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Update personal profile
    new_email = _unique_email()
    res_p = client.put("/api/v1/auth/profile", json={
        "full_name": "Updated Shopkeeper Name",
        "email": new_email
    }, headers=headers)
    assert res_p.status_code == 200
    assert res_p.json()["full_name"] == "Updated Shopkeeper Name"
    assert res_p.json()["email"] == new_email

    # Update shop business details
    res_s = client.put("/api/v1/auth/shop", json={
        "shop_name": "Updated Apna Bazaar",
        "shop_address": "Shop No. 12, Subhash Nagar, New Delhi",
        "gstin": "07AAAAA0000A1Z5",
        "shop_phone": "+91 98111 22334",
        "shop_email": "bazaar@delhi.in"
    }, headers=headers)
    assert res_s.status_code == 200
    s_data = res_s.json()
    assert s_data["shop_name"] == "Updated Apna Bazaar"
    assert s_data["gstin"] == "07AAAAA0000A1Z5"
    assert s_data["shop_phone"] == "+91 98111 22334"

    # Re-fetch via /me to confirm persistence
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["full_name"] == "Updated Shopkeeper Name"
    assert me["shop_profile"]["shop_name"] == "Updated Apna Bazaar"
    assert me["shop_profile"]["gstin"] == "07AAAAA0000A1Z5"


def test_09_change_password_workflow():
    """Verify password change enforces current password and works with new credentials."""
    phone = _unique_phone()
    reg = client.post("/api/v1/auth/register", json={
        "full_name": "Password Changer",
        "phone": phone,
        "password": "OldPassword@123",
        "confirm_password": "OldPassword@123"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Incorrect current password fails
    fail_res = client.put("/api/v1/auth/change-password", json={
        "current_password": "WrongOldPassword@99",
        "new_password": "NewPassword@456",
        "confirm_new_password": "NewPassword@456"
    }, headers=headers)
    assert fail_res.status_code == 400
    assert "incorrect current password" in fail_res.json()["detail"].lower()

    # Successful password change
    good_res = client.put("/api/v1/auth/change-password", json={
        "current_password": "OldPassword@123",
        "new_password": "NewPassword@456",
        "confirm_new_password": "NewPassword@456"
    }, headers=headers)
    assert good_res.status_code == 200
    assert good_res.json()["success"] is True

    # Old password no longer works
    login_old = client.post("/api/v1/auth/login", json={
        "identifier": phone,
        "password": "OldPassword@123"
    })
    assert login_old.status_code == 401

    # New password works
    login_new = client.post("/api/v1/auth/login", json={
        "identifier": phone,
        "password": "NewPassword@456"
    })
    assert login_new.status_code == 200
    assert "access_token" in login_new.json()


def test_10_settings_and_localization_preferences():
    """Verify configurable shop settings (currency, timezone, invoice footer, units) persist."""
    phone = _unique_phone()
    reg = client.post("/api/v1/auth/register", json={
        "full_name": "Settings User",
        "phone": phone,
        "password": "Password@123",
        "confirm_password": "Password@123"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Update settings
    up_res = client.put("/api/v1/auth/settings", json={
        "currency": "₹ INR",
        "timezone": "Asia/Kolkata",
        "invoice_footer": "Dhanyawaad! Phir Padhaariye.",
        "default_measurement_unit": "packet",
        "default_min_stock_threshold": 15.0
    }, headers=headers)
    assert up_res.status_code == 200
    data = up_res.json()
    assert data["currency"] == "₹ INR"
    assert data["invoice_footer"] == "Dhanyawaad! Phir Padhaariye."
    assert data["default_measurement_unit"] == "packet"
    assert data["default_min_stock_threshold"] == 15.0

    # Retrieve settings
    get_res = client.get("/api/v1/auth/settings", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["default_min_stock_threshold"] == 15.0


def test_11_forgot_password_and_reset_workflow():
    """Verify legacy custom OTP forgot password & reset endpoints are safely deprecated (HTTP 410)."""
    phone = _unique_phone()

    # Request legacy reset OTP - must return 410 GONE (deprecated in favor of Firebase)
    forgot_res = client.post("/api/v1/auth/forgot-password", json={
        "phone_or_email": phone
    })
    assert forgot_res.status_code == 410
    assert "deprecated" in forgot_res.json()["detail"].lower()

    # Test legacy reset endpoint - must return 410 GONE
    reset_res = client.post("/api/v1/auth/reset-password", json={
        "phone_or_email": phone,
        "otp_code": "123456",
        "new_password": "BrandNewPassword@789",
        "confirm_new_password": "BrandNewPassword@789"
    })
    assert reset_res.status_code == 410
    assert "deprecated" in reset_res.json()["detail"].lower()


def test_12_logout_endpoint():
    """Verify logout endpoint returns success."""
    phone = _unique_phone()
    reg = client.post("/api/v1/auth/register", json={
        "full_name": "Logout User",
        "phone": phone,
        "password": "Password@123",
        "confirm_password": "Password@123"
    })
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post("/api/v1/auth/logout", headers=headers)
    assert res.status_code == 200
    assert res.json()["success"] is True
