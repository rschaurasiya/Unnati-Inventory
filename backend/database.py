"""
Database configuration and Multi-Tenant Store Isolation Engine.
Provides dynamic routing for:
1. Default Demo Account (9876543210 / owner@apnakirana.com) -> data/shopkeeper.db (pre-seeded catalog)
2. Every newly registered user -> data/tenants/store_<user_id>.db (100% isolated empty bucket)
"""
import os
import re
import datetime
import threading
from pathlib import Path
from typing import Optional, Dict, Any

import jwt
from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from backend.config import settings

# ==============================================================================
# 1. Master Database Configuration (Demo Account & Master Registry)
# ==============================================================================

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False
)

# Enable foreign keys for master SQLite connection
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ==============================================================================
# 2. Multi-Tenant Isolated SQLite Registry
# ==============================================================================

_TENANT_ENGINES: Dict[str, Any] = {}
_TENANT_LOCK = threading.Lock()

TENANTS_DIR = Path("./data/tenants")
TENANTS_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_tenant_id(raw_id: Any) -> str:
    """Sanitizes user/tenant identifier for safe filename use."""
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", str(raw_id).strip())
    return clean or "default"


def get_tenant_db_path(tenant_id: str) -> Path:
    """Returns filesystem path for isolated user database."""
    clean_id = sanitize_tenant_id(tenant_id)
    return TENANTS_DIR / f"store_{clean_id}.db"


def get_tenant_engine(tenant_id: str):
    """
    Retrieves or creates a dedicated SQLite engine for an isolated user tenant.
    Initializes all application tables via Base.metadata.create_all.
    """
    clean_id = sanitize_tenant_id(tenant_id)
    with _TENANT_LOCK:
        if clean_id in _TENANT_ENGINES:
            return _TENANT_ENGINES[clean_id]

        db_path = get_tenant_db_path(clean_id)
        db_url = f"sqlite:///{db_path.resolve().as_posix()}"

        tenant_engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            echo=False
        )

        @event.listens_for(tenant_engine, "connect")
        def set_tenant_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        # Ensure all models are imported and created in the tenant database
        import backend.models  # noqa: F401
        Base.metadata.create_all(bind=tenant_engine)

        _TENANT_ENGINES[clean_id] = tenant_engine
        return tenant_engine


def provision_tenant_store(user, shop_data: Optional[dict] = None):
    """
    Seeds an isolated store database with ONLY the user and shop profile.
    Leaves products, customers, bills, sales, and forecasts 100% EMPTY.
    """
    if not user:
        return

    user_id_str = str(user.id)
    phone_str = getattr(user, "phone", "") or ""
    email_str = getattr(user, "email", "") or ""

    # Demo account stays strictly on master database
    if user_id_str == "1" or phone_str == "9876543210" or email_str == "owner@apnakirana.com":
        return

    clean_id = sanitize_tenant_id(user_id_str)
    t_engine = get_tenant_engine(clean_id)
    TenantSession = sessionmaker(autocommit=False, autoflush=False, bind=t_engine)
    db = TenantSession()
    try:
        from backend.models import ShopkeeperUser, ShopProfile

        now = datetime.datetime.utcnow()
        existing_u = db.query(ShopkeeperUser).filter(ShopkeeperUser.id == user.id).first()
        if not existing_u:
            t_user = ShopkeeperUser(
                id=user.id,
                full_name=user.full_name or "Shopkeeper",
                phone=user.phone,
                email=user.email,
                firebase_uid=getattr(user, "firebase_uid", None),
                hashed_password=user.hashed_password,
                role=getattr(user, "role", "Shop Owner") or "Shop Owner",
                avatar_url=getattr(user, "avatar_url", None),
                is_active=getattr(user, "is_active", True),
                created_at=getattr(user, "created_at", now) or now,
                updated_at=getattr(user, "updated_at", now) or now
            )
            db.add(t_user)
            db.flush()

        existing_shop = db.query(ShopProfile).filter(ShopProfile.user_id == user.id).first()
        if not existing_shop:
            master_shop = getattr(user, "shop_profile", None)
            shop_name = (
                (shop_data.get("shop_name") if shop_data is not None and "shop_name" in shop_data else None)
                or (master_shop.shop_name if master_shop else "")
                or ""
            )
            shop_addr = (
                (shop_data.get("shop_address") if shop_data is not None and "shop_address" in shop_data else None)
                or (master_shop.shop_address if master_shop else "")
                or ""
            )
            shop_ph = (
                (shop_data.get("shop_phone") if shop_data is not None and "shop_phone" in shop_data else None)
                or (master_shop.shop_phone if master_shop else "")
                or ""
            )
            t_shop = ShopProfile(
                user_id=user.id,
                shop_name=shop_name,
                shop_address=shop_addr,
                shop_phone=shop_ph,
                shop_email=user.email,
                currency="INR (₹)",
                timezone="Asia/Kolkata (IST)",
                invoice_footer="Thank you for shopping with us! Visit again.",
                default_measurement_unit="kg",
                default_min_stock_threshold=10.0,
                created_at=now,
                updated_at=now
            )
            db.add(t_shop)

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[MultiTenant] Provisioning tenant error for user {user.id}: {e}")
    finally:
        db.close()


