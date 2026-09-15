"""Database Knowledgebase ORM Models with Multi-Tenancy (RLS) and Encrypted Credentials Storage"""

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    Integer,
    UUID as SQLAlchemyUUID,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
import uuid
from typing import Dict, Any, Optional

from app.models.base import Base


class DatabaseKnowledgebase(Base):
    """
    Database Knowledgebase entity - represents a live relational database data source.

    CRITICAL ARCHITECTURAL CONSTRAINTS:
    - Belongs strictly to one tenant (enforced by PostgreSQL RLS + server context).
    - Database credentials are encrypted at rest with AES-GCM (Fernet) and NEVER stored in plaintext.
    - Plaintext credentials are NEVER exposed in string representations, logs, or API responses.
    - Tracks deterministic schema version / fingerprint for drift detection.
    """

    __tablename__ = "database_knowledgebases"

    # ============= PRIMARY KEY =============
    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= MULTI-TENANCY =============
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ============= OWNERSHIP & AGENT LINK =============
    user_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ============= METADATA =============
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    database_type = Column(String(50), nullable=False, default="postgresql")

    # ============= ENCRYPTED CREDENTIALS (NEVER PLAINTEXT) =============
    encrypted_credentials = Column(Text, nullable=False)

    # ============= LIFECYCLE & DRIFT TRACKING =============
    status = Column(String(50), nullable=False, default="configured")  # configured, tested, introspected, error
    schema_version = Column(String(64), nullable=True, index=True)  # SHA-256 canonical schema fingerprint
    last_tested_at = Column(DateTime(timezone=True), nullable=True)
    last_introspected_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)

    # ============= SOFT DELETE & ACTIVE STATUS =============
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

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

    __table_args__ = (
        Index("ix_db_kb_tenant_id", "tenant_id"),
        Index("ix_db_kb_tenant_user", "tenant_id", "user_id"),
        Index("ix_db_kb_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_db_kb_tenant_active", "tenant_id", "is_active"),
        {"extend_existing": True},
    )

    @property
    def tenant_metadata(self) -> Dict[str, Any]:
        """Tenant configuration metadata (e.g. antonym_overrides, canonical_overrides)."""
        if hasattr(self, "_tenant_metadata") and isinstance(self._tenant_metadata, dict):
            return self._tenant_metadata
        return {}

    @tenant_metadata.setter
    def tenant_metadata(self, val: Dict[str, Any]) -> None:
        self._tenant_metadata = val

    def __repr__(self) -> str:
        # Explicitly omit credentials from string representation
        return (
            f"<DatabaseKnowledgebase id={self.id} name='{self.name}' "
            f"type='{self.database_type}' tenant_id={self.tenant_id} status='{self.status}'>"
        )


class DatabaseSchemaSnapshot(Base):
    """
    Historical snapshot of a database schema catalog.
    Enables schema versioning, drift detection, and offline schema retrieval.
    """

    __tablename__ = "db_schema_snapshots"

    # ============= PRIMARY KEY =============
    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= MULTI-TENANCY =============
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ============= RELATIONSHIP =============
    db_knowledgebase_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("database_knowledgebases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ============= VERSIONING & PAYLOAD =============
    schema_version = Column(String(64), nullable=False, index=True)  # SHA-256 fingerprint
    schema_data = Column(JSONB, nullable=False)  # Serialized canonical DatabaseSchema

    # ============= SUMMARY METRICS =============
    table_count = Column(Integer, nullable=False, default=0)
    column_count = Column(Integer, nullable=False, default=0)
    relationship_count = Column(Integer, nullable=False, default=0)

    # ============= TIMESTAMP =============
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_db_snap_tenant_id", "tenant_id"),
        Index("ix_db_snap_db_kb", "db_knowledgebase_id"),
        Index("ix_db_snap_version", "db_knowledgebase_id", "schema_version"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<DatabaseSchemaSnapshot id={self.id} db_kb_id={self.db_knowledgebase_id} "
            f"version='{self.schema_version}' tables={self.table_count}>"
        )
