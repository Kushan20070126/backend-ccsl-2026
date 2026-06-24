import enum
from sqlalchemy import Column, String, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from app.db.database import Base


class RoleName(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    DEVELOPER = "DEVELOPER"
    VIEWER = "VIEWER"
    AI_AGENT = "AI_AGENT"


class Role(Base):
    __tablename__ = "ROLES"

    ROLE_ID = Column(String(36), primary_key=True)
    ROLE_NAME = Column(SAEnum(RoleName), unique=True, nullable=False)

    # Relationships
    user_roles = relationship("UserRole", back_populates="role")

    def __repr__(self):
        return f"<Role {self.ROLE_NAME}>"


class UserRole(Base):
    __tablename__ = "USER_ROLES"

    USER_ID = Column(String(36), ForeignKey("USERS.USER_ID"), primary_key=True)
    ROLE_ID = Column(String(36), ForeignKey("ROLES.ROLE_ID"), primary_key=True)

    # Relationships
    user = relationship("User", back_populates="roles")
    role = relationship("Role", back_populates="user_roles")

    def __repr__(self):
        return f"<UserRole user={self.USER_ID} role={self.ROLE_ID}>"
