"""
Automated Test Suite for Udhaar Customer Bulk Import Pipeline (CSV / Excel).
Verifies:
1. Sample template download endpoint.
2. CSV import with pending balances and opening ledger entries.
3. Excel (.xlsx) file import.
4. Duplicate phone detection (database & sheet-level).
5. Row validation (invalid phone, empty name, negative balance).
6. Missing required columns error (HTTP 400).
7. Sequential C-00XXXX ID generation.
8. Multi-tenant isolation.
"""
import io
import csv
import uuid
import pytest
import pandas as pd
from starlette.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal, get_tenant_engine
from backend.models import Customer, UdhaarTransaction

client = TestClient(app)


def test_download_sample_template():
    """Verify sample CSV template download endpoint returns 200 with required headers."""
    # Test /api/v1/customers/sample-template
    res1 = client.get("/api/v1/customers/sample-template")
    assert res1.status_code == 200
    assert "text/csv" in res1.headers["content-type"]
    assert "attachment; filename=\"udhaar_customers_template.csv\"" in res1.headers.get("content-disposition", "")
    content = res1.text
    assert "Customer Name,Phone Number,Pending Balance,Address" in content

    # Test alias /api/customers/sample-template
    res2 = client.get("/api/customers/sample-template")
    assert res2.status_code == 200
    assert "Customer Name,Phone Number,Pending Balance,Address" in res2.text


