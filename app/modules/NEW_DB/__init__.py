"""NEW_DB Module - Lightweight, Grounded Database Knowledgebase

A clean, streamlined Text-to-SQL RAG module built exclusively around:
1. Fast deterministic catalog introspection.
2. AI-understandable Markdown cheat sheets.
3. pgvector cosine similarity retrieval.
4. DeepSeek grounded SQL generation.
5. sqlglot AST security validation.
6. Safe read-only execution with Zero-Row temporal recovery.
7. Executive natural-language answer synthesis.

Zero heavy 7-stage profiling background queues.
"""

from .routes import router
from .service import NewDBService
from .schemas import (
    DBConnectionConfig,
    ConnectionTestResult,
    RegisterDatabaseRequest,
    RegisterDatabaseResponse,
    CanonicalSchema,
    TableInfo,
    ColumnInfo,
    SyncResult,
    QueryRequest,
    QueryResponse,
)

__all__ = [
    "router",
    "NewDBService",
    "DBConnectionConfig",
    "ConnectionTestResult",
    "RegisterDatabaseRequest",
    "RegisterDatabaseResponse",
    "CanonicalSchema",
    "TableInfo",
    "ColumnInfo",
    "SyncResult",
    "QueryRequest",
    "QueryResponse",
]
