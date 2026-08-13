"""
Analytics models for tracking conversational intelligence.
"""

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Index,
    Text,
    Enum,
    UUID as SQLAlchemyUUID,
)
from sqlalchemy.sql import func
import uuid
import enum
from ...models.base import Base

class ResponseStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    UNANSWERED = "UNANSWERED"
    CONFIDENCE_FAILURE = "CONFIDENCE_FAILURE"
    ERROR = "ERROR"

class AnalyticsSummary(Base):
    """Aggregated metrics for a session or report."""
    __tablename__ = "analytics_summaries"

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
    )

    session_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        nullable=True,
    )

    total_queries = Column(Integer, default=0, nullable=False)
    answered_queries = Column(Integer, default=0, nullable=False)
    unanswered_queries = Column(Integer, default=0, nullable=False)
    accuracy_score = Column(Float, default=0.0, nullable=False)
    avg_confidence = Column(Float, default=0.0, nullable=False)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_analytics_summaries_tenant_id", "tenant_id"),
        Index("ix_analytics_summaries_session_id", "session_id"),
    )

class AnalyticsQueryLog(Base):
    """Per-query analytics for deep-dive tracking."""
    __tablename__ = "analytics_query_logs"

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
    )

    session_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        nullable=True,
    )

    user_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    request_id = Column(String(255), nullable=True, index=True)
    model_name = Column(String(255), nullable=True, index=True)

    query = Column(Text, nullable=False)
    response_status = Column(Enum(ResponseStatus), default=ResponseStatus.SUCCESS, nullable=False)
    confidence_score = Column(Float, default=0.0, nullable=False)
    latency_ms = Column(Float, default=0.0, nullable=False)
    
    llm_input_tokens = Column(Integer, default=0, nullable=False)
    llm_output_tokens = Column(Integer, default=0, nullable=False)
    embedding_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    llm_cost_usd = Column(Float, default=0.0, nullable=False)
    embedding_cost_usd = Column(Float, default=0.0, nullable=False)
    total_cost_usd = Column(Float, default=0.0, nullable=False)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_query_logs_tenant_id", "tenant_id"),
        Index("ix_query_logs_session_id", "session_id"),
        Index("ix_query_logs_user_id", "user_id"),
        Index("ix_query_logs_model_name", "model_name"),
        Index("ix_query_logs_created_at", "created_at"),
        Index("ix_query_logs_tenant_user", "tenant_id", "user_id"),
        Index("ix_query_logs_tenant_model", "tenant_id", "model_name"),
        Index("ix_query_logs_tenant_created", "tenant_id", "created_at"),
    )


class AppErrorLog(Base):
    """Application and pipeline error logs for diagnostics."""
    __tablename__ = "app_error_logs"

    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )

    user_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    module = Column(String(100), nullable=False, index=True)      # e.g., "RAG", "Ingestion", "Auth", "API"
    endpoint = Column(String(255), nullable=True)                  # e.g., "/api/v1/chats/message"
    error_type = Column(String(100), nullable=False, index=True)   # e.g., "ValueError", "NameError"
    message = Column(Text, nullable=False)
    stack_trace = Column(Text, nullable=True)
    
    from sqlalchemy.dialects.postgresql import JSONB
    request_metadata = Column(JSONB, nullable=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_app_error_logs_tenant_id", "tenant_id"),
        Index("ix_app_error_logs_created_at", "created_at"),
    )
