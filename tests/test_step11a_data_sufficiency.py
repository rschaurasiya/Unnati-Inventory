"""
Step 11A Test Suite: Product-Level Historical Data Sufficiency Validation
Validates:
1. Product with 0 historical days -> insufficient_data
2. Product with 1 day -> insufficient_data
3. Product with 6 distinct days -> insufficient_data
4. Product with exactly 7 distinct days -> eligible
5. Product with 8+ days -> eligible
6. Multiple sales rows on the same date count as ONE historical day
7. Two products with different coverage evaluate independently
8. One eligible product must NOT make another product eligible
9. Invalid/ignored rows (quantity <= 0, inactive, pending bill, future dates) do not increase count
10. Duplicate imported records do not inflate historical-day count
11. Historical records from different products remain strictly isolated
12. Empty historical dataset handled safely
13. API response structure and status code validation
14. Database / 404 error handling for non-existent products
15. Regression: existing Step 10 sales aggregation and data sufficiency APIs remain intact
"""
import pytest
from datetime import date, datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import app
from backend.database import SessionLocal
from backend.models import (
    Product, DailySalesSummary, HistoricalSaleRecord, Bill, BillItem
)
from backend.services.forecasting_sufficiency import (
    evaluate_product_data_sufficiency,
    evaluate_all_products_data_sufficiency,
    MIN_USABLE_DAYS_REQUIRED
)
from backend.services.sales_aggregation import check_data_sufficiency

client = TestClient(app)


