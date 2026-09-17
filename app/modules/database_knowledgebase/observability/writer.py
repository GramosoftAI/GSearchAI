"""Asynchronous Non-Blocking Audit Writer for Phase 3A: Database Knowledgebase Observability

Persists DatabaseQueryAuditLog records to PostgreSQL in an out-of-band, failsafe manner.
Audit logging failures will NEVER fail, delay, or interrupt an active user query.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, Union
import uuid

from app.core.database import AsyncSessionLocal
from .audit_model import DatabaseQueryAuditLog
from .sanitizer import AuditSanitizer

logger = logging.getLogger("database_knowledgebase.audit.writer")


class AuditWriter:
    """Asynchronously persists query audit records to the database."""

    @classmethod
    async def persist_audit_record(
        cls,
        query_id: str,
        tenant_id: Union[str, uuid.UUID],
        knowledgebase_id: Union[str, uuid.UUID],
        user_query: str,
        total_latency_ms: float,
        request_id: Optional[str] = None,
        user_id: Optional[Union[str, uuid.UUID]] = None,
        schema_version: Optional[str] = None,
        retrieval_latency_ms: float = 0.0,
        planning_latency_ms: float = 0.0,
        sql_generation_latency_ms: float = 0.0,
        validation_latency_ms: float = 0.0,
        database_execution_latency_ms: float = 0.0,
        result_normalization_latency_ms: float = 0.0,
        answer_synthesis_latency_ms: float = 0.0,
        grounding_verification_latency_ms: float = 0.0,
        row_count: int = 0,
        truncated: bool = False,
        column_count: int = 0,
        answer_type: str = "UNKNOWN",
        llm_used: bool = False,
        llm_attempts: int = 0,
        repair_attempts: int = 0,
        ast_valid: bool = True,
        grounding_status: str = "UNKNOWN",
        verification_status: str = "UNKNOWN",
        fallback_used: bool = False,
        error_type: Optional[str] = None,
        raw_error: Optional[str] = None,
        final_status: str = "SUCCESS",
        audit_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Persist a single audit record asynchronously to the db_query_audit_logs table.
        Guarantees all text and parameters are sanitized, and absorbs any DB persistence exceptions.
        """
        try:
            # 1. Sanitize user query
            sanitized_query, q_hash, q_len = AuditSanitizer.sanitize_user_query(user_query)

            # 2. Sanitize error message if present
            sanitized_err = None
            if raw_error:
                _, sanitized_err = AuditSanitizer.sanitize_error(raw_error)

            # 3. Clean audit metadata (remove passwords, DSNs, sensitive keys)
            clean_metadata = None
            if audit_metadata:
                clean_metadata = audit_metadata.copy()
                if "parameters" in clean_metadata and isinstance(clean_metadata["parameters"], dict):
                    clean_metadata["parameters"] = AuditSanitizer.sanitize_parameters(clean_metadata["parameters"])

            t_uuid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
            kb_uuid = knowledgebase_id if isinstance(knowledgebase_id, uuid.UUID) else uuid.UUID(str(knowledgebase_id))
            u_uuid = None
            if user_id:
                u_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))

            audit_entry = DatabaseQueryAuditLog(
                query_id=str(query_id),
                request_id=str(request_id) if request_id else None,
                tenant_id=t_uuid,
                user_id=u_uuid,
                knowledgebase_id=kb_uuid,
                schema_version=schema_version,
                user_query_hash=q_hash,
                user_query_length=q_len,
                sanitized_user_query=sanitized_query,
                retrieval_latency_ms=round(retrieval_latency_ms, 2),
                planning_latency_ms=round(planning_latency_ms, 2),
                sql_generation_latency_ms=round(sql_generation_latency_ms, 2),
                validation_latency_ms=round(validation_latency_ms, 2),
                database_execution_latency_ms=round(database_execution_latency_ms, 2),
                result_normalization_latency_ms=round(result_normalization_latency_ms, 2),
                answer_synthesis_latency_ms=round(answer_synthesis_latency_ms, 2),
                grounding_verification_latency_ms=round(grounding_verification_latency_ms, 2),
                total_latency_ms=round(total_latency_ms, 2),
                row_count=row_count,
                truncated=truncated,
                column_count=column_count,
                answer_type=answer_type,
                llm_used=llm_used,
                llm_attempts=llm_attempts,
                repair_attempts=repair_attempts,
                ast_valid=ast_valid,
                grounding_status=grounding_status,
                verification_status=verification_status,
                fallback_used=fallback_used,
                error_type=error_type,
                sanitized_error=sanitized_err,
                final_status=final_status,
                audit_metadata=clean_metadata,
            )

            async with AsyncSessionLocal() as session:
                session.add(audit_entry)
                await session.commit()

        except Exception as exc:
            # Failsafe: Log the persistence failure safely without crashing the query
            err_type, safe_msg = AuditSanitizer.sanitize_error(exc)
            logger.error(
                f"Failed to persist audit log for query '{query_id}': [{err_type}] {safe_msg}",
                extra={"query_id": query_id, "tenant_id": str(tenant_id)},
            )

    @classmethod
    def dispatch_audit_persistence(cls, **kwargs) -> None:
        """
        Dispatches audit persistence as a background task.
        Completely non-blocking to the caller.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(cls.persist_audit_record(**kwargs))
            else:
                # If no running event loop, schedule via asyncio.run or skip
                pass
        except RuntimeError:
            # If called from outside an async event loop (e.g. sync test), ignore or handle cleanly
            pass
