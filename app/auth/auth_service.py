from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from fastapi import HTTPException, status
import uuid

from app.models.user import User, OAuthProvider
from app.models.role import Role, UserRole, RoleName
from app.models.refresh_token import RefreshToken
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    create_email_verification_token,
    create_password_reset_token,
    decode_token,
)
from app.core.config import settings
from app.services.token_service import TokenService
from app.schemas.auth import RegisterRequest, LoginRequest


class AuthService:


    @staticmethod
    async def register(db: AsyncSession, data: RegisterRequest) -> User:
        """Register a new local user."""

        # Check if email already exists
        existing = await db.execute(select(User).where(User.EMAIL == data.email))
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Check if username is taken
        existing_username = await db.execute(
            select(User).where(User.USERNAME == data.username)
        )
        if existing_username.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken",
            )

        # Create user
        user = User(
            USER_ID=str(uuid.uuid4()),
            EMAIL=data.email,
            USERNAME=data.username,
            PASSWORD_HASH=hash_password(data.password),
            PROVIDER=OAuthProvider.LOCAL,
            IS_VERIFIED=False,
            IS_ACTIVE=True,
        )
        db.add(user)
        await db.flush()  # get USER_ID before assigning role

        # Assign default VIEWER role
        await AuthService._assign_default_role(db, user.USER_ID)

        return user


    @staticmethod
    async def login(db: AsyncSession, data: LoginRequest) -> tuple[User, str, str]:
        """
        Authenticate a local user.
        Returns: (user, access_token, refresh_token)
        Raises: HTTPException on failure.
        """
        result = await db.execute(select(User).where(User.EMAIL == data.email))
        user = result.scalar_one_or_none()

        # Generic error to prevent user enumeration
        invalid_err = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

        if not user:
            raise invalid_err

        # Check account lock
        if user.LOCKED_UNTIL and datetime.now(timezone.utc) < user.LOCKED_UNTIL:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Account locked. Try again after {user.LOCKED_UNTIL.isoformat()}",
            )

        # Verify password
        if not user.PASSWORD_HASH or not verify_password(data.password, user.PASSWORD_HASH):
            # Increment failed attempts
            attempts = int(user.FAILED_LOGIN_ATTEMPTS or 0) + 1
            lock_until = None
            if attempts >= settings.MAX_LOGIN_ATTEMPTS:
                lock_until = datetime.now(timezone.utc) + timedelta(
                    minutes=settings.LOCKOUT_DURATION_MINUTES
                )
            await db.execute(
                update(User)
                .where(User.USER_ID == user.USER_ID)
                .values(FAILED_LOGIN_ATTEMPTS=str(attempts), LOCKED_UNTIL=lock_until)
            )
            raise invalid_err

        if not user.IS_ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated",
            )

        # Reset failed attempts on success
        await db.execute(
            update(User)
            .where(User.USER_ID == user.USER_ID)
            .values(FAILED_LOGIN_ATTEMPTS="0", LOCKED_UNTIL=None)
        )

        # Get user roles
        roles = await AuthService._get_user_roles(db, user.USER_ID)

        # Generate tokens
        access_token = create_access_token({"sub": user.USER_ID, "email": user.EMAIL, "role": roles})
        refresh_token = create_refresh_token({"sub": user.USER_ID})
        await TokenService.save_refresh_token(db, user.USER_ID, refresh_token)

        return user, access_token, refresh_token


    @staticmethod
    async def logout(db: AsyncSession, refresh_token: str) -> None:
        """Revoke the provided refresh token."""
        token_record = await TokenService.get_refresh_token(db, refresh_token)
        if token_record:
            await TokenService.revoke_token(db, refresh_token)


    @staticmethod
    async def refresh_access_token(db: AsyncSession, refresh_token: str) -> tuple[str, str]:
        """Rotate refresh token and return new access + refresh token."""
        # Validate JWT
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

        # Check DB record
        token_record = await TokenService.get_refresh_token(db, refresh_token)
        if not token_record or not token_record.is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token expired or revoked",
            )

        user_id = payload["sub"]
        roles = await AuthService._get_user_roles(db, user_id)

        # Rotate
        new_access, new_refresh = await TokenService.rotate_refresh_token(
            db, refresh_token, user_id, roles
        )
        return new_access, new_refresh


    @staticmethod
    async def send_verification_email(user_email: str) -> str:
        """Generate and return email verification token (caller sends the email)."""
        return create_email_verification_token(user_email)

    @staticmethod
    async def verify_email(db: AsyncSession, token: str) -> None:
        """Mark user's email as verified."""
        payload = decode_token(token)
        if not payload or payload.get("purpose") != "email_verification":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification token",
            )

        email = payload.get("sub")
        result = await db.execute(select(User).where(User.EMAIL == email))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if user.IS_VERIFIED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Email already verified"
            )

        await db.execute(
            update(User).where(User.EMAIL == email).values(IS_VERIFIED=True)
        )


    @staticmethod
    async def forgot_password(db: AsyncSession, email: str) -> str | None:
        """
        Generate password reset token.
        Returns token if user exists, None otherwise (silent to prevent enumeration).
        """
        result = await db.execute(select(User).where(User.EMAIL == email))
        user = result.scalar_one_or_none()
        if not user:
            return None  # Don't reveal whether email exists
        return create_password_reset_token(email)

    @staticmethod
    async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
        """Reset the user's password using a valid reset token."""
        payload = decode_token(token)
        if not payload or payload.get("purpose") != "password_reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token",
            )

        email = payload.get("sub")
        new_hash = hash_password(new_password)

        result = await db.execute(select(User).where(User.EMAIL == email))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Update password and revoke all sessions for security
        await db.execute(
            update(User).where(User.EMAIL == email).values(PASSWORD_HASH=new_hash)
        )
        await TokenService.revoke_all_user_tokens(db, user.USER_ID)


    @staticmethod
    async def _assign_default_role(db: AsyncSession, user_id: str) -> None:
        """Assign VIEWER as the default role for new users."""
        result = await db.execute(
            select(Role).where(Role.ROLE_NAME == RoleName.VIEWER)
        )
        viewer_role = result.scalar_one_or_none()
        if viewer_role:
            db.add(UserRole(USER_ID=user_id, ROLE_ID=viewer_role.ROLE_ID))

    @staticmethod
    async def _get_user_roles(db: AsyncSession, user_id: str) -> list[str]:
        """Return list of role names for a user."""
        result = await db.execute(
            select(Role.ROLE_NAME)
            .join(UserRole, UserRole.ROLE_ID == Role.ROLE_ID)
            .where(UserRole.USER_ID == user_id)
        )
        return [row[0] for row in result.fetchall()]