def _create_product(db: Session, name_suffix: str) -> Product:
    prod = Product(
        name=f"Sufficiency-Test-{name_suffix}",
        category="Test Category",
        unit="packet",
        unit_price=100.0,
        stock_quantity=50.0,
        min_stock_threshold=10.0
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    return prod


def _add_daily_summaries(db: Session, product_id: int, days_count: int, start_days_ago: int = 20):
    for i in range(days_count):
        d = date.today() - timedelta(days=start_days_ago - i)
        summary = DailySalesSummary(
            product_id=product_id,
            sale_date=d,
            total_quantity_sold=5.0,
            total_revenue=500.0,
            transaction_count=1,
            updated_at=datetime.utcnow()
        )
        db.add(summary)
    db.commit()


# ==============================================================================
# Requirement 1: Product with 0 historical days -> insufficient_data
# ==============================================================================
def test_1_zero_historical_days_insufficient():
    db = SessionLocal()
    try:
        prod = _create_product(db, "Zero-Days")
        result = evaluate_product_data_sufficiency(db, prod.id)

        assert result is not None
        assert result["product_id"] == prod.id
        assert result["product_name"] == prod.name
        assert result["historical_days"] == 0
        assert result["earliest_date"] is None
        assert result["latest_date"] is None
        assert result["eligibility_status"] == "insufficient_data"
        assert result["eligibility_reason"] == "Fewer than 7 usable historical days"
    finally:
        db.close()


# ==============================================================================
# Requirement 2: Product with 1 day -> insufficient_data
# ==============================================================================
def test_2_one_historical_day_insufficient():
    db = SessionLocal()
    try:
        prod = _create_product(db, "One-Day")
        _add_daily_summaries(db, prod.id, days_count=1, start_days_ago=5)

        result = evaluate_product_data_sufficiency(db, prod.id)
        assert result is not None
        assert result["historical_days"] == 1
        assert result["eligibility_status"] == "insufficient_data"
        assert result["eligibility_reason"] == "Fewer than 7 usable historical days"
        assert result["earliest_date"] is not None
        assert result["latest_date"] == result["earliest_date"]
    finally:
        db.close()


# ==============================================================================
# Requirement 3: Product with 6 distinct days -> insufficient_data
# ==============================================================================
def test_3_six_historical_days_insufficient():
    db = SessionLocal()
    try:
        prod = _create_product(db, "Six-Days")
        _add_daily_summaries(db, prod.id, days_count=6, start_days_ago=10)

        result = evaluate_product_data_sufficiency(db, prod.id)
        assert result is not None
        assert result["historical_days"] == 6
        assert result["eligibility_status"] == "insufficient_data"
        assert result["eligibility_reason"] == "Fewer than 7 usable historical days"
    finally:
        db.close()


# ==============================================================================
# Requirement 4: Product with exactly 7 distinct days -> eligible
# ==============================================================================
def test_4_exactly_seven_historical_days_eligible():
    db = SessionLocal()
    try:
        prod = _create_product(db, "Seven-Days")
        _add_daily_summaries(db, prod.id, days_count=7, start_days_ago=14)

        result = evaluate_product_data_sufficiency(db, prod.id)
        assert result is not None
        assert result["historical_days"] == 7
        assert result["eligibility_status"] == "eligible"
        assert result["eligibility_reason"] == "7 or more usable historical days"
        assert result["earliest_date"] is not None
        assert result["latest_date"] is not None
        assert result["earliest_date"] < result["latest_date"]
    finally:
        db.close()


# ==============================================================================
# Requirement 5: Product with 8+ days -> eligible
# ==============================================================================
def test_5_eight_plus_historical_days_eligible():
    db = SessionLocal()
    try:
        prod = _create_product(db, "Twelve-Days")
        _add_daily_summaries(db, prod.id, days_count=12, start_days_ago=20)

        result = evaluate_product_data_sufficiency(db, prod.id)
        assert result is not None
        assert result["historical_days"] == 12
        assert result["eligibility_status"] == "eligible"
        assert result["eligibility_reason"] == "7 or more usable historical days"
    finally:
        db.close()


# ==============================================================================
# Requirement 6: Multiple sales rows on the same date -> count as ONE historical day
# ==============================================================================
def test_6_multiple_sales_rows_on_same_date_count_as_one():
    db = SessionLocal()
    try:
        prod = _create_product(db, "Same-Day-Duplicates")
        sale_d = date.today() - timedelta(days=2)

        # 1. Summary row
        db.add(DailySalesSummary(
            product_id=prod.id,
            sale_date=sale_d,
            total_quantity_sold=3.0,
            total_revenue=300.0,
            transaction_count=1
        ))
        # 2. HistoricalSaleRecord on same date
        db.add(HistoricalSaleRecord(
            import_id="IMP-TEST-1",
            raw_product_name=prod.name,
            product_id=prod.id,
            sale_date=sale_d,
            quantity=2.0,
            unit=prod.unit,
            unit_price=100.0,
            total_amount=200.0,
            row_fingerprint="fp_same_day_1",
            is_active=True
        ))
        # 3. Another HistoricalSaleRecord on same date
        db.add(HistoricalSaleRecord(
            import_id="IMP-TEST-2",
            raw_product_name=prod.name,
            product_id=prod.id,
            sale_date=sale_d,
            quantity=4.0,
            unit=prod.unit,
            unit_price=100.0,
            total_amount=400.0,
            row_fingerprint="fp_same_day_2",
            is_active=True
        ))
        # 4. Completed BillItem on same date
        bill = Bill(
            bill_number=f"BILL-{prod.id}-SAME-DAY",
            subtotal=100.0,
            total_amount=100.0,
            status="COMPLETED",
            created_at=datetime.combine(sale_d, datetime.min.time()) + timedelta(hours=10)
        )
        db.add(bill)
        db.commit()
        db.refresh(bill)

        db.add(BillItem(
            bill_id=bill.id,
            product_id=prod.id,
            quantity=1.0,
            unit=prod.unit,
            unit_price=100.0,
            line_total=100.0
        ))
        db.commit()

        result = evaluate_product_data_sufficiency(db, prod.id)
        assert result is not None
        # 4 records on the exact same date MUST count as exactly ONE distinct historical day
        assert result["historical_days"] == 1
        assert result["eligibility_status"] == "insufficient_data"
    finally:
        db.close()


# ==============================================================================
# Requirement 7 & 8: Products evaluated independently, no cross-contamination
# ==============================================================================
def test_7_and_8_products_evaluated_independently_no_contamination():
    db = SessionLocal()
    try:
        prod_eligible = _create_product(db, "Independent-Eligible")
        prod_insufficient = _create_product(db, "Independent-Insufficient")

        _add_daily_summaries(db, prod_eligible.id, days_count=10, start_days_ago=15)
        _add_daily_summaries(db, prod_insufficient.id, days_count=3, start_days_ago=5)

        res_elig = evaluate_product_data_sufficiency(db, prod_eligible.id)
        res_insuf = evaluate_product_data_sufficiency(db, prod_insufficient.id)

        assert res_elig["historical_days"] == 10
        assert res_elig["eligibility_status"] == "eligible"

        assert res_insuf["historical_days"] == 3
        assert res_insuf["eligibility_status"] == "insufficient_data"
        # Product B does not become eligible because Product A is eligible
        assert res_insuf["eligibility_status"] != res_elig["eligibility_status"]
    finally:
        db.close()


# ==============================================================================
# Requirement 9: Invalid/ignored historical rows must not increase day count
# ==============================================================================
def test_9_invalid_and_ignored_rows_do_not_increase_count():
    db = SessionLocal()
    try:
        prod = _create_product(db, "Invalid-Rows-Test")

        # 1. Zero quantity summary
        db.add(DailySalesSummary(
            product_id=prod.id,
            sale_date=date.today() - timedelta(days=1),
            total_quantity_sold=0.0,
            total_revenue=0.0,
            transaction_count=0
        ))
        # 2. Inactive historical record
        db.add(HistoricalSaleRecord(
            import_id="IMP-INACTIVE",
            raw_product_name=prod.name,
            product_id=prod.id,
            sale_date=date.today() - timedelta(days=2),
            quantity=5.0,
            unit=prod.unit,
            unit_price=100.0,
            total_amount=500.0,
            row_fingerprint="fp_inactive_1",
            is_active=False  # INACTIVE / ROLLED BACK
        ))
        # 3. Future date sale (leakage prevention)
        db.add(HistoricalSaleRecord(
            import_id="IMP-FUTURE",
            raw_product_name=prod.name,
            product_id=prod.id,
            sale_date=date.today() + timedelta(days=3),  # FUTURE DATE
            quantity=10.0,
            unit=prod.unit,
            unit_price=100.0,
            total_amount=1000.0,
            row_fingerprint="fp_future_1",
            is_active=True
        ))
        # 4. Pending / cancelled bill
        pending_bill = Bill(
            bill_number=f"BILL-{prod.id}-PENDING",
            subtotal=100.0,
            total_amount=100.0,
            status="PENDING",  # NOT COMPLETED
            created_at=datetime.utcnow() - timedelta(days=4)
        )
        db.add(pending_bill)
        db.commit()
        db.refresh(pending_bill)

        db.add(BillItem(
            bill_id=pending_bill.id,
            product_id=prod.id,
            quantity=2.0,
            unit=prod.unit,
            unit_price=100.0,
            line_total=200.0
        ))
        db.commit()

        result = evaluate_product_data_sufficiency(db, prod.id)
        assert result is not None
        # All 4 entries were invalid/ignored: historical days must strictly be 0
        assert result["historical_days"] == 0
        assert result["eligibility_status"] == "insufficient_data"
    finally:
        db.close()


# ==============================================================================
# Requirement 10: Duplicate imported records do not inflate historical-day count
# ==============================================================================
def test_10_duplicate_imported_records_deduplicated():
    db = SessionLocal()
    try:
        prod = _create_product(db, "Duplicate-Import-Deduplication")
        fixed_date = date.today() - timedelta(days=7)

        # 10 identical import rows on the exact same date
        for i in range(10):
            db.add(HistoricalSaleRecord(
                import_id=f"IMP-DUP-{i}",
                raw_product_name=prod.name,
                product_id=prod.id,
                sale_date=fixed_date,
                quantity=1.0,
                unit=prod.unit,
                unit_price=100.0,
                total_amount=100.0,
                row_fingerprint=f"fp_dup_{i}",
                is_active=True
            ))
        db.commit()

        result = evaluate_product_data_sufficiency(db, prod.id)
        assert result["historical_days"] == 1
        assert result["eligibility_status"] == "insufficient_data"
    finally:
        db.close()


# ==============================================================================
# Requirement 11: Historical records from different products remain isolated
# ==============================================================================
def test_11_cross_product_isolation():
    db = SessionLocal()
    try:
        prod_active = _create_product(db, "Active-Sales-Prod")
        prod_isolated = _create_product(db, "Isolated-No-Sales-Prod")

        # Give prod_active 9 days of sales
        _add_daily_summaries(db, prod_active.id, days_count=9, start_days_ago=12)

        res_active = evaluate_product_data_sufficiency(db, prod_active.id)
        res_isolated = evaluate_product_data_sufficiency(db, prod_isolated.id)

        assert res_active["historical_days"] == 9
        assert res_active["eligibility_status"] == "eligible"

        assert res_isolated["historical_days"] == 0
        assert res_isolated["eligibility_status"] == "insufficient_data"
        assert res_isolated["earliest_date"] is None
        assert res_isolated["latest_date"] is None
    finally:
        db.close()


# ==============================================================================
# Requirement 12: Empty historical dataset handled safely
# ==============================================================================
def test_12_empty_dataset_safe_handling():
    db = SessionLocal()
    try:
        prod = _create_product(db, "Empty-History-Safe")
        result = evaluate_product_data_sufficiency(db, prod.id)

        assert result["product_id"] == prod.id
        assert result["historical_days"] == 0
        assert result["earliest_date"] is None
        assert result["latest_date"] is None
        assert result["eligibility_status"] == "insufficient_data"

        all_res = evaluate_all_products_data_sufficiency(db)
        assert "total_products" in all_res
        assert "eligible_count" in all_res
        assert "insufficient_count" in all_res
        assert all_res["min_days_required"] == 7
        assert isinstance(all_res["products"], list)
    finally:
        db.close()


# ==============================================================================
# Requirement 13: API Response Validation
# ==============================================================================
def test_13_api_response_validation():
    db = SessionLocal()
    try:
        prod_elig = _create_product(db, "API-Eligible")
        prod_insuf = _create_product(db, "API-Insufficient")

        _add_daily_summaries(db, prod_elig.id, days_count=8, start_days_ago=12)
        _add_daily_summaries(db, prod_insuf.id, days_count=2, start_days_ago=4)

        # 1. Test GET /api/forecasting/data-sufficiency/{prod_id}
        res1 = client.get(f"/api/forecasting/data-sufficiency/{prod_elig.id}")
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["product_id"] == prod_elig.id
        assert data1["product_name"] == prod_elig.name
        assert data1["historical_days"] == 8
        assert data1["eligibility_status"] == "eligible"
        assert data1["eligibility_reason"] == "7 or more usable historical days"
        assert data1["earliest_date"] is not None
        assert data1["latest_date"] is not None

        # 2. Test GET /api/forecasting/data-sufficiency?product_id={prod_id}
        res2 = client.get(f"/api/forecasting/data-sufficiency?product_id={prod_insuf.id}")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["product_id"] == prod_insuf.id
        assert data2["historical_days"] == 2
        assert data2["eligibility_status"] == "insufficient_data"
        assert data2["eligibility_reason"] == "Fewer than 7 usable historical days"

        # 3. Test GET /api/v1/forecast/data-sufficiency/{prod_id}
        res3 = client.get(f"/api/v1/forecast/data-sufficiency/{prod_elig.id}")
        assert res3.status_code == 200
        assert res3.json()["eligibility_status"] == "eligible"

        # 4. Test GET /api/forecasting/data-sufficiency (store overview)
        res4 = client.get("/api/forecasting/data-sufficiency")
        assert res4.status_code == 200
        data4 = res4.json()
        assert "total_products" in data4
        assert "eligible_count" in data4
        assert "insufficient_count" in data4
        assert data4["min_days_required"] == 7
        assert len(data4["products"]) >= 2
    finally:
        db.close()


# ==============================================================================
# Requirement 14: Non-existent product / 404 handling
# ==============================================================================
def test_14_non_existent_product_returns_404():
    res1 = client.get("/api/forecasting/data-sufficiency/9999999")
    assert res1.status_code == 404
    assert "not found" in res1.json()["detail"].lower()

    res2 = client.get("/api/forecasting/data-sufficiency?product_id=9999999")
    assert res2.status_code == 404
    assert "not found" in res2.json()["detail"].lower()

    res3 = client.get("/api/v1/forecast/data-sufficiency/9999999")
    assert res3.status_code == 404


# ==============================================================================
# Requirement 15: Regression test - existing analytics & Step 10 sufficiency intact
# ==============================================================================
def test_15_regression_existing_step10_sufficiency_intact():
    db = SessionLocal()
    try:
        # Existing Step 10 check_data_sufficiency continues to function
        step10_res = check_data_sufficiency(db)
        assert "status" in step10_res
        assert "usable_days_count" in step10_res
        assert "min_days_required" in step10_res
        assert "products" in step10_res

        # Existing Step 10 analytics API route remains functional
        api_res = client.get("/api/v1/analytics/sufficiency")
        assert api_res.status_code == 200

        # Existing Step 11 forecasting sufficiency endpoint remains functional
        fc_res = client.get("/api/v1/forecast/sufficiency")
        assert fc_res.status_code == 200
    finally:
        db.close()
