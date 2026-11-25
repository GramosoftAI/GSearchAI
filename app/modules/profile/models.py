"""User Profile model for Profile Management"""

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Index, text, JSON
from sqlalchemy.sql import func
import uuid
from sqlalchemy import UUID

from ...models.base import Base


class UserProfile(Base):
    """
    UserProfile model - maintains personal profile and metadata independently.

    CRITICAL:
    - user_id is 1:1 with users.id (CASCADE on delete)
    - tenant_id is used for RLS filtering and strict tenant isolation
    - Synchronized with login credentials (email, registered username, names)
    """

    __tablename__ = "user_profiles"

    # ============= PRIMARY KEY =============
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= RELATIONSHIPS =============
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # RLS filtering
    )

    # ============= CORE LOGIN ATTRIBUTES =============
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), index=True, nullable=False)

    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    display_name = Column(String(200), nullable=True)

    # ============= CONTACT & PERSONAL =============
    phone_number = Column(String(50), nullable=True)
    avatar_url = Column(String(1000), nullable=True)
    bio = Column(String(1000), nullable=True)

    # ============= WORK & ORGANIZATION =============
    job_title = Column(String(200), nullable=True)
    department = Column(String(200), nullable=True)
    organization = Column(String(200), nullable=True)
    country = Column(String(100), nullable=True)

    # ============= PREFERENCES =============
    timezone = Column(String(100), default="UTC", nullable=False)
    language = Column(String(20), default="en", nullable=False)
    theme = Column(String(20), default="system", nullable=False)  # "light", "dark", "system"
    notification_preferences = Column(JSON, default=dict, nullable=False)
    custom_metadata = Column(JSON, default=dict, nullable=True)

    # ============= TIMESTAMPS =============
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ============= INDEXES =============
    __table_args__ = (
        Index("ix_user_profiles_tenant_user", "tenant_id", "user_id"),
        Index("ix_user_profiles_tenant_email", "tenant_id", "email"),
    )

    def __repr__(self) -> str:
        return f"<UserProfile id={self.id} user_id={self.user_id} username={self.username} email={self.email}>"
