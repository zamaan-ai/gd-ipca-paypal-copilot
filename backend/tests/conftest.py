"""
Pytest configuration and fixtures for GD-IPCA Mark 2
"""
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.db.session import Base, get_db
from app.main import app
from app.routers.auth import ensure_seed_users

# Force simulation mode for automated tests to ensure hermetic, deterministic execution
settings.PAYPAL_MODE = "simulation"

# Use an isolated SQLite test database
TEST_DB_URL = "sqlite:///./test_gdipca.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    ensure_seed_users(db)
    db.close()
    yield
    Base.metadata.drop_all(bind=test_engine)
    test_db_file = Path("./test_gdipca.db")
    if test_db_file.exists():
        try:
            test_db_file.unlink()
        except Exception:
            pass


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client):
    # Log in as demo user
    res = client.post(
        f"{settings.API_V1_STR}/auth/login",
        json={"email": "demo@gdipca.io", "password": "Demo12345!"},
    )
    assert res.status_code == 200, f"Login failed: {res.text}"
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(client):
    # Log in as admin user
    res = client.post(
        f"{settings.API_V1_STR}/auth/login",
        json={"email": "admin@gdipca.io", "password": "Admin12345!"},
    )
    assert res.status_code == 200, f"Login failed: {res.text}"
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
