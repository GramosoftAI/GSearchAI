"""Audit Log API Schemas for Phase 3B

Defines request filter parameters and sanitized response representations
for tenant-isolated audit log querying and compliance inspection.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class AuditLogFilterParams(BaseModel):
    """Query parameters for filtering and paginating audit logs."""
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, ge=1, le=200, description="Maximum records to return")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    start_time: Optional[datetime] = Field(default=None, description="Filter logs starting at this timestamp")
    end_time: Optional[datetime] = Field(default=None, description="Filter logs ending at this timestamp")
    final_status: Optional[str] = Field(default=None, description="Filter by status (SUCCESS, SECURITY_REJECTED, QUERY_FAILED)")
    min_latency_ms: Optional[float] = Field(default=None, ge=0.0, description="Filter logs exceeding latency threshold")


class AuditLogEntryResponse(BaseModel):
    """Sanitized individual audit trail entry for a database query execution."""
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    query_id: str
    request_id: Optional[str] = None
    schema_version: Optional[str] = None
    request_timestamp: datetime
    sanitized_user_query: str
    final_status: str
    total_latency_ms: float
    retrieval_latency_ms: float = 0.0
    planning_latency_ms: float = 0.0
    sql_generation_latency_ms: float = 0.0
    validation_latency_ms: float = 0.0
    database_execution_latency_ms: float = 0.0
    result_normalization_latency_ms: float = 0.0
    answer_synthesis_latency_ms: float = 0.0
    grounding_verification_latency_ms: float = 0.0
    row_count: int = 0
    truncated: bool = False
    column_count: int = 0
    answer_type: str = "UNKNOWN"
    llm_used: bool = False
    repair_attempts: int = 0
    ast_valid: bool = True
    grounding_status: str = "UNKNOWN"
    verification_status: str = "UNKNOWN"
    fallback_used: bool = False
    error_type: Optional[str] = None
    sanitized_error: Optional[str] = None
    audit_metadata: Optional[Dict[str, Any]] = None


class AuditLogListResponse(BaseModel):
    """Paginated list response for audit log queries."""
    model_config = ConfigDict(extra="forbid")

    items: List[AuditLogEntryResponse]
    total: int
    limit: int
    offset: int
