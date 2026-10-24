"""
Test Suite: Mandatory Onboarding Gate Verification
Validates Phase 1, Phase 2, Phase 3, and Phase 4 of the Mandatory Onboarding Workflow:
- Strict tab and drawer hiding during onboarding (CSS & JS)
- Unified Master Onboarding Submit button in index.html
- Cross-container validation and API submission in profile.js
- Dynamic tab unlocking and redirect to dashboard
- Cache-busting query string ?v=20261022_onboarding_lock
"""
import uuid
import re
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import ShopkeeperUser, ShopProfile

client = TestClient(app)


def _unique_phone() -> str:
    return f"9{uuid.uuid4().int % 1000000000:09d}"


def _unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:8]}@kirana.test"


def test_phase1_strict_navigation_tab_hiding():
    """Verify CSS and app.js implement strict tab and drawer lock."""
    with open("frontend/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    # 1. Main navigation tabs forcefully hidden
    assert "body.onboarding-locked #main-nav-tabs" in css
    assert "display: none !important" in css
    assert "pointer-events: none !important" in css

    # 2. Mobile drawer navigation links hidden except profile
    assert "body.onboarding-locked #mobile-nav-toggle" in css
    assert "body.onboarding-locked .mobile-drawer-nav .mobile-nav-item:not([data-tab=\"profile\"])" in css

    # 3. Individual card save buttons hidden during onboarding
    assert "body.onboarding-locked #profile-card-personal .card-action-bar" in css
    assert "body.onboarding-locked #profile-card-shop .card-action-bar" in css
    assert "body.onboarding-locked #profile-card-settings .card-action-bar" in css

    # 4. Error highlight styling
    assert ".input-error-highlight" in css
    assert "border-color: #ef4444 !important" in css

    with open("frontend/js/app.js", "r", encoding="utf-8") as f:
        app_js = f.read()

    # 5. Functions defined and exported
    assert "function isProfileAndShopSetupComplete(" in app_js
    assert "function setOnboardingLock(" in app_js
    assert "window.isProfileAndShopSetupComplete = isProfileAndShopSetupComplete;" in app_js
    assert "window.setOnboardingLock = setOnboardingLock;" in app_js

    # 6. Tab switching and navigation gating
    assert "if (!isProfileAndShopSetupComplete()" in app_js
    assert "setOnboardingLock(true);" in app_js


def test_phase2_unified_master_submit_button_in_index():
    """Verify frontend/index.html includes the master onboarding button and cache buster."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Container and Button exist
    assert 'id="onboarding-master-container"' in html
    assert 'id="master-onboarding-submit"' in html
    assert 'id="master-onboarding-alert"' in html
    assert "Complete Profile &amp; Launch Dashboard" in html or "Complete Profile & Launch Dashboard" in html
    assert 'handleMasterOnboardingSubmit(event)' in html

    # 2. Cache buster ?v=20261022_blank_onboarding
    assert ("?v=20261022_blank_onboarding" in html or "?v=20261022_onboarding_lock" in html)
    css_match = re.search(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html)
    assert css_match and ("?v=20261022_blank_onboarding" in css_match.group(1) or "?v=20261022_onboarding_lock" in css_match.group(1))


def test_phase3_profile_js_validation_and_submission():
    """Verify frontend/js/profile.js implements cross-container validation and unified submission."""
    with open("frontend/js/profile.js", "r", encoding="utf-8") as f:
        profile_js = f.read()

    # 1. Master handler definition and binding
    assert "async function handleMasterOnboardingSubmit(" in profile_js
    assert "window.handleMasterOnboardingSubmit = handleMasterOnboardingSubmit;" in profile_js
    assert "handleMasterOnboardingSubmit: handleMasterOnboardingSubmit" in profile_js or "handleMasterOnboardingSubmit," in profile_js

    # 2. Strict validation rules
    assert "prof-fullname" in profile_js
    assert "prof-phone" in profile_js
    assert "shop-name-input" in profile_js
    assert "shop-address-input" in profile_js
    assert "shop-phone-input" in profile_js
    assert "setting-currency" in profile_js
    assert "setting-unit" in profile_js

    # 3. Card expansion & input error highlight
    assert "expandExclusiveProfileCard" in profile_js
    assert "input-error-highlight" in profile_js

    # 4. API PUT requests
    assert "/api/v1/auth/profile" in profile_js
    assert "/api/v1/auth/shop" in profile_js
    assert "/api/v1/auth/settings" in profile_js


def test_phase4_unlock_tabs_and_redirect_flow():
    """Verify profile.js marks user complete, unlocks tabs and redirects to dashboard."""
    with open("frontend/js/profile.js", "r", encoding="utf-8") as f:
        profile_js = f.read()

    # 1. Onboarding completion flag
    assert "localStorage.setItem(\"pos_onboarding_completed\", \"true\");" in profile_js or "localStorage.setItem('pos_onboarding_completed', 'true');" in profile_js

    # 2. Dynamic tab unlocking
    assert "setOnboardingLock(false)" in profile_js

    # 3. Notification and redirect
    assert "Profile setup complete!" in profile_js
    assert "navigateTo(\"/dashboard\")" in profile_js or "navigateTo('/dashboard')" in profile_js or "switchTab(\"dashboard\"" in profile_js


def test_backend_put_endpoints_for_master_submit():
    """Verify backend endpoints /api/v1/auth/profile, /shop, and /settings all succeed for master submission."""
    phone = _unique_phone()
    email = _unique_email()

    reg_res = client.post("/api/v1/auth/register", json={
        "full_name": "New Onboarding User",
        "phone": phone,
        "email": email,
        "password": "Password@123",
        "confirm_password": "Password@123",
        "shop_name": "Initial Store Name",
        "role": "Shop Owner"
    })
    assert reg_res.status_code == 201
    token = reg_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. PUT /api/v1/auth/profile
    prof_res = client.put("/api/v1/auth/profile", json={
        "full_name": "Confirmed Shopkeeper",
        "phone": phone,
        "email": email
    }, headers=headers)
    assert prof_res.status_code == 200
    assert prof_res.json()["full_name"] == "Confirmed Shopkeeper"

    # 2. PUT /api/v1/auth/shop
    shop_res = client.put("/api/v1/auth/shop", json={
        "shop_name": "Apna Super Kirana",
        "shop_address": "Shop 14, Main Market, Delhi",
        "shop_phone": f"+91 {phone}",
        "gstin": "07AAAAA0000A1Z5",
        "shop_email": email
    }, headers=headers)
    assert shop_res.status_code == 200
    assert shop_res.json()["shop_name"] == "Apna Super Kirana"
    assert shop_res.json()["shop_address"] == "Shop 14, Main Market, Delhi"

    # 3. PUT /api/v1/auth/settings
    settings_res = client.put("/api/v1/auth/settings", json={
        "currency": "INR (₹)",
        "timezone": "Asia/Kolkata (IST)",
        "default_measurement_unit": "kg",
        "default_min_stock_threshold": 15.0,
        "invoice_footer": "Thank you for visiting Apna Super Kirana!"
    }, headers=headers)
    assert settings_res.status_code == 200
    assert settings_res.json()["default_min_stock_threshold"] == 15.0


def test_blank_default_fields_and_greeting_button_arrows():
    """Verify new registered users get completely blank store fields and button has two arrows."""
    # 1. Check models schema defaults
    assert ShopProfile.shop_name.property.columns[0].default.arg == ""
    assert ShopProfile.shop_address.property.columns[0].default.arg == ""
    assert ShopProfile.shop_phone.property.columns[0].default.arg == ""

    # 2. Check registration creates completely blank store fields
    phone = _unique_phone()
    email = _unique_email()
    reg = client.post("/api/v1/auth/register", json={
        "full_name": "Blank Store User",
        "phone": phone,
        "email": email,
        "password": "Password@123",
        "confirm_password": "Password@123"
    })
    assert reg.status_code == 201
    reg_data = reg.json()
    assert reg_data["user"]["full_name"] == "Blank Store User"
    assert reg_data["user"]["phone"] == phone
    assert reg_data["user"]["email"] == email
    assert reg_data["user"]["shop_profile"]["shop_name"] == ""
    assert reg_data["user"]["shop_profile"]["shop_address"] == ""
    assert reg_data["user"]["shop_profile"]["shop_phone"] == ""

    # 3. Check /api/v1/auth/me returns blank store fields for new user
    token = reg_data["token"]
    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["shop_profile"]["shop_name"] == ""
    assert me_data["shop_profile"]["shop_address"] == ""
    assert me_data["shop_profile"]["shop_phone"] == ""

    # 4. Check demo user still has Apna Kirana Store
    demo_login = client.post("/api/v1/auth/login", json={
        "identifier": "9876543210",
        "password": "Password@123"
    })
    assert demo_login.status_code == 200
    demo_shop = demo_login.json()["user"]["shop_profile"]
    assert demo_shop["shop_name"] == "Apna Kirana Store"
    assert "Main Market" in demo_shop["shop_address"]

    # 5. Check index.html greeting button has two arrows and cache buster
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()
    assert "Continue to Profile &amp; Settings &rarr; &rarr;" in html
    assert "?v=20261022_blank_onboarding" in html

