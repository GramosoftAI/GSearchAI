"""Phase 2 Database Knowledge Layer ORM Models

Defines models under kb2_ prefix:
- KB2KnowledgeItem: kb2_knowledge_items
- KB2EntityValue: kb2_entity_values
- KB2QueryMemory: kb2_query_memory

Strictly tenant-isolated with PostgreSQL RLS support.
Phase 2 is built FRESH and does not depend on legacy semantic/ schema_doc/ modules.
"""

import uuid
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    Index,
    Boolean,
    Float,
    Integer,
    UniqueConstraint,
    CheckConstraint,
    Computed,
    UUID as SQLAlchemyUUID,
)
from sqlalchemy.orm import validates
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, ARRAY
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.models.base import Base
from app.core.config import get_settings
from ..sensitivity import validate_not_sensitive

settings = get_settings()


class KB2KnowledgeItem(Base):
    """Unified metadata & governance item for database knowledge (Phase 2)."""
    __tablename__ = "kb2_knowledge_items"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    db_knowledgebase_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("database_knowledgebases.id", ondelete="CASCADE"), nullable=False, index=True)

    item_type = Column(String(50), nullable=False)
    item_key = Column(String(512), nullable=False)
    valid_from_version = Column(String(64), nullable=False)
    object_hash = Column(String(64), nullable=False)

    source = Column(String(30), nullable=False)
    status = Column(String(30), server_default="draft", nullable=False)
    is_locked_by_admin = Column(Boolean, server_default="false", nullable=False)
    is_sensitive = Column(Boolean, server_default="false", nullable=False)
    confidence = Column(Float, server_default="1.0", nullable=False)

    payload = Column(JSONB, server_default="{}", nullable=False)
    staged_payload = Column(JSONB, nullable=True)

    reviewed_by = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("db_knowledgebase_id", "item_type", "item_key", name="uq_kb2_ki_kb_type_key"),
        CheckConstraint(
            "item_type IN ('table', 'column', 'relationship', 'metric', 'rule', 'example', 'glossary')",
            name="ck_kb2_ki_item_type",
        ),
        CheckConstraint(
            "source IN ('declared', 'inferred', 'llm', 'admin')",
            name="ck_kb2_ki_source",
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'rejected', 'conflict', 'stale')",
            name="ck_kb2_ki_status",
        ),
        Index("ix_kb2_ki_tenant_id", "tenant_id"),
        Index("ix_kb2_ki_lookup", "db_knowledgebase_id", "item_type", "status"),
        Index("ix_kb2_ki_tenant_kb_type", "tenant_id", "db_knowledgebase_id", "item_type"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<KB2KnowledgeItem id={self.id} kb={self.db_knowledgebase_id} "
            f"type='{self.item_type}' key='{self.item_key}' status='{self.status}'>"
        )


class KB2EntityValue(Base):
    """Indexed distinct/categorical column entity values for grounded fuzzy/semantic lookup."""
    __tablename__ = "kb2_entity_values"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    db_knowledgebase_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("database_knowledgebases.id", ondelete="CASCADE"), nullable=False, index=True)

    table_name = Column(String(255), nullable=False)
    column_name = Column(String(255), nullable=False)
    raw_value = Column(Text, nullable=False)
    normalized_value = Column(Text, nullable=False)
    frequency_count = Column(Integer, nullable=True)

    # tsvector using PostgreSQL 'simple' dictionary
    tsv_value = Column(TSVECTOR, Computed("to_tsvector('simple', raw_value)", persisted=True), nullable=True)
    embedding = Column(Vector(settings.embedding_dimension), nullable=True)

    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("db_knowledgebase_id", "table_name", "column_name", "normalized_value", name="uq_kb2_entity_val"),
        CheckConstraint("length(normalized_value) <= 255", name="ck_kb2_ev_normalized_value_len"),
        Index("ix_kb2_ev_tenant_id", "tenant_id"),
        Index("ix_kb2_ev_lookup", "db_knowledgebase_id", "table_name", "column_name"),
        Index("ix_kb2_ev_tsv", "tsv_value", postgresql_using="gin"),
        {"extend_existing": True},
    )

    @validates("column_name")
    def validate_column_not_sensitive(self, key: str, column_name: str) -> str:
        """Reject sensitive columns at write time."""
        validate_not_sensitive(column_name)
        return column_name

    def __repr__(self) -> str:
        return (
            f"<KB2EntityValue id={self.id} kb={self.db_knowledgebase_id} "
            f"col='{self.table_name}.{self.column_name}' val='{self.raw_value[:20]}'>"
        )


