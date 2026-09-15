"""API Request & Response Schemas for Database Knowledgebase

CRITICAL SECURITY RULE:
No API response will ever contain plain or encrypted database passwords.
Credentials are accepted on creation/update, encrypted immediately, and masked in all output.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from .connection import DatabaseConnectionConfig, ConnectionTestResult
from .canonical import DatabaseSchema


class DatabaseKnowledgebaseCreate(BaseModel):
    """Payload to create a new database knowledgebase."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255, description="Human-readable knowledgebase name")
    description: Optional[str] = Field(default=None, max_length=1000, description="Optional description")
    agent_id: Optional[uuid.UUID] = Field(default=None, description="Optional agent to associate this KB with")
    connection: DatabaseConnectionConfig = Field(..., description="Database connection parameters (passwords are encrypted immediately)")


class DatabaseKnowledgebaseUpdate(BaseModel):
    """Payload to update database knowledgebase metadata or credentials."""
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    agent_id: Optional[uuid.UUID] = Field(default=None)
    connection: Optional[DatabaseConnectionConfig] = Field(default=None, description="Updated connection parameters")


class DatabaseKnowledgebaseResponse(BaseModel):
    """
    Public response representation of a DatabaseKnowledgebase.
    NEVER leaks credentials, password hashes, or encrypted payload.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    agent_id: Optional[uuid.UUID] = None
    name: str
    description: Optional[str] = None
    database_type: str
    status: str
    schema_version: Optional[str] = None
    masked_dsn: Optional[str] = None
    last_tested_at: Optional[datetime] = None
    last_introspected_at: Optional[datetime] = None
    last_error: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DatabaseKnowledgebaseListResponse(BaseModel):
    """Paginated or listed response of database knowledgebases."""
    success: bool = True
    data: List[DatabaseKnowledgebaseResponse]
    meta: Dict[str, Any] = Field(default_factory=dict)


class DatabaseSchemaResponse(BaseModel):
    """Response containing canonical schema metadata."""
    success: bool = True
    db_knowledgebase_id: uuid.UUID
    schema_version: str
    schema_data: DatabaseSchema
    introspected_at: datetime


class SchemaSnapshotResponse(BaseModel):
    """Summary of a saved schema snapshot."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    db_knowledgebase_id: uuid.UUID
    schema_version: str
    table_count: int
    column_count: int
    relationship_count: int
    created_at: datetime


class SchemaRetrievalApiRequest(BaseModel):
    """Payload to perform semantic schema retrieval for a user query."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2000, description="Natural language question")
    conversation_context: Optional[List[str]] = Field(default=None, description="Optional conversation context")
    top_k_tables: int = Field(default=5, ge=1, le=50, description="Maximum tables to retrieve")
    top_k_columns_per_table: int = Field(default=25, ge=1, le=100, description="Max columns per table")
    include_relationships: bool = Field(default=True, description="Whether to include foreign key join paths")


class QueryPlanApiRequest(BaseModel):
    """Payload to construct a QueryPlanIR for a user query."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2000, description="Natural language question")
    top_k_tables: int = Field(default=5, ge=1, le=50, description="Maximum tables to plan")
    top_k_columns_per_table: int = Field(default=25, ge=1, le=100, description="Max columns per table")


class GenerateSQLApiRequest(BaseModel):
    """Payload to generate, validate, and repair candidate SQL."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2000, description="Natural language question")
    top_k_tables: int = Field(default=5, ge=1, le=50, description="Maximum tables to include")
    top_k_columns_per_table: int = Field(default=25, ge=1, le=100, description="Max columns per table")
    use_llm: bool = Field(default=True, description="Whether to use LLM or deterministic fallback")


class DatabaseQueryApiRequest(BaseModel):
    """Payload to execute safe, end-to-end natural-language database query."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2000, description="Natural language question")
    top_k_tables: int = Field(default=5, ge=1, le=50, description="Maximum tables to include in sub-schema")
    top_k_columns_per_table: int = Field(default=25, ge=1, le=100, description="Maximum columns per table")
    use_llm: bool = Field(default=True, description="Whether to use LLM for candidate SQL generation")
    timeout_seconds: Optional[int] = Field(default=5, ge=1, le=60, description="Execution timeout budget in seconds")


class StandardApiResponse(BaseModel):
    """Standard generic API response."""
    success: bool = True
    data: Optional[Any] = None
    error: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class GlossaryConfirmApiRequest(BaseModel):
    """Payload for operator confirmation and publication of a glossary entry."""
    model_config = ConfigDict(extra="forbid")

    table_name: str = Field(..., min_length=1, max_length=255)
    column_name: str = Field(..., min_length=1, max_length=255)
    synonyms: Optional[List[str]] = Field(default=None)
    business_description: Optional[str] = Field(default=None, max_length=1000)
    semantic_role: Optional[str] = Field(default=None, max_length=100)

