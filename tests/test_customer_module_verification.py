import re
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Customer, UdhaarTransaction, FamilyMember, Bill

client = TestClient(app)

def test_1_dataset_pruned_to_20_to_25_demo_customers():
    """Requirement 1: Pruned customer dataset to 20-25 realistic demo customers with active Udhaar & history."""
    res = client.get("/api/v1/customers")
    assert res.status_code == 200
    custs = res.json()
    assert 20 <= len(custs) <= 25, f"Expected 20-25 customers, got {len(custs)}"
    
    # Check that there are active Udhaar balances and ledger transactions
    with_udhaar = [c for c in custs if c["current_udhaar_balance"] > 0]
    assert len(with_udhaar) >= 15, f"Expected majority of demo customers to have active Udhaar, got {len(with_udhaar)}"
    
    # Check KPI cards dynamic totals
    total_udhaar = sum(c["current_udhaar_balance"] for c in custs)
    total_available = sum(c["available_credit"] for c in custs)
    active_count = sum(1 for c in custs if c["is_active"])
    
    assert total_udhaar > 0
    assert total_available > 0
    assert active_count == len(custs)


def test_2_cleanup_duplicates_button_removed():
    """Requirement 2: Cleanup Duplicates button removed from HTML/UI and click listener disconnected."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()
    
    assert "btn-open-duplicate-cleanup" not in html, "btn-open-duplicate-cleanup must not exist in index.html"
    assert "Cleanup Duplicates" not in html, "Cleanup Duplicates button text must not exist in index.html"
    
    with open("frontend/js/customers.js", "r", encoding="utf-8") as f:
        js = f.read()
    
    assert 'btn-open-duplicate-cleanup' not in js, "Event listener for btn-open-duplicate-cleanup must be removed from customers.js"


def test_3_compact_ledger_table_and_pagination_structure():
    """Requirement 3: Compact ledger table styling and pagination UI."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()
    
    # Pagination bar elements present in index.html
    assert 'id="ledger-pagination-container"' in html
    assert 'id="ledger-pagination-info"' in html
    assert 'id="ledger-pagination-controls"' in html
    
    with open("frontend/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()
    
    # Check compact padding: 8px 10px
    assert "padding: 8px 10px" in css
    # Check pagination CSS rules
    assert ".ledger-pagination-bar" in css
    assert ".ledger-page-btn" in css
    
    with open("frontend/js/customers.js", "r", encoding="utf-8") as f:
        js = f.read()
    
    # Check pagination logic
    assert "LEDGER_PAGE_SIZE = 10" in js
    assert "renderLedgerHistoryPage" in js
    assert "goToLedgerPage" in js
    assert "currentLedgerPage = 1" in js


def test_4_responsive_layout_and_no_clipping():
    """Requirement 4: 100% zoom responsiveness, min-width: 0, flex layout, flex-wrap."""
    with open("frontend/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()
    
    # Check min-width: 0 on udhaar-detail-col to prevent clipping
    assert ".udhaar-detail-col" in css
    assert "min-width: 0" in css
    # Check flex-wrap on profile header and actions
    assert ".profile-top-row" in css
    assert "flex-wrap: wrap" in css
    assert ".profile-actions" in css
    assert ".credit-bar-labels" in css
    # Check overflow-x: auto on table container
    assert "overflow-x: auto" in css


def test_5_sequential_customer_id_format_and_auto_reordering_on_delete():
    """Requirement 5: Sequential C-00XXXX format and automatic gapless reordering on delete."""
    res = client.get("/api/v1/customers")
    assert res.status_code == 200
    custs = res.json()
    
    # Verify all customers follow C-00XXXX format
    for idx, c in enumerate(custs, start=1):
        expected_code = f"C-{idx:06d}"
        assert c["customer_code"] == expected_code, f"Expected {expected_code}, got {c['customer_code']}"
    
    # Attempting to delete a customer with positive balance MUST FAIL (HTTP 400)
    ramesh = next(c for c in custs if c["full_name"] == "Ramesh Sharma")
    assert ramesh["current_udhaar_balance"] > 0
    del_fail = client.delete(f"/api/v1/customers/{ramesh['id']}")
    assert del_fail.status_code == 400
    assert "cannot be deleted because outstanding udhaar remains" in del_fail.json()["detail"].lower()
    
    # Create a temporary zero-balance test customer to test deletion and re-sequencing
    temp_phone = "9899990001"
    create_res = client.post("/api/v1/customers", json={
        "full_name": "Temporary Test Person",
        "phone": temp_phone,
        "credit_limit": 2000.0,
        "address_line": "123 Test St",
        "city": "Chandigarh",
        "state": "Chandigarh",
        "pincode": "160017",
        "country": "India"
    })
    assert create_res.status_code == 201
    temp_cust = create_res.json()
    temp_id = temp_cust["id"]
    
    # Verify new customer was assigned sequential ID
    list_after_create = client.get("/api/v1/customers").json()
    assert len(list_after_create) == len(custs) + 1
    for idx, c in enumerate(list_after_create, start=1):
        assert c["customer_code"] == f"C-{idx:06d}"
        
    # Now delete the zero-balance temporary customer
    del_res = client.delete(f"/api/v1/customers/{temp_id}?hard_delete=true")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True
    
    # Verify remaining customers re-sequenced gaplessly
    list_after_delete = client.get("/api/v1/customers").json()
    assert len(list_after_delete) == len(custs)
    for idx, c in enumerate(list_after_delete, start=1):
        expected_code = f"C-{idx:06d}"
        assert c["customer_code"] == expected_code, f"Expected {expected_code}, got {c['customer_code']}"
        
    # Verify Ramesh's ledger transactions remained 100% intact
    ramesh_detail = client.get(f"/api/v1/customers/{ramesh['id']}").json()
    assert len(ramesh_detail["transactions"]) >= 1


def test_6_modal_responsive_styles_and_2col_grid():
    """Requirement 1: Modal Fix for 100% Zoom, Sticky Header/Footer, Scrollable Body, and 2-Col compact rows."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Verify modal-card-responsive class applied to Create and Edit modals
    assert 'id="create-customer-modal"' in html
    assert 'id="edit-customer-modal"' in html
    assert 'class="modal-card modal-card-responsive"' in html

    # Verify 2-column grid row for phone and credit limit
    assert 'for="create-cust-phone"' in html
    assert 'for="create-cust-limit"' in html
    assert 'for="edit-cust-phone"' in html
    assert 'for="edit-cust-limit"' in html
    assert 'form-row-2col' in html

    with open("frontend/css/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    # Check modal-backdrop constraints
    assert "inset: 0" in css
    assert "padding: 16px" in css
    # Check responsive modal card constraints
    assert "max-height: 90vh" in css
    assert "width: min(560px, 92vw)" in css
    assert "overflow-y: auto" in css
    assert ".modal-card-responsive .form-row-2col" in css
    assert "padding: 8px 12px" in css


def test_7_country_dropdown_and_backend_validation():
    """Requirement 2: Country Dropdown Selection in Create/Edit modals & Database / API validation."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Dropdown select elements
    assert '<select id="create-cust-country"' in html
    assert '<select id="edit-cust-country"' in html

    expected_countries = ["India", "Nepal", "Bangladesh", "Sri Lanka", "USA", "UAE", "Canada"]
    for country in expected_countries:
        assert f'<option value="{country}"' in html, f"Country {country} must be in dropdown"

    # Default country is India
    assert '<option value="India" selected>India</option>' in html

    # Test backend customer creation with foreign country and international postal code
    foreign_phone = "9888880002"
    res = client.post("/api/v1/customers", json={
        "full_name": "John Doe USA",
        "phone": foreign_phone,
        "credit_limit": 5000.0,
        "address_line": "742 Evergreen Terrace",
        "city": "Springfield",
        "state": "Oregon",
        "pincode": "97477",
        "country": "USA"
    })
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    created = res.json()
    assert created["country"] == "USA"
    assert created["pincode"] == "97477"
    assert "USA" in created["address"]
    cust_id = created["id"]

    # Test invalid country rejection (422)
    invalid_country_res = client.post("/api/v1/customers", json={
        "full_name": "Invalid Country User",
        "phone": "9888880003",
        "credit_limit": 2000.0,
        "address_line": "123 Main St",
        "city": "Berlin",
        "state": "Berlin",
        "pincode": "10115",
        "country": "Germany"
    })
    assert invalid_country_res.status_code == 422
    assert "country must be one of" in invalid_country_res.text.lower()

    # Clean up test customer
    del_res = client.delete(f"/api/v1/customers/{cust_id}?hard_delete=true")
    assert del_res.status_code == 200


def test_8_strict_3_button_layout_and_edit_profile_api():
    """Requirement 3: Strict 3-Button Layout, Edit Profile pre-population & Real-time API update."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Check strictly 3 action buttons in order: Settle Balance, Edit Profile, Delete Account
    actions_match = re.search(r'<div class="profile-actions">(.*?)</div>', html, re.DOTALL)
    assert actions_match is not None
    actions_html = actions_match.group(1)

    # Must contain exactly the 3 buttons in order
    settle_idx = actions_html.find("btn-open-settle-modal")
    edit_idx = actions_html.find("btn-open-edit-profile-modal")
    delete_idx = actions_html.find("btn-delete-customer")

    assert settle_idx != -1, "Settle Balance button must exist"
    assert edit_idx != -1, "Edit Profile button must exist"
    assert delete_idx != -1, "Delete Account button must exist"
    assert settle_idx < edit_idx < delete_idx, "Buttons must be strictly ordered: Settle Balance, Edit Profile, Delete Account"

    # Edit Limit button must NOT be in customer profile actions
    assert "btn-open-edit-limit-modal" not in actions_html

    with open("frontend/js/customers.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "openEditProfileModal" in js
    assert "submitEditProfile" in js

    # Test API: Update customer profile and credit limit
    custs = client.get("/api/v1/customers").json()
    first_cust = custs[0]
    first_id = first_cust["id"]

    orig_limit = first_cust["credit_limit"]
    orig_balance = first_cust["current_udhaar_balance"]
    new_limit = orig_limit + 1500.0

    put_res = client.put(f"/api/v1/customers/{first_id}", json={
        "full_name": first_cust["full_name"],
        "phone": first_cust["phone"],
        "credit_limit": new_limit,
        "address_line": "Updated Street 42",
        "city": "Mohali",
        "state": "Punjab",
        "pincode": "160055",
        "country": "India"
    })
    assert put_res.status_code == 200
    updated = put_res.json()
    assert updated["credit_limit"] == new_limit
    assert updated["available_credit"] == round(new_limit - orig_balance, 2)
    assert updated["city"] == "Mohali"
    assert updated["state"] == "Punjab"
    assert updated["country"] == "India"
    assert "Mohali" in updated["address"]

    # Revert credit limit and address back
    revert_res = client.put(f"/api/v1/customers/{first_id}", json={
        "full_name": first_cust["full_name"],
        "phone": first_cust["phone"],
        "credit_limit": orig_limit,
        "address_line": first_cust.get("address_line") or "Main Bazaar",
        "city": first_cust.get("city") or "Chandigarh",
        "state": first_cust.get("state") or "Chandigarh",
        "pincode": first_cust.get("pincode") or "160017",
        "country": first_cust.get("country") or "India"
    })
    assert revert_res.status_code == 200

    # Also test PATCH /api/v1/customers/{id} and /api/customers/{id}
    patch_res = client.patch(f"/api/v1/customers/{first_id}", json={
        "credit_limit": orig_limit
    })
    assert patch_res.status_code == 200
    assert patch_res.json()["credit_limit"] == orig_limit

    alias_res = client.patch(f"/api/customers/{first_id}", json={
        "credit_limit": orig_limit
    })
    assert alias_res.status_code == 200
    assert alias_res.json()["credit_limit"] == orig_limit


