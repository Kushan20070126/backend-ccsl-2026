import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.orm import relationship
from app.db.database import Base
import enum


class OAuthProvider(str, enum.Enum):
    LOCAL = "LOCAL"
    GOOGLE = "GOOGLE"
    GITHUB = "GITHUB"
    FACEBOOK = "FACEBOOK"
    APPLE = "APPLE"


class User(Base):
    __tablename__ = "USERS"

    USER_ID = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    EMAIL = Column(String(255), unique=True, nullable=False, index=True)
    USERNAME = Column(String(100), unique=True, nullable=True)
    PASSWORD_HASH = Column(String(255), nullable=True)  # Null for OAuth users
    PROVIDER = Column(SAEnum(OAuthProvider), default=OAuthProvider.LOCAL, nullable=False)
    PROVIDER_ID = Column(String(255), nullable=True)  # OAuth provider's user ID
    IS_VERIFIED = Column(Boolean, default=False, nullable=False)
    IS_ACTIVE = Column(Boolean, default=True, nullable=False)
    FAILED_LOGIN_ATTEMPTS = Column(String(10), default="0")  # Track failed logins
    LOCKED_UNTIL = Column(DateTime(timezone=True), nullable=True)
    CREATED_AT = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    UPDATED_AT = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.EMAIL}>"
