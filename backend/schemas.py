"""
Pydantic Schemas for Request & Response Validation
Covers Products, Inventory Adjustments, and Low Stock Summaries.
"""
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator, computed_field


# --- Product Schemas ---

class ProductBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=120, description="Product commercial name")
    hindi_name: Optional[str] = Field(None, max_length=120, description="Product name in Hindi script")
    aliases: str = Field("", max_length=255, description="Spoken Hindi/Hinglish search keywords, comma-separated")
    category: str = Field("General", min_length=2, max_length=60, description="Product category")
    unit: str = Field("piece", min_length=1, max_length=20, description="Measurement unit (kg, packet, litre, piece, dozen)")
    unit_price: float = Field(..., gt=0.0, description="Price per unit in INR (must be positive)")
    min_stock_threshold: float = Field(10.0, ge=0.0, description="Threshold for low-stock trigger")

    @model_validator(mode="before")
    @classmethod
    def populate_unit_price(cls, values):
        if isinstance(values, dict):
            if "price" in values and ("unit_price" not in values or values["unit_price"] is None):
                values["unit_price"] = values["price"]
        return values

    @field_validator("name")
    @classmethod
    def validate_name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Product name cannot be empty")
        if len(v.strip()) < 2:
            raise ValueError("Product name must be at least 2 characters long")
        return v.strip()


class ProductCreate(ProductBase):
    stock_quantity: float = Field(0.0, ge=0.0, description="Initial stock quantity")


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    hindi_name: Optional[str] = Field(None, max_length=120)
    aliases: Optional[str] = Field(None, max_length=255)
    category: Optional[str] = Field(None, min_length=2, max_length=60)
    unit: Optional[str] = Field(None, min_length=1, max_length=20)
    unit_price: Optional[float] = Field(None, gt=0.0)
    stock_quantity: Optional[float] = Field(None, ge=0.0)
    min_stock_threshold: Optional[float] = Field(None, ge=0.0)
    is_active: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def populate_unit_price(cls, values):
        if isinstance(values, dict):
            if "price" in values and ("unit_price" not in values or values["unit_price"] is None):
                values["unit_price"] = values["price"]
        return values

    @field_validator("name")
    @classmethod
    def validate_update_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.strip() or len(v.strip()) < 2:
                raise ValueError("Product name must be at least 2 characters long")
            return v.strip()
        return v


class ProductPriceUpdate(BaseModel):
    unit_price: float = Field(..., gt=0.0, description="Updated price per unit in INR (must be positive)")

    @model_validator(mode="before")
    @classmethod
    def populate_unit_price(cls, values):
        if isinstance(values, dict):
            if "price" in values and ("unit_price" not in values or values["unit_price"] is None):
                values["unit_price"] = values["price"]
        return values


class ProductResponse(ProductBase):
    id: int
    stock_quantity: float
    is_low_stock: bool
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def price(self) -> float:
        return self.unit_price

    model_config = ConfigDict(from_attributes=True)


# --- Inventory Schemas ---

class StockAdjustRequest(BaseModel):
    product_id: int = Field(..., description="Target product ID")
    quantity_delta: Optional[float] = Field(None, description="Quantity to add (positive) or deduct (negative)")
    quantity: Optional[float] = Field(None, description="Quantity to add")
    quantity_added: Optional[float] = Field(None, description="Alternative positive quantity to add")
    adjustment: Optional[float] = Field(None, description="Alternative quantity delta")
    notes: Optional[str] = Field(None, max_length=255, description="Reason for stock change (e.g. Supplier restock, damaged)")
    reason: Optional[str] = Field(None, max_length=255, description="Alternative reason description")

    @model_validator(mode="after")
    def populate_defaults(self):
        if self.quantity_delta is None:
            if self.quantity is not None:
                self.quantity_delta = self.quantity
            elif self.adjustment is not None:
                self.quantity_delta = self.adjustment
            elif self.quantity_added is not None:
                self.quantity_delta = self.quantity_added
            else:
                self.quantity_delta = 0.0
        if self.notes is None and self.reason is not None:
            self.notes = self.reason
        return self


class StockAdjustResponse(BaseModel):
    product_id: int
    product_name: str
    previous_stock: float
    quantity_delta: float
    new_stock: float
    unit: str
    is_low_stock: bool
    notes: Optional[str] = None


class LowStockProductResponse(BaseModel):
    id: int
    name: str
    hindi_name: Optional[str] = None
    category: str
    unit: str
    stock_quantity: float
    min_stock_threshold: float
    shortage_quantity: float

    model_config = ConfigDict(from_attributes=True)


class InventorySummaryResponse(BaseModel):
    total_products: int
    total_inventory_value: float
    low_stock_count: int
    out_of_stock_count: int


# --- Voice & NLP Parsing Schemas ---

class VoiceParseRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500, description="Spoken or typed shopkeeper order sentence")
    language: Optional[str] = Field("hinglish", description="Voice input language: english, hinglish, or hindi")


