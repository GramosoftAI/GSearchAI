"""Audit Sanitizer for Phase 3A: Production Observability & Audit Logging

Enforces zero data leakage across logs, traces, and persistent audit stores:
- Redacts database passwords, DSNs, connection strings, and URIs.
- Redacts API keys, JWT bearer tokens, and credentials.
- Masks SQL parameter literals into abstract type/shape metadata (e.g. "[str:len=10]").
- Cleanses database exception messages and stack traces.
- Prevents database rows and employee/customer records from ever appearing in telemetry.
"""

from datetime import date, datetime
from decimal import Decimal
import hashlib
import re
from typing import Any, Dict, Optional, Tuple, Union


class AuditSanitizer:
    """Security engine for sanitizing queries, parameters, errors, and connection details."""

    # Regex to catch database connection strings with passwords (postgresql, mysql, etc.)
    URI_PASSWORD_REGEX = re.compile(
        r"((?:[a-zA-Z0-9_\+]+):\/\/[^:@\s\n\r]+:)(.*)(@[^/\s:\n\r]+)",
        re.IGNORECASE,
    )

    # Regex for standard token / key patterns
    JWT_REGEX = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-.]+\b")
    BEARER_TOKEN_REGEX = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9\-\._~\+\/]+=*)")
    API_KEY_REGEX = re.compile(r"(?i)\b((?:api[_-]?key|secret|token|password|auth|jwt)\s*[:=]\s*['\"]?)([^'\"\s,\}\]]+)(['\"]?)")
    BASIC_AUTH_REGEX = re.compile(r"(?i)\b(basic\s+)[A-Za-z0-9+\/]+=*")

    # Sensitive personal information patterns in text
    SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    CREDIT_CARD_REGEX = re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b")

    # Local file system paths
    PATH_REGEX = re.compile(r"(?:[A-Za-z]:\\|/(?:home|app|usr|var|etc|opt)/)[A-Za-z0-9_\-\.\\/]+")

    @classmethod
    def sanitize_connection_string(cls, uri_or_text: str) -> str:
        """
        Redact username passwords from database connection strings and URIs.
        Example: postgresql://postgres:mypassword@localhost:5432/mydb
        Becomes: postgresql://postgres:***@localhost:5432/mydb
        """
        if not uri_or_text:
            return ""

        return cls.URI_PASSWORD_REGEX.sub(r"\1***\3", uri_or_text)

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """
        Redact sensitive tokens, passwords, bearer credentials, and API keys from arbitrary text.
        """
        if not text:
            return ""

        cleaned = cls.sanitize_connection_string(text)
        cleaned = cls.BEARER_TOKEN_REGEX.sub(r"\1[REDACTED]", cleaned)
        cleaned = cls.JWT_REGEX.sub("[JWT_REDACTED]", cleaned)
        cleaned = cls.BASIC_AUTH_REGEX.sub(r"\1[REDACTED]", cleaned)
        cleaned = cls.SSN_REGEX.sub("[SSN_REDACTED]", cleaned)
        cleaned = cls.CREDIT_CARD_REGEX.sub("[CARD_REDACTED]", cleaned)

        def _redact_key_val(match: re.Match) -> str:
            prefix = match.group(1)
            suffix = match.group(3) or ""
            return f"{prefix}[REDACTED]{suffix}"

        cleaned = cls.API_KEY_REGEX.sub(_redact_key_val, cleaned)
        return cleaned

    @classmethod
    def sanitize_user_query(cls, query: str) -> Tuple[str, str, int]:
        """
        Sanitize user query string, compute cryptographic SHA-256 hash, and record length.
        Returns: (sanitized_query, query_hash, query_length)
        """
        if not query:
            return ("", hashlib.sha256(b"").hexdigest(), 0)

        sanitized = cls.sanitize_text(query.strip())
        query_hash = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
        query_length = len(sanitized)
        return (sanitized, query_hash, query_length)

    @classmethod
    def mask_parameter_value(cls, val: Any) -> str:
        """
        Mask parameter value into abstract type/length metadata.
        NEVER preserves the actual literal value (e.g. employee names, salaries).
        Example:
            'John Smith' -> '[str:len=10]'
            150000 -> '[int]'
            19.99 -> '[float]'
            True -> '[bool]'
            datetime.date(2023, 1, 1) -> '[date]'
            [1, 2, 3] -> '[list:len=3]'
        """
        if val is None:
            return "[null]"
        if isinstance(val, bool):
            return "[bool]"
        if isinstance(val, int):
            return "[int]"
        if isinstance(val, (float, Decimal)):
            return "[float]"
        if isinstance(val, (datetime, date)):
            return "[date]"
        if isinstance(val, str):
            return f"[str:len={len(val)}]"
        if isinstance(val, (list, tuple, set)):
            return f"[list:len={len(val)}]"
        if isinstance(val, dict):
            return f"[dict:keys={len(val)}]"
        return f"[{type(val).__name__}]"

    @classmethod
    def sanitize_parameters(cls, parameters: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """
        Convert a dictionary of SQL execution parameters into an abstracted metadata map.
        Guarantees sensitive search terms and filters are not written to audit logs.
        """
        if not parameters:
            return {}

        return {
            str(k): cls.mask_parameter_value(v)
            for k, v in parameters.items()
        }

    @classmethod
    def sanitize_error(cls, exc: Union[Exception, str]) -> Tuple[str, str]:
        """
        Sanitize an exception object or error message:
        - Classifies error type
        - Strips connection strings and passwords
        - Strips local file system paths
        Returns: (error_type, sanitized_message)
        """
        if isinstance(exc, Exception):
            error_type = type(exc).__name__
            msg = str(exc)
        else:
            error_type = "Error"
            msg = str(exc)

        sanitized_msg = cls.sanitize_text(msg)

        # Strip file system paths (e.g., E:\graphmind\... or /home/.../...)
        sanitized_msg = cls.PATH_REGEX.sub("[PATH_REDACTED]", sanitized_msg)

        return (error_type, sanitized_msg)
