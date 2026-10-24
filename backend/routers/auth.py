"""
Authentication, Profile & Settings Router
Provides endpoints for Shopkeeper registration, login, JWT token verification,
profile management, shop configuration, password changes, and secure password reset.
"""
import datetime
from datetime import timedelta
import os
import re
import secrets
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db, provision_tenant_store
from backend.models import ShopkeeperUser, ShopProfile
from backend.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    FirebaseSyncRequest,
    TokenResponse,
    UserProfileResponse,
    ShopProfileResponse,
    UserProfileUpdateRequest,
    ShopProfileUpdateRequest,
    ShopSettingsUpdateRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest
)
from backend.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & Profile"])


def _clean_phone(raw: str) -> str:
    """Extracts numeric digits from phone string."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 10:
        return digits[-10:]
    return digits


# ==============================================================================
# 1. Registration & Login
# ==============================================================================

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserRegisterRequest, db: Session = Depends(get_db)):
    """
    Registers a new shopkeeper account with encrypted password storage.
    Automatically provisions store profile and returns authenticated session token.
    """
    full_name = payload.full_name.strip()
    if not full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full name is required."
        )

    clean_phone = _clean_phone(payload.phone)
    if len(clean_phone) != 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valid 10-digit mobile phone number is required."
        )

    # Validate email format if provided
    clean_email = payload.email.strip().lower() if payload.email and payload.email.strip() else None
    if clean_email:
        email_pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_pattern, clean_email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email address format."
            )

    # Password validation
    if len(payload.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long."
        )

    if payload.password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password and confirmation password do not match."
        )

    # Prevent duplicate accounts
    existing_phone = db.query(ShopkeeperUser).filter(ShopkeeperUser.phone == clean_phone).first()
    if existing_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this phone number already exists. Please log in instead."
        )

    if clean_email:
        existing_email = db.query(ShopkeeperUser).filter(ShopkeeperUser.email == clean_email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email address already exists."
            )

    # Hash password securely
    hashed = hash_password(payload.password)

    new_user = ShopkeeperUser(
        full_name=full_name,
        phone=clean_phone,
        email=clean_email,
        firebase_uid=payload.firebase_uid,
        hashed_password=hashed,
        role=payload.role or "Shop Owner",
        is_active=True,
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow()
    )
    db.add(new_user)
    db.flush()

    # Create associated Shop Profile with empty store fields for new user onboarding
    shop_profile = ShopProfile(
        user_id=new_user.id,
        shop_name="",
        shop_address="",
        shop_phone="",
        shop_email=clean_email,
        currency="INR (₹)",
        timezone="Asia/Kolkata (IST)",
        invoice_footer="Thank you for shopping with us! Visit again.",
        default_measurement_unit="kg",
        default_min_stock_threshold=10.0,
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow()
    )
    db.add(shop_profile)
    db.commit()
    db.refresh(new_user)

    # Initialize isolated empty tenant store for new user
    provision_tenant_store(new_user, {
        "shop_name": "",
        "shop_address": "",
        "shop_phone": ""
    })

    # Create access token
    access_token = create_access_token(data={"sub": str(new_user.id), "phone": new_user.phone})
    user_resp = UserProfileResponse.model_validate(new_user)

    return TokenResponse(
        status="success",
        token=access_token,
        access_token=access_token,
        token_type="bearer",
        expires_in_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        user=user_resp,
        data={
            "token": access_token,
            "access_token": access_token,
            "user": user_resp.model_dump()
        }
    )


@router.post("/login", response_model=TokenResponse)
def login_user(payload: UserLoginRequest, db: Session = Depends(get_db)):
    """
    Authenticates shopkeeper via mobile phone or email and password.
    Returns signed JWT access token and user profile.
    """
    ident = payload.identifier.strip()
    if not ident:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number or email is required."
        )

    if not payload.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is required."
        )

    # Try lookup by clean phone or email
    clean_digits = _clean_phone(ident)
    user = None
    if len(clean_digits) == 10:
        user = db.query(ShopkeeperUser).filter(ShopkeeperUser.phone == clean_digits).first()

    if not user:
        user = db.query(ShopkeeperUser).filter(
            ShopkeeperUser.email == ident.lower()
        ).first()

    if not user:
        # Fallback raw phone check
        user = db.query(ShopkeeperUser).filter(ShopkeeperUser.phone == ident).first()

    # Guarantee demo shopkeeper account exists if demo credentials are submitted
    if not user and (clean_digits == "9876543210" or ident.lower() == "owner@apnakirana.com"):
        demo_user = ShopkeeperUser(
            full_name="Radheshyam Gupta",
            phone="9876543210",
            email="owner@apnakirana.com",
            hashed_password=hash_password("Password@123"),
            role="Shop Owner",
            is_active=True,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow()
        )
        db.add(demo_user)
        db.flush()
        demo_shop = ShopProfile(
            user_id=demo_user.id,
            shop_name="Apna Kirana Store",
            shop_address="Main Market, Sector 4, New Delhi",
            shop_phone="+91 98765 43210",
            shop_email="owner@apnakirana.com",
            gstin="07AAAAA0000A1Z5",
            currency="INR (₹)",
            timezone="Asia/Kolkata (IST)",
            invoice_footer="Thank you for shopping with us! Visit again.",
            default_measurement_unit="kg",
            default_min_stock_threshold=10.0,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow()
        )
        db.add(demo_shop)
        db.commit()
        db.refresh(demo_user)
        user = demo_user

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone/email or password.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Please contact administrator."
        )

    # Update last login timestamp
    user.last_login_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(user)

    # Ensure isolated tenant store is provisioned
    provision_tenant_store(user)

    # Create access token
    access_token = create_access_token(data={"sub": str(user.id), "phone": user.phone})
    user_resp = UserProfileResponse.model_validate(user)

    return TokenResponse(
        status="success",
        token=access_token,
        access_token=access_token,
        token_type="bearer",
        expires_in_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        user=user_resp,
        data={
            "token": access_token,
            "access_token": access_token,
            "user": user_resp.model_dump()
        }
    )


# ==============================================================================
# 2. Profile Management
# ==============================================================================

@router.get("/me", response_model=UserProfileResponse)
def get_current_user_profile(current_user: ShopkeeperUser = Depends(get_current_user)):
    """Retrieves full profile for the currently authenticated shopkeeper."""
    return UserProfileResponse.model_validate(current_user)


@router.put("/profile", response_model=UserProfileResponse)
def update_user_profile(
    payload: UserProfileUpdateRequest,
    current_user: ShopkeeperUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Updates personal user information (Full Name, Phone, Email, Avatar)."""
    if payload.full_name is not None:
        name = payload.full_name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Full name cannot be empty."
            )
        current_user.full_name = name

    if payload.phone is not None:
        clean_p = _clean_phone(payload.phone)
        if len(clean_p) != 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number must be a valid 10-digit number."
            )
        # Check uniqueness if changed
        if clean_p != current_user.phone:
            exist = db.query(ShopkeeperUser).filter(
                ShopkeeperUser.phone == clean_p,
                ShopkeeperUser.id != current_user.id
            ).first()
            if exist:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This phone number is already registered to another account."
                )
            current_user.phone = clean_p

    if payload.email is not None:
        email = payload.email.strip().lower() if payload.email.strip() else None
        if email:
            if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid email address format."
                )
            if email != current_user.email:
                exist_email = db.query(ShopkeeperUser).filter(
                    ShopkeeperUser.email == email,
                    ShopkeeperUser.id != current_user.id
                ).first()
                if exist_email:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="This email address is already in use by another account."
                    )
        current_user.email = email

    if payload.avatar_url is not None:
        current_user.avatar_url = payload.avatar_url.strip() or None

    current_user.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(current_user)

    _sync_user_to_master_db(current_user.id, {
        "full_name": current_user.full_name,
        "phone": current_user.phone,
        "email": current_user.email,
        "avatar_url": current_user.avatar_url,
        "updated_at": current_user.updated_at
    })

    return UserProfileResponse.model_validate(current_user)