class ParsedItemResponse(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    matched_alias: Optional[str] = None
    raw_input_phrase: str
    raw_item_name: str
    quantity: float
    unit: str
    unit_price: float
    line_total: float
    confidence: float
    status: str  # MATCHED, AMBIGUOUS, UNMATCHED
    match_status: Optional[str] = "MATCHED"
    unmatched_reason: Optional[str] = None


class VoiceParseResponse(BaseModel):
    raw_text: str
    items: List[ParsedItemResponse]
    matched_count: int
    unmatched_count: int
    ambiguous_count: int
    total_estimated_amount: float


# --- POS Draft Bill Schemas ---

class DraftBillItem(BaseModel):
    product_id: Optional[int] = None
    product_name: str
    raw_item_name: Optional[str] = None
    quantity: float = Field(..., gt=0.0)
    unit: str
    unit_price: float = Field(0.0, ge=0.0)
    line_total: float = Field(0.0, ge=0.0)
    status: str = "MATCHED"  # MATCHED, AMBIGUOUS, UNMATCHED
    match_status: Optional[str] = "MATCHED"
    unmatched_reason: Optional[str] = None


class DraftBillRequest(BaseModel):
    text: Optional[str] = Field(None, max_length=500, description="Voice transcript or typed order")
    items: Optional[List[DraftBillItem]] = None
    language: Optional[str] = Field("hinglish", description="Voice input language: english, hinglish, or hindi")


class DraftBillRecalculateRequest(BaseModel):
    items: List[DraftBillItem]


class DraftBillResponse(BaseModel):
    draft_id: str
    raw_text: Optional[str] = None
    items: List[DraftBillItem]
    subtotal: float
    tax: float
    total_amount: float
    matched_items_count: int
    unmatched_items_count: int
    status: str = "DRAFT"
    notes: Optional[str] = None


# --- Finalized Bill & Transaction Schemas ---

class FinalizeBillItem(BaseModel):
    product_id: int = Field(..., description="Target catalog product ID")
    quantity: float = Field(..., gt=0.0, description="Quantity to purchase")


class FinalizeBillRequest(BaseModel):
    items: List[FinalizeBillItem] = Field(..., min_length=1, description="List of items to finalize")
    payment_mode: str = Field("CASH", pattern="^(CASH|UPI|UDHAAR)$", description="Payment mode")
    idempotency_key: Optional[str] = Field(None, max_length=64, description="Unique client key preventing double-charge")
    customer_id: Optional[int] = Field(None, description="Primary customer ID (required for UDHAAR)")
    family_member_id: Optional[int] = Field(None, description="Optional family member purchasing on behalf of primary customer")
    notes: Optional[str] = Field(None, max_length=255)


class FinalizedBillItemResponse(BaseModel):
    product_id: int
    product_name: str
    quantity: float
    unit: str
    unit_price: float
    line_total: float

    model_config = ConfigDict(from_attributes=True)


class LowStockAlert(BaseModel):
    product_id: int
    product_name: str
    current_stock: float
    min_stock_threshold: float
    unit: str


class FinalizedBillResponse(BaseModel):
    id: int
    bill_number: str
    subtotal: float
    discount: float
    tax: float
    total_amount: float
    payment_mode: str
    status: str
    created_at: datetime
    items: List[FinalizedBillItemResponse]
    low_stock_alerts: List[LowStockAlert]
    is_duplicate_replay: bool = False
    customer_id: Optional[int] = None
    customer_code: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone_masked: Optional[str] = None
    is_phone_verified: Optional[bool] = None
    family_member_id: Optional[int] = None
    buyer_name: Optional[str] = None
    notification_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Verification & 2FA Schemas (Step 7)
# ==============================================================================

class CreateVerificationSessionRequest(BaseModel):
    bill_id: int = Field(..., description="ID of the completed bill to verify")
    expiry_seconds: int = Field(default=180, ge=30, le=600, description="Session expiry duration in seconds")
    delivery_channel: str = Field("SMS", pattern="^(SMS|WHATSAPP)$", description="Delivery channel for challenge: SMS or WHATSAPP")
    verification_type: Optional[str] = Field(None, description="Verification type: OTP (default for Udhaar) or NUMBER_MATCHING")


class VerificationSessionResponse(BaseModel):
    session_id: int
    session_token: str
    bill_id: int
    bill_number: str
    bill_total: float
    verification_type: str
    status: str  # PENDING, VERIFIED, EXPIRED, FAILED
    challenge_numbers: List[int] = Field(default=[], description="The challenge numbers if NUMBER_MATCHING")
    otp_length: int = Field(default=4, description="Length of OTP (4 digits)")
    demo_otp: Optional[str] = Field(None, description="Mock/simulated OTP for testing without log exposure")
    attempts: int
    expires_at: datetime
    expires_in_seconds: int
    created_at: datetime
    verified_at: Optional[datetime] = None
    # Step 9 context fields
    payment_mode: Optional[str] = None
    customer_id: Optional[int] = None
    customer_code: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone_masked: Optional[str] = None
    is_phone_verified: Optional[bool] = None
    family_member_id: Optional[int] = None
    buyer_name: Optional[str] = None
    notification_message: Optional[str] = None
    delivery_channel: str = "SMS"
    delivery_status: str = "NOT_CONFIGURED"
    channel_status_note: str = "SMS Verification — Demo/Not Configured"
    delivery_message_preview: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SubmitVerificationRequest(BaseModel):
    session_id: Optional[int] = Field(None, description="Verification session ID")
    session_token: Optional[str] = Field(None, description="Verification session token (alternative to session_id)")
    bill_id: Optional[int] = Field(None, description="Optional bill ID to verify transaction association")
    customer_id: Optional[int] = Field(None, description="Optional customer ID to verify customer binding")
    otp: Optional[str] = Field(None, description="The 4-digit verification OTP entered by customer")
    otp_code: Optional[str] = Field(None, description="Alias for otp")
    selected_number: Optional[int] = Field(None, description="The challenge number selected by customer (for legacy NUMBER_MATCHING)")


class VerificationResultResponse(BaseModel):
    session_id: int
    bill_id: int
    bill_number: str
    success: bool
    status: str  # VERIFIED, FAILED, EXPIRED
    message: str
    verified_at: Optional[datetime] = None
    # Step 9 context fields
    payment_mode: Optional[str] = None
    udhaar_balance_after: Optional[float] = None
    low_stock_alerts: List[LowStockAlert] = []

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Digital Receipt & Delivery Preparation Schemas (Step 8)
# ==============================================================================

class ReceiptItemResponse(BaseModel):
    product_id: int
    product_name: str
    quantity: float
    unit: str
    unit_price: float
    line_total: float

    model_config = ConfigDict(from_attributes=True)


class DigitalReceiptResponse(BaseModel):
    receipt_id: str
    shop_name: str
    shop_address: Optional[str] = None
    shop_phone: Optional[str] = None
    shop_logo_url: Optional[str] = None
    gstin: Optional[str] = None
    invoice_footer: Optional[str] = None
    currency: Optional[str] = None
    bill_id: int
    bill_number: str
    created_at: datetime
    payment_mode: str
    status: str
    is_verified: bool
    verified_at: Optional[datetime] = None
    items: List[ReceiptItemResponse]
    subtotal: float
    discount: float
    tax: float
    total_amount: float
    formatted_text_receipt: str
    customer_id: Optional[int] = None
    customer_code: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone_masked: Optional[str] = None
    buyer_name: Optional[str] = None
    outstanding_balance: Optional[float] = None
    udhaar_transaction_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class ReceiptDeliveryRequest(BaseModel):
    bill_id: int = Field(..., description="ID of the verified bill")
    customer_phone: Optional[str] = Field(None, description="Optional customer 10-digit or international mobile number")


class WhatsAppDeliveryPreparation(BaseModel):
    customer_phone: Optional[str] = None
    formatted_message: str
    click_to_chat_url: str
    prepared: bool = True


class SMSDeliveryPreparation(BaseModel):
    customer_phone: Optional[str] = None
    sms_text: str
    char_count: int
    is_mock: bool = True
    delivery_status: str = Field(default="NOT_CONFIGURED", description="MOCK_PREVIEW or NOT_CONFIGURED")
    note: str = Field(default="SMS Preview / Simulation - No external SMS gateway configured.", description="Gateway status explanation")


class ReceiptDeliveryResponse(BaseModel):
    receipt: DigitalReceiptResponse
    whatsapp: WhatsAppDeliveryPreparation
    sms: SMSDeliveryPreparation


# ==============================================================================
# Customer Accounts, Family Members & Udhaar Ledger Schemas (Step 9 & Hardening)
# ==============================================================================

import re
from pydantic import field_validator


def _validate_10_digit_phone(val: Optional[str], required: bool = True) -> Optional[str]:
    """Strictly validates 10-digit phone number format."""
    if val is None or str(val).strip() == "":
        if required:
            raise ValueError("Phone number is required and cannot be empty.")
        return None
    cleaned = re.sub(r"[\s\-\(\)]", "", str(val).strip())
    if not cleaned:
        if required:
            raise ValueError("Phone number cannot be empty.")
        return None
    if not cleaned.isdigit():
        raise ValueError(f"Phone number must contain digits only. Received: '{val}'")
    if len(cleaned) != 10:
        raise ValueError(f"Phone number must be exactly 10 digits. Received {len(cleaned)} digits: '{val}'")
    return cleaned


ALLOWED_COUNTRIES = ["India", "Nepal", "Bangladesh", "Sri Lanka", "USA", "UAE", "Canada"]
COUNTRY_MAP = {c.lower(): c for c in ALLOWED_COUNTRIES}


def _validate_pincode(val: Optional[str], required: bool = True, country: Optional[str] = "India") -> Optional[str]:
    """Validates postal / PIN code format. Strictly 6 digits for India, 4-10 alphanumeric characters for international."""
    if val is None or str(val).strip() == "":
        if required:
            raise ValueError("PIN code is mandatory and cannot be empty.")
        return None
    cleaned = str(val).strip()
    if not cleaned:
        if required:
            raise ValueError("PIN code cannot be empty.")
        return None

    country_norm = (country or "India").strip().lower()
    if country_norm == "india":
        if not cleaned.isdigit():
            raise ValueError(f"PIN code must contain digits only. Received: '{val}'")
        if len(cleaned) != 6:
            raise ValueError(f"PIN code must contain exactly 6 digits. Received {len(cleaned)} digits: '{val}'")
    else:
        alphanumeric_count = sum(1 for c in cleaned if c.isalnum())
        if not re.match(r"^[A-Za-z0-9\s\-]{3,10}$", cleaned) or alphanumeric_count < 3:
            raise ValueError(f"Postal code for {country or 'selected country'} must be 4 to 10 alphanumeric characters. Received: '{val}'")
    return cleaned


def _validate_non_empty_str(val: Optional[str], field_name: str, required: bool = True) -> Optional[str]:
    """Validates non-empty string, trimming whitespace and rejecting blank values."""
    if val is None or str(val).strip() == "":
        if required:
            raise ValueError(f"{field_name} is mandatory and cannot be empty.")
        return None
    return str(val).strip()


class FamilyMemberCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    relation_type: str = Field(..., description="e.g. Son, Daughter, Spouse, Parent, Brother, etc.")
    phone: Optional[str] = Field(None, description="Optional 10-digit contact number")
    allowed_spending_limit: Optional[float] = Field(None, ge=0.0, description="Optional cap on individual purchases")

    @field_validator("phone")
    @classmethod
    def validate_member_phone(cls, v: Optional[str]) -> Optional[str]:
        return _validate_10_digit_phone(v, required=False)


class FamilyMemberResponse(BaseModel):
    id: int
    primary_customer_id: int
    full_name: str
    relation_type: str
    phone: Optional[str] = None
    allowed_spending_limit: Optional[float] = None
    is_active: bool
    is_phone_verified: bool = False
    phone_verification_status: str = "UNVERIFIED"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomerCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    phone: str = Field(..., description="Exactly 10-digit primary contact number")
    credit_limit: float = Field(2000.0, ge=0.0)
    address_line: str = Field(..., description="Street address or house number")
    city: str = Field(..., description="City name")
    state: str = Field(..., description="State name")
    pincode: str = Field(..., description="PIN or Postal code (6 digits for India, 4-10 alphanumeric for international)")
    country: str = Field("India", description="Country name")
    address: Optional[str] = Field(None, max_length=255)
    is_phone_verified: bool = Field(False, description="Initial phone verification status")

    @field_validator("phone")
    @classmethod
    def validate_customer_phone(cls, v: str) -> str:
        res = _validate_10_digit_phone(v, required=True)
        assert res is not None
        return res

    @field_validator("address_line")
    @classmethod
    def validate_addr_line(cls, v: str) -> str:
        res = _validate_non_empty_str(v, "Address", required=True)
        assert res is not None
        return res

    @field_validator("city")
    @classmethod
    def validate_city(cls, v: str) -> str:
        res = _validate_non_empty_str(v, "City", required=True)
        assert res is not None
        return res

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        res = _validate_non_empty_str(v, "State", required=True)
        assert res is not None
        return res

    @field_validator("country")
    @classmethod
    def validate_country(cls, v: str) -> str:
        res = _validate_non_empty_str(v, "Country", required=True)
        assert res is not None
        cleaned_key = res.strip().lower()
        if cleaned_key not in COUNTRY_MAP:
            raise ValueError(f"Country must be one of: {', '.join(ALLOWED_COUNTRIES)}. Received: '{v}'")
        return COUNTRY_MAP[cleaned_key]

    @field_validator("pincode")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        if v is None or str(v).strip() == "":
            raise ValueError("PIN code is mandatory and cannot be empty.")
        cleaned = str(v).strip()
        if not cleaned:
            raise ValueError("PIN code cannot be empty.")
        return cleaned

    @model_validator(mode="after")
    def validate_postal_code_for_country(self) -> 'CustomerCreate':
        _validate_pincode(self.pincode, required=True, country=self.country)
        return self


class CustomerUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    phone: Optional[str] = Field(None, description="Optional updated 10-digit phone number")
    credit_limit: Optional[float] = Field(None, ge=0.0)
    address_line: Optional[str] = Field(None, max_length=255)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    pincode: Optional[str] = Field(None, max_length=10)
    country: Optional[str] = Field(None, max_length=60)
    address: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None

    @field_validator("phone")
    @classmethod
    def validate_customer_update_phone(cls, v: Optional[str]) -> Optional[str]:
        return _validate_10_digit_phone(v, required=False)

    @field_validator("country")
    @classmethod
    def validate_customer_update_country(cls, v: Optional[str]) -> Optional[str]:
        if v is None or str(v).strip() == "":
            return None
        cleaned_key = str(v).strip().lower()
        if cleaned_key not in COUNTRY_MAP:
            raise ValueError(f"Country must be one of: {', '.join(ALLOWED_COUNTRIES)}. Received: '{v}'")
        return COUNTRY_MAP[cleaned_key]

    @field_validator("pincode")
    @classmethod
    def validate_customer_update_pincode(cls, v: Optional[str]) -> Optional[str]:
        if v is None or str(v).strip() == "":
            return None
        cleaned = str(v).strip()
        if not cleaned:
            return None
        return cleaned

    @model_validator(mode="after")
    def validate_update_postal_code(self) -> 'CustomerUpdate':
        if self.pincode is not None:
            _validate_pincode(self.pincode, required=True, country=self.country or "India")
        return self


# --- Phone OTP Verification Schemas ---

class PhoneOTPRequest(BaseModel):
    notes: Optional[str] = Field(None, max_length=255)


class PhoneOTPVerifyRequest(BaseModel):
    otp_code: str = Field(..., min_length=4, max_length=10, description="Verification OTP code")


class PhoneOTPResponse(BaseModel):
    success: bool
    phone: str
    status: str  # PENDING, VERIFIED, EXPIRED, FAILED
    message: str
    is_demo: bool = True
    demo_otp: Optional[str] = None
    expires_in_seconds: Optional[int] = None
    attempts_remaining: Optional[int] = None


class UdhaarTransactionResponse(BaseModel):
    id: int
    customer_code: Optional[str] = None
    primary_customer_id: int
    primary_customer_name: Optional[str] = None
    family_member_id: Optional[int] = None
    family_member_name: Optional[str] = None
    bill_id: Optional[int] = None
    bill_number: Optional[str] = None
    amount: float
    transaction_type: str  # DEBIT_PURCHASE, CREDIT_PAYMENT
    balance_before: float
    balance_after: float
    verified_by: str
    notes: Optional[str] = None
    created_at: datetime
    items: List[FinalizedBillItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class CustomerResponse(BaseModel):
    id: int
    customer_code: Optional[str] = None
    full_name: str
    phone: str
    credit_limit: float
    current_udhaar_balance: float
    available_credit: float
    is_active: bool
    is_phone_verified: bool = False
    phone_verification_status: str = "UNVERIFIED"
    address_line: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    country: Optional[str] = "India"
    address: Optional[str] = None
    created_at: datetime
    family_members: List[FamilyMemberResponse] = []

    model_config = ConfigDict(from_attributes=True)


class CustomerDetailResponse(CustomerResponse):
    transactions: List[UdhaarTransactionResponse] = []


class UdhaarSettlementRequest(BaseModel):
    amount: float = Field(..., gt=0.0, description="Repayment amount")
    payment_mode: str = Field("CASH", pattern="^(CASH|UPI)$", description="Repayment method")
    notes: Optional[str] = Field(None, max_length=255)


class UdhaarSettlementResponse(BaseModel):
    success: bool
    customer_id: int
    customer_name: str
    settled_amount: float
    previous_balance: float
    new_balance: float
    transaction: UdhaarTransactionResponse
    message: str


class CustomerImportResponse(BaseModel):
    status: str = Field(..., description="Overall operation status (e.g. 'success')")
    total_processed: int = Field(..., description="Total rows parsed from the uploaded file")
    successfully_added: int = Field(..., description="Total new customers inserted into database")
    skipped_duplicates: int = Field(..., description="Count of duplicate phone records skipped")
    errors: List[str] = Field(default_factory=list, description="Row-by-row validation issues or notes")


# --- Duplicate Customer Cleanup Schemas ---

class DuplicateCustomerInfo(BaseModel):
    """Lightweight customer snapshot used inside a duplicate group."""
    id: int
    customer_code: Optional[str] = None
    full_name: str
    phone: str
    credit_limit: float
    current_udhaar_balance: float
    is_active: bool
    is_phone_verified: bool = False
    has_bills: bool = False
    has_udhaar_transactions: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DuplicateGroupResponse(BaseModel):
    """A group of customers sharing the same name (case-insensitive)."""
    duplicate_name: str
    count: int
    safe_to_delete_ids: List[int]   # IDs with zero balance and no history
    keep_id: Optional[int] = None   # Oldest / primary record to retain
    members: List[DuplicateCustomerInfo]


class DuplicatesListResponse(BaseModel):
    total_duplicate_groups: int
    total_duplicate_accounts: int
    safe_to_delete_count: int
    groups: List[DuplicateGroupResponse]


class DuplicateCleanupRequest(BaseModel):
    """Optional list of customer IDs to delete; if omitted, all safe duplicates are deleted."""
    customer_ids: Optional[List[int]] = Field(None, description="Specific IDs to delete. Omit to auto-delete all safe duplicates.")
    dry_run: bool = Field(False, description="If true, simulate without actually deleting.")


class DuplicateCleanupResponse(BaseModel):
    success: bool
    dry_run: bool
    deleted_count: int
    skipped_count: int
    deleted_ids: List[int]
    skipped_ids: List[int]
    skipped_reasons: Dict[str, str]
    message: str


# --- Step 10: Sales History & Daily Aggregation Schemas ---

class DailySalesItem(BaseModel):
    product_id: int
    product_name: str
    category: Optional[str] = None
    unit: str
    unit_price: float
    total_quantity_sold: float
    total_sales_amount: float
    transaction_count: int


class DailySalesSummaryResponse(BaseModel):
    sale_date: str
    total_revenue: float
    total_quantity_sold: float
    transaction_count: int
    items: List[DailySalesItem] = []


class SalesHistoryPoint(BaseModel):
    sale_date: str
    quantity_sold: float
    sales_amount: float
    transaction_count: int


class ProductSalesHistoryResponse(BaseModel):
    product_id: int
    product_name: str
    category: Optional[str] = None
    unit: str
    unit_price: float
    start_date: str
    end_date: str
    total_quantity_sold: float
    total_sales_amount: float
    total_transactions: int
    active_days_count: int
    average_daily_quantity: float
    history: List[SalesHistoryPoint] = []


class SalesDateRangeSummaryResponse(BaseModel):
    start_date: str
    end_date: str
    total_revenue: float
    total_quantity_sold: float
    total_transactions: int
    distinct_products_count: int
    usable_days_count: int
    daily_summaries: List[DailySalesSummaryResponse] = []


class CompletedSaleItemResponse(BaseModel):
    bill_id: int
    bill_number: str
    product_id: int
    product_name: str
    category: Optional[str] = None
    quantity: float
    unit: str
    unit_price: float
    line_total: float
    payment_mode: str
    status: Optional[str] = "Completed"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductSufficiencyDetail(BaseModel):
    product_id: int
    product_name: str
    category: Optional[str] = None
    unit: str
    usable_days_count: int
    status: str  # SUFFICIENT_DATA or INSUFFICIENT_DATA
    earliest_date: Optional[str] = None
    latest_date: Optional[str] = None
    total_quantity_sold: float
    total_sales_amount: float


class DataSufficiencyResponse(BaseModel):
    status: str  # SUFFICIENT_DATA or INSUFFICIENT_DATA
    usable_days_count: int
    min_days_required: int = 7
    earliest_date: Optional[str] = None
    latest_date: Optional[str] = None
    total_active_products: int
    sufficient_products_count: int
    insufficient_products_count: int
    message: str
    products: List[ProductSufficiencyDetail] = []


class RebuildHistoryResponse(BaseModel):
    status: str
    message: str
    dates_rebuilt_count: int
    summaries_created_or_updated: int


class SeedDemoDataResponse(BaseModel):
    status: str
    message: str
    days_seeded: int
    bills_created: int
    items_created: int
    inventory_unaltered: bool
    earliest_date: str
    latest_date: str


# ============================================================
# Historical Sales Import & Normalization Pipeline Schemas
# ============================================================

class ValidationIssue(BaseModel):
    row: int
    field: str
    value: Optional[Any] = None
    message: str
    severity: str = "ERROR"  # ERROR or WARNING


class NormalizedSalePreview(BaseModel):
    row: int
    sale_date: str
    raw_product_name: str
    matched_product_id: Optional[int] = None
    matched_product_name: Optional[str] = None
    match_confidence: float = 1.0
    match_type: str = "EXACT"  # EXACT, ALIAS, HINDI, NORMALIZED, FUZZY, MANUAL, UNMATCHED
    quantity: float
    unit: str
    unit_price: float
    total_amount: float
    transaction_id: Optional[str] = None
    warnings: List[str] = []


class ValidationSummary(BaseModel):
    total_rows: int
    valid_rows: int
    warning_rows: int
    invalid_rows: int
    earliest_date: Optional[str] = None
    latest_date: Optional[str] = None
    usable_days_count: int = 0


class UnmatchedProductInfo(BaseModel):
    raw_name: str
    occurrence_count: int
    suggested_product_id: Optional[int] = None
    suggested_product_name: Optional[str] = None
    confidence: float = 0.0


class ImportAnalyzeResponse(BaseModel):
    status: str  # READY, AMBIGUOUS_COLUMNS, MISSING_REQUIRED_COLUMNS, INVALID_FILE, NO_VALID_DATA
    import_id: str
    filename: str
    file_type: str
    file_size_bytes: int
    total_rows: int
    total_columns: int
    detected_columns: List[str]
    detected_mapping: Dict[str, Optional[str]]
    ambiguous_columns: Dict[str, List[str]] = {}
    missing_required_columns: List[str] = []
    ignored_columns: List[str] = []
    validation_summary: ValidationSummary
    sample_preview: List[NormalizedSalePreview] = []
    unmatched_products: List[UnmatchedProductInfo] = []
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []
    is_ready_for_import: bool
    message: str


class ConfirmImportRequest(BaseModel):
    import_id: str
    column_mapping: Optional[Dict[str, str]] = None
    product_mappings: Optional[Dict[str, int]] = None
    skip_unmatched_products: bool = True
    import_mode: str = "SKIP_INVALID"  # SKIP_INVALID, REJECT_IF_ANY_INVALID
    notes: Optional[str] = None


class ConfirmImportResponse(BaseModel):
    status: str  # SUCCESS, ROLLED_BACK, FAILED
    import_id: str
    message: str
    total_rows_processed: int
    imported_records_count: int
    skipped_duplicate_count: int
    skipped_invalid_count: int
    earliest_date: Optional[str] = None
    latest_date: Optional[str] = None
    usable_days_count: int
    forecasting_status: str  # SUFFICIENT_DATA or INSUFFICIENT_DATA
    min_days_required: int = 7
    active_products_updated_count: int


class ImportBatchSummaryResponse(BaseModel):
    id: int
    import_id: str
    source_filename: str
    file_type: str
    file_size_bytes: int
    total_rows: int
    imported_records: int
    skipped_duplicates: int
    invalid_rows: int
    warning_rows: int
    earliest_date: Optional[date] = None
    latest_date: Optional[date] = None
    usable_days_count: int
    status: str
    created_at: datetime
    confirmed_at: Optional[datetime] = None
    rolled_back_at: Optional[datetime] = None
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class RollbackImportResponse(BaseModel):
    status: str
    import_id: str
    message: str
    records_deactivated_count: int
    dates_recalculated_count: int


# ==============================================================================
# Step 11: Demand Forecasting & Stock/Reorder Intelligence Schemas
# ==============================================================================

class DailyForecastPoint(BaseModel):
    date: str = Field(..., description="Forecast date (YYYY-MM-DD)")
    day_of_week: str = Field(..., description="Day name, e.g. Monday")
    forecast_quantity: float = Field(..., ge=0.0, description="Predicted sales quantity")
    lower_bound: float = Field(..., ge=0.0, description="Lower prediction interval (95%)")
    upper_bound: float = Field(..., ge=0.0, description="Upper prediction interval (95%)")


class HistoricalDemandPoint(BaseModel):
    date: str = Field(..., description="Historical sale date (YYYY-MM-DD)")
    day_of_week: str = Field(..., description="Day name, e.g. Monday")
    actual_quantity: float = Field(..., ge=0.0, description="Historical recorded quantity sold")


class ModelBacktestMetric(BaseModel):
    model_name: str
    mae: float = Field(..., ge=0.0, description="Mean Absolute Error")
    rmse: float = Field(..., ge=0.0, description="Root Mean Squared Error")
    wape: float = Field(..., ge=0.0, description="Weighted Absolute Percentage Error")
    is_selected: bool = False


class StockoutRiskAnalysis(BaseModel):
    current_stock: float = Field(..., ge=0.0)
    expected_7d_demand: float = Field(..., ge=0.0)
    expected_30d_demand: float = Field(..., ge=0.0)
    avg_daily_demand: float = Field(..., ge=0.0)
    days_inventory_remaining: Optional[float] = None
    projected_stockout_date: Optional[str] = None
    potential_7d_shortfall: float = Field(0.0, ge=0.0)
    risk_level: str = Field(..., description="IMMEDIATE_ATTENTION, POTENTIAL_STOCKOUT, LOW_STOCK, SUFFICIENT, INSUFFICIENT_DATA")
    risk_label: str
    explanation: str


class ReorderRecommendation(BaseModel):
    current_stock: float = Field(..., ge=0.0)
    expected_7d_demand: float = Field(..., ge=0.0)
    lead_time_days: int = Field(3, description="Estimated supplier replenishment lead time")
    buffer_days: int = Field(2, description="Days of safety stock buffer")
    safety_stock: float = Field(..., ge=0.0)
    suggested_minimum_stock: float = Field(..., ge=0.0)
    suggested_reorder_quantity: float = Field(..., ge=0.0)
    urgency: str = Field(..., description="OPTIMAL, RECOMMENDED, URGENT")
    formula_breakdown: str
    advisory_notice: str = "Advisory only: No automated orders placed, no inventory altered."


class DayOfWeekDemand(BaseModel):
    day_name: str
    weekday_idx: int
    avg_quantity: float
    factor: float


class SeasonalityAnalysis(BaseModel):
    status: str  # "SEASONALITY_AVAILABLE" or "SEASONALITY_INSUFFICIENT_DATA"
    is_supported: bool
    min_days_required: int = 14
    history_days_available: int
    weekday_breakdown: List[DayOfWeekDemand] = []
    pattern_summary: str


class ProductForecastDetailResponse(BaseModel):
    product_id: int
    product_name: str
    category: str
    unit: str
    current_stock: float
    unit_price: float
    status: str = Field(..., description="ELIGIBLE or INSUFFICIENT_DATA")
    eligibility_status: Optional[str] = None
    usable_days_count: int
    min_days_required: int = 7
    earliest_date: Optional[str] = None
    latest_date: Optional[str] = None
    selected_model: Optional[str] = None
    model_metrics: List[ModelBacktestMetric] = []
    total_7d_demand: float = 0.0
    total_30d_demand: float = 0.0
    avg_daily_demand: float = 0.0
    forecast_7d: List[DailyForecastPoint] = []
    forecast_30d: List[DailyForecastPoint] = []
    recent_history: List[HistoricalDemandPoint] = []
    stockout_risk: StockoutRiskAnalysis
    reorder_recommendation: ReorderRecommendation
    seasonality_analysis: Optional[SeasonalityAnalysis] = None
    explanation: str
    computed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductForecastSummaryItem(BaseModel):
    product_id: int
    product_name: str
    category: str
    unit: str
    current_stock: float
    unit_price: float
    usable_days_count: int
    status: str  # ELIGIBLE or INSUFFICIENT_DATA
    selected_model: Optional[str] = None
    total_7d_demand: float = 0.0
    total_30d_demand: float = 0.0
    avg_daily_demand: float = 0.0
    days_inventory_remaining: Optional[float] = None
    projected_stockout_date: Optional[str] = None
    potential_7d_shortfall: float = 0.0
    risk_level: str
    suggested_reorder_qty: float = 0.0
    reorder_urgency: str
    earliest_date: Optional[str] = None
    latest_date: Optional[str] = None


class ForecastOverviewResponse(BaseModel):
    total_products: int
    eligible_products_count: int
    insufficient_products_count: int
    immediate_attention_count: int
    potential_stockout_count: int
    low_stock_count: int
    sufficient_stock_count: int
    total_reorder_units_needed: float
    last_refresh_at: datetime


class ForecastListResponse(BaseModel):
    overview: ForecastOverviewResponse
    products: List[ProductForecastSummaryItem]


class RefreshForecastResponse(BaseModel):
    status: str
    message: str
    products_processed: int
    eligible_count: int
    refreshed_at: datetime


# ==============================================================================
# Step 11A: Data Sufficiency Validation Schemas
# ==============================================================================

class ProductDataSufficiencyResponse(BaseModel):
    product_id: int
    product_name: Optional[str] = None
    historical_days: int
    earliest_date: Optional[str] = None
    latest_date: Optional[str] = None
    eligibility_status: str  # "eligible" or "insufficient_data"
    eligibility_reason: str

    model_config = ConfigDict(from_attributes=True)


class StoreDataSufficiencySummaryResponse(BaseModel):
    total_products: int
    eligible_count: int
    insufficient_count: int
    min_days_required: int = 7
    products: List[ProductDataSufficiencyResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Authentication, Profile & Settings Schemas
# ==============================================================================

class UserRegisterRequest(BaseModel):
    full_name: str
    phone: str
    email: Optional[str] = None
    password: str
    confirm_password: str
    shop_name: Optional[str] = "Apna Kirana Store"
    role: Optional[str] = "Shop Owner"
    firebase_uid: Optional[str] = None


class UserLoginRequest(BaseModel):
    identifier: str  # Phone, Email, or Username
    password: str


class FirebaseSyncRequest(BaseModel):
    firebase_uid: str
    email: Optional[str] = None
    phone: Optional[str] = None
    display_name: Optional[str] = None
    photo_url: Optional[str] = None
    id_token: Optional[str] = None


class ShopProfileResponse(BaseModel):
    id: int
    shop_name: str
    shop_logo_url: Optional[str] = None
    shop_address: str
    gstin: Optional[str] = None
    shop_phone: str
    shop_email: Optional[str] = None
    currency: str
    timezone: str
    invoice_footer: str
    default_measurement_unit: str
    default_min_stock_threshold: float

    model_config = ConfigDict(from_attributes=True)


class UserProfileResponse(BaseModel):
    id: int
    full_name: str
    phone: str
    email: Optional[str] = None
    role: str
    avatar_url: Optional[str] = None
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime
    shop_profile: Optional[ShopProfileResponse] = None

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    status: str = "success"
    token: str = ""
    access_token: str = ""
    token_type: str = "bearer"
    expires_in_minutes: int = 10080
    user: UserProfileResponse
    data: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def populate_token_fields(cls, values):
        if isinstance(values, dict):
            tok = values.get("token") or values.get("access_token", "")
            if not values.get("token"):
                values["token"] = tok
            if not values.get("access_token"):
                values["access_token"] = tok
            if "status" not in values:
                values["status"] = "success"
            if "data" not in values or values["data"] is None:
                user_val = values.get("user")
                if hasattr(user_val, "model_dump"):
                    user_dict = user_val.model_dump()
                elif isinstance(user_val, dict):
                    user_dict = user_val
                else:
                    user_dict = None
                values["data"] = {
                    "token": tok,
                    "access_token": tok,
                    "user": user_dict
                }
        return values


class UserProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None


class ShopProfileUpdateRequest(BaseModel):
    shop_name: Optional[str] = None
    shop_logo_url: Optional[str] = None
    shop_address: Optional[str] = None
    gstin: Optional[str] = None
    shop_phone: Optional[str] = None
    shop_email: Optional[str] = None


class ShopSettingsUpdateRequest(BaseModel):
    currency: Optional[str] = None
    timezone: Optional[str] = None
    invoice_footer: Optional[str] = None
    default_measurement_unit: Optional[str] = None
    default_min_stock_threshold: Optional[float] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_new_password: str


class ForgotPasswordRequest(BaseModel):
    phone_or_email: str


class ForgotPasswordResponse(BaseModel):
    success: bool
    message: str
    phone_or_email: str
    demo_otp: Optional[str] = None  # Provided in dev/mock environment
    expires_in_seconds: int = 300


class ResetPasswordRequest(BaseModel):
    phone_or_email: str
    otp_code: str
    new_password: str
    confirm_new_password: str


# --- ElevenLabs Voice & TTS Schemas ---

class VoiceSpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Natural text phrase to synthesize to speech")
    voice_id: Optional[str] = Field(None, description="Optional ElevenLabs voice ID override")


class VoiceStatusResponse(BaseModel):
    status: str = Field(..., description="Service status (e.g. active, unconfigured)")
    configured: bool = Field(..., description="Whether ELEVENLABS_API_KEY is configured")
    voice_id: str = Field(..., description="Default ElevenLabs Voice ID")
    model_id: str = Field(..., description="ElevenLabs Model ID (eleven_flash_v2_5)")
    cached_phrases: int = Field(0, description="Total cached audio phrases in local storage")
    provider: Optional[str] = Field("elevenlabs", description="Active voice provider (elevenlabs, edge-tts, browser)")
    fallback_available: Optional[bool] = Field(True, description="Whether edge-tts fallback is available")
    edge_tts_available: Optional[bool] = Field(True, description="Whether edge-tts is installed and ready")


# --- Kirana AI Copilot Schemas ---

class AssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="User message or voice transcript")
    history: Optional[List[Dict[str, str]]] = Field(default=[], description="Previous conversation turns")
    input_source: Optional[str] = Field("text", description="Input communication source: 'text' or 'mic'")


class AssistantChatResponse(BaseModel):
    reply: str = Field(..., description="Natural language assistant response in English, Hindi, or Hinglish")
    action_tab: Optional[str] = Field(None, description="Suggested navigation tab (dashboard, billing, inventory, udhaar, analytics, forecasting, profile)")
    action_label: Optional[str] = Field(None, description="Button label for navigation chip")
    source: str = Field("groq", description="Response source: groq or fallback")
    input_source: Optional[str] = Field("text", description="Reflected communication source: 'text' or 'mic'")
