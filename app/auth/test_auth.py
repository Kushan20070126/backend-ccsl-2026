import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.database import Base
from app.db.session import get_db

# Use SQLite for tests (no Oracle needed in CI)
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create fresh tables before each test."""
    from app.models import user, role, refresh_token  # noqa
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed roles
    from app.models.role import Role, RoleName
    import uuid
    async with TestSessionLocal() as db:
        for role_name in RoleName:
            db.add(Role(ROLE_ID=str(uuid.uuid4()), ROLE_NAME=role_name))
        await db.commit()

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ─── Registration ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success(client):
    async with client as c:
        response = await c.post("/auth/register", json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "Password1",
        })
    assert response.status_code == 201
    assert "Registration successful" in response.json()["message"]


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    payload = {"email": "dup@example.com", "username": "user1", "password": "Password1"}
    async with client as c:
        await c.post("/auth/register", json=payload)
        response = await c.post("/auth/register", json={**payload, "username": "user2"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_register_weak_password(client):
    async with client as c:
        response = await c.post("/auth/register", json={
            "email": "weak@example.com",
            "username": "weakuser",
            "password": "short",
        })
    assert response.status_code == 422


# ─── Login ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(client):
    async with client as c:
        await c.post("/auth/register", json={
            "email": "login@example.com",
            "username": "loginuser",
            "password": "Password1",
        })
        response = await c.post("/auth/login", json={
            "email": "login@example.com",
            "password": "Password1",
        })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    async with client as c:
        await c.post("/auth/register", json={
            "email": "wrong@example.com",
            "username": "wronguser",
            "password": "Password1",
        })
        response = await c.post("/auth/login", json={
            "email": "wrong@example.com",
            "password": "WrongPassword1",
        })
    assert response.status_code == 401


# ─── Token Refresh ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_token(client):
    async with client as c:
        await c.post("/auth/register", json={
            "email": "refresh@example.com",
            "username": "refreshuser",
            "password": "Password1",
        })
        login_resp = await c.post("/auth/login", json={
            "email": "refresh@example.com",
            "password": "Password1",
        })
        refresh_token = login_resp.json()["refresh_token"]
        response = await c.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 200
    assert "access_token" in response.json()


# ─── Profile ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_profile(client):
    async with client as c:
        await c.post("/auth/register", json={
            "email": "me@example.com",
            "username": "meuser",
            "password": "Password1",
        })
        login_resp = await c.post("/auth/login", json={
            "email": "me@example.com",
            "password": "Password1",
        })
        access_token = login_resp.json()["access_token"]
        response = await c.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


# ─── Token Verification ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_token(client):
    async with client as c:
        await c.post("/auth/register", json={
            "email": "verify@example.com",
            "username": "verifyuser",
            "password": "Password1",
        })
        login_resp = await c.post("/auth/login", json={
            "email": "verify@example.com",
            "password": "Password1",
        })
        access_token = login_resp.json()["access_token"]
        response = await c.post("/auth/verify-token", json={"token": access_token})

    assert response.status_code == 200
    assert response.json()["valid"] is True
