from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.schemas.user import UserPublic, PermissionsResponse
from app.models.user import User
from app.models.role import Role, UserRole, RoleName
from app.middleware.auth_middleware import get_current_verified_user, require_roles
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Users"])

# Role → permissions mapping
ROLE_PERMISSIONS: dict[str, list[str]] = {
    RoleName.OWNER: ["*"],  # All permissions
    RoleName.ADMIN: ["manage_users", "manage_projects", "view_all", "execute_code", "use_ai"],
    RoleName.DEVELOPER: ["manage_own_projects", "execute_code", "use_ai", "collaborate"],
    RoleName.VIEWER: ["view_own_projects"],
    RoleName.AI_AGENT: ["use_ai", "execute_code"],
}


# ─── GET /auth/user/{id} ──────────────────────────────────────────────────────

@router.get("/user/{user_id}", response_model=UserPublic)
async def get_user_by_id(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(RoleName.ADMIN, RoleName.OWNER)),
):
    """
    Get a user by ID.
    Restricted to ADMIN and OWNER roles.
    Used by other microservices that need user info.
    """
    result = await db.execute(select(User).where(User.USER_ID == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    roles = await AuthService._get_user_roles(db, user.USER_ID)
    return UserPublic(
        user_id=user.USER_ID,
        email=user.EMAIL,
        username=user.USERNAME,
        roles=roles,
        is_active=user.IS_ACTIVE,
    )


# ─── GET /auth/permissions ────────────────────────────────────────────────────

@router.get("/permissions", response_model=PermissionsResponse)
async def get_permissions(
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current user's roles and resolved permissions.
    Used by frontend to show/hide UI elements.
    """
    roles = await AuthService._get_user_roles(db, current_user.USER_ID)

    # Collect all permissions for assigned roles
    permissions = set()
    for role in roles:
        role_perms = ROLE_PERMISSIONS.get(role, [])
        permissions.update(role_perms)

    return PermissionsResponse(
        user_id=current_user.USER_ID,
        roles=roles,
        permissions=sorted(permissions),
    )