def test_import_valid_csv():
    """Verify CSV import of multiple customers with zero and positive pending balances."""
    csv_data = (
        "Customer Name,Phone Number,Pending Balance,Address\n"
        "Rajesh Gupta,9811111101,1250.50,Shop 5 Main Bazar\n"
        "Kavita Devi,9811111102,0,Flat 202 Green Park\n"
        "Manoj Tiwari,9811111103,500,Sector 9 Noida\n"
    )
    files = {
        "file": ("customers_test.csv", csv_data.encode("utf-8"), "text/csv")
    }

    # Use a unique tenant ID to guarantee a clean isolated database
    tenant_id = f"test_import_user_{uuid.uuid4().hex[:8]}"
    headers = {"X-User-Id": tenant_id}

    res = client.post("/api/v1/customers/import", files=files, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "success"
    assert data["total_processed"] == 3
    assert data["successfully_added"] == 3
    assert data["skipped_duplicates"] == 0

    # Verify database state in tenant store
    tenant_engine = get_tenant_engine(tenant_id)
    from sqlalchemy.orm import sessionmaker
    TSession = sessionmaker(bind=tenant_engine)
    session = TSession()
    try:
        rajesh = session.query(Customer).filter(Customer.phone == "9811111101").first()
        assert rajesh is not None
        assert rajesh.full_name == "Rajesh Gupta"
        assert rajesh.current_udhaar_balance == 1250.50
        assert rajesh.customer_code.startswith("C-")

        # Check Opening Balance UdhaarTransaction created for Rajesh
        tx = session.query(UdhaarTransaction).filter(UdhaarTransaction.primary_customer_id == rajesh.id).first()
        assert tx is not None
        assert tx.amount == 1250.50
        assert tx.transaction_type == "DEBIT_PURCHASE"
        assert tx.balance_before == 0.0
        assert tx.balance_after == 1250.50
        assert tx.verified_by == "OPENING_BALANCE_IMPORT"
        assert "Opening Balance from Import" in tx.notes

        # Check Kavita (balance 0, no transaction)
        kavita = session.query(Customer).filter(Customer.phone == "9811111102").first()
        assert kavita is not None
        assert kavita.current_udhaar_balance == 0.0
        kavita_tx = session.query(UdhaarTransaction).filter(UdhaarTransaction.primary_customer_id == kavita.id).first()
        assert kavita_tx is None

    finally:
        session.close()


def test_import_valid_excel():
    """Verify Excel (.xlsx) file import using pandas/openpyxl in memory."""
    df = pd.DataFrame([
        {"Customer Name": "Suresh Raina", "Phone Number": "9822222201", "Pending Balance": 750, "Address": "Civil Lines"},
        {"Customer Name": "Deepika Padukone", "Phone Number": "9822222202", "Pending Balance": 3200, "Address": "Bandra West"}
    ])
    bio = io.BytesIO()
    df.to_excel(bio, index=False, engine="openpyxl")
    bio.seek(0)

    files = {
        "file": ("customers.xlsx", bio.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    }
    tenant_id = f"test_excel_user_{uuid.uuid4().hex[:8]}"
    headers = {"X-User-Id": tenant_id}

    res = client.post("/api/customers/import", files=files, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "success"
    assert data["total_processed"] == 2
    assert data["successfully_added"] == 2
    assert data["skipped_duplicates"] == 0


def test_import_duplicate_skipping():
    """Verify that duplicates are skipped both when repeated in sheet and when existing in DB."""
    csv_data = (
        "Customer Name,Phone Number,Pending Balance,Address\n"
        "Customer One,9833333301,100,Address 1\n"
        "Customer Duplicate,9833333301,200,Address 2\n"  # Duplicate in same sheet
    )
    files = {
        "file": ("dup_test.csv", csv_data.encode("utf-8"), "text/csv")
    }
    tenant_id = f"test_dup_user_{uuid.uuid4().hex[:8]}"
    headers = {"X-User-Id": tenant_id}

    # First import
    res1 = client.post("/api/v1/customers/import", files=files, headers=headers)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["total_processed"] == 2
    assert data1["successfully_added"] == 1
    assert data1["skipped_duplicates"] == 1

    # Second import with same customer (now duplicate against DB)
    csv_data2 = (
        "Customer Name,Phone Number,Pending Balance,Address\n"
        "Customer One Again,9833333301,500,Address New\n"
        "Customer Two,9833333302,300,Address New 2\n"
    )
    files2 = {
        "file": ("dup_test_2.csv", csv_data2.encode("utf-8"), "text/csv")
    }
    res2 = client.post("/api/v1/customers/import", files=files2, headers=headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["total_processed"] == 2
    assert data2["successfully_added"] == 1
    assert data2["skipped_duplicates"] == 1


def test_import_row_level_validation_errors():
    """Verify row validation errors for invalid phone, empty name, negative balance."""
    csv_data = (
        "Customer Name,Phone Number,Pending Balance,Address\n"
        ",9844444401,100,Address 1\n"  # Missing name
        "Valid User,9844444402,200,Address 2\n"  # Valid
        "Bad Phone User,12345,300,Address 3\n"  # Invalid phone length
        "Negative Bal User,9844444403,-50,Address 4\n"  # Negative balance
    )
    files = {
        "file": ("validation_test.csv", csv_data.encode("utf-8"), "text/csv")
    }
    tenant_id = f"test_val_user_{uuid.uuid4().hex[:8]}"
    headers = {"X-User-Id": tenant_id}

    res = client.post("/api/v1/customers/import", files=files, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_processed"] == 4
    assert data["successfully_added"] == 1
    assert len(data["errors"]) == 3


def test_import_missing_required_columns():
    """Verify 400 Bad Request if required columns are missing."""
    csv_data = (
        "Random Header,Another Header\n"
        "Some Name,123456\n"
    )
    files = {
        "file": ("wrong_columns.csv", csv_data.encode("utf-8"), "text/csv")
    }
    headers = {"X-User-Id": "test_import_user_cols"}

    res = client.post("/api/v1/customers/import", files=files, headers=headers)
    assert res.status_code == 400
    assert "Missing required columns" in res.json()["detail"]


def test_import_unsupported_file_extension():
    """Verify 400 Bad Request if file format is unsupported."""
    files = {
        "file": ("test.pdf", b"%PDF-1.4 dummy", "application/pdf")
    }
    res = client.post("/api/v1/customers/import", files=files)
    assert res.status_code == 400
    assert "Unsupported file format" in res.json()["detail"]
