"""
System-Wide Real-Time Profile & Business Data Synchronization Test Suite
Verifies that updating Shop Name, Address, Phone, GSTIN, Logo, Footer, and Preferences:
1. Immediately updates the backend single source of truth.
2. Synchronizes across digital receipts, printable thermal receipts, WhatsApp deliveries, SMS mock text, and Udhaar OTP verification messages.
3. Automatically reflects in any new bill or transaction generated without requiring server or session restarts.
4. Preserves backward compatibility and cleans up state after test execution.
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import ShopProfile, ShopkeeperUser, Product, Customer

client = TestClient(app)


@pytest.fixture
def auth_headers():
    """Logs in default shopkeeper or registers to retrieve valid auth token."""
    login_res = client.post("/api/v1/auth/login", json={
        "identifier": "9876543210",
        "password": "Password@123"
    })
    if login_res.status_code == 200:
        token = login_res.json()["access_token"]
    else:
        # Register new shopkeeper if default not present
        reg_res = client.post("/api/v1/auth/register", json={
            "full_name": "Test Shopkeeper",
            "phone": "9876543210",
            "email": "shopkeeper@test.com",
            "password": "Password@123",
            "confirm_password": "Password@123",
            "shop_name": "Apna Kirana Store"
        })
        assert reg_res.status_code == 201
        token = reg_res.json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


def test_system_wide_profile_and_business_data_synchronization(auth_headers):
    """
    Complete end-to-end synchronization test:
    Update Shop Details -> Verify GET /shop -> Create New Bill -> Verify Receipt, WhatsApp, SMS, Verification.
    """
    try:
        # 1. Update Shop Profile with new authoritative business identity
        new_shop_data = {
            "shop_name": "Shree Krishna Super Store",
            "shop_address": "Sector 18 Commercial Complex, Shop 104, Noida",
            "gstin": "07AAAAA0000A1Z5",
            "shop_phone": "+91 99887 76655",
            "shop_email": "billing@shreekrishnastores.com",
            "shop_logo_url": "https://example.com/assets/krishna_logo.png"
        }
        update_res = client.put("/api/v1/auth/shop", json=new_shop_data, headers=auth_headers)
        assert update_res.status_code == 200, f"Shop update failed: {update_res.text}"
        updated_shop = update_res.json()
        assert updated_shop["shop_name"] == "Shree Krishna Super Store"
        assert updated_shop["shop_address"] == "Sector 18 Commercial Complex, Shop 104, Noida"
        assert updated_shop["gstin"] == "07AAAAA0000A1Z5"
        assert updated_shop["shop_phone"] == "+91 99887 76655"

        # 2. Update Settings & Preferences
        settings_data = {
            "currency": "₹",
            "timezone": "Asia/Kolkata",
            "default_measurement_unit": "packets",
            "default_min_stock_threshold": 12.0,
            "invoice_footer": "Special Discount on next purchase! Goods once sold can be exchanged in 7 days."
        }
        settings_res = client.put("/api/v1/auth/settings", json=settings_data, headers=auth_headers)
        assert settings_res.status_code == 200, f"Settings update failed: {settings_res.text}"
        updated_settings = settings_res.json()
        assert updated_settings["invoice_footer"] == "Special Discount on next purchase! Goods once sold can be exchanged in 7 days."

        # 3. Verify public GET /api/v1/auth/shop returns updated authoritative data
        get_shop_res = client.get("/api/v1/auth/shop")
        assert get_shop_res.status_code == 200
        active_shop = get_shop_res.json()
        assert active_shop["shop_name"] == "Shree Krishna Super Store"
        assert active_shop["gstin"] == "07AAAAA0000A1Z5"

        # 4. Create a NEW Bill after update
        db = SessionLocal()
        try:
            sugar = db.query(Product).filter(Product.name.like("%Sugar%")).first()
            milk = db.query(Product).filter(Product.name.like("%Milk%")).first()
            assert sugar is not None and milk is not None, "Products required for test"
            sugar_id, milk_id = sugar.id, milk.id
        finally:
            db.close()

        finalize_res = client.post("/api/v1/billing/finalize", json={
            "items": [
                {"product_id": sugar_id, "quantity": 2.0},
                {"product_id": milk_id, "quantity": 1.0}
            ],
            "payment_mode": "CASH",
            "notes": "Sync test cash bill"
        })
        assert finalize_res.status_code == 201
        final_bill = finalize_res.json()
        bill_id = final_bill["id"]

        # 5. Check Digital Receipt endpoint
        receipt_res = client.get(f"/api/v1/receipts/{bill_id}")
        assert receipt_res.status_code == 200
        receipt_data = receipt_res.json()

        assert receipt_data["shop_name"] == "Shree Krishna Super Store"
        assert receipt_data["shop_address"] == "Sector 18 Commercial Complex, Shop 104, Noida"
        assert receipt_data["shop_phone"] == "+91 99887 76655"
        assert receipt_data["gstin"] == "07AAAAA0000A1Z5"
        assert receipt_data["shop_logo_url"] == "https://example.com/assets/krishna_logo.png"
        assert receipt_data["invoice_footer"] == "Special Discount on next purchase! Goods once sold can be exchanged in 7 days."

        # Verify formatted ASCII thermal receipt contains the latest business info
        thermal_text = receipt_data["formatted_text_receipt"]
        assert "SHREE KRISHNA SUPER STORE" in thermal_text
        assert ("Sector 18 Commercial Complex, Shop 104, Noida" in thermal_text or "Sector 18 Commercial Complex" in thermal_text)
        assert "07AAAAA0000A1Z5" in thermal_text
        assert "Special Discount on next purchase!" in thermal_text

        # 6. Check Delivery Prep (WhatsApp & SMS)
        prep_res = client.post("/api/v1/receipts/delivery-prep", json={
            "bill_id": bill_id,
            "customer_phone": "9876543210"
        })
        assert prep_res.status_code == 200
        prep_data = prep_res.json()

        # WhatsApp message verification
        wa_msg = prep_data["whatsapp"]["formatted_message"]
        assert "SHREE KRISHNA SUPER STORE" in wa_msg
        assert "Sector 18 Commercial Complex, Shop 104, Noida" in wa_msg
        assert "07AAAAA0000A1Z5" in wa_msg
        assert "Special Discount on next purchase!" in wa_msg

        # SMS text verification
        sms_text = prep_data["sms"]["sms_text"]
        assert "Shree Krishna Super Store" in sms_text

        # 7. Check Udhaar Verification Session message preview
        db = SessionLocal()
        try:
            cust = db.query(Customer).filter(Customer.is_active == True).first()
        finally:
            db.close()

        if cust:
            u_fin_res = client.post("/api/v1/billing/finalize", json={
                "customer_id": cust.id,
                "items": [{"product_id": sugar_id, "quantity": 1.0}],
                "payment_mode": "UDHAAR",
                "notes": "Sync test Udhaar bill"
            })
            assert u_fin_res.status_code == 201
            u_bill = u_fin_res.json()
            u_bill_id = u_bill["id"]

            verif_session_res = client.post("/api/v1/verification/sessions", json={
                "bill_id": u_bill_id,
                "verification_type": "OTP",
                "delivery_channel": "SMS"
            })
            assert verif_session_res.status_code in [200, 201]
            verif_data = verif_session_res.json()
            assert "Shree Krishna Super Store" in verif_data["delivery_message_preview"]
    finally:
        # 8. TEARDOWN: Restore default shop profile for other test suites
        client.put("/api/v1/auth/shop", json={
            "shop_name": "Apna Kirana Store",
            "shop_address": "Main Market, Sector 4, New Delhi",
            "gstin": None,
            "shop_phone": "+91 98765 43210",
            "shop_email": None,
            "shop_logo_url": None
        }, headers=auth_headers)

        client.put("/api/v1/auth/settings", json={
            "currency": "₹",
            "timezone": "Asia/Kolkata",
            "default_measurement_unit": "kg",
            "default_min_stock_threshold": 10.0,
            "invoice_footer": "Thank you for shopping with us! Visit again."
        }, headers=auth_headers)
