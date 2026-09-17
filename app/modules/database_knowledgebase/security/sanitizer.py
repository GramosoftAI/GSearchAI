"""Error and Log Sanitization Utility

Ensures passwords, raw connection strings, tokens, and internal filesystem paths
are NEVER leaked to client responses, logs, or exception traces.
"""

import re
from typing import Union


# Regex to match and mask passwords inside connection DSN URLs
DSN_PASSWORD_REGEX = re.compile(
    r"((?:postgresql|mysql|sqlite|oracle|snowflake|clickhouse|mssql)(?:\+[a-zA-Z0-9_]+)?:\/\/[^:]+:)([^@]+)(@)",
    re.IGNORECASE,
)

# Regex to match password patterns with quoted values: password='secret', password="secret", password: 'secret', password 'secret'
QUOTED_PASSWORD_REGEX = re.compile(
    r"\b(password|passwd|pwd|secret|key|token|auth)\b(?:\s*[:=]|\s+is|\s+with)?\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)

# Regex to match unquoted password assignments: password=secret, pwd:secret
UNQUOTED_PASSWORD_REGEX = re.compile(
    r"\b(password|passwd|pwd|secret|key|token|auth)\s*[:=]\s*([^\s,;]+)",
    re.IGNORECASE,
)

# Regex to match Windows or Unix absolute file paths
PATH_REGEX = re.compile(
    r"([a-zA-Z]:\\[^:\n\r]+|\/(?:home|app|usr|var|etc)\/[^:\n\r]+)",
    re.IGNORECASE,
)

# Regex to match private IP addresses (RFC 1918)
PRIVATE_IP_REGEX = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b"
)


def mask_connection_string(conn_str: str) -> str:
    """Mask password inside any database connection string."""
    if not conn_str:
        return ""
    return DSN_PASSWORD_REGEX.sub(r"\1***\3", conn_str)


def sanitize_error_message(err: Union[Exception, str]) -> str:
    """
    Sanitize error messages by stripping passwords, tokens, connection strings,
    internal IP addresses, and absolute paths before returning to API callers.
    """
    if isinstance(err, Exception):
        msg = str(err)
    else:
        msg = str(err or "")

    # 1. Mask DSN passwords
    msg = mask_connection_string(msg)

    # 2. Mask password values (quoted and unquoted)
    msg = QUOTED_PASSWORD_REGEX.sub(r"\1: '***'", msg)
    msg = UNQUOTED_PASSWORD_REGEX.sub(r"\1: '***'", msg)

    # 3. Clean up common raw driver noise
    msg = re.sub(r"asyncpg\.exceptions\.[A-Za-z0-9_]+Error:\s*", "", msg)
    msg = re.sub(r"psycopg2\.[A-Za-z0-9_]+:\s*", "", msg)
    msg = re.sub(r"sqlalchemy\.exc\.[A-Za-z0-9_]+:\s*", "", msg)

    # 4. Remove internal source code line paths if present
    msg = PATH_REGEX.sub("[internal_path]", msg)

    # 5. Mask private internal IP addresses
    msg = PRIVATE_IP_REGEX.sub("[internal_ip]", msg)

    return msg.strip()
