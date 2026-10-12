"""User-defined Database Mapping ORM Model

Represents custom relationships/foreign keys configured by users on the Schema ER Diagram.
Directly ingested into the Universal Semantic Model and Text-to-SQL planning pipeline.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, String, Boolean, Text, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID, JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base


class KBUserMapping(Base):
    """
    User-defined foreign key / relationship mapping.
    Stored table: k2b_user_mapping
    """

    __tablename__ = "k2b_user_mapping"

    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    db_knowledgebase_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("database_knowledgebases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Physical mapping references
    source_table = Column(String(255), nullable=False)
    source_column = Column(String(255), nullable=False)
    target_table = Column(String(255), nullable=False)
    target_column = Column(String(255), nullable=False)

    # Relationship metadata & pipeline controls
    relationship_type = Column(String(50), default="many_to_one", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sync_status = Column(String(50), default="SUCCESS", nullable=False)  # 'SUCCESS' or 'FAILED'
    sync_error = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    extra_metadata = Column(JSONB, default=dict, nullable=False)

    created_at = Column(
        String,
        default=lambda: datetime.now(timezone.utc).isoformat(),
        nullable=False,
    )
    updated_at = Column(
        String,
        default=lambda: datetime.now(timezone.utc).isoformat(),
        onupdate=lambda: datetime.now(timezone.utc).isoformat(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "db_knowledgebase_id",
            "source_table",
            "source_column",
            "target_table",
            "target_column",
            name="uq_kb_user_mapping",
        ),
    )
