"""SQL Diagnostics and Validation Result Models

Structured error representation for AST validation and LLM repair loops.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class DiagnosticErrorCode(str, Enum):
    """Specific error codes for SQL validation failures."""
    SYNTAX_ERROR = "SYNTAX_ERROR"
    NON_SELECT_STATEMENT = "NON_SELECT_STATEMENT"
    CATALOG_ACCESS_FORBIDDEN = "CATALOG_ACCESS_FORBIDDEN"
    UNAPPROVED_TABLE = "UNAPPROVED_TABLE"
    UNAPPROVED_COLUMN = "UNAPPROVED_COLUMN"
    UNAPPROVED_JOIN = "UNAPPROVED_JOIN"
    CARTESIAN_JOIN = "CARTESIAN_JOIN"
    FORBIDDEN_FUNCTION = "FORBIDDEN_FUNCTION"
    COMPLEXITY_EXCEEDED = "COMPLEXITY_EXCEEDED"
    MISSING_LIMIT = "MISSING_LIMIT"
    EXCESSIVE_LIMIT = "EXCESSIVE_LIMIT"


class DiagnosticSeverity(str, Enum):
    """Severity of a diagnostic finding."""
    ERROR = "ERROR"
    WARNING = "WARNING"


class DiagnosticError(BaseModel):
    """Structured diagnostic finding produced by the SQL Security Policy Engine."""
    model_config = ConfigDict(extra="forbid")

    error_code: DiagnosticErrorCode
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    message: str
    offending_node: Optional[str] = None
    suggested_action: Optional[str] = None


class ValidationResult(BaseModel):
    """Outcome of SQL Security Policy Engine validation."""
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    is_valid: bool
    errors: List[DiagnosticError] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    sanitized_sql: Optional[str] = None
