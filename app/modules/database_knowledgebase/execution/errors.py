"""Phase 2C Typed Execution Exceptions

Defines structured, sanitized exceptions for execution policy violations,
timeouts, connection errors, result limits, and tenant denials.
All exceptions inherit from DatabaseKnowledgebaseError and sanitize details.
"""

from typing import Any, Dict, Optional
from fastapi import status

from ..exceptions.errors import DatabaseKnowledgebaseError
from ..security.sanitizer import sanitize_error_message


class ExecutionPolicyViolation(DatabaseKnowledgebaseError):
    """Raised when an execution request violates the execution boundary contract."""

    def __init__(
        self,
        detail: str = "Execution request violated execution security policy.",
        error_code: str = "EXECUTION_POLICY_VIOLATION",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_403_FORBIDDEN,
            error_code=error_code,
            details=details,
        )


class TenantExecutionDenied(DatabaseKnowledgebaseError):
    """Raised when an authenticated tenant attempts to execute against an unauthorized knowledgebase."""

    def __init__(
        self,
        detail: str = "Cross-tenant database query execution is strictly forbidden.",
        error_code: str = "CROSS_TENANT_EXECUTION_DENIED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_403_FORBIDDEN,
            error_code=error_code,
            details=details,
        )


class StaleSchemaVersionError(DatabaseKnowledgebaseError):
    """Raised when candidate SQL targets a stale or mismatched schema version."""

    def __init__(
        self,
        detail: str = "Candidate SQL was compiled against a stale schema version. Re-planning required.",
        error_code: str = "STALE_SCHEMA_VERSION",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_409_CONFLICT,
            error_code=error_code,
            details=details,
        )


class ParameterBindingError(DatabaseKnowledgebaseError):
    """Raised when parameters cannot be safely bound to the parameterized query."""

    def __init__(
        self,
        detail: str = "Parameter binding failed or parameters do not match query placeholders.",
        error_code: str = "PARAMETER_BINDING_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=error_code,
            details=details,
        )


class QueryConnectionError(DatabaseKnowledgebaseError):
    """Raised when acquiring or using a connection to the target database fails."""

    def __init__(
        self,
        detail: str = "Failed to connect to target database for query execution.",
        error_code: str = "QUERY_CONNECTION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_502_BAD_GATEWAY,
            error_code=error_code,
            details=details,
        )


class QueryExecutionTimeout(DatabaseKnowledgebaseError):
    """Raised when query execution exceeds the configured statement timeout."""

    def __init__(
        self,
        detail: str = "Database query execution timed out.",
        error_code: str = "QUERY_EXECUTION_TIMEOUT",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            error_code=error_code,
            details=details,
        )


class ResultLimitExceeded(DatabaseKnowledgebaseError):
    """Raised when query results exceed maximum allowed memory or row bounds in strict mode."""

    def __init__(
        self,
        detail: str = "Query result exceeded maximum allowed resource bounds.",
        error_code: str = "RESULT_LIMIT_EXCEEDED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            error_code=error_code,
            details=details,
        )


class ResultValidationError(DatabaseKnowledgebaseError):
    """Raised when returned database records fail structure or data type validation."""

    def __init__(
        self,
        detail: str = "Database result set failed validation.",
        error_code: str = "RESULT_VALIDATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=error_code,
            details=details,
        )


class QueryExecutionError(DatabaseKnowledgebaseError):
    """Raised when query execution fails inside the target database."""

    def __init__(
        self,
        detail: str = "An error occurred during query execution.",
        error_code: str = "QUERY_EXECUTION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=error_code,
            details=details,
        )
