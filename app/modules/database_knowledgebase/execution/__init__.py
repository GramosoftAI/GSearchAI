"""Phase 2C Safe Read-Only SQL Execution Package"""

from .errors import (
    ExecutionPolicyViolation,
    ParameterBindingError,
    QueryConnectionError,
    QueryExecutionError,
    QueryExecutionTimeout,
    ResultLimitExceeded,
    ResultValidationError,
    StaleSchemaVersionError,
    TenantExecutionDenied,
)
from .executor import ReadOnlyDatabaseExecutor
from .models import (
    CanonicalQueryResult,
    ExecutionAuditRecord,
    ExecutionAuthorization,
    ExecutionConfig,
)
from .policy import ExecutionPolicyEngine
from .pool_manager import ReadOnlyPoolManager
from .result_limiter import ResultLimiter
from .result_validator import ResultValidator
from .timeout import TimeoutManager
from .transaction import TransactionManager

__all__ = [
    "CanonicalQueryResult",
    "ExecutionAuthorization",
    "ExecutionAuditRecord",
    "ExecutionConfig",
    "ExecutionPolicyEngine",
    "ReadOnlyDatabaseExecutor",
    "ReadOnlyPoolManager",
    "ResultLimiter",
    "ResultValidator",
    "TimeoutManager",
    "TransactionManager",
    "ExecutionPolicyViolation",
    "ParameterBindingError",
    "QueryConnectionError",
    "QueryExecutionError",
    "QueryExecutionTimeout",
    "ResultLimitExceeded",
    "ResultValidationError",
    "StaleSchemaVersionError",
    "TenantExecutionDenied",
]
