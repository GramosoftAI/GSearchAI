"""Pydantic Models and Schemas for NEW_DB Module

Defines data contracts for connection, deterministic schema metadata,
Markdown documentation, vector retrieval, and grounded SQL execution.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from enum import Enum
import uuid
from datetime import datetime


class DatabaseType(str, Enum):
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    MARIADB = "mariadb"
    SQLITE = "sqlite"


class SSLMode(str, Enum):
    DISABLE = "disable"
    ALLOW = "allow"
    PREFER = "prefer"
    REQUIRE = "require"


class DBConnectionConfig(BaseModel):
    """Database connection configuration parameters."""
    db_type: DatabaseType = DatabaseType.POSTGRESQL
    host: str = Field(..., description="Database host (e.g. localhost or 127.0.0.1)")
    port: int = Field(default=5432, description="Database port")
    database_name: str = Field(..., description="Target database name")
    username: str = Field(..., description="Database user name")
    password: str = Field(..., description="Database user password")
    ssl_mode: SSLMode = SSLMode.PREFER
    connection_timeout: int = 15
    schemas: Optional[List[str]] = Field(default=None, description="Optional schemas filter, e.g. ['public']")

    @property
    def masked_dsn(self) -> str:
        return f"{self.db_type.value}://{self.username}:***@{self.host}:{self.port}/{self.database_name}"


class RegisterDatabaseRequest(BaseModel):
    """Payload to register a new database connection."""
    name: str = Field(..., description="Human-readable name for database knowledgebase")
    description: Optional[str] = Field(default=None, description="Optional description")
    connection: DBConnectionConfig


class RegisterDatabaseResponse(BaseModel):
    """Response returned upon database registration."""
    success: bool = True
    id: str
    name: str
    database_type: str
    masked_dsn: str
    status: str


class ConnectionTestResult(BaseModel):
    """Outcome of testing a database connection."""
    success: bool
    latency_ms: float = 0.0
    server_version: Optional[str] = None
    error_message: Optional[str] = None


class ColumnInfo(BaseModel):
    """Metadata describing a single database column."""
    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False
    default_value: Optional[str] = None
    description: Optional[str] = None
    sample_values: Optional[List[Any]] = None


class ForeignKeyInfo(BaseModel):
    """Foreign key relationship metadata."""
    column_name: str
    target_schema: str
    target_table: str
    target_column: str


class TableInfo(BaseModel):
    """Metadata describing a database table or view."""
    schema_name: str = "public"
    table_name: str
    is_view: bool = False
    columns: List[ColumnInfo] = []
    primary_keys: List[str] = []
    foreign_keys: List[ForeignKeyInfo] = []
    row_count: Optional[int] = None
    markdown_doc: Optional[str] = None


class CanonicalSchema(BaseModel):
    """Canonical representation of the introspected database schema."""
    database_name: str
    database_type: str
    fingerprint: str
    introspected_at: datetime = Field(default_factory=datetime.utcnow)
    tables: List[TableInfo] = []


class SyncResult(BaseModel):
    """Result of running the fast Sync pipeline."""
    success: bool
    kb_id: uuid.UUID
    schema_version: str
    table_count: int
    column_count: int
    docs_generated: int
    embeddings_indexed: int
    elapsed_seconds: float
    message: str


class QueryRequest(BaseModel):
    """Request payload to query the database using natural language."""
    query: str = Field(..., description="Natural language question, e.g. 'What tasks did Arun complete this week?'")
    top_k_tables: int = Field(default=6, ge=1, le=20, description="Number of relevant table docs to retrieve via pgvector")
    model: Optional[str] = Field(default=None, description="Override LLM model (defaults to DeepSeek)")
    resolved_entities: Optional[List[Dict[str, Any]]] = Field(default=None, description="Explicit entity resolution (e.g. user ID 113)")


class QueryResponse(BaseModel):
    """Rich grounded response generated from live database execution."""
    success: bool
    query: str
    answer: str
    sql: str
    rows: List[Dict[str, Any]] = []
    columns: List[str] = []
    row_count: int = 0
    truncated: bool = False
    execution_time_ms: float = 0.0
    candidate_tables: List[str] = []
    disambiguation_notice: Optional[str] = None
    disambiguation_options: Optional[List[Dict[str, Any]]] = None