def resolve_tenant_id_from_request(request: Request = None) -> Optional[str]:
    """
    Extracts tenant/user identity from request:
    1. X-Tenant-Id or X-User-Id header
    2. Authorization Bearer token -> decode 'sub' claim
    """
    if not request:
        return None

    # Check explicit headers
    header_user = request.headers.get("x-user-id") or request.headers.get("x-tenant-id")
    if header_user and header_user.strip():
        val = header_user.strip()
        if val in ("1", "demo", "9876543210"):
            return "1"
        return val

    # Check Authorization header
    auth_header = request.headers.get("authorization") or ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            sub = payload.get("sub")
            phone = payload.get("phone")
            if phone == "9876543210" or sub in ("1", 1):
                return "1"
            if sub is not None:
                return str(sub)
        except Exception:
            pass

    return None


def get_master_db():
    """Always yields a session connected to the master database."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db(request: Request = None):
    """
    Dependency that dynamically yields the appropriate database session:
    - Master DB for Demo user (id 1, 9876543210, owner@apnakirana.com) or unauthenticated requests.
    - Isolated per-tenant SQLite database for registered users.
    """
    # 1. Master registry endpoints always route to master database
    if request:
        path = request.url.path.lower()
        if any(path.endswith(p) for p in [
            "/auth/login", "/auth/register", "/auth/check-user",
            "/auth/forgot-password", "/auth/reset-password", "/auth/firebase-config"
        ]):
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()
            return

    tenant_id = resolve_tenant_id_from_request(request) if request else None

    # 2. If demo account or no tenant specified, use master database
    if not tenant_id or tenant_id in ("1", "demo", "9876543210", "owner@apnakirana.com"):
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
        return

    # 3. Resolve dedicated tenant database
    clean_id = sanitize_tenant_id(tenant_id)
    t_engine = get_tenant_engine(clean_id)

    # 4. Ensure tenant DB has user record synchronized from master DB if needed
    try:
        TenantSession = sessionmaker(autocommit=False, autoflush=False, bind=t_engine)
        tdb = TenantSession()
        try:
            from backend.models import ShopkeeperUser
            u = tdb.query(ShopkeeperUser).filter(
                (ShopkeeperUser.id == clean_id) | (ShopkeeperUser.firebase_uid == clean_id)
            ).first()
            if not u:
                mdb = SessionLocal()
                try:
                    master_u = mdb.query(ShopkeeperUser).filter(
                        (ShopkeeperUser.id == clean_id) | (ShopkeeperUser.firebase_uid == clean_id)
                    ).first()
                    if master_u:
                        provision_tenant_store(master_u)
                finally:
                    mdb.close()
        finally:
            tdb.close()
    except Exception as e:
        print(f"[MultiTenant] Sync check error for tenant {clean_id}: {e}")

    TenantSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=t_engine)
    session = TenantSessionLocal()
    try:
        yield session
    finally:
        session.close()