@router.get("/shop", response_model=ShopProfileResponse)
def get_active_shop_profile(
    db: Session = Depends(get_db)
):
    """Retrieves authoritative active business and store details."""
    shop = db.query(ShopProfile).first()
    if not shop:
        user = db.query(ShopkeeperUser).first()
        user_id = user.id if user else 1
        shop = ShopProfile(user_id=user_id)
        db.add(shop)
        db.commit()
        db.refresh(shop)
    return ShopProfileResponse.model_validate(shop)


@router.put("/shop", response_model=ShopProfileResponse)
def update_shop_profile(
    payload: ShopProfileUpdateRequest,
    current_user: ShopkeeperUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Updates business & store details (Shop Name, Logo, Address, GSTIN, Phone, Email)."""
    shop = current_user.shop_profile
    if not shop:
        shop = ShopProfile(user_id=current_user.id)
        db.add(shop)
        db.flush()

    if payload.shop_name is not None:
        sname = payload.shop_name.strip()
        if not sname:
            raise HTTPException(status_code=400, detail="Shop name cannot be empty.")
        shop.shop_name = sname

    if payload.shop_logo_url is not None:
        shop.shop_logo_url = payload.shop_logo_url.strip() or None

    if payload.shop_address is not None:
        shop.shop_address = payload.shop_address.strip() or shop.shop_address

    if payload.gstin is not None:
        shop.gstin = payload.gstin.strip().upper() or None

    if payload.shop_phone is not None:
        shop.shop_phone = payload.shop_phone.strip() or shop.shop_phone

    if payload.shop_email is not None:
        shop.shop_email = payload.shop_email.strip().lower() or None

    shop.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(shop)

    return ShopProfileResponse.model_validate(shop)


def _sync_user_to_master_db(user_id: int, updates: dict):
    from backend.database import SessionLocal
    master_db = SessionLocal()
    try:
        mu = master_db.query(ShopkeeperUser).filter(ShopkeeperUser.id == user_id).first()
        if mu:
            for k, v in updates.items():
                if hasattr(mu, k):
                    setattr(mu, k, v)
            master_db.commit()
    except Exception as e:
        print(f"[AuthRouter] Warning: could not sync user to master DB: {e}")
    finally:
        master_db.close()


@router.put("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: ShopkeeperUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Verifies current password and updates to newly hashed password.
    Enforces password length and confirmation equality.
    """
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password."
        )

    if len(payload.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 6 characters long."
        )

    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password and confirm password do not match."
        )

    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password."
        )

    new_hash = hash_password(payload.new_password)
    current_user.hashed_password = new_hash
    current_user.updated_at = datetime.datetime.utcnow()
    db.commit()

    _sync_user_to_master_db(current_user.id, {
        "hashed_password": new_hash,
        "updated_at": current_user.updated_at
    })

    return {
        "success": True,
        "message": "Password updated successfully. Please use your new password next time you log in."
    }


