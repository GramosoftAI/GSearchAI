"""Pipeline Tracer for Phase 3A: Database Knowledgebase Observability & Audit Logging

Coordinates lifecycle event emissions, stage latency tracking, anti-leakage parameter masking,
operational metrics recording, and asynchronous audit persistence.
"""

import time
from typing import Any, Dict, List, Optional, Union
import uuid

from .audit_model import DatabaseQueryAuditLog
from .logger import AuditEventNames, DatabaseAuditLogger
from .metrics import DatabaseKnowledgebaseMetrics
from .models import (
    ExecutionTrace,
    PipelineTrace,
    PlanningTrace,
    RetrievalTrace,
    SQLGenerationTrace,
    SynthesisTrace,
)
from .sanitizer import AuditSanitizer
from .writer import AuditWriter


class PipelineTracer:
    """Collects and aggregates stage-by-stage diagnostics, emits events, and persists audit logs."""

    def __init__(
        self,
        query_id: str,
        kb_id: uuid.UUID,
        user_query: str,
        tenant_id: Optional[Union[str, uuid.UUID]] = None,
        request_id: Optional[str] = None,
        user_id: Optional[Union[str, uuid.UUID]] = None,
    ):
        self.query_id = str(query_id)
        self.kb_id = kb_id
        self.user_query = user_query
        self.tenant_id = str(tenant_id) if tenant_id else "unknown_tenant"
        self.request_id = str(request_id) if request_id else None
        self.user_id = str(user_id) if user_id else None
        self.start_time = time.perf_counter()
        self.schema_version = ""
        self.final_status = "SUCCESS"

        self.retrieval_trace = RetrievalTrace()
        self.planning_trace = PlanningTrace()
        self.sql_trace = SQLGenerationTrace()
        self.execution_trace = ExecutionTrace()
        self.synthesis_trace = SynthesisTrace()
        self.error: Optional[str] = None
        self.error_type: Optional[str] = None

        # Stage 1: Emit QUERY_STARTED event with query metadata only (zero employee names/salaries)
        _, q_hash, q_len = AuditSanitizer.sanitize_user_query(user_query)
        DatabaseAuditLogger.emit_event(
            event_name=AuditEventNames.QUERY_STARTED,
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            request_id=self.request_id,
            data={"query_length": q_len, "query_hash": q_hash},
        )

    def record_retrieval(
        self,
        retrieved_tables: List[str],
        table_scores: Dict[str, float],
        omitted_tables: List[str],
        retrieved_columns: Dict[str, List[str]],
        selected_relationships: List[str],
        latency_ms: float,
        schema_version: Optional[str] = None,
    ) -> None:
        """Record Phase 2A semantic schema retrieval and emit SCHEMA_RETRIEVED event."""
        if schema_version:
            self.schema_version = schema_version

        self.retrieval_trace = RetrievalTrace(
            retrieved_tables=retrieved_tables,
            table_scores=table_scores,
            omitted_tables=omitted_tables,
            retrieved_columns=retrieved_columns,
            selected_relationships=selected_relationships,
            latency_ms=round(latency_ms, 2),
        )

        DatabaseAuditLogger.emit_event(
            event_name=AuditEventNames.SCHEMA_RETRIEVED,
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            request_id=self.request_id,
            schema_version=self.schema_version,
            latency_ms=latency_ms,
            data={
                "retrieved_tables_count": len(retrieved_tables),
                "retrieved_tables": retrieved_tables,
                "selected_relationships_count": len(selected_relationships),
            },
        )

    def record_planning(
        self,
        intent: str,
        tables: List[str],
        joins: List[str],
        filters: List[str],
        aggregations: List[str],
        group_by: List[str],
        order_by: List[str],
        limit: Optional[int],
        latency_ms: float,
    ) -> None:
        """Record Phase 2B query planning and emit QUERY_PLAN_CREATED event."""
        self.planning_trace = PlanningTrace(
            intent=intent,
            tables=tables,
            joins=joins,
            filters=filters,
            aggregations=aggregations,
            group_by=group_by,
            order_by=order_by,
            limit=limit,
            latency_ms=round(latency_ms, 2),
        )

        DatabaseAuditLogger.emit_event(
            event_name=AuditEventNames.QUERY_PLAN_CREATED,
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            request_id=self.request_id,
            schema_version=self.schema_version,
            latency_ms=latency_ms,
            data={
                "intent": intent,
                "tables": tables,
                "join_count": len(joins),
                "filter_count": len(filters),
                "limit": limit,
            },
        )

    def record_sql_generation(
        self,
        candidate_sql: str,
        parameters: Dict[str, Any],
        ast_valid: bool,
        ast_errors: List[str],
        ast_warnings: List[str],
        repair_attempts: int,
        latency_ms: float,
        validation_latency_ms: float = 0.0,
        sql_generation_mode: str = "llm",
        deterministic_sql_compilation: bool = False,
        sql_llm_bypassed: bool = False,
    ) -> None:
        """Record candidate SQL generation, parameterization, and AST security validation."""
        self.sql_trace = SQLGenerationTrace(
            candidate_sql=candidate_sql,
            parameters=parameters,
            ast_valid=ast_valid,
            ast_errors=ast_errors,
            ast_warnings=ast_warnings,
            repair_attempts=repair_attempts,
            validation_latency_ms=round(validation_latency_ms, 2),
            latency_ms=round(latency_ms, 2),
            sql_generation_mode=sql_generation_mode,
            deterministic_sql_compilation=deterministic_sql_compilation,
            sql_llm_bypassed=sql_llm_bypassed,
        )

        # Emit SQL_GENERATED
        DatabaseAuditLogger.emit_event(
            event_name=AuditEventNames.SQL_GENERATED,
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            request_id=self.request_id,
            schema_version=self.schema_version,
            latency_ms=latency_ms,
            data={
                "candidate_sql": candidate_sql,
                "parameters": parameters,
                "repair_attempts": repair_attempts,
                "sql_generation_mode": sql_generation_mode,
                "deterministic_sql_compilation": deterministic_sql_compilation,
                "sql_llm_bypassed": sql_llm_bypassed,
            },
        )

        # Emit SQL_VALIDATED or SECURITY_REJECTED
        if ast_valid:
            DatabaseAuditLogger.emit_event(
                event_name=AuditEventNames.SQL_VALIDATED,
                query_id=self.query_id,
                tenant_id=self.tenant_id,
                knowledgebase_id=self.kb_id,
                request_id=self.request_id,
                schema_version=self.schema_version,
                latency_ms=validation_latency_ms,
                data={"ast_valid": True, "warnings": ast_warnings},
            )
        else:
            self.final_status = "SECURITY_REJECTED"
            DatabaseAuditLogger.emit_event(
                event_name=AuditEventNames.SECURITY_REJECTED,
                query_id=self.query_id,
                tenant_id=self.tenant_id,
                knowledgebase_id=self.kb_id,
                request_id=self.request_id,
                schema_version=self.schema_version,
                latency_ms=validation_latency_ms,
                data={"ast_valid": False, "errors": ast_errors},
            )

    def record_execution_authorization(self, allowed: bool, reason: str = "Authorized") -> None:
        """Record execution policy authorization."""
        DatabaseAuditLogger.emit_event(
            event_name=AuditEventNames.EXECUTION_AUTHORIZED,
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            request_id=self.request_id,
            schema_version=self.schema_version,
            data={"allowed": allowed, "reason": reason},
        )

    def record_execution_start(self) -> None:
        """Record database driver execution initiation."""
        DatabaseAuditLogger.emit_event(
            event_name=AuditEventNames.DATABASE_EXECUTION_STARTED,
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            request_id=self.request_id,
            schema_version=self.schema_version,
        )

    def record_execution(
        self,
        executed: bool,
        row_count: int,
        truncated: bool,
        execution_time_ms: float,
        column_count: int,
        normalization_latency_ms: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        """Record driver execution and result normalization telemetry."""
        self.execution_trace = ExecutionTrace(
            executed=executed,
            row_count=row_count,
            truncated=truncated,
            execution_time_ms=round(execution_time_ms, 2),
            normalization_latency_ms=round(normalization_latency_ms, 2),
            column_count=column_count,
            error=error,
        )

        DatabaseAuditLogger.emit_event(
            event_name=AuditEventNames.DATABASE_EXECUTION_COMPLETED,
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            request_id=self.request_id,
            schema_version=self.schema_version,
            latency_ms=execution_time_ms,
            data={"row_count": row_count, "executed": executed, "error": error},
        )

        DatabaseAuditLogger.emit_event(
            event_name=AuditEventNames.RESULT_NORMALIZED,
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            request_id=self.request_id,
            schema_version=self.schema_version,
            latency_ms=normalization_latency_ms,
            data={
                "row_count": row_count,
                "column_count": column_count,
                "truncated": truncated,
            },
        )

    def record_synthesis(
        self,
        answer_type: str,
        deterministic: bool,
        grounding_status: str,
        verification_status: str,
        repair_attempts: int,
        latency_ms: float,
        grounding_latency_ms: float = 0.0,
        fallback_used: bool = False,
    ) -> None:
        """Record Phase 2D answer synthesis, grounding verification, and fallback outcome."""
        self.synthesis_trace = SynthesisTrace(
            answer_type=answer_type,
            deterministic=deterministic,
            grounding_status=grounding_status,
            verification_status=verification_status,
            fallback_used=fallback_used,
            repair_attempts=repair_attempts,
            grounding_latency_ms=round(grounding_latency_ms, 2),
            latency_ms=round(latency_ms, 2),
        )

        DatabaseAuditLogger.emit_event(
            event_name=AuditEventNames.ANSWER_GENERATED,
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            request_id=self.request_id,
            schema_version=self.schema_version,
            latency_ms=latency_ms,
            data={
                "answer_type": answer_type,
                "deterministic": deterministic,
                "repair_attempts": repair_attempts,
            },
        )

        if fallback_used:
            DatabaseAuditLogger.emit_event(
                event_name=AuditEventNames.ANSWER_FALLBACK,
                query_id=self.query_id,
                tenant_id=self.tenant_id,
                knowledgebase_id=self.kb_id,
                request_id=self.request_id,
                schema_version=self.schema_version,
                latency_ms=grounding_latency_ms,
                data={
                    "grounding_status": grounding_status,
                    "verification_status": verification_status,
                    "reason": "Failed LLM grounding verification",
                },
            )
        else:
            DatabaseAuditLogger.emit_event(
                event_name=AuditEventNames.ANSWER_VERIFIED,
                query_id=self.query_id,
                tenant_id=self.tenant_id,
                knowledgebase_id=self.kb_id,
                request_id=self.request_id,
                schema_version=self.schema_version,
                latency_ms=grounding_latency_ms,
                data={
                    "grounding_status": grounding_status,
                    "verification_status": verification_status,
                },
            )

    def record_security_rejection(self, error_msg: str, ast_errors: Optional[List[str]] = None) -> None:
        """Record explicit security rejection and trigger failure logging."""
        self.error = error_msg
        self.error_type = "SecurityPolicyViolationError"
        self.final_status = "SECURITY_REJECTED"
        self.sql_trace.ast_valid = False
        if ast_errors:
            self.sql_trace.ast_errors = ast_errors

        DatabaseAuditLogger.emit_event(
            event_name=AuditEventNames.SECURITY_REJECTED,
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            request_id=self.request_id,
            schema_version=self.schema_version,
            data={"error": error_msg, "ast_errors": ast_errors or []},
        )
        self._dispatch_persistence_and_metrics()

    def set_error(self, err_msg: str) -> None:
        """Backwards-compatible helper to record an error string."""
        self.error = err_msg
        self.final_status = "QUERY_FAILED"

    def record_failure(self, error_type: str, error_msg: str, stage: str = "UNKNOWN") -> None:
        """Record unhandled pipeline failure and trigger audit emission."""
        self.error = error_msg
        self.error_type = error_type
        self.final_status = "QUERY_FAILED"

        DatabaseAuditLogger.emit_event(
            event_name=AuditEventNames.QUERY_FAILED,
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            request_id=self.request_id,
            schema_version=self.schema_version,
            data={"stage": stage, "error_type": error_type, "error": error_msg},
        )
        self._dispatch_persistence_and_metrics()

    def _dispatch_persistence_and_metrics(self) -> None:
        """Persist audit record asynchronously and update metrics registry."""
        total_ms = (time.perf_counter() - self.start_time) * 1000.0

        # Update in-memory metrics
        is_success = self.final_status == "SUCCESS"
        DatabaseKnowledgebaseMetrics.get_instance().record_query(
            tenant_id=self.tenant_id,
            success=is_success,
            total_latency_ms=total_ms,
            db_latency_ms=self.execution_trace.execution_time_ms,
            llm_latency_ms=self.synthesis_trace.latency_ms if not self.synthesis_trace.deterministic else 0.0,
            security_rejected=self.final_status == "SECURITY_REJECTED",
            execution_failed=self.execution_trace.error is not None,
            timed_out=("timeout" in str(self.error or "").lower() or "timed out" in str(self.error or "").lower() or "timeout" in str(self.error_type or "").lower()),
            grounding_failed=self.synthesis_trace.grounding_status == "FAILED",
            fallback_used=self.synthesis_trace.fallback_used,
            llm_used=not self.synthesis_trace.deterministic,
            repair_attempts=self.synthesis_trace.repair_attempts,
            truncated=self.execution_trace.truncated,
        )

        # Dispatch async audit database persistence
        AuditWriter.dispatch_audit_persistence(
            query_id=self.query_id,
            tenant_id=self.tenant_id,
            knowledgebase_id=self.kb_id,
            user_query=self.user_query,
            total_latency_ms=total_ms,
            request_id=self.request_id,
            user_id=self.user_id,
            schema_version=self.schema_version,
            retrieval_latency_ms=self.retrieval_trace.latency_ms,
            planning_latency_ms=self.planning_trace.latency_ms,
            sql_generation_latency_ms=self.sql_trace.latency_ms,
            validation_latency_ms=self.sql_trace.validation_latency_ms,
            database_execution_latency_ms=self.execution_trace.execution_time_ms,
            result_normalization_latency_ms=self.execution_trace.normalization_latency_ms,
            answer_synthesis_latency_ms=self.synthesis_trace.latency_ms,
            grounding_verification_latency_ms=self.synthesis_trace.grounding_latency_ms,
            row_count=self.execution_trace.row_count,
            truncated=self.execution_trace.truncated,
            column_count=self.execution_trace.column_count,
            answer_type=self.synthesis_trace.answer_type,
            llm_used=not self.synthesis_trace.deterministic,
            llm_attempts=1 if not self.synthesis_trace.deterministic else 0,
            repair_attempts=self.synthesis_trace.repair_attempts,
            ast_valid=self.sql_trace.ast_valid,
            grounding_status=self.synthesis_trace.grounding_status,
            verification_status=self.synthesis_trace.verification_status,
            fallback_used=self.synthesis_trace.fallback_used,
            error_type=self.error_type,
            raw_error=self.error,
            final_status=self.final_status,
            audit_metadata={
                "retrieved_tables": self.retrieval_trace.retrieved_tables,
                "intent": self.planning_trace.intent,
                "candidate_sql": self.sql_trace.candidate_sql,
                "parameters": self.sql_trace.parameters,
            },
        )

    def finalize(self) -> PipelineTrace:
        """Compile and return complete pipeline trace."""
        total_ms = (time.perf_counter() - self.start_time) * 1000.0
        success = self.final_status == "SUCCESS"

        if success:
            DatabaseAuditLogger.emit_event(
                event_name=AuditEventNames.QUERY_COMPLETED,
                query_id=self.query_id,
                tenant_id=self.tenant_id,
                knowledgebase_id=self.kb_id,
                request_id=self.request_id,
                schema_version=self.schema_version,
                latency_ms=total_ms,
                data={
                    "row_count": self.execution_trace.row_count,
                    "answer_type": self.synthesis_trace.answer_type,
                    "grounding_status": self.synthesis_trace.grounding_status,
                },
            )

        self._dispatch_persistence_and_metrics()

        return PipelineTrace(
            query_id=self.query_id,
            request_id=self.request_id,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            database_knowledgebase_id=self.kb_id,
            schema_version=self.schema_version,
            user_query=self.user_query,
            success=success,
            final_status=self.final_status,
            total_latency_ms=round(total_ms, 2),
            error=self.error,
            retrieval=self.retrieval_trace,
            planning=self.planning_trace,
            sql_generation=self.sql_trace,
            execution=self.execution_trace,
            synthesis=self.synthesis_trace,
        )
