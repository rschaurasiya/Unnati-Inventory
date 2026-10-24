from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from backend.config import settings
from backend.routers import health, products, inventory, nlp, billing, verification, receipts, customers, analytics, historical_import, forecasting, auth, voice, assistant, exports
from backend.init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables and seed product catalog
    init_db(seed=True)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API for Shopkeeper-Customer Voice Billing & AI Inventory System",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from typing import Optional, List
from fastapi import Depends, HTTPException, Query, status, UploadFile, File
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.services.forecasting_sufficiency import (
    evaluate_product_data_sufficiency,
    evaluate_all_products_data_sufficiency
)
from backend.schemas import (
    ProductDataSufficiencyResponse,
    StoreDataSufficiencySummaryResponse,
    ProductForecastDetailResponse,
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    CustomerDetailResponse,
    CustomerImportResponse
)

# Include Routers
app.include_router(health.router)
app.include_router(products.router)
app.include_router(inventory.router)
app.include_router(nlp.router)
app.include_router(billing.router)
app.include_router(verification.router)
app.include_router(receipts.router)
app.include_router(customers.router)
app.include_router(analytics.router)
app.include_router(historical_import.router)
app.include_router(forecasting.router)
app.include_router(auth.router)
app.include_router(voice.router)
app.include_router(assistant.router)
app.include_router(exports.router)


from backend.schemas import ForecastOverviewResponse, ForecastListResponse
forecasting_alias_router = APIRouter(prefix="/api/v1/forecasting", tags=["Demand Forecasting & Reorder Intelligence"])

@forecasting_alias_router.get("/summary", response_model=ForecastOverviewResponse, status_code=status.HTTP_200_OK)
def api_forecasting_summary_alias(db: Session = Depends(get_db)):
    from backend.services.forecasting import get_all_product_forecasts
    data = get_all_product_forecasts(db, force_refresh=False)
    return data["overview"]

@forecasting_alias_router.get("/all", response_model=ForecastListResponse, status_code=status.HTTP_200_OK)
def api_forecasting_all_alias(
    risk_level: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    force_refresh: bool = Query(False),
    db: Session = Depends(get_db)
):
    from backend.services.forecasting import get_all_product_forecasts
    data = get_all_product_forecasts(db, force_refresh=force_refresh)
    products = data["products"]
    if risk_level:
        products = [p for p in products if p["risk_level"].upper() == risk_level.strip().upper()]
    if status_filter:
        products = [p for p in products if p["status"].upper() == status_filter.strip().upper()]
    return {
        "overview": data["overview"],
        "products": products
    }

app.include_router(forecasting_alias_router)

# Customers Alias Router for /api/customers
customers_alias_router = APIRouter(prefix="/api/customers", tags=["Customer Accounts & Udhaar Ledger"])

@customers_alias_router.get("/sample-template")
def api_customer_sample_template_alias():
    return customers.download_sample_template()