# ==============================================================================
# 4. Settings & Preferences
# ==============================================================================

@router.get("/settings", response_model=ShopProfileResponse)
def get_shop_settings(current_user: ShopkeeperUser = Depends(get_current_user)):
    """Retrieves store settings, currency, and invoice configuration."""
    shop = current_user.shop_profile
    if not shop:
        raise HTTPException(status_code=404, detail="Store settings not found.")
    return ShopProfileResponse.model_validate(shop)


@router.put("/settings", response_model=ShopProfileResponse)
def update_shop_settings(
    payload: ShopSettingsUpdateRequest,
    current_user: ShopkeeperUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Updates localization, invoice footer, and stock threshold preferences."""
    shop = current_user.shop_profile
    if not shop:
        shop = ShopProfile(user_id=current_user.id)
        db.add(shop)
        db.flush()

    if payload.currency is not None:
        shop.currency = payload.currency.strip() or shop.currency

    if payload.timezone is not None:
        shop.timezone = payload.timezone.strip() or shop.timezone

    if payload.invoice_footer is not None:
        shop.invoice_footer = payload.invoice_footer.strip() or shop.invoice_footer

    if payload.default_measurement_unit is not None:
        shop.default_measurement_unit = payload.default_measurement_unit.strip() or shop.default_measurement_unit

    if payload.default_min_stock_threshold is not None:
        if payload.default_min_stock_threshold < 0:
            raise HTTPException(status_code=400, detail="Threshold cannot be negative.")
        shop.default_min_stock_threshold = float(payload.default_min_stock_threshold)

    shop.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(shop)

    return ShopProfileResponse.model_validate(shop)


# ==============================================================================
# 5. Forgot Password & Reset (DEPRECATED - Replaced by Firebase Authentication)
# ==============================================================================
# Legacy custom OTP password reset endpoints have been deprecated and disabled.
# Password recovery is now securely handled directly via Firebase Authentication
# native sendPasswordResetEmail on the client application.

@router.post("/forgot-password", deprecated=True, tags=["Authentication & Profile"])
def request_password_reset(payload: Optional[dict] = None):
    """
    DEPRECATED: Password recovery is now handled via Firebase Authentication
    sendPasswordResetEmail directly in the frontend. This legacy endpoint is disabled.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Legacy OTP password recovery is deprecated. Please use the Firebase email password reset flow on the login page."
    )


