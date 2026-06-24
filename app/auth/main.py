from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api import auth, oauth, users
from app.core.config import settings
from app.db.database import Base, engine


# ─── Lifespan: startup / shutdown ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup: create tables (use Alembic for production migrations).
    On shutdown: dispose engine.
    """
    # NOTE: In production, tables are managed by Alembic migrations.
    # This line is for development convenience only.
    async with engine.begin() as conn:
        # Import all models so Base knows about them
        from app.models import user, role, refresh_token  # noqa
        await conn.run_sync(Base.metadata.create_all)

    # Seed default roles if they don't exist
    await seed_roles()

    yield  # App runs here

    await engine.dispose()


async def seed_roles():
    """Insert default roles into DB if not present."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import select
    from app.db.database import AsyncSessionLocal
    from app.models.role import Role, RoleName
    import uuid

    async with AsyncSessionLocal() as db:
        for role_name in RoleName:
            result = await db.execute(select(Role).where(Role.ROLE_NAME == role_name))
            if not result.scalar_one_or_none():
                db.add(Role(ROLE_ID=str(uuid.uuid4()), ROLE_NAME=role_name))
        await db.commit()


# ─── App Instance ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Auth Microservice",
    description="Authentication & Authorization for the Collaborative Code Editor",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── Middleware ───────────────────────────────────────────────────────────────

# Session middleware is required for OAuth state management (authlib)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

# CORS – update origins for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ─────────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(users.router)


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "auth-microservice"}