@customers_alias_router.post("/import", response_model=CustomerImportResponse)
async def api_customer_import_alias(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    return await customers.import_customers(file, db)

@customers_alias_router.get("/{customer_id}", response_model=CustomerDetailResponse)
def api_customer_details_alias(customer_id: int, db: Session = Depends(get_db)):
    return customers.get_customer_details(customer_id, db)

@customers_alias_router.put("/{customer_id}", response_model=CustomerResponse)
@customers_alias_router.patch("/{customer_id}", response_model=CustomerResponse)
def api_update_customer_alias(customer_id: int, payload: CustomerUpdate, db: Session = Depends(get_db)):
    return customers.update_customer(customer_id, payload, db)

@customers_alias_router.get("", response_model=List[CustomerResponse])
def api_list_customers_alias(
    query: Optional[str] = Query(None),
    active_only: bool = Query(True),
    db: Session = Depends(get_db)
):
    return customers.list_customers(query, active_only, db)

@customers_alias_router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def api_create_customer_alias(payload: CustomerCreate, db: Session = Depends(get_db)):
    return customers.create_customer(payload, db)

@customers_alias_router.delete("/{customer_id}")
def api_delete_customer_alias(customer_id: int, hard_delete: bool = Query(False), db: Session = Depends(get_db)):
    return customers.delete_customer(customer_id, hard_delete, db)

app.include_router(customers_alias_router)

# Auth Alias Router for /api/auth
auth_alias_router = APIRouter(prefix="/api/auth", tags=["Authentication & Profile (Alias)"])

@auth_alias_router.post("/login", response_model=auth.TokenResponse)
def auth_login_alias(payload: auth.UserLoginRequest, db: Session = Depends(get_db)):
    return auth.login_user(payload, db)

@auth_alias_router.post("/register", response_model=auth.TokenResponse, status_code=status.HTTP_201_CREATED)
def auth_register_alias(payload: auth.UserRegisterRequest, db: Session = Depends(get_db)):
    return auth.register_user(payload, db)

@auth_alias_router.get("/me", response_model=auth.UserProfileResponse)
def auth_me_alias(current_user: auth.ShopkeeperUser = Depends(auth.get_current_user)):
    return auth.get_current_user_profile(current_user)

@auth_alias_router.get("/firebase-config")
def auth_firebase_config_alias():
    return auth.get_firebase_config()

@auth_alias_router.post("/firebase-sync", response_model=auth.TokenResponse)
def auth_firebase_sync_alias(payload: auth.FirebaseSyncRequest, db: Session = Depends(get_db)):
    return auth.sync_firebase_user(payload, db)

@auth_alias_router.post("/logout")
def auth_logout_alias(current_user: auth.ShopkeeperUser = Depends(auth.get_current_user)):
    return auth.logout_user(current_user)

@auth_alias_router.get("/check-user")
def auth_check_user_alias(
    identifier: Optional[str] = None,
    firebase_uid: Optional[str] = None,
    db: Session = Depends(get_db)
):
    return auth.check_user_registered(identifier=identifier, firebase_uid=firebase_uid, db=db)

app.include_router(auth_alias_router)

# Exports Alias Router for /api/exports
exports_alias_router = APIRouter(prefix="/api/exports", tags=["Export & Reports (Alias)"])
for r in exports.router.routes:
    exports_alias_router.routes.append(r)
app.include_router(exports_alias_router)




@app.get(
    "/api/forecasting/data-sufficiency",
    summary="Data Sufficiency Validation Gate (Step 11A)",
    tags=["Demand Forecasting & Reorder Intelligence"]
)
def api_forecasting_data_sufficiency(
    product_id: Optional[int] = Query(None, description="Optional catalog product ID"),
    db: Session = Depends(get_db)
):
    if product_id is not None:
        res = evaluate_product_data_sufficiency(db, product_id)
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with ID {product_id} not found in catalog."
            )
        return res
    return evaluate_all_products_data_sufficiency(db)


@app.get(
    "/api/forecasting/data-sufficiency/{product_id}",
    response_model=ProductDataSufficiencyResponse,
    summary="Product-Specific Data Sufficiency Validation Gate (Step 11A)",
    tags=["Demand Forecasting & Reorder Intelligence"]
)
def api_product_data_sufficiency(
    product_id: int,
    db: Session = Depends(get_db)
):
    res = evaluate_product_data_sufficiency(db, product_id)
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found in catalog."
        )
    return res


@app.get(
    "/api/forecasting/product/{product_id}",
    response_model=ProductForecastDetailResponse,
    summary="Product Forecasting & Reorder Intelligence (Step 11)",
    tags=["Demand Forecasting & Reorder Intelligence"]
)
def api_product_forecast_detail(
    product_id: int,
    force_refresh: bool = Query(False, description="Force recalculation bypassing cache"),
    db: Session = Depends(get_db)
):
    from backend.models import Product
    from backend.services.forecasting import generate_product_forecast
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found in catalog."
        )
    return generate_product_forecast(db, product, force_recalculate=force_refresh)


# Mount Frontend Static Assets & Page Routing
FRONTEND_PAGE_ROUTES = [
    "/dashboard",
    "/billing",
    "/pos",
    "/inventory",
    "/customers",
    "/udhaar",
    "/sales",
    "/sales/history",
    "/sales/import",
    "/forecast",
    "/forecasting",
    "/login",
    "/register",
    "/forgot-password",
    "/profile",
    "/settings",
    "/reports",
    "/export",
]

if settings.FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(settings.FRONTEND_DIR)), name="static")

if settings.UPLOADS_DIR.exists():
    app.mount("/uploads", StaticFiles(directory=str(settings.UPLOADS_DIR)), name="uploads")


@app.get("/", include_in_schema=False)
async def serve_index():
    index_file = settings.FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend index.html not found"}


for page_path in FRONTEND_PAGE_ROUTES:
    @app.get(page_path, include_in_schema=False)
    async def serve_frontend_page():
        index_file = settings.FRONTEND_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"message": "Frontend index.html not found"}


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    if (
        full_path.startswith("api/")
        or full_path.startswith("static/")
        or full_path in ["docs", "redoc", "openapi.json"]
    ):
        raise HTTPException(status_code=404, detail="Not Found")
    index_file = settings.FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Frontend index.html not found")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", settings.PORT))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=False)


