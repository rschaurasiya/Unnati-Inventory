import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Date, Time,
    ForeignKey, Text, CheckConstraint, Index
)
from sqlalchemy.orm import relationship as orm_relationship
from backend.database import Base


class Product(Base):
    """
    Product Entity representing items sold in the kirana/grocery store.
    Supports English & Hindi naming, phonetic aliases, category, unit, pricing, and stock limits.
    """
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(120), nullable=False, index=True)
    hindi_name = Column(String(120), nullable=True)
    aliases = Column(String(255), nullable=False, default="")  # Comma-separated: "cheeni, chini, sugar"
    category = Column(String(60), nullable=False, index=True)
    unit = Column(String(20), nullable=False)  # kg, packet, litre, piece, dozen, etc.
    unit_price = Column(Float, nullable=False)
    stock_quantity = Column(Float, nullable=False, default=0.0)
    min_stock_threshold = Column(Float, nullable=False, default=10.0)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="chk_product_price_positive"),
        CheckConstraint("stock_quantity >= 0", name="chk_product_stock_non_negative"),
        CheckConstraint("min_stock_threshold >= 0", name="chk_product_threshold_non_negative"),
    )

    # Relationships
    bill_items = orm_relationship("BillItem", back_populates="product", cascade="all, delete-orphan")
    daily_summaries = orm_relationship("DailySalesSummary", back_populates="product", cascade="all, delete-orphan")
    historical_sales = orm_relationship("HistoricalSaleRecord", back_populates="product")
    forecast = orm_relationship("ProductForecast", back_populates="product", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Product(id={self.id}, name='{self.name}', price={self.unit_price}, stock={self.stock_quantity} {self.unit})>"


class Customer(Base):
    """
    Primary Customer / Account Holder (Mukhiya / Head of Family).
    Maintains phone identity, credit limit, and current outstanding Udhaar balance.
    """
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    full_name = Column(String(100), nullable=False, index=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    credit_limit = Column(Float, nullable=False, default=2000.0)
    current_udhaar_balance = Column(Float, nullable=False, default=0.0)
    customer_code = Column(String(20), unique=True, index=True, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_phone_verified = Column(Boolean, nullable=False, default=False)
    phone_verification_status = Column(String(30), nullable=False, default="UNVERIFIED")  # UNVERIFIED, OTP_REQUESTED, VERIFIED
    address_line = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    pincode = Column(String(10), nullable=True)
    country = Column(String(60), nullable=False, default="India")
    address = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("credit_limit >= 0", name="chk_customer_credit_limit_non_negative"),
        CheckConstraint("current_udhaar_balance >= 0", name="chk_customer_udhaar_non_negative"),
    )

    # Relationships
    family_members = orm_relationship("FamilyMember", back_populates="primary_customer", cascade="all, delete-orphan")
    bills = orm_relationship("Bill", back_populates="customer")
    udhaar_transactions = orm_relationship("UdhaarTransaction", back_populates="primary_customer")

    def __repr__(self):
        return f"<Customer(id={self.id}, name='{self.full_name}', phone='{self.phone}', balance={self.current_udhaar_balance})>"


class FamilyMember(Base):
    """
    Family member linked to a Primary Customer account.
    Permitted to make purchases under the family's Udhaar credit line.
    """
    __tablename__ = "family_members"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    primary_customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    full_name = Column(String(100), nullable=False)
    relation_type = Column(String(50), nullable=False)  # Son, Daughter, Spouse, Parent, Brother, etc.
    phone = Column(String(20), nullable=True)
    allowed_spending_limit = Column(Float, nullable=True)  # Optional per-member spending cap
    is_active = Column(Boolean, nullable=False, default=True)
    is_phone_verified = Column(Boolean, nullable=False, default=False)
    phone_verification_status = Column(String(30), nullable=False, default="UNVERIFIED")  # UNVERIFIED, OTP_REQUESTED, VERIFIED, INHERITED
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    # Relationships
    primary_customer = orm_relationship("Customer", back_populates="family_members")
    bills = orm_relationship("Bill", back_populates="family_member")
    udhaar_transactions = orm_relationship("UdhaarTransaction", back_populates="family_member")

    def __repr__(self):
        return f"<FamilyMember(id={self.id}, name='{self.full_name}', relation='{self.relation_type}')>"


class PhoneOTPVerification(Base):
    """
    Demo/Mock OTP verification session for customer and family member phone verification.
    """
    __tablename__ = "phone_otp_verifications"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    phone = Column(String(20), nullable=False, index=True)
    otp_code = Column(String(10), nullable=False)
    entity_type = Column(String(30), nullable=False)  # CUSTOMER, FAMILY_MEMBER
    entity_id = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, VERIFIED, EXPIRED, FAILED
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<PhoneOTPVerification(phone='{self.phone}', status='{self.status}')>"


class Bill(Base):
    """
    Sales Transaction / Bill generated via voice or manual entry.
    """
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    bill_number = Column(String(36), unique=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    family_member_id = Column(Integer, ForeignKey("family_members.id", ondelete="SET NULL"), nullable=True)
    subtotal = Column(Float, nullable=False, default=0.0)
    discount = Column(Float, nullable=False, default=0.0)
    tax = Column(Float, nullable=False, default=0.0)
    total_amount = Column(Float, nullable=False, default=0.0)
    payment_mode = Column(String(20), nullable=False, default="CASH")  # CASH, UPI, UDHAAR
    status = Column(String(30), nullable=False, default="DRAFT")  # DRAFT, PENDING_VERIFICATION, COMPLETED, CANCELLED
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    # Relationships
    customer = orm_relationship("Customer", back_populates="bills")
    family_member = orm_relationship("FamilyMember", back_populates="bills")
    items = orm_relationship("BillItem", back_populates="bill", cascade="all, delete-orphan")
    verification_session = orm_relationship("VerificationSession", back_populates="bill", uselist=False, cascade="all, delete-orphan")
    udhaar_transaction = orm_relationship("UdhaarTransaction", back_populates="bill", uselist=False)

    def __repr__(self):
        return f"<Bill(id={self.id}, number='{self.bill_number}', total={self.total_amount}, status='{self.status}')>"


class BillItem(Base):
    """
    Individual line item in a Bill.
    """
    __tablename__ = "bill_items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    bill_id = Column(Integer, ForeignKey("bills.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)
    unit_price = Column(Float, nullable=False)
    line_total = Column(Float, nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_bill_item_quantity_positive"),
        CheckConstraint("line_total >= 0", name="chk_bill_item_total_non_negative"),
    )

    # Relationships
    bill = orm_relationship("Bill", back_populates="items")
    product = orm_relationship("Product", back_populates="bill_items")


class VerificationSession(Base):
    """
    Security verification session (2FA Number Matching / OTP).
    Shopkeeper screen shows 3 candidate numbers; customer selects the target number on their device.
    """
    __tablename__ = "verification_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    bill_id = Column(Integer, ForeignKey("bills.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    session_token = Column(String(64), unique=True, nullable=False, index=True)
    target_number = Column(Integer, nullable=False)  # Secret correct number e.g. 54
    candidate_numbers = Column(String(50), nullable=False)  # Comma-separated: "32, 54, 89"
    otp_code = Column(String(10), nullable=True)  # Cryptographically secure 4-digit OTP for Udhaar
    verification_type = Column(String(30), nullable=False, default="NUMBER_MATCHING")  # NUMBER_MATCHING, OTP
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, VERIFIED, EXPIRED, FAILED
    delivery_channel = Column(String(20), nullable=False, default="SMS")  # SMS, WHATSAPP
    delivery_status = Column(String(30), nullable=False, default="NOT_CONFIGURED")  # NOT_CONFIGURED, SENT, DEMO
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)

    # Relationships
    bill = orm_relationship("Bill", back_populates="verification_session")


class UdhaarTransaction(Base):
    """
    Immutable ledger of credit transactions and debt settlements.
    """
    __tablename__ = "udhaar_transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    primary_customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    family_member_id = Column(Integer, ForeignKey("family_members.id", ondelete="SET NULL"), nullable=True)
    bill_id = Column(Integer, ForeignKey("bills.id", ondelete="SET NULL"), nullable=True, unique=True)
    amount = Column(Float, nullable=False)
    transaction_type = Column(String(30), nullable=False)  # DEBIT_PURCHASE, CREDIT_PAYMENT
    balance_before = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    verified_by = Column(String(50), nullable=False, default="PRIMARY_2FA")  # PRIMARY_2FA, SHOPKEEPER_OVERRIDE
    notes = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    # Relationships
    primary_customer = orm_relationship("Customer", back_populates="udhaar_transactions")
    family_member = orm_relationship("FamilyMember", back_populates="udhaar_transactions")
    bill = orm_relationship("Bill", back_populates="udhaar_transaction")


class DailySalesSummary(Base):
    """
    Aggregated daily sales records per product.
    Serves as the empirical time-series data foundation for demand forecasting and stockout analytics.
    """
    __tablename__ = "daily_sales_summaries"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    sale_date = Column(Date, nullable=False, index=True)
    total_quantity_sold = Column(Float, nullable=False, default=0.0)
    total_revenue = Column(Float, nullable=False, default=0.0)
    transaction_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=True)

    __table_args__ = (
        Index("idx_daily_sales_product_date", "product_id", "sale_date", unique=True),
    )

    # Relationships
    product = orm_relationship("Product", back_populates="daily_summaries")

    @property
    def total_sales_amount(self) -> float:
        """Alias for total_revenue matching Step 10 specification."""
        return self.total_revenue

    def __repr__(self):
        return f"<DailySalesSummary(product_id={self.product_id}, date={self.sale_date}, qty={self.total_quantity_sold}, rev={self.total_revenue})>"


