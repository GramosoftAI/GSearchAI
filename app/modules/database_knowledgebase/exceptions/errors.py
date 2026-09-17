"""Typed Exception Hierarchy for Database Knowledgebase Module"""

from fastapi import HTTPException, status
from typing import Optional, Dict, Any
from ..security.sanitizer import sanitize_error_message


class DatabaseKnowledgebaseError(HTTPException):
    """Base exception for all Database Knowledgebase operations."""

    def __init__(
        self,
        detail: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code: str = "DATABASE_KNOWLEDGEBASE_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        safe_detail = sanitize_error_message(detail)
        super().__init__(status_code=status_code, detail=safe_detail)
        self.error_code = error_code
        self.details = details or {}


class DatabaseConnectionError(DatabaseKnowledgebaseError):
    """Raised when connecting to the external database fails."""

    def __init__(
        self,
        detail: str = "Failed to establish connection to target database.",
        error_code: str = "DATABASE_CONNECTION_FAILED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_502_BAD_GATEWAY,
            error_code=error_code,
            details=details,
        )


class DatabaseAuthenticationError(DatabaseKnowledgebaseError):
    """Raised when authentication to the target database or credentials fail."""

    def __init__(
        self,
        detail: str = "Target database authentication failed or credentials invalid.",
        error_code: str = "DATABASE_AUTHENTICATION_FAILED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code=error_code,
            details=details,
        )


class UnsupportedDatabaseError(DatabaseKnowledgebaseError):
    """Raised when an unsupported database engine is requested."""

    def __init__(
        self,
        database_type: str,
        error_code: str = "UNSUPPORTED_DATABASE_TYPE",
    ):
        detail = f"Database engine '{database_type}' is not currently supported."
        super().__init__(
            detail=detail,
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code=error_code,
            details={"database_type": database_type},
        )


class SchemaIntrospectionError(DatabaseKnowledgebaseError):
    """Raised when schema discovery or metadata extraction fails."""

    def __init__(
        self,
        detail: str = "Database schema introspection failed.",
        error_code: str = "SCHEMA_INTROSPECTION_FAILED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=error_code,
            details=details,
        )


class DatabasePermissionError(DatabaseKnowledgebaseError):
    """Raised when the database user lacks permission for catalog access."""

    def __init__(
        self,
        detail: str = "Permission denied while accessing database metadata catalogs.",
        error_code: str = "DATABASE_PERMISSION_DENIED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_403_FORBIDDEN,
            error_code=error_code,
            details=details,
        )


class DatabaseTimeoutError(DatabaseKnowledgebaseError):
    """Raised when a database connection or metadata query exceeds timeout limit."""

    def __init__(
        self,
        detail: str = "Database operation timed out.",
        error_code: str = "DATABASE_TIMEOUT",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            error_code=error_code,
            details=details,
        )


class InvalidDatabaseConfigError(DatabaseKnowledgebaseError):
    """Raised when database configuration fails semantic validation."""

    def __init__(
        self,
        detail: str = "Invalid database connection configuration.",
        error_code: str = "INVALID_DATABASE_CONFIG",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code=error_code,
            details=details,
        )


class TenantMismatchError(DatabaseKnowledgebaseError):
    """Raised when a cross-tenant data access attempt is detected."""

    def __init__(
        self,
        detail: str = "Access to requested database knowledgebase is forbidden for current tenant.",
        error_code: str = "CROSS_TENANT_ACCESS_DENIED",
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_403_FORBIDDEN,
            error_code=error_code,
        )


class SchemaParsingError(DatabaseKnowledgebaseError):
    """Raised when schema normalization encounters unparseable data."""

    def __init__(
        self,
        detail: str = "Failed to normalize database schema to canonical representation.",
        error_code: str = "SCHEMA_NORMALIZATION_FAILED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=error_code,
            details=details,
        )


class DatabaseKnowledgebaseNotFoundError(DatabaseKnowledgebaseError):
    """Raised when a requested database knowledgebase is not found."""

    def __init__(
        self,
        detail: str = "Database knowledgebase not found.",
        error_code: str = "DATABASE_KNOWLEDGEBASE_NOT_FOUND",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_404_NOT_FOUND,
            error_code=error_code,
            details=details,
        )


class SchemaSnapshotNotFoundError(DatabaseKnowledgebaseError):
    """Raised when no schema snapshot exists for a database knowledgebase."""

    def __init__(
        self,
        detail: str = "Database schema snapshot not found.",
        error_code: str = "SCHEMA_SNAPSHOT_NOT_FOUND",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_404_NOT_FOUND,
            error_code=error_code,
            details=details,
        )


class SchemaVersionMismatchError(DatabaseKnowledgebaseError):
    """Raised when a query plan or request targets a stale or mismatching schema version."""

    def __init__(
        self,
        detail: str = "Schema version mismatch: active snapshot has drifted.",
        error_code: str = "SCHEMA_VERSION_MISMATCH",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_409_CONFLICT,
            error_code=error_code,
            details=details,
        )


class QueryPlanError(DatabaseKnowledgebaseError):
    """Raised when query planning or IR validation fails."""

    def __init__(
        self,
        detail: str = "Failed to construct valid query plan.",
        error_code: str = "QUERY_PLAN_FAILED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code=error_code,
            details=details,
        )


class SQLSyntaxError(DatabaseKnowledgebaseError):
    """Raised when candidate SQL syntax parsing fails."""

    def __init__(
        self,
        detail: str = "Invalid SQL syntax.",
        error_code: str = "SQL_SYNTAX_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code=error_code,
            details=details,
        )


class SQLValidationError(DatabaseKnowledgebaseError):
    """Raised when candidate SQL violates security policy or sub-schema constraints."""

    def __init__(
        self,
        detail: str = "Candidate SQL failed security policy validation.",
        error_code: str = "SQL_SECURITY_VALIDATION_FAILED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code=error_code,
            details=details,
        )

