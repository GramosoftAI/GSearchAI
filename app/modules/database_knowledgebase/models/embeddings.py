"""Database Schema Vector Embedding Model

Stores dense vector representations and semantic metadata for database schema elements:
- Database summary documents
- Schema documents
- Table documents
- Column documents
- Relationship documents

Strictly isolated in 'db_schema_embeddings' and version-pinned to SHA-256 schema fingerprints.
"""

import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    Index,
    UUID as SQLAlchemyUUID,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.models.base import Base
from app.core.config import get_settings

settings = get_settings()


class DatabaseSchemaEmbedding(Base):
    """
    Stores vector embeddings and semantic metadata for database schema elements.

    CRITICAL:
    - Scoped by tenant_id for RLS multi-tenant isolation.
    - Associated with a specific database_knowledgebase_id.
    - Pinned to a specific schema_version (deterministic SHA-256 fingerprint).
    - Isolated in its own table 'db_schema_embeddings'.
    """
    __tablename__ = "db_schema_embeddings"

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
        nullable=False,
        index=True,
    )

    db_knowledgebase_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("database_knowledgebases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    schema_version = Column(
        String(64),
        nullable=False,
        index=True,
    )

    entity_type = Column(
        String(30),
        nullable=False,
        index=True,
    )  # 'database', 'schema', 'table', 'column', 'relationship'

    entity_key = Column(
        String(255),
        nullable=False,
        index=True,
    )  # e.g., 'public.customers', 'public.orders.total_amount', 'rel:orders->order_items'

    document_text = Column(
        Text,
        nullable=False,
    )

    embedding = Column(
        Vector(settings.embedding_dimension),
        nullable=False,
    )

    metadata_json = Column(
        JSONB,
        nullable=False,
        default=dict,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_db_schema_emb_tenant_kb_ver", "tenant_id", "db_knowledgebase_id", "schema_version"),
        Index("ix_db_schema_emb_entity", "db_knowledgebase_id", "schema_version", "entity_type"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<DatabaseSchemaEmbedding id={self.id} type='{self.entity_type}' "
            f"key='{self.entity_key}' version='{self.schema_version[:8]}'>"
        )
