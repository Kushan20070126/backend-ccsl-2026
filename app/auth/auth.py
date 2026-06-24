from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.auth import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshRequest,
    ForgotPasswordRequest, ResetPasswordRequest, VerifyEmailRequest,
    MessageResponse, AccessTokenResponse, VerifyTokenRequest, VerifyTokenResponse
)
from app.schemas.user import UserProfile
from app.services.auth_service import AuthService
from app.core.security import decode_token
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ─── POST /auth/register ──────────────────────────────────────────────────────

@router.post("/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new user.
    Sends a verification email in the background.
    """
    user = await AuthService.register(db, data)
    token = await AuthService.send_verification_email(user.EMAIL)

    # In production, send email via SMTP here
    # background_tasks.add_task(send_email, user.EMAIL, token)
    # For development, we log the token
    print(f"[DEV] Email verification token for {user.EMAIL}: {token}")

    return MessageResponse(message="Registration successful. Please check your email to verify your account.")


# ─── POST /auth/login ─────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and return JWT access + refresh tokens."""
    user, access_token, refresh_token = await AuthService.login(db, data)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ─── POST /auth/logout ────────────────────────────────────────────────────────

@router.post("/logout", response_model=MessageResponse)
async def logout(
    data: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Logout by revoking the provided refresh token."""
    await AuthService.logout(db, data.refresh_token)
    return MessageResponse(message="Logged out successfully")


# ─── POST /auth/refresh ───────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    data: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a valid refresh token for a new access + refresh token pair (rotation)."""
    new_access, new_refresh = await AuthService.refresh_access_token(db, data.refresh_token)
    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ─── GET /auth/me ─────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserProfile)
async def get_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the currently authenticated user's profile."""
    roles = await AuthService._get_user_roles(db, current_user.USER_ID)
    return UserProfile(
        user_id=current_user.USER_ID,
        email=current_user.EMAIL,
        username=current_user.USERNAME,
        provider=current_user.PROVIDER,
        is_verified=current_user.IS_VERIFIED,
        is_active=current_user.IS_ACTIVE,
        roles=roles,
        created_at=current_user.CREATED_AT,
    )


# ─── POST /auth/forgot-password ───────────────────────────────────────────────

@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a password reset email.
    Always returns success to prevent email enumeration.
    """
    token = await AuthService.forgot_password(db, data.email)
    if token:
        # In production: background_tasks.add_task(send_reset_email, data.email, token)
        print(f"[DEV] Password reset token for {data.email}: {token}")
    return MessageResponse(message="If that email exists, a reset link has been sent.")


# ─── POST /auth/reset-password ────────────────────────────────────────────────

@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset password using the token from the reset email."""
    await AuthService.reset_password(db, data.token, data.new_password)
    return MessageResponse(message="Password reset successfully. Please log in with your new password.")


# ─── POST /auth/verify-email ──────────────────────────────────────────────────

@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    data: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify a user's email address using the token from the verification email."""
    await AuthService.verify_email(db, data.token)
    return MessageResponse(message="Email verified successfully. You can now log in.")


# ─── POST /auth/verify-token (for other microservices) ───────────────────────

@router.post("/verify-token", response_model=VerifyTokenResponse)
async def verify_token(
    data: VerifyTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Validate a JWT access token.
    Used by other microservices to verify user identity.
    """
    payload = decode_token(data.token)
    if not payload:
        return VerifyTokenResponse(valid=False)

    roles = payload.get("role", [])
    return VerifyTokenResponse(
        valid=True,
        user_id=payload.get("sub"),
        email=payload.get("email"),
        roles=roles if isinstance(roles, list) else [roles],
    )
