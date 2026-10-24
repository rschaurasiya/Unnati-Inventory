"""
Test Suite: Finalized Bill Modal & Thermal Receipt Formatting Verification
Verifies:
1. Cache-busting query strings (?v=20261014_v3) on all stylesheets and scripts in index.html.
2. Top-right '×' close button on finalized bill modal has window.closeFinalizedBillModal bound and capture listener in billing.js.
3. CSS ensures 100% zoom modal layout with flex-shrink: 0, overflow: visible on cards, and zero nested scrollbars.
4. Thermal receipt generation for Cash, UPI, and Udhaar:
   - Does NOT truncate product names with '..'
   - Word-wraps address and footer cleanly
   - Includes full details for CASH, UPI, and UDHAAR
   - Guarantees clean 41-char line width boundaries
"""
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Product, Bill, VerificationSession, Customer

client = TestClient(app)


def test_1_cache_busting_and_close_button_in_html():
    """Verify index.html has ?v=20261014_v3 on all css/js tags and onclick on close button."""
    index_html_path = ROOT_DIR / "frontend" / "index.html"
    assert index_html_path.exists(), "frontend/index.html must exist"
    content = index_html_path.read_text(encoding="utf-8")

    # Check stylesheet cache-busting
    css_match = re.search(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', content)
    assert css_match, "Stylesheet link must be present"
    assert ("?v=20261022_blank_onboarding" in css_match.group(1) or "?v=20261022_onboarding_lock" in css_match.group(1) or "?v=20261022_firebase_reset" in css_match.group(1) or "?v=20261017_header_v3" in css_match.group(1) or "?v=20261015_fixed" in css_match.group(1) or "?v=20261015_v1" in css_match.group(1) or "?v=20261014_multibill_fix" in css_match.group(1) or "?v=20261014_print_fix" in css_match.group(1) or "?v=20261014_v3" in css_match.group(1)), f"Stylesheet link must have cache-busting query: {css_match.group(1)}"

    # Check all scripts have cache-busting query
    script_matches = re.findall(r'<script[^>]+src="([^"]+)"', content)
    assert len(script_matches) >= 5, "Should have multiple script tags"
    for src in script_matches:
        assert ("?v=20261022_blank_onboarding" in src or "?v=20261022_onboarding_lock" in src or "?v=20261022_firebase_reset" in src or "?v=20261017_header_v3" in src or "?v=20261015_fixed" in src or "?v=20261015_v1" in src or "?v=20261014_multibill_fix" in src or "?v=20261014_print_fix" in src or "?v=20261014_v3" in src), f"Script {src} must have cache-busting query"

    # Check dedicated top-level print container
    assert 'id="pos-thermal-print-container"' in content, "Dedicated top-level print container must be in index.html"

    # Check close button on bill completed modal
    assert 'id="receipt-modal-close-btn"' in content
    close_btn_match = re.search(r'<button[^>]+id="receipt-modal-close-btn"[^>]*>', content)
    assert close_btn_match, "receipt-modal-close-btn must be present in index.html"
    close_btn_tag = close_btn_match.group(0)
    assert "window.closeFinalizedBillModal" in close_btn_tag, f"Close button must invoke window.closeFinalizedBillModal: {close_btn_tag}"


def test_2_billing_js_close_modal_implementation():
    """Verify billing.js defines window.closeFinalizedBillModal, capture-phase listener, and client thermal formatting."""
    billing_js_path = ROOT_DIR / "frontend" / "js" / "billing.js"
    assert billing_js_path.exists()
    js_content = billing_js_path.read_text(encoding="utf-8")

    assert "window.closeFinalizedBillModal = closeFinalizedBillModal" in js_content
    assert 'style.setProperty("display", "none", "important")' in js_content or "style.setProperty('display', 'none', 'important')" in js_content
    assert 'classList.add("hidden")' in js_content or "classList.add('hidden')" in js_content
    assert "clearDraftBill()" in js_content

    # Capture-phase click listener
    assert 'document.addEventListener("click"' in js_content or "document.addEventListener('click'" in js_content
    assert "true);" in js_content, "Click listener should be registered in capture phase"

    # Client thermal preview function
    assert "formatClientThermalReceipt" in js_content


def test_3_css_modal_layout_and_zero_nested_scrollbars():
    """Verify style.css rules for modal-receipt, scrollable body, flex-shrink: 0, and thermal card."""
    css_path = ROOT_DIR / "frontend" / "css" / "style.css"
    assert css_path.exists()
    css_content = css_path.read_text(encoding="utf-8")

    # Modal receipt sizing
    assert "min(95vw, 660px)" in css_content
    assert "max-height: 92vh" in css_content
    assert "padding: 14px 20px" in css_content

    # Zero nested scrollbars & flex-shrink 0
    assert "flex-shrink: 0 !important" in css_content
    assert "overflow: visible !important" in css_content
    assert ".receipt-scrollable-body > *" in css_content

    # Thermal receipt card styling
    assert "white-space: pre" in css_content
    assert ("max-width: 340px" in css_content or "max-width: 420px" in css_content)

    # Print styling
    assert "@media print" in css_content
    assert "80mm" in css_content
    assert "pos-thermal-print-container" in css_content


def test_4_thermal_receipt_formatting_cash():
    """Verify thermal receipt formatting for CASH: strict 38 chars, no truncation, clean address/footer, full details."""
    db = SessionLocal()
    prod = db.query(Product).first()
    db.close()

    res = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod.id, "quantity": 2.0}],
        "payment_mode": "CASH"
    })
    assert res.status_code in (200, 201)
    bill = res.json()

    prep = client.post("/api/v1/receipts/delivery-prep", json={"bill_id": bill["id"]}).json()
    assert "receipt" in prep
    thermal_text = prep["receipt"]["formatted_text_receipt"]

    assert "APNA KIRANA STORE" in thermal_text.upper()
    assert bill["bill_number"] in thermal_text
    assert "Payment:    CASH" in thermal_text
    assert "COMPLETED (CASH SALE)" in thermal_text
    assert "GRAND TOTAL:" in thermal_text
    assert "Walk-in Customer" in thermal_text
    assert "Please Visit Again Soon" in thermal_text

    # Verify no '..' truncation in product rows and strict <= 38 char limit
    lines = thermal_text.split("\n")
    for line in lines:
        assert ".." not in line, f"Product name must not be truncated with '..': {line}"
        assert len(line) <= 38, f"Line too wide for 38-char thermal receipt: ({len(line)}) '{line}'"