@router.post("/reset-password", deprecated=True, tags=["Authentication & Profile"])
def reset_password(payload: Optional[dict] = None):
    """
    DEPRECATED: Password recovery is now handled via Firebase Authentication.
    This legacy endpoint is disabled.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Legacy OTP password reset is deprecated. Please reset your password via the Firebase email link."
    )


# ==============================================================================
# 6. Avatar & Logo File Uploads
# ==============================================================================

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".svg"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: ShopkeeperUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Uploads and saves a user profile avatar image."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image format. Allowed: {', '.join(sorted(ALLOWED_IMAGE_EXTS))}"
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds maximum limit of 5MB."
        )

    safe_filename = f"avatar_u{current_user.id}_{secrets.token_hex(6)}{ext}"
    dest_path = settings.UPLOADS_DIR / safe_filename
    with open(dest_path, "wb") as f:
        f.write(contents)

    rel_url = f"/uploads/{safe_filename}"
    current_user.avatar_url = rel_url
    current_user.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "avatar_url": rel_url,
        "message": "Avatar uploaded successfully."
    }


@router.post("/upload-logo")
async def upload_logo(
    file: UploadFile = File(...),
    current_user: ShopkeeperUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Uploads and saves a shop branding logo image."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image format. Allowed: {', '.join(sorted(ALLOWED_IMAGE_EXTS))}"
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds maximum limit of 5MB."
        )

    shop = current_user.shop_profile
    if not shop:
        shop = ShopProfile(user_id=current_user.id)
        db.add(shop)
        db.flush()

    safe_filename = f"logo_u{current_user.id}_{secrets.token_hex(6)}{ext}"
    dest_path = settings.UPLOADS_DIR / safe_filename
    with open(dest_path, "wb") as f:
        f.write(contents)

    rel_url = f"/uploads/{safe_filename}"
    shop.shop_logo_url = rel_url
    shop.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "logo_url": rel_url,
        "shop_logo_url": rel_url,
        "message": "Shop logo uploaded successfully."
    }


@router.post("/logout")
def logout_user(current_user: ShopkeeperUser = Depends(get_current_user)):
    """Logs out user and invalidates client session state."""
    return {
        "success": True,
        "message": f"Goodbye, {current_user.full_name}. Successfully logged out."
    }


@router.get("/firebase-config")
def get_firebase_config():
    """
    Returns public Firebase configuration for client-side authentication.
    """
    is_dummy = (
        not settings.FIREBASE_API_KEY
        or settings.FIREBASE_API_KEY.startswith("DUMMY")
        or "REPLACE" in settings.FIREBASE_API_KEY
    )
    return {
        "apiKey": settings.FIREBASE_API_KEY,
        "authDomain": settings.FIREBASE_AUTH_DOMAIN,
        "databaseURL": settings.FIREBASE_DATABASE_URL,
        "projectId": settings.FIREBASE_PROJECT_ID,
        "storageBucket": settings.FIREBASE_STORAGE_BUCKET,
        "messagingSenderId": settings.FIREBASE_MESSAGING_SENDER_ID,
        "appId": settings.FIREBASE_APP_ID,
        "measurementId": settings.FIREBASE_MEASUREMENT_ID,
        "isDummy": is_dummy
    }


@router.post("/firebase-sync", response_model=TokenResponse)
def sync_firebase_user(payload: FirebaseSyncRequest, db: Session = Depends(get_db)):
    """
    Synchronizes an authenticated Firebase user (Email, 10-digit Phone, or Google)
    with the local SQLite shopkeeper database.
    Creates or updates the user and shop profile, generating a local JWT session token.
    """
    uid = payload.firebase_uid.strip() if payload.firebase_uid else None
    if not uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Firebase UID is required.")

    # 1. Clean email and extract virtual phone if 10digits@user.apnakirana.in
    clean_email = payload.email.strip().lower() if payload.email and payload.email.strip() else None
    clean_phone = None
    if payload.phone:
        clean_phone = _clean_phone(payload.phone)

    if not clean_phone and clean_email and "@user.apnakirana.in" in clean_email:
        extracted = clean_email.split("@")[0]
        if len(extracted) == 10 and extracted.isdigit():
            clean_phone = extracted

    # 2. Lookup existing user by firebase_uid, email, or phone
    user = None
    if hasattr(ShopkeeperUser, "firebase_uid"):
        user = db.query(ShopkeeperUser).filter(ShopkeeperUser.firebase_uid == uid).first()

    if not user and clean_email:
        user = db.query(ShopkeeperUser).filter(ShopkeeperUser.email == clean_email).first()

    if not user and clean_phone:
        user = db.query(ShopkeeperUser).filter(ShopkeeperUser.phone == clean_phone).first()

    now = datetime.datetime.utcnow()

    if user:
        # Update user fields
        if hasattr(user, "firebase_uid"):
            user.firebase_uid = uid
        if payload.display_name and (not user.full_name or user.full_name.startswith("Shopkeeper")):
            user.full_name = payload.display_name.strip()
        if payload.photo_url and not user.avatar_url:
            user.avatar_url = payload.photo_url
        if clean_email and not user.email:
            user.email = clean_email
        if clean_phone and not user.phone:
            user.phone = clean_phone
        user.last_login_at = now
        user.updated_at = now

        # Ensure shop profile exists
        shop = db.query(ShopProfile).filter(ShopProfile.user_id == user.id).first()
        if not shop:
            shop = ShopProfile(
                user_id=user.id,
                shop_name="",
                shop_address="",
                shop_phone="",
                shop_email=user.email,
                currency="INR (₹)",
                timezone="Asia/Kolkata (IST)",
                created_at=now,
                updated_at=now
            )
            db.add(shop)

        db.commit()
        db.refresh(user)
    else:
        # Create brand new user
        # Phone is non-nullable in SQLite schema, so ensure we have a valid 10-digit number
        if not clean_phone:
            numeric_seed = abs(hash(uid)) % 1000000000
            clean_phone = f"9{numeric_seed:09d}"
            existing_p = db.query(ShopkeeperUser).filter(ShopkeeperUser.phone == clean_phone).first()
            if existing_p:
                clean_phone = f"9{secrets.randbelow(1000000000):09d}"

        display_name = payload.display_name.strip() if payload.display_name and payload.display_name.strip() else f"Shopkeeper {clean_phone[-4:]}"
        user = ShopkeeperUser(
            full_name=display_name,
            phone=clean_phone,
            email=clean_email,
            firebase_uid=uid,
            hashed_password=hash_password(secrets.token_urlsafe(16)),
            role="Shop Owner",
            avatar_url=payload.photo_url,
            is_active=True,
            last_login_at=now,
            created_at=now,
            updated_at=now
        )
        db.add(user)
        db.flush()

        shop = ShopProfile(
            user_id=user.id,
            shop_name="",
            shop_address="",
            shop_phone="",
            shop_email=clean_email,
            currency="INR (₹)",
            timezone="Asia/Kolkata (IST)",
            created_at=now,
            updated_at=now
        )
        db.add(shop)
        db.commit()
        db.refresh(user)

    # Ensure isolated tenant store is provisioned
    provision_tenant_store(user)

    access_token = create_access_token(data={"sub": str(user.id), "phone": user.phone})
    user_resp = UserProfileResponse.model_validate(user)

    return TokenResponse(
        status="success",
        token=access_token,
        access_token=access_token,
        token_type="bearer",
        expires_in_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        user=user_resp,
        data={
            "token": access_token,
            "access_token": access_token,
            "user": user_resp.model_dump()
        }
    )


@router.get("/check-user")
def check_user_registered(
    identifier: Optional[str] = None,
    firebase_uid: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Checks whether an account is already registered in the master registry.
    Used by frontend to enforce strict 'Register First' workflow.
    """
    if identifier:
        ident = identifier.strip()
        clean = _clean_phone(ident)

        # Demo account check
        if clean == "9876543210" or ident.lower() == "owner@apnakirana.com":
            return {"status": "success", "registered": True, "exists": True, "identifier": ident}

        # Check phone
        if len(clean) == 10:
            u = db.query(ShopkeeperUser).filter(ShopkeeperUser.phone == clean).first()
            if u:
                return {"status": "success", "registered": True, "exists": True, "identifier": ident, "full_name": u.full_name}

        # Check email
        u = db.query(ShopkeeperUser).filter(ShopkeeperUser.email == ident.lower()).first()
        if u:
            return {"status": "success", "registered": True, "exists": True, "identifier": ident, "full_name": u.full_name}

        # Virtual email from phone check
        if "@user.apnakirana.in" in ident:
            prefix = ident.split("@")[0]
            if len(prefix) == 10 and prefix.isdigit():
                u = db.query(ShopkeeperUser).filter(ShopkeeperUser.phone == prefix).first()
                if u:
                    return {"status": "success", "registered": True, "exists": True, "identifier": ident, "full_name": u.full_name}

    if firebase_uid:
        f_uid = firebase_uid.strip()
        u = db.query(ShopkeeperUser).filter(ShopkeeperUser.firebase_uid == f_uid).first()
        if u:
            return {"status": "success", "registered": True, "exists": True, "firebase_uid": f_uid, "full_name": u.full_name}

    return {"status": "success", "registered": False, "exists": False}


