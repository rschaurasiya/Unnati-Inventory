"""
Step 1 Verification Test Suite
Tests:
- Python module imports
- Database connectivity & SQLite initialization
- FastAPI TestClient requests to /api/v1/health
- Static frontend index.html response
"""
import sys
from pathlib import Path

# Ensure workspace root is in python path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from sqlalchemy import text


def test_python_imports():
    """Verify that all Step 1 backend modules import cleanly."""
    import backend.config
    import backend.database
    import backend.routers.health
    import backend.main
    assert backend.config.settings.APP_NAME is not None


def test_database_connection():
    """Verify SQLite database engine creates tables and executes raw query."""
    db = SessionLocal()
    try:
        result = db.execute(text("SELECT 1 AS test_val")).scalar()
        assert result == 1, "Database query did not return 1"
    finally:
        db.close()


def test_health_endpoint():
    """Verify GET /api/v1/health returns 200 OK and healthy status."""
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert "app_name" in data
    assert "version" in data


def test_frontend_index_serving():
    """Verify root GET / returns the frontend index.html."""
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Shopkeeper Voice POS" in response.text


if __name__ == "__main__":
    print("Running Step 1 automated tests...")
    test_python_imports()
    print("[PASS] Python imports cleanly verified")
    test_database_connection()
    print("[PASS] Database connectivity verified (SQLite engine functional)")
    test_health_endpoint()
    print("[PASS] Health endpoint GET /api/v1/health returned 200 OK and healthy status")
    test_frontend_index_serving()
    print("[PASS] Frontend index.html served at / with 200 OK")
    print("\nALL STEP 1 TESTS PASSED SUCCESSFULLY!")
