from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.refresh_token import RefreshToken
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.core.config import settings
import uuid


class TokenService:

    @staticmethod
    async def save_refresh_token(db: AsyncSession, user_id: str, token: str) -> RefreshToken:
        """Persist a refresh token to the database."""
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        db_token = RefreshToken(
            TOKEN_ID=str(uuid.uuid4()),
            USER_ID=user_id,
            TOKEN=token,
            EXPIRES_AT=expires_at,
            IS_REVOKED=False,
        )
        db.add(db_token)
        await db.flush()
        return db_token

    @staticmethod
    async def get_refresh_token(db: AsyncSession, token: str) -> RefreshToken | None:
        """Fetch a refresh token record from DB."""
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.TOKEN == token)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def revoke_token(db: AsyncSession, token: str) -> None:
        """Revoke a specific refresh token."""
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.TOKEN == token)
            .values(IS_REVOKED=True)
        )

    @staticmethod
    async def revoke_all_user_tokens(db: AsyncSession, user_id: str) -> None:
        """Revoke ALL refresh tokens for a user (useful on logout / password change)."""
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.USER_ID == user_id)
            .values(IS_REVOKED=True)
        )

    @staticmethod
    async def rotate_refresh_token(
        db: AsyncSession, old_token: str, user_id: str, roles: list[str]
    ) -> tuple[str, str]:
        """
        Refresh Token Rotation:
        1. Revoke old refresh token
        2. Issue new access + refresh token pair
        """
        # Revoke the old token
        await TokenService.revoke_token(db, old_token)

        # Issue new pair
        payload = {"sub": user_id, "role": roles}
        new_access = create_access_token(payload)
        new_refresh = create_refresh_token({"sub": user_id})

        # Save new refresh token
        await TokenService.save_refresh_token(db, user_id, new_refresh)

        return new_access, new_refresh

    @staticmethod
    async def cleanup_expired_tokens(db: AsyncSession) -> None:
        """Remove expired tokens to keep the table clean (run periodically)."""
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.EXPIRES_AT < now)
        )
        tokens = result.scalars().all()
        for token in tokens:
            await db.delete(token)
