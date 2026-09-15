"""Database Knowledgebase Module - Live Relational Database Catalog & Introspection

Provides isolated, multi-tenant database connection management, deterministic
schema introspection, canonical schema normalization, and secure catalog storage.
"""

from .models.database_knowledgebase import DatabaseKnowledgebase, DatabaseSchemaSnapshot
from .schemas.connection import DatabaseConnectionConfig, DatabaseType, SSLMode, ConnectionTestResult
from .schemas.canonical import DatabaseSchema, TableSchema, ColumnSchema, RelationshipSchema
from .services.service import DatabaseKnowledgebaseService
from .repositories.repository import DatabaseKnowledgebaseRepository
from .routes import router

__all__ = [
    "DatabaseKnowledgebase",
    "DatabaseSchemaSnapshot",
    "DatabaseConnectionConfig",
    "DatabaseType",
    "SSLMode",
    "ConnectionTestResult",
    "DatabaseSchema",
    "TableSchema",
    "ColumnSchema",
    "RelationshipSchema",
    "DatabaseKnowledgebaseService",
    "DatabaseKnowledgebaseRepository",
    "router",
]
