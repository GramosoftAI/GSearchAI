"""User-defined Table Alias ORM Model

Represents custom table aliases / alternative names configured by users on the Schema UI.
Directly ingested into the Schema Keyword Matcher, Retriever, and Query Rewriting pipeline.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, String, Text, ForeignKey, UniqueConstraint, Index, DateTime
from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID, JSONB
from sqlalchemy.sql import func

from app.models.base import Base


class KBTableAlias(Base):
    """
    User-defined alternative names / aliases for database tables.
    Stored table: k2b_table_aliases
    """

    __tablename__ = "k2b_table_aliases"

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

    table_name = Column(String(255), nullable=False)
    aliases = Column(JSONB, default=list, server_default="[]", nullable=False)
    description = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("db_knowledgebase_id", "table_name", name="uq_k2b_table_aliases_kb_tbl"),
        Index("ix_k2b_table_aliases_lookup", "db_knowledgebase_id", "table_name"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return f"<KBTableAlias kb={self.db_knowledgebase_id} table={self.table_name} aliases={self.aliases}>"
