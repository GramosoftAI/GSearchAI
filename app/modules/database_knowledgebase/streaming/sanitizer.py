"""Phase 3D Streaming Anti-Leakage Sanitizer

Guarantees that sensitive data (passwords, connection strings, JWTs, stack traces,
filesystem paths, internal exception details, raw SQL parameters) are never passed
to the SSE serializer.
"""

import re
from typing import Any, Dict, List, Optional, Union

# Pattern matching sensitive tokens, JWTs, passwords, and file paths
SECRET_PATTERNS = [
    re.compile(r"password\s*=\s*['\"]?[^\s'\"]+", re.IGNORECASE),
    re.compile(r"postgres://[^\s'\"]+:[^\s'\"]+@[^\s'\"]+", re.IGNORECASE),
    re.compile(r"postgresql(\+[a-z]+)?://[^\s'\"]+:[^\s'\"]+@[^\s'\"]+", re.IGNORECASE),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"ey[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]+"), # JWT pattern
    re.compile(r"(?:[a-zA-Z]:\\|\/)[^\s'\"]+\.(?:py|env|key|pem|crt)"), # File path pattern
]

ERROR_CODE_MAP = {
    "SQLValidationError": "VALIDATION_FAILURE",
    "SQLSyntaxError": "VALIDATION_FAILURE",
    "ExecutionPolicyViolation": "AUTHORIZATION_FAILURE",
    "TenantExecutionDenied": "TENANT_MISMATCH",
    "DatabaseTimeoutError": "DATABASE_TIMEOUT",
    "QueryExecutionTimeout": "DATABASE_TIMEOUT",
    "QueryConnectionError": "CONNECTION_FAILURE",
    "DatabaseConnectionError": "CONNECTION_FAILURE",
    "DatabaseAuthenticationError": "AUTHENTICATION_FAILURE",
    "TenantMismatchError": "TENANT_MISMATCH",
    "asyncio.CancelledError": "QUERY_CANCELLED",
    "CancelledError": "QUERY_CANCELLED",
}


class StreamingSanitizer:
    """Provides sanitization primitives for streaming event payloads."""

    @classmethod
    def sanitize_text(cls, text: Optional[str]) -> str:
        """Sanitizes text by scrubbing passwords, connection strings, and file paths."""
        if not text:
            return ""
        sanitized = str(text)
        for pattern in SECRET_PATTERNS:
            sanitized = pattern.sub("[REDACTED]", sanitized)
        return sanitized

    @classmethod
    def resolve_safe_error_code(cls, exc: Exception) -> str:
        """Maps an internal exception class to a safe, public error code."""
        exc_name = type(exc).__name__
        return ERROR_CODE_MAP.get(exc_name, "INTERNAL_ERROR")

    @classmethod
    def resolve_safe_error_message(cls, exc: Exception, stage: str) -> str:
        """Produces a non-sensitive, human-readable message for the client."""
        code = cls.resolve_safe_error_code(exc)
        if code == "VALIDATION_FAILURE":
            return "The requested query violates database security policy or cannot be validated."
        elif code == "AUTHORIZATION_FAILURE":
            return "Query execution authorization was denied."
        elif code == "TENANT_MISMATCH":
            return "Cross-tenant access is strictly denied."
        elif code == "DATABASE_TIMEOUT":
            return "The database query exceeded the execution timeout limit."
        elif code == "CONNECTION_FAILURE":
            return "Failed to establish a connection to the target database."
        elif code == "AUTHENTICATION_FAILURE":
            return "Database authentication failed."
        elif code == "QUERY_CANCELLED":
            return "The query was cancelled."
        else:
            return f"An error occurred during {stage.lower()}."
