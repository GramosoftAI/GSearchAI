"""Admin ORM Models with Multi-Tenancy (RLS) support"""

import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID
from sqlalchemy.sql import func
from app.models.base import Base


class AdminAnnouncement(Base):
    """Platform / Tenant Admin announcement or bulletin board note"""
    __tablename__ = "admin_announcements"

    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    priority = Column(String(50), default="info", nullable=False)  # "info", "warning", "critical", "success"
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

