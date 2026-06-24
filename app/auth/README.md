# Authentication & Authorization Microservice

FastAPI-based auth service for the Collaborative Code Editor. Handles registration, login, JWT tokens, OAuth (Google/GitHub/Facebook/Apple), RBAC, and token validation for other microservices.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.13 |
| Framework | FastAPI + Uvicorn |
| Database | Oracle Database 23c |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Auth | JWT (python-jose) + OAuth2 (authlib) |
| Passwords | Passlib + Bcrypt |
| Rate Limiting | Redis + fastapi-limiter |
| Package Manager | uv |

---

## Project Structure

```
auth/
├── app/
│   ├── api/
│   │   ├── auth.py          # Register, Login, Logout, Refresh, Me, Password, Verify
│   │   ├── oauth.py         # Google, GitHub, Facebook, Apple OAuth
│   │   └── users.py         # User lookup, Permissions
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── security.py      # JWT creation/validation, bcrypt
│   │   └── oauth_config.py  # Authlib OAuth clients
│   ├── db/
│   │   ├── database.py      # Async Oracle engine + Base
│   │   └── session.py       # get_db dependency
│   ├── models/
│   │   ├── user.py          # USERS table
│   │   ├── role.py          # ROLES + USER_ROLES tables
│   │   └── refresh_token.py # REFRESH_TOKENS table
│   ├── schemas/
│   │   ├── auth.py          # Request/Response Pydantic models
│   │   └── user.py          # User profile schemas
│   ├── services/
│   │   ├── auth_service.py  # Core business logic
│   │   ├── oauth_service.py # OAuth provider handling
│   │   └── token_service.py # Refresh token DB operations
│   ├── middleware/
│   │   └── auth_middleware.py # JWT dependency, RBAC
│   └── main.py              # FastAPI app, startup, routers
├── alembic/                 # DB migration scripts
├── tests/                   # pytest test suite
├── .env.example             # Environment variable template
├── alembic.ini
├── Dockerfile
└── pyproject.toml
```

---

## Step-by-Step Setup

### Step 1 — Prerequisites

Make sure you have:
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) installed: `pip install uv`
- Oracle Database 23c running (or Oracle XE for local dev)
- Redis running (for rate limiting)

### Step 2 — Clone & Navigate

```bash
git clone <your-repo-url>
cd project-root/auth
git checkout -b auth-service
```

### Step 3 — Install Dependencies

```bash
uv pip install -e .
```

### Step 4 — Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
SECRET_KEY=your-random-32+-char-secret-key
ORACLE_USER=auth_user
ORACLE_PASSWORD=your_password
ORACLE_DSN=localhost:1521/XEPDB1
REDIS_URL=redis://localhost:6379
```

Generate a secure SECRET_KEY:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Step 5 — Oracle Database Setup

Connect to Oracle and run:

```sql
-- Create user/schema for the auth service
CREATE USER auth_user IDENTIFIED BY your_password;
GRANT CONNECT, RESOURCE TO auth_user;
GRANT CREATE SESSION TO auth_user;
GRANT UNLIMITED TABLESPACE TO auth_user;
```

### Step 6 — Run Database Migrations

```bash
# Initialize Alembic (already done — just run the migration)
alembic upgrade head
```

If you need to generate a new migration after model changes:
```bash
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

### Step 7 — Run the Server

```bash
# Development
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Step 8 — Access API Docs

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## API Reference

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Register new user |
| POST | `/auth/login` | Login, get JWT tokens |
| POST | `/auth/logout` | Revoke refresh token |
| POST | `/auth/refresh` | Rotate tokens |
| GET | `/auth/me` | Get current user profile |
| POST | `/auth/forgot-password` | Request reset email |
| POST | `/auth/reset-password` | Reset with token |
| POST | `/auth/verify-email` | Verify email token |

### OAuth

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/auth/google/login` | Start Google OAuth |
| GET | `/auth/google/callback` | Google callback |
| GET | `/auth/github/login` | Start GitHub OAuth |
| GET | `/auth/github/callback` | GitHub callback |
| GET | `/auth/facebook/login` | Start Facebook OAuth |
| GET | `/auth/facebook/callback` | Facebook callback |
| GET | `/auth/apple/login` | Start Apple Sign In |
| POST | `/auth/apple/callback` | Apple callback |

### Authorization (for other microservices)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/verify-token` | Validate JWT token |
| GET | `/auth/user/{id}` | Get user by ID |
| GET | `/auth/permissions` | Get user permissions |

---

## JWT Token Structure

**Access Token** (15 min):
```json
{
  "sub": "user-uuid",
  "email": "user@example.com",
  "role": ["VIEWER"],
  "exp": 1234567890,
  "iat": 1234567890
}
```

**Refresh Token** (7 days):
```json
{
  "sub": "user-uuid",
  "type": "refresh",
  "exp": 1234567890,
  "iat": 1234567890
}
```

---

## RBAC Roles

| Role | Description |
|------|-------------|
| OWNER | Full access to everything |
| ADMIN | Manage users, all projects |
| DEVELOPER | Own projects, code execution, AI |
| VIEWER | Read-only access |
| AI_AGENT | AI and code execution only |

---

## Setting Up OAuth Providers

### Google
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create OAuth 2.0 credentials
3. Add `http://localhost:8000/auth/google/callback` as authorized redirect URI
4. Copy Client ID and Secret to `.env`

### GitHub
1. Go to GitHub → Settings → Developer settings → OAuth Apps
2. Set callback URL to `http://localhost:8000/auth/github/callback`
3. Copy Client ID and Secret to `.env`

### Facebook
1. Go to [developers.facebook.com](https://developers.facebook.com)
2. Create a new app → Add Facebook Login product
3. Set Valid OAuth Redirect URIs to `http://localhost:8000/auth/facebook/callback`
4. Copy App ID and Secret to `.env`

### Apple
1. Go to [developer.apple.com](https://developer.apple.com)
2. Create a Services ID with Sign In with Apple capability
3. Generate a private key (.p8 file)
4. Fill in `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY_PATH` in `.env`

---

## Running Tests

```bash
# Install test deps
uv pip install pytest pytest-asyncio httpx aiosqlite

# Run tests
pytest tests/ -v
```

---

## Docker

```bash
# Build
docker build -t auth-microservice .

# Run
docker run -p 8000:8000 --env-file .env auth-microservice
```

---

## How Other Microservices Use This

Other services (Project, AI, Collaboration, Runtime) call:

```http
POST /auth/verify-token
Content-Type: application/json

{ "token": "<JWT from Authorization header>" }
```

Response:
```json
{
  "valid": true,
  "user_id": "uuid",
  "email": "user@example.com",
  "roles": ["DEVELOPER"]
}
```

---

## Security Features

- ✅ bcrypt password hashing
- ✅ JWT access tokens (15 min) + refresh token rotation (7 days)
- ✅ Account lockout after 5 failed attempts
- ✅ Email verification required
- ✅ Token revocation on logout/password change
- ✅ HTTPS enforced in production
- ✅ Rate limiting via Redis
- ✅ RBAC with role-based permissions
- ✅ Generic error messages (no user enumeration)