class HistoricalImportBatch(Base):
    """
    Audit log and metadata for historical sales data imports.
    Tracks file provenance, processing stats, date ranges, and rollback status.
    """
    __tablename__ = "historical_import_batches"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    import_id = Column(String(64), unique=True, nullable=False, index=True)
    source_filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)  # CSV, XLSX, XLS
    file_size_bytes = Column(Integer, nullable=False, default=0)
    total_rows = Column(Integer, nullable=False, default=0)
    valid_rows = Column(Integer, nullable=False, default=0)
    invalid_rows = Column(Integer, nullable=False, default=0)
    warning_rows = Column(Integer, nullable=False, default=0)
    imported_records = Column(Integer, nullable=False, default=0)
    skipped_duplicates = Column(Integer, nullable=False, default=0)
    earliest_date = Column(Date, nullable=True)
    latest_date = Column(Date, nullable=True)
    usable_days_count = Column(Integer, nullable=False, default=0)
    status = Column(String(30), nullable=False, default="COMPLETED")  # STAGED, COMPLETED, ROLLED_BACK, FAILED
    column_mapping_json = Column(Text, nullable=True)
    validation_summary_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    # Relationships
    records = orm_relationship("HistoricalSaleRecord", back_populates="import_batch", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<HistoricalImportBatch(import_id='{self.import_id}', file='{self.source_filename}', records={self.imported_records}, status='{self.status}')>"


class HistoricalSaleRecord(Base):
    """
    Canonical row-level historical sales record.
    Unifies imported historical transactions into the same analytical foundation as completed bills.
    Excludes all customer personal identification (phone numbers, addresses, personal notes).
    """
    __tablename__ = "historical_sales_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    import_batch_id = Column(Integer, ForeignKey("historical_import_batches.id", ondelete="CASCADE"), nullable=True, index=True)
    import_id = Column(String(64), nullable=True, index=True)
    source_type = Column(String(20), nullable=False, default="IMPORTED")  # IMPORTED, POS
    source_file = Column(String(255), nullable=True)
    external_transaction_id = Column(String(100), nullable=True, index=True)
    row_fingerprint = Column(String(64), nullable=False, index=True)  # SHA-256 for deduplication
    sale_date = Column(Date, nullable=False, index=True)
    sale_time = Column(Time, nullable=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    raw_product_name = Column(String(200), nullable=True)
    quantity = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)
    unit_price = Column(Float, nullable=False)
    total_amount = Column(Float, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_hist_sale_qty_positive"),
        CheckConstraint("total_amount >= 0", name="chk_hist_sale_total_non_negative"),
        Index("idx_hist_sales_date_product", "sale_date", "product_id"),
        Index("idx_hist_sales_fingerprint", "row_fingerprint"),
    )

    # Relationships
    import_batch = orm_relationship("HistoricalImportBatch", back_populates="records")
    product = orm_relationship("Product", back_populates="historical_sales")

    def __repr__(self):
        return f"<HistoricalSaleRecord(id={self.id}, date={self.sale_date}, prod_id={self.product_id}, qty={self.quantity} {self.unit}, total={self.total_amount})>"


class ProductForecast(Base):
    """
    Demand forecasts, stockout risk analytics, and reorder intelligence per product.
    Computed deterministically from canonical daily sales history.
    Advisory only: does not alter product inventory or place supplier orders.
    """
    __tablename__ = "product_forecasts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    status = Column(String(30), nullable=False, default="ELIGIBLE")  # ELIGIBLE, INSUFFICIENT_DATA
    model_name = Column(String(50), nullable=False, default="BASELINE_EWMA")
    usable_days_count = Column(Integer, nullable=False, default=0)
    avg_daily_demand = Column(Float, nullable=False, default=0.0)
    total_7d_demand = Column(Float, nullable=False, default=0.0)
    total_30d_demand = Column(Float, nullable=False, default=0.0)
    current_stock = Column(Float, nullable=False, default=0.0)
    days_inventory_remaining = Column(Float, nullable=True)
    projected_stockout_date = Column(Date, nullable=True)
    risk_level = Column(String(30), nullable=False, default="SUFFICIENT")  # SUFFICIENT, LOW_STOCK, POTENTIAL_STOCKOUT, IMMEDIATE_ATTENTION, INSUFFICIENT_DATA
    suggested_reorder_qty = Column(Float, nullable=False, default=0.0)
    safety_stock = Column(Float, nullable=False, default=0.0)
    reorder_urgency = Column(String(30), nullable=False, default="OPTIMAL")  # OPTIMAL, RECOMMENDED, URGENT
    forecast_data_json = Column(Text, nullable=True)
    explanation = Column(Text, nullable=True)
    computed_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    # Relationships
    product = orm_relationship("Product", back_populates="forecast")

    def __repr__(self):
        return f"<ProductForecast(product_id={self.product_id}, status='{self.status}', model='{self.model_name}', 7d={self.total_7d_demand}, risk='{self.risk_level}')>"


class ShopkeeperUser(Base):
    """
    Shopkeeper / Store Admin User Account.
    Handles authentication, credentials, profile, and authorization.
    """
    __tablename__ = "shopkeeper_users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    full_name = Column(String(100), nullable=False, index=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=True, index=True)
    firebase_uid = Column(String(128), unique=True, nullable=True, index=True)
    hashed_password = Column(String(255), nullable=True)
    role = Column(String(50), nullable=False, default="Shop Owner")
    avatar_url = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    # Relationships
    shop_profile = orm_relationship("ShopProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    # Legacy: password_reset_tokens is decoupled from ShopkeeperUser (Firebase native auth handles password resets)

    def __repr__(self):
        return f"<ShopkeeperUser(id={self.id}, name='{self.full_name}', phone='{self.phone}', role='{self.role}')>"


class ShopProfile(Base):
    """
    Business & Store Details and Preferences associated with a Shopkeeper.
    Includes business contact, GSTIN, store branding, and localization preferences.
    """
    __tablename__ = "shop_profiles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("shopkeeper_users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    shop_name = Column(String(150), nullable=False, default="")
    shop_logo_url = Column(String(255), nullable=True)
    shop_address = Column(String(255), nullable=False, default="")
    gstin = Column(String(20), nullable=True)
    shop_phone = Column(String(20), nullable=False, default="")
    shop_email = Column(String(120), nullable=True)
    currency = Column(String(20), nullable=False, default="INR (₹)")
    timezone = Column(String(50), nullable=False, default="Asia/Kolkata (IST)")
    invoice_footer = Column(String(255), nullable=False, default="Thank you for shopping with us! Visit again.")
    default_measurement_unit = Column(String(20), nullable=False, default="kg")
    default_min_stock_threshold = Column(Float, nullable=False, default=10.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    # Relationships
    user = orm_relationship("ShopkeeperUser", back_populates="shop_profile")

    def __repr__(self):
        return f"<ShopProfile(shop_name='{self.shop_name}', user_id={self.user_id})>"


class PasswordResetToken(Base):
    """
    Legacy password reset verification session table (DEPRECATED).
    Retained solely for database schema backwards compatibility.
    Main authentication flow now uses Firebase Authentication email reset links.
    """
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("shopkeeper_users.id", ondelete="CASCADE"), nullable=False, index=True)
    phone_or_email = Column(String(120), nullable=False)
    otp_code = Column(String(10), nullable=False)
    reset_token = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, USED, EXPIRED
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    # Decoupled relationship (not used in main application flow)
    user = orm_relationship("ShopkeeperUser")

    def __repr__(self):
        return f"<PasswordResetToken(user_id={self.user_id}, status='{self.status}')>"


