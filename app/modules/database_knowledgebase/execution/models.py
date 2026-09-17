"""Phase 2C Execution Models

Defines strongly-typed canonical query results, execution authorizations,
audit records, and execution configurations.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class ExecutionConfig(BaseModel):
    """Configuration parameters for database query execution limits."""
    model_config = ConfigDict(extra="forbid")

    statement_timeout_ms: int = Field(default=5000, ge=100, le=60000, description="PostgreSQL statement timeout in milliseconds")
    lock_timeout_ms: int = Field(default=2000, ge=100, le=30000, description="PostgreSQL lock timeout in milliseconds")
    connection_timeout_seconds: int = Field(default=5, ge=1, le=30, description="Database connection timeout in seconds")
    max_rows: int = Field(default=1000, ge=1, le=10000, description="Maximum number of rows returned")
    max_columns: int = Field(default=100, ge=1, le=500, description="Maximum number of columns returned")
    max_serialized_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024, description="Maximum serialized result size in bytes (5MB)")
    max_cell_length: int = Field(default=65536, ge=256, le=1048576, description="Maximum character length of any single cell (64KB)")


class ExecutionAuthorization(BaseModel):
    """
    Immutable authorization token issued by ExecutionPolicyEngine.
    Required by ReadOnlyDatabaseExecutor to authorize SQL execution.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(..., description="Authenticated tenant identifier")
    knowledgebase_id: uuid.UUID = Field(..., description="Target database knowledgebase ID")
    schema_version: str = Field(..., description="Pinned canonical schema fingerprint")
    authorized_tables: List[str] = Field(..., description="Whitelisted table names for this execution")
    authorized_columns: List[str] = Field(..., description="Whitelisted column names for this execution")
    query_hash: str = Field(..., description="Deterministic SHA-256 hash of validated SQL")
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC issuance timestamp")
    expires_at: datetime = Field(..., description="UTC expiration timestamp")


class CanonicalQueryResult(BaseModel):
    """
    Canonical, engine-independent, serializable query result.
    Represents the terminal output boundary of Phase 2C.
    """
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique execution query identifier")
    database_knowledgebase_id: uuid.UUID = Field(..., description="Target database knowledgebase ID")
    schema_version: str = Field(..., description="Schema version against which the query was executed")
    columns: List[str] = Field(default_factory=list, description="Ordered list of projection column names")
    column_types: Dict[str, str] = Field(default_factory=dict, description="Mapping of column name to data type string")
    rows: List[Dict[str, Any]] = Field(default_factory=list, description="Normalized rows as dictionary of column -> value")
    row_count: int = Field(default=0, ge=0, description="Total number of rows returned")
    truncated: bool = Field(default=False, description="Whether the result was truncated due to exceeding MAX_ROWS or MAX_BYTES")
    execution_time_ms: float = Field(default=0.0, ge=0.0, description="Query execution duration in milliseconds")
    warnings: List[str] = Field(default_factory=list, description="Audit warnings or truncation notices")
    audit_metadata: Dict[str, Any] = Field(default_factory=dict, description="Safe execution metadata for telemetry")


class ExecutionAuditRecord(BaseModel):
    """Safe audit trail record capturing query execution metrics without sensitive data."""
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(..., description="Unique query execution ID")
    tenant_id: str = Field(..., description="Tenant ID")
    knowledgebase_id: uuid.UUID = Field(..., description="Database knowledgebase ID")
    schema_version: str = Field(..., description="Schema version")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Execution timestamp")
    execution_duration_ms: float = Field(..., description="Duration in milliseconds")
    success: bool = Field(..., description="Whether execution succeeded")
    row_count: int = Field(default=0, description="Number of rows returned")
    truncated: bool = Field(default=False, description="Whether result was truncated")
    error_code: Optional[str] = Field(default=None, description="Error code if execution failed")
    query_hash: str = Field(..., description="Deterministic hash of the executed query")
