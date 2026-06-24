from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import decode_token
from app.models.user import User
from app.models.role import Role, UserRole, RoleName
from app.db.session import get_db

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency: Extract and validate JWT, return the current user.
    Use this on any protected route.
    """
    token = credentials.credentials
    payload = decode_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    result = await db.execute(select(User).where(User.USER_ID == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.IS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


async def get_current_verified_user(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: Require email verification."""
    if not current_user.IS_VERIFIED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your email first.",
        )
    return current_user


def require_roles(*required_roles: RoleName):
    """
    Role-based access control dependency factory.

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user = Depends(require_roles(RoleName.ADMIN, RoleName.OWNER))):
            ...
    """
    async def role_checker(
        current_user: User = Depends(get_current_verified_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        result = await db.execute(
            select(Role.ROLE_NAME)
            .join(UserRole, UserRole.ROLE_ID == Role.ROLE_ID)
            .where(UserRole.USER_ID == current_user.USER_ID)
        )
        user_roles = {row[0] for row in result.fetchall()}
        required_set = {r.value for r in required_roles}

        if not user_roles.intersection(required_set):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(required_set)}",
            )
        return current_user

    return role_checker