class KB2QueryMemory(Base):
    """Verified query execution and NL-to-SQL plan cache with referenced items."""
    __tablename__ = "kb2_query_memory"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    db_knowledgebase_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("database_knowledgebases.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_version = Column(String(64), nullable=False, index=True)

    natural_query = Column(Text, nullable=False)
    normalized_query = Column(Text, nullable=False)
    compiled_sql = Column(Text, nullable=False)
    plan_ir = Column(JSONB, nullable=False)
    execution_stats = Column(JSONB, server_default="{}", nullable=False)

    status = Column(String(30), server_default="verified", nullable=False)
    is_locked_by_admin = Column(Boolean, server_default="false", nullable=False)
    referenced_items = Column(ARRAY(Text), server_default="{}", nullable=False)

    embedding = Column(Vector(settings.embedding_dimension), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("db_knowledgebase_id", "schema_version", "normalized_query", name="uq_kb2_qm_kb_ver_query"),
        CheckConstraint("status IN ('verified', 'deprecated')", name="ck_kb2_qm_status"),
        Index("ix_kb2_qm_tenant_id", "tenant_id"),
        Index("ix_kb2_qm_lookup", "db_knowledgebase_id", "schema_version", "status"),
        Index("ix_kb2_qm_referenced_items", "referenced_items", postgresql_using="gin"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<KB2QueryMemory id={self.id} kb={self.db_knowledgebase_id} "
            f"ver='{self.schema_version}' query='{self.natural_query[:30]}'>"
        )


class KB2JobRun(Base):
    """Pipeline execution tracking and heartbeat record (Phase 2)."""
    __tablename__ = "kb2_job_runs"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    db_knowledgebase_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("database_knowledgebases.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_version = Column(String(64), nullable=False)

    status = Column(String(30), server_default="queued", nullable=False)
    stages = Column(JSONB, server_default="{}", nullable=False)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'superseded')",
            name="ck_kb2_job_runs_status",
        ),
        Index("ix_kb2_job_runs_tenant_id", "tenant_id"),
        Index("ix_kb2_job_runs_lookup", "db_knowledgebase_id", "schema_version", "status"),
        Index("ix_kb2_job_runs_heartbeat", "status", "heartbeat_at"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<KB2JobRun id={self.id} kb={self.db_knowledgebase_id} "
            f"ver='{self.schema_version}' status='{self.status}'>"
        )


class KB2AuditLog(Base):
    """Audit log tracking all admin actions on knowledge items (Phase 2)."""
    __tablename__ = "kb2_audit_log"

    id = Column(SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    db_knowledgebase_id = Column(SQLAlchemyUUID(as_uuid=True), ForeignKey("database_knowledgebases.id", ondelete="CASCADE"), nullable=False, index=True)

    actor = Column(String(255), nullable=False)
    action = Column(String(100), nullable=False)
    item_key = Column(String(512), nullable=False)
    before = Column(JSONB, nullable=True)
    after = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_kb2_audit_tenant_id", "tenant_id"),
        Index("ix_kb2_audit_lookup", "db_knowledgebase_id", "item_key"),
        Index("ix_kb2_audit_created", "created_at"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<KB2AuditLog id={self.id} kb={self.db_knowledgebase_id} "
            f"action='{self.action}' item='{self.item_key}'>"
        )


