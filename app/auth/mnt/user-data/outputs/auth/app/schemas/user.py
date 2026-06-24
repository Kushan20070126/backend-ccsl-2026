from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from app.models.user import OAuthProvider
from app.models.role import RoleName


class UserProfile(BaseModel):
    user_id: str
    email: str
    username: Optional[str]
    provider: OAuthProvider
    is_verified: bool
    is_active: bool
    roles: List[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class UserPublic(BaseModel):
    user_id: str
    email: str
    username: Optional[str]
    roles: List[str]
    is_active: bool

    model_config = {"from_attributes": True}


class PermissionsResponse(BaseModel):
    user_id: str
    roles: List[str]
    permissions: List[str]