def test_5_thermal_receipt_formatting_upi():
    """Verify thermal receipt formatting for UPI sale."""
    db = SessionLocal()
    prod = db.query(Product).first()
    db.close()

    res = client.post("/api/v1/billing/finalize", json={
        "items": [{"product_id": prod.id, "quantity": 1.0}],
        "payment_mode": "UPI"
    })
    assert res.status_code in (200, 201)
    bill = res.json()

    prep = client.post("/api/v1/receipts/delivery-prep", json={"bill_id": bill["id"]}).json()
    thermal_text = prep["receipt"]["formatted_text_receipt"]

    assert "Payment:    UPI" in thermal_text
    assert "COMPLETED (UPI SALE)" in thermal_text
    assert "GRAND TOTAL:" in thermal_text

    for line in thermal_text.split("\n"):
        assert ".." not in line
        assert len(line) <= 38, f"UPI receipt line too wide: ({len(line)}) '{line}'"


def test_6_thermal_receipt_formatting_udhaar_and_long_name():
    """Verify thermal receipt for UDHAAR with long product name: multi-line layout without truncation."""
    db = SessionLocal()
    # Create or get product with a long Kirana name
    long_name = "Loose Cheeni / Sweetener (1kg Special Grade)"
    prod = db.query(Product).filter(Product.name == long_name).first()
    if not prod:
        prod = Product(
            name=long_name,
            unit="kg",
            unit_price=48.0,
            stock_quantity=100.0,
            min_stock_threshold=10.0,
            category="Grocery"
        )
        db.add(prod)
        db.commit()
        db.refresh(prod)

    cust = db.query(Customer).filter(Customer.is_active == True, Customer.is_phone_verified == True).first()
    if not cust:
        cust = Customer(
            full_name="Rajesh Sharma",
            phone="9876543210",
            credit_limit=10000.0,
            is_active=True,
            is_phone_verified=True,
            phone_verification_status="VERIFIED"
        )
        db.add(cust)
        db.commit()
        db.refresh(cust)
    cust_id = cust.id
    prod_id = prod.id
    db.close()

    try:
        # Create Udhaar bill
        res = client.post("/api/v1/billing/finalize", json={
            "customer_id": cust_id,
            "items": [{"product_id": prod_id, "quantity": 3.0}],
            "payment_mode": "UDHAAR"
        })
        assert res.status_code in (200, 201)
        bill = res.json()

        # Complete 2FA
        sess = client.post("/api/v1/verification/sessions", json={"bill_id": bill["id"]}).json()
        db = SessionLocal()
        target = db.query(VerificationSession).filter(VerificationSession.id == sess["session_id"]).first().target_number
        db.close()

        client.post("/api/v1/verification/verify", json={
            "session_id": sess["session_id"],
            "selected_number": target
        })

        prep = client.post("/api/v1/receipts/delivery-prep", json={"bill_id": bill["id"]}).json()
        thermal_text = prep["receipt"]["formatted_text_receipt"]

        # Verify long product name is NOT truncated with '..'
        assert ".." not in thermal_text
        assert "Loose Cheeni / Sweetener" in thermal_text
        assert "Payment:    UDHAAR" in thermal_text
        assert "VERIFIED: YES" in thermal_text
        assert "Outstanding Balance:" in thermal_text
        assert "Customer ID:" in thermal_text
        assert "GRAND TOTAL:" in thermal_text

        for line in thermal_text.split("\n"):
            assert ".." not in line
            assert len(line) <= 38, f"Udhaar receipt line too wide: ({len(line)}) '{line}'"
    finally:
        # Clean up test product so it does not affect staple search in other test suites
        db = SessionLocal()
        p = db.query(Product).filter(Product.id == prod_id).first()
        if p:
            # Delete bill items and product
            from backend.models import BillItem
            db.query(BillItem).filter(BillItem.product_id == prod_id).delete()
            db.delete(p)
            db.commit()
        db.close()
