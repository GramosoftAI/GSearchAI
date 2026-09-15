"""Phase 2C Execution Policy Engine

Enforces defense-in-depth security contract validation at the Phase 2C execution boundary.
Verifies ValidatedCandidateSQL integrity, schema version locking, parameter completeness,
multi-tenant authorization, and issues immutable ExecutionAuthorization tokens.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any, Dict, List, Optional, Set
import uuid

from ..sql_generator.repair import ValidatedCandidateSQL
from .errors import (
    ExecutionPolicyViolation,
    ParameterBindingError,
    StaleSchemaVersionError,
    TenantExecutionDenied,
)
from .models import ExecutionAuthorization


class ExecutionPolicyEngine:
    """
    Deterministic Security Gatekeeper for Database Execution.
    Guarantees that ONLY certified, schema-versioned ValidatedCandidateSQL
    can obtain an ExecutionAuthorization token.
    """

    AUTHORIZATION_VALIDITY_SECONDS = 60

    @classmethod
    def authorize_execution(
        cls,
        candidate_sql: Any,
        request_tenant_id: str,
        knowledgebase_tenant_id: str,
        active_schema_version: str,
        knowledgebase_id: uuid.UUID,
    ) -> ExecutionAuthorization:
        """
        Evaluate all security preconditions and issue an immutable ExecutionAuthorization.
        Fails closed on any inconsistency.
        """
        # 1. Type Gate: MUST be an instance of ValidatedCandidateSQL
        if not isinstance(candidate_sql, ValidatedCandidateSQL):
            raise ExecutionPolicyViolation(
                detail=f"Execution rejected: Expected ValidatedCandidateSQL, got '{type(candidate_sql).__name__}'. Direct SQL strings, arbitrary dicts, or uncertified objects are strictly forbidden.",
                error_code="INVALID_CANDIDATE_SQL_TYPE",
            )

        # 2. Validation Report Gate
        if not candidate_sql.validation_report or not candidate_sql.validation_report.is_valid:
            error_msgs = "; ".join(e.message for e in candidate_sql.validation_report.errors) if candidate_sql.validation_report else "No validation report"
            raise ExecutionPolicyViolation(
                detail=f"Execution rejected: Candidate SQL validation report is invalid: {error_msgs}",
                error_code="VALIDATION_REPORT_INVALID",
            )

        # 3. Statement Structure Gate: SELECT-only root and no stacked statements
        raw_sql = candidate_sql.sanitized_sql.strip()
        if not raw_sql.upper().startswith("SELECT"):
            raise ExecutionPolicyViolation(
                detail="Execution rejected: Only SELECT root queries are permitted.",
                error_code="NON_SELECT_ROOT_STATEMENT",
            )

        # Reject semicolon followed by non-whitespace (stacked injection attempt)
        if ";" in raw_sql:
            after_semicolon = raw_sql.split(";", 1)[1].strip()
            if after_semicolon:
                raise ExecutionPolicyViolation(
                    detail="Execution rejected: Stacked multi-statement queries are strictly forbidden.",
                    error_code="STACKED_STATEMENT_DETECTED",
                )

        # 4. Mandatory LIMIT check
        if "LIMIT" not in raw_sql.upper():
            raise ExecutionPolicyViolation(
                detail="Execution rejected: Query lacks a mandatory LIMIT clause.",
                error_code="MISSING_MANDATORY_LIMIT",
            )

        # 5. Tenant Isolation Gate: Request tenant must match Knowledgebase tenant
        req_t = str(request_tenant_id).strip()
        kb_t = str(knowledgebase_tenant_id).strip()
        if not req_t or not kb_t or req_t != kb_t:
            raise TenantExecutionDenied(
                detail=f"Cross-tenant execution denied: Request tenant '{req_t}' does not match knowledgebase tenant '{kb_t}'.",
                details={"request_tenant_id": req_t, "knowledgebase_tenant_id": kb_t},
            )

        # 6. Schema Version Lock Gate
        plan_schema_version = getattr(candidate_sql.plan, "schema_version", None)
        active_ver = str(active_schema_version).strip() if active_schema_version else ""

        if not plan_schema_version or not active_ver or str(plan_schema_version).strip() != active_ver:
            raise StaleSchemaVersionError(
                detail=f"Schema version mismatch: Candidate SQL compiled against version '{plan_schema_version}', but active schema version is '{active_ver}'. Re-planning required.",
                details={
                    "plan_schema_version": plan_schema_version,
                    "active_schema_version": active_ver,
                },
            )

        # 7. Knowledgebase ID Gate
        plan_kb_id = getattr(candidate_sql.plan, "database_knowledgebase_id", None)
        if plan_kb_id and plan_kb_id != knowledgebase_id:
            raise ExecutionPolicyViolation(
                detail=f"Knowledgebase ID mismatch: Plan targeted '{plan_kb_id}', but execution requested for '{knowledgebase_id}'.",
                error_code="KNOWLEDGEBASE_ID_MISMATCH",
            )

        # 8. Parameter Consistency Gate
        param_sql = candidate_sql.parameterized.parameterized_sql
        param_dict = candidate_sql.parameterized.parameters or {}

        # Extract all :p[0-9]+ placeholders in the parameterized SQL
        placeholders_in_sql = set(re.findall(r":([a-zA-Z0-9_]+)\b", param_sql))
        keys_in_dict = set(param_dict.keys())

        missing_params = placeholders_in_sql - keys_in_dict
        extra_params = keys_in_dict - placeholders_in_sql

        if missing_params:
            raise ParameterBindingError(
                detail=f"Parameter mismatch: Query contains placeholders with no binding values: {sorted(list(missing_params))}",
                details={"missing_parameters": list(missing_params)},
            )
        if extra_params:
            raise ParameterBindingError(
                detail=f"Parameter mismatch: Parameter dictionary contains unused bindings: {sorted(list(extra_params))}",
                details={"extra_parameters": list(extra_params)},
            )

        # 9. Extract Authorized Tables and Columns
        authorized_tables: List[str] = [t.table_name for t in candidate_sql.plan.tables]
        authorized_columns: List[str] = [p.column_name for p in candidate_sql.plan.projections]

        # 10. Deterministic Query Hash
        hasher = hashlib.sha256()
        hasher.update(raw_sql.encode("utf-8"))
        for k in sorted(param_dict.keys()):
            hasher.update(f"{k}={param_dict[k]}".encode("utf-8"))
        query_hash = hasher.hexdigest()

        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=cls.AUTHORIZATION_VALIDITY_SECONDS)

        return ExecutionAuthorization(
            tenant_id=req_t,
            knowledgebase_id=knowledgebase_id,
            schema_version=active_ver,
            authorized_tables=authorized_tables,
            authorized_columns=authorized_columns,
            query_hash=query_hash,
            issued_at=now,
            expires_at=expires,
        )

    @classmethod
    def verify_authorization(
        cls,
        authorization: Any,
        expected_query_hash: str,
        expected_tenant_id: str,
    ) -> bool:
        """
        Verify that an ExecutionAuthorization token is authentic, valid, and unexpired.
        """
        if not isinstance(authorization, ExecutionAuthorization):
            raise ExecutionPolicyViolation(
                detail="Missing or invalid ExecutionAuthorization token.",
                error_code="INVALID_AUTHORIZATION_TOKEN",
            )

        now = datetime.now(timezone.utc)
        if now > authorization.expires_at:
            raise ExecutionPolicyViolation(
                detail="ExecutionAuthorization token has expired.",
                error_code="AUTHORIZATION_EXPIRED",
            )

        if authorization.tenant_id != expected_tenant_id:
            raise TenantExecutionDenied(
                detail="ExecutionAuthorization tenant mismatch.",
                details={"authorized_tenant": authorization.tenant_id, "request_tenant": expected_tenant_id},
            )

        if authorization.query_hash != expected_query_hash:
            raise ExecutionPolicyViolation(
                detail="ExecutionAuthorization query hash does not match query candidate.",
                error_code="QUERY_HASH_MISMATCH",
            )

        return True
