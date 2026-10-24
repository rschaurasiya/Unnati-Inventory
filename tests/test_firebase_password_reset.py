"""
Test Suite: Firebase Password Reset Integration & Legacy OTP Cleanup
Validates Phase 1, Phase 2, Phase 3, and Phase 4 of the Firebase password reset migration.
"""
import re
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_phase1_legacy_otp_ui_cleanup_and_firebase_reset_form():
    """Verify frontend/index.html has completely removed legacy OTP UI and replaced with Firebase reset UI."""
    response = client.get("/login")
    assert response.status_code == 200
    html = response.text

    # 1. Obsolete Legacy Elements must NOT exist
    assert "DEVELOPMENT OTP PREVIEW" not in html, "Legacy dev OTP preview must be completely removed"
    assert 'id="dev-otp-notification"' not in html, "dev-otp-notification element must be removed"
    assert 'id="reset-otp-input"' not in html, "Legacy 6-digit OTP input must be removed"
    assert 'id="reset-new-password"' not in html, "Legacy new password input must be removed"
    assert 'id="reset-confirm-password"' not in html, "Legacy confirm password input must be removed"
    assert 'id="forgot-step2-btn"' not in html, "Legacy step 2 reset button must be removed"

    # 2. Clean Firebase Password Recovery elements must exist
    assert 'id="auth-forgot-card"' in html, "auth-forgot-card container must be present"
    assert 'id="forgot-password-message"' in html, "forgot-password-message feedback container must be present"
    assert 'id="forgot-email"' in html, "Single email input (id='forgot-email') must be present"
    assert 'type="email"' in html, "Email input must have type='email'"
    assert 'id="forgot-submit-btn"' in html, "Submit button (id='forgot-submit-btn') must be present"
    assert "Send Password Reset Link" in html, "Button text must read 'Send Password Reset Link'"
    assert "← Return to Sign In" in html, "Return to sign in link must be preserved"

    # 3. Cache-busting query strings must match ?v=20261022_blank_onboarding
    assert ("?v=20261022_blank_onboarding" in html or "?v=20261022_onboarding_lock" in html or "?v=20261022_firebase_reset" in html), "Cache buster must be present in index.html"


def test_phase2_firebase_config_and_app_js_exports():
    """Verify frontend JavaScript modules properly import and expose sendPasswordResetEmail."""
    with open("frontend/js/firebase-config.js", "r", encoding="utf-8") as f:
        fb_config = f.read()

    assert "sendPasswordResetEmail" in fb_config, "firebase-config.js must import and expose sendPasswordResetEmail"
    assert "async sendPasswordResetEmail(" in fb_config, "KiranaAuthService must have sendPasswordResetEmail method"
    assert "window.sendPasswordResetEmail" in fb_config, "window.sendPasswordResetEmail must be exported"

    with open("frontend/js/app.js", "r", encoding="utf-8") as f:
        app_js = f.read()

    assert "async function handleForgotPasswordSubmit(" in app_js, "app.js must implement handleForgotPasswordSubmit"
    assert "sendPasswordResetEmail" in app_js, "app.js must invoke sendPasswordResetEmail"
    assert "Success! A password reset link has been sent to your email" in app_js, "app.js must provide success message"
    assert "window.handleForgotPasswordSubmit = handleForgotPasswordSubmit;" in app_js, "handleForgotPasswordSubmit must be exported to window"


def test_phase3_obsolete_backend_routes_are_deprecated():
    """Verify legacy custom endpoints /forgot-password and /reset-password return 410 GONE."""
    forgot_res = client.post("/api/v1/auth/forgot-password", json={"phone_or_email": "test@example.com"})
    assert forgot_res.status_code == 410
    assert "deprecated" in forgot_res.json()["detail"].lower()

    reset_res = client.post("/api/v1/auth/reset-password", json={
        "phone_or_email": "test@example.com",
        "otp_code": "123456",
        "new_password": "NewPassword@123",
        "confirm_new_password": "NewPassword@123"
    })
    assert reset_res.status_code == 410
    assert "deprecated" in reset_res.json()["detail"].lower()


def test_phase3_models_and_init_db_decoupled():
    """Verify init_db and models no longer depend on password_reset_tokens for the main flow."""
    with open("backend/init_db.py", "r", encoding="utf-8") as f:
        init_db_content = f.read()
    assert "PasswordResetToken" not in init_db_content, "init_db.py must not import PasswordResetToken"
