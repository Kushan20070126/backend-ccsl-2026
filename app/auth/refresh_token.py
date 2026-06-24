import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db.database import Base


class RefreshToken(Base):
    __tablename__ = "REFRESH_TOKENS"

    TOKEN_ID = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    USER_ID = Column(String(36), ForeignKey("USERS.USER_ID"), nullable=False, index=True)
    TOKEN = Column(String(512), unique=True, nullable=False)
    EXPIRES_AT = Column(DateTime(timezone=True), nullable=False)
    IS_REVOKED = Column(Boolean, default=False, nullable=False)
    CREATED_AT = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationship
    user = relationship("User", back_populates="refresh_tokens")

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.EXPIRES_AT

    @property
    def is_valid(self) -> bool:
        return not self.IS_REVOKED and not self.is_expired

    def __repr__(self):
        return f"<RefreshToken user={self.USER_ID} revoked={self.IS_REVOKED}>"
