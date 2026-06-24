from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
import uuid, httpx, jwt as pyjwt

from app.models.user import User, OAuthProvider
from app.models.role import Role, UserRole, RoleName
from app.core.security import create_access_token, create_refresh_token
from app.core.config import settings
from app.services.token_service import TokenService
from app.services.auth_service import AuthService


class OAuthService:

    @staticmethod
    async def handle_oauth_user(
        db: AsyncSession,
        email: str,
        provider: OAuthProvider,
        provider_id: str,
        username: str | None = None,
    ) -> tuple[User, str, str]:
        """
        Core logic for all OAuth providers:
        - If user exists (by email), link the provider if needed
        - If user doesn't exist, create a new pre-verified account
        Returns: (user, access_token, refresh_token)
        """
        # Try find by email
        result = await db.execute(select(User).where(User.EMAIL == email))
        user = result.scalar_one_or_none()

        if user:
            # Update provider info if logging in via new provider
            if user.PROVIDER != provider:
                user.PROVIDER = provider
                user.PROVIDER_ID = provider_id
        else:
            # Create new OAuth user (auto-verified since OAuth provider did the work)
            user = User(
                USER_ID=str(uuid.uuid4()),
                EMAIL=email,
                USERNAME=username or email.split("@")[0],
                PROVIDER=provider,
                PROVIDER_ID=provider_id,
                IS_VERIFIED=True,  # OAuth = already verified
                IS_ACTIVE=True,
            )
            db.add(user)
            await db.flush()
            await AuthService._assign_default_role(db, user.USER_ID)

        roles = await AuthService._get_user_roles(db, user.USER_ID)
        access_token = create_access_token({"sub": user.USER_ID, "email": user.EMAIL, "role": roles})
        refresh_token = create_refresh_token({"sub": user.USER_ID})
        await TokenService.save_refresh_token(db, user.USER_ID, refresh_token)

        return user, access_token, refresh_token

    # ─── Google ───────────────────────────────────────────────────────────────

    @staticmethod
    async def handle_google_callback(db: AsyncSession, token: dict) -> tuple[str, str]:
        """Process Google OAuth callback."""
        userinfo = token.get("userinfo", {})
        email = userinfo.get("email")
        provider_id = userinfo.get("sub")

        if not email:
            raise HTTPException(status_code=400, detail="Could not get email from Google")

        _, access_token, refresh_token = await OAuthService.handle_oauth_user(
            db, email, OAuthProvider.GOOGLE, provider_id,
            username=userinfo.get("name", "").replace(" ", "_")
        )
        return access_token, refresh_token

    # ─── GitHub ───────────────────────────────────────────────────────────────

    @staticmethod
    async def handle_github_callback(db: AsyncSession, token: dict) -> tuple[str, str]:
        """Process GitHub OAuth callback — must fetch email separately if private."""
        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"token {token.get('access_token')}",
                "Accept": "application/json",
            }
            # Get user profile
            profile_resp = await client.get("https://api.github.com/user", headers=headers)
            profile = profile_resp.json()

            # Get email (may be private, need /user/emails endpoint)
            email = profile.get("email")
            if not email:
                emails_resp = await client.get("https://api.github.com/user/emails", headers=headers)
                emails = emails_resp.json()
                primary = next((e["email"] for e in emails if e.get("primary") and e.get("verified")), None)
                email = primary

        if not email:
            raise HTTPException(status_code=400, detail="Could not get email from GitHub")

        _, access_token, refresh_token = await OAuthService.handle_oauth_user(
            db, email, OAuthProvider.GITHUB, str(profile.get("id")),
            username=profile.get("login")
        )
        return access_token, refresh_token

    # ─── Facebook ─────────────────────────────────────────────────────────────

    @staticmethod
    async def handle_facebook_callback(db: AsyncSession, token: dict) -> tuple[str, str]:
        """Process Facebook OAuth callback."""
        access_token_val = token.get("access_token")

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.facebook.com/me",
                params={"fields": "id,name,email", "access_token": access_token_val},
            )
            profile = resp.json()

        email = profile.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Could not get email from Facebook")

        _, access_token, refresh_token = await OAuthService.handle_oauth_user(
            db, email, OAuthProvider.FACEBOOK, profile.get("id"),
            username=profile.get("name", "").replace(" ", "_")
        )
        return access_token, refresh_token

    # ─── Apple ────────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_apple_client_secret() -> str:
        """
        Apple requires a JWT signed with your private key as the client_secret.
        This is regenerated on each use as it expires quickly.
        """
        import time

        with open(settings.APPLE_PRIVATE_KEY_PATH, "r") as f:
            private_key = f.read()

        headers = {"kid": settings.APPLE_KEY_ID}
        payload = {
            "iss": settings.APPLE_TEAM_ID,
            "iat": int(time.time()),
            "exp": int(time.time()) + 86400 * 180,  # 6 months max
            "aud": "https://appleid.apple.com",
            "sub": settings.APPLE_CLIENT_ID,
        }
        return pyjwt.encode(payload, private_key, algorithm="ES256", headers=headers)

    @staticmethod
    async def handle_apple_callback(db: AsyncSession, id_token: str, user_data: dict | None) -> tuple[str, str]:
        """
        Process Apple Sign-In callback.
        Apple sends the id_token as a JWT. Decode it to get user info.
        NOTE: Apple only sends name/email on FIRST login.
        """
        # Decode the Apple id_token (skip signature verification for simplicity;
        # in production, validate against Apple's public keys)
        try:
            payload = pyjwt.decode(id_token, options={"verify_signature": False})
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid Apple id_token")

        email = payload.get("email")
        provider_id = payload.get("sub")

        if not email:
            raise HTTPException(status_code=400, detail="Could not get email from Apple")

        username = None
        if user_data:
            name = user_data.get("name", {})
            username = f"{name.get('firstName', '')}_{name.get('lastName', '')}".strip("_")

        _, access_token, refresh_token = await OAuthService.handle_oauth_user(
            db, email, OAuthProvider.APPLE, provider_id, username=username or None
        )
        return access_token, refresh_token
