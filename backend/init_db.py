"""
Database Initialization & Seeding Utility
Creates all database tables defined in backend.models and seeds the default Kirana product catalog.
"""
from backend.database import engine, Base, SessionLocal
from backend.models import (
    Product, Customer, FamilyMember, Bill, BillItem,
    VerificationSession, UdhaarTransaction, DailySalesSummary,
    HistoricalImportBatch, HistoricalSaleRecord, ProductForecast,
    ShopkeeperUser, ShopProfile
)
from backend.seed_data import INITIAL_PRODUCTS, INITIAL_CUSTOMERS
from backend.security import hash_password


def init_db(seed: bool = True) -> dict:
    """
    Creates all database tables and seeds initial products & customer accounts if empty.
    Returns status summary dictionary.
    """
    # Create all tables in database engine
    Base.metadata.create_all(bind=engine)

    # SQLite column migration helper for added columns
    try:
        with engine.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA table_info(customers)").fetchall()
            cust_cols = [r[1] for r in result]
            if "is_phone_verified" not in cust_cols:
                conn.exec_driver_sql("ALTER TABLE customers ADD COLUMN is_phone_verified BOOLEAN DEFAULT 0 NOT NULL")
            if "phone_verification_status" not in cust_cols:
                conn.exec_driver_sql("ALTER TABLE customers ADD COLUMN phone_verification_status VARCHAR(30) DEFAULT 'UNVERIFIED' NOT NULL")
            if "customer_code" not in cust_cols:
                conn.exec_driver_sql("ALTER TABLE customers ADD COLUMN customer_code VARCHAR(20)")
                conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_code ON customers(customer_code)")
            if "address_line" not in cust_cols:
                conn.exec_driver_sql("ALTER TABLE customers ADD COLUMN address_line VARCHAR(255)")
            if "city" not in cust_cols:
                conn.exec_driver_sql("ALTER TABLE customers ADD COLUMN city VARCHAR(100)")
            if "state" not in cust_cols:
                conn.exec_driver_sql("ALTER TABLE customers ADD COLUMN state VARCHAR(100)")
            if "pincode" not in cust_cols:
                conn.exec_driver_sql("ALTER TABLE customers ADD COLUMN pincode VARCHAR(10)")
            if "country" not in cust_cols:
                conn.exec_driver_sql("ALTER TABLE customers ADD COLUMN country VARCHAR(60) DEFAULT 'India' NOT NULL")

            # Backfill customer_code and structured address for existing customers
            conn.exec_driver_sql("UPDATE customers SET customer_code = printf('C-%06d', id) WHERE customer_code IS NULL")
            conn.exec_driver_sql("UPDATE customers SET address_line = coalesce(address, 'Main Market'), city = 'Chandigarh', state = 'Chandigarh', pincode = '160017', country = 'India' WHERE address_line IS NULL")

            result_m = conn.exec_driver_sql("PRAGMA table_info(family_members)").fetchall()
            fam_cols = [r[1] for r in result_m]
            if "is_phone_verified" not in fam_cols:
                conn.exec_driver_sql("ALTER TABLE family_members ADD COLUMN is_phone_verified BOOLEAN DEFAULT 0 NOT NULL")
            if "phone_verification_status" not in fam_cols:
                conn.exec_driver_sql("ALTER TABLE family_members ADD COLUMN phone_verification_status VARCHAR(30) DEFAULT 'UNVERIFIED' NOT NULL")

            result_p = conn.exec_driver_sql("PRAGMA table_info(products)").fetchall()
            prod_cols = [r[1] for r in result_p]
            if "is_active" not in prod_cols:
                conn.exec_driver_sql("ALTER TABLE products ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL")

            # Verification sessions migration
            result_v = conn.exec_driver_sql("PRAGMA table_info(verification_sessions)").fetchall()
            verif_cols = [r[1] for r in result_v]
            if "delivery_channel" not in verif_cols:
                conn.exec_driver_sql("ALTER TABLE verification_sessions ADD COLUMN delivery_channel VARCHAR(20) DEFAULT 'SMS' NOT NULL")
            if "delivery_status" not in verif_cols:
                conn.exec_driver_sql("ALTER TABLE verification_sessions ADD COLUMN delivery_status VARCHAR(30) DEFAULT 'NOT_CONFIGURED' NOT NULL")
            if "max_attempts" not in verif_cols:
                conn.exec_driver_sql("ALTER TABLE verification_sessions ADD COLUMN max_attempts INTEGER DEFAULT 3 NOT NULL")
            if "otp_code" not in verif_cols:
                conn.exec_driver_sql("ALTER TABLE verification_sessions ADD COLUMN otp_code VARCHAR(10)")

            # Daily sales summaries migration
            result_s = conn.exec_driver_sql("PRAGMA table_info(daily_sales_summaries)").fetchall()
            summary_cols = [r[1] for r in result_s]
            if "updated_at" not in summary_cols:
                conn.exec_driver_sql("ALTER TABLE daily_sales_summaries ADD COLUMN updated_at DATETIME")

            # Shopkeeper users migration
            result_u = conn.exec_driver_sql("PRAGMA table_info(shopkeeper_users)").fetchall()
            user_cols = [r[1] for r in result_u]
            if "firebase_uid" not in user_cols:
                conn.exec_driver_sql("ALTER TABLE shopkeeper_users ADD COLUMN firebase_uid VARCHAR(128)")
                conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_shopkeeper_firebase_uid ON shopkeeper_users(firebase_uid)")

            # Mark seeded initial customers as phone verified
            conn.exec_driver_sql("UPDATE customers SET is_phone_verified = 1, phone_verification_status = 'VERIFIED' WHERE phone IN ('9876543210', '9812345678', '9823456789')")
            conn.exec_driver_sql("UPDATE family_members SET is_phone_verified = 1, phone_verification_status = 'VERIFIED' WHERE primary_customer_id IN (SELECT id FROM customers WHERE phone IN ('9876543210', '9812345678', '9823456789'))")
            conn.commit()
    except Exception as e:
        print(f"[init_db] Column migration notice: {e}")

    seeded_products = 0
    seeded_customers = 0

    if seed:
        db = SessionLocal()
        try:
            # Seed Products
            existing_count = db.query(Product).count()
            if existing_count == 0:
                for item in INITIAL_PRODUCTS:
                    product = Product(
                        name=item["name"],
                        hindi_name=item.get("hindi_name"),
                        aliases=item.get("aliases", ""),
                        category=item["category"],
                        unit=item["unit"],
                        unit_price=float(item["unit_price"]),
                        stock_quantity=float(item.get("stock_quantity", 0.0)),
                        min_stock_threshold=float(item.get("min_stock_threshold", 10.0)),
                    )
                    db.add(product)
                db.commit()
                seeded_products = len(INITIAL_PRODUCTS)
                print(f"[init_db] Successfully seeded {seeded_products} Kirana products.")
            else:
                print(f"[init_db] Products table already contains {existing_count} records. Seeding skipped.")

            # Seed Customers & Family Members (Step 9)
            customer_count = db.query(Customer).count()
            if customer_count == 0:
                for cust_data in INITIAL_CUSTOMERS:
                    cust = Customer(
                        full_name=cust_data["full_name"],
                        phone=cust_data["phone"],
                        credit_limit=float(cust_data["credit_limit"]),
                        current_udhaar_balance=float(cust_data.get("current_udhaar_balance", 0.0)),
                        address_line=cust_data.get("address_line", cust_data.get("address", "Main Market")),
                        city=cust_data.get("city", "Chandigarh"),
                        state=cust_data.get("state", "Chandigarh"),
                        pincode=cust_data.get("pincode", "160017"),
                        country=cust_data.get("country", "India"),
                        address=cust_data.get("address", ""),
                        is_active=True,
                        is_phone_verified=True,
                        phone_verification_status="VERIFIED"
                    )
                    db.add(cust)
                    db.flush()
                    cust.customer_code = f"C-{cust.id:06d}"

                    for member_data in cust_data.get("family_members", []):
                        member = FamilyMember(
                            primary_customer_id=cust.id,
                            full_name=member_data["full_name"],
                            relation_type=member_data["relation_type"],
                            phone=member_data.get("phone"),
                            allowed_spending_limit=float(member_data["allowed_spending_limit"]) if member_data.get("allowed_spending_limit") else None,
                            is_active=True,
                            is_phone_verified=True,
                            phone_verification_status="VERIFIED"
                        )
                        db.add(member)

                    # If customer has initial balance, record an initial ledger entry
                    if cust.current_udhaar_balance > 0:
                        ledger_entry = UdhaarTransaction(
                            primary_customer_id=cust.id,
                            amount=cust.current_udhaar_balance,
                            transaction_type="DEBIT_PURCHASE",
                            balance_before=0.0,
                            balance_after=cust.current_udhaar_balance,
                            verified_by="INITIAL_BALANCE",
                            notes="Initial verified Udhaar balance record"
                        )
                        db.add(ledger_entry)

                db.commit()
                seeded_customers = len(INITIAL_CUSTOMERS)
                print(f"[init_db] Successfully seeded {seeded_customers} customer accounts with family members.")
            else:
                print(f"[init_db] Customers table already contains {customer_count} records. Seeding skipped.")

            # Seed default demo shopkeeper account if shopkeeper_users is empty
            user_count = db.query(ShopkeeperUser).count()
            if user_count == 0:
                print("[init_db] Seeding default demo shopkeeper account...")
                default_user = ShopkeeperUser(
                    full_name="Radheshyam Gupta",
                    phone="9876543210",
                    email="owner@apnakirana.com",
                    hashed_password=hash_password("Password@123"),
                    role="Shop Owner",
                    is_active=True
                )
                db.add(default_user)
                db.flush()

                default_shop = ShopProfile(
                    user_id=default_user.id,
                    shop_name="Apna Kirana Store",
                    shop_address="Main Market, Sector 4, New Delhi",
                    shop_phone="+91 98765 43210",
                    shop_email="owner@apnakirana.com",
                    gstin="07AAAAA0000A1Z5",
                    currency="INR (₹)",
                    timezone="Asia/Kolkata (IST)",
                    invoice_footer="Thank you for shopping with us! Visit again.",
                    default_measurement_unit="kg",
                    default_min_stock_threshold=10.0
                )
                db.add(default_shop)
                db.commit()
                print("[init_db] Default shopkeeper account seeded: Phone 9876543210, Password Password@123")
            else:
                print(f"[init_db] Shopkeeper users table already contains {user_count} accounts.")

        finally:
            db.close()

    return {
        "status": "success",
        "tables": list(Base.metadata.tables.keys()),
        "products_seeded": seeded_products,
        "customers_seeded": seeded_customers
    }


if __name__ == "__main__":
    result = init_db(seed=True)
    print("Database initialization complete:")
    print("Tables:", result["tables"])
    print(f"Products seeded: {result['products_seeded']}")
