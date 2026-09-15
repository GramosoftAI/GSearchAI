"""SQLAlchemy ORM Model for Phase 3A: Database Knowledgebase Query Audit Logging

Persists comprehensive, non-sensitive audit records for every executed query.
Strictly excludes passwords, DSNs, raw parameter values, and raw database rows.
Enforces tenant isolation via foreign key and indexed queries.
"""

from datetime import datetime
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UUID as SQLAlchemyUUID,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.models.base import Base


class DatabaseQueryAuditLog(Base):
    """
    Persistent audit record for a single Database Knowledgebase natural language query execution.
    Contains timing breakdowns, safety verification outcomes, and structural metadata.
    """
    __tablename__ = "db_query_audit_logs"

    # ============= IDENTIFIERS & MULTI-TENANCY =============
    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )
    query_id = Column(String(64), nullable=False, index=True)
    request_id = Column(String(64), nullable=True, index=True)
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    knowledgebase_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("database_knowledgebases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_version = Column(String(64), nullable=True)

    # ============= QUERY METADATA =============
    request_timestamp = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    user_query_hash = Column(String(64), nullable=False)
    user_query_length = Column(Integer, nullable=False, default=0)
    sanitized_user_query = Column(Text, nullable=False)

    # ============= STAGE LATENCIES (MILLISECONDS) =============
    retrieval_latency_ms = Column(Float, nullable=False, default=0.0)
    planning_latency_ms = Column(Float, nullable=False, default=0.0)
    sql_generation_latency_ms = Column(Float, nullable=False, default=0.0)
    validation_latency_ms = Column(Float, nullable=False, default=0.0)
    database_execution_latency_ms = Column(Float, nullable=False, default=0.0)
    result_normalization_latency_ms = Column(Float, nullable=False, default=0.0)
    answer_synthesis_latency_ms = Column(Float, nullable=False, default=0.0)
    grounding_verification_latency_ms = Column(Float, nullable=False, default=0.0)
    total_latency_ms = Column(Float, nullable=False, default=0.0)

    # ============= EXECUTION RESULTS (STRUCTURAL ONLY - ZERO ROWS) =============
    row_count = Column(Integer, nullable=False, default=0)
    truncated = Column(Boolean, nullable=False, default=False)
    column_count = Column(Integer, nullable=False, default=0)
    answer_type = Column(String(32), nullable=False, default="UNKNOWN")

    # ============= LLM TELEMETRY =============
    llm_used = Column(Boolean, nullable=False, default=False)
    llm_attempts = Column(Integer, nullable=False, default=0)
    repair_attempts = Column(Integer, nullable=False, default=0)

    # ============= SAFETY & VERIFICATION GATES =============
    ast_valid = Column(Boolean, nullable=False, default=True)
    grounding_status = Column(String(32), nullable=False, default="UNKNOWN")
    verification_status = Column(String(32), nullable=False, default="UNKNOWN")
    fallback_used = Column(Boolean, nullable=False, default=False)

    # ============= STATUS & AUDIT METADATA =============
    error_type = Column(String(64), nullable=True)
    sanitized_error = Column(Text, nullable=True)
    final_status = Column(String(32), nullable=False, default="SUCCESS", index=True)
    audit_metadata = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_db_audit_tenant_id", "tenant_id"),
        Index("ix_db_audit_query_id", "query_id"),
        Index("ix_db_audit_kb_id", "knowledgebase_id"),
        Index("ix_db_audit_tenant_kb", "tenant_id", "knowledgebase_id"),
        Index("ix_db_audit_tenant_created", "tenant_id", "request_timestamp"),
        Index("ix_db_audit_tenant_status", "tenant_id", "final_status"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<DatabaseQueryAuditLog query_id='{self.query_id}' "
            f"tenant_id='{self.tenant_id}' kb_id='{self.knowledgebase_id}' "
            f"status='{self.final_status}' rows={self.row_count} latency_ms={self.total_latency_ms}>"
        )
