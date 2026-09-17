"""Structured Audit Logger for Phase 3A: Database Knowledgebase Observability

Emits standardized, JSON-serialized lifecycle events to the logging infrastructure.
Every event contains complete correlation metadata (query_id, tenant_id, knowledgebase_id).
Strictly prevents leakage of credentials, passwords, raw parameters, and database rows.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional, Union
import uuid

from .sanitizer import AuditSanitizer

audit_log = logging.getLogger("database_knowledgebase.audit")


class AuditEventNames:
    """Canonical event names for the 15 pipeline lifecycle transitions."""
    QUERY_STARTED = "QUERY_STARTED"
    SCHEMA_RETRIEVED = "SCHEMA_RETRIEVED"
    QUERY_PLAN_CREATED = "QUERY_PLAN_CREATED"
    SQL_GENERATED = "SQL_GENERATED"
    SQL_VALIDATED = "SQL_VALIDATED"
    SECURITY_REJECTED = "SECURITY_REJECTED"
    EXECUTION_AUTHORIZED = "EXECUTION_AUTHORIZED"
    DATABASE_EXECUTION_STARTED = "DATABASE_EXECUTION_STARTED"
    DATABASE_EXECUTION_COMPLETED = "DATABASE_EXECUTION_COMPLETED"
    RESULT_NORMALIZED = "RESULT_NORMALIZED"
    ANSWER_GENERATED = "ANSWER_GENERATED"
    ANSWER_VERIFIED = "ANSWER_VERIFIED"
    ANSWER_FALLBACK = "ANSWER_FALLBACK"
    QUERY_COMPLETED = "QUERY_COMPLETED"
    QUERY_FAILED = "QUERY_FAILED"


class DatabaseAuditLogger:
    """Structured logger emitting JSON lifecycle events."""

    @classmethod
    def emit_event(
        cls,
        event_name: str,
        query_id: str,
        tenant_id: Union[str, uuid.UUID],
        knowledgebase_id: Union[str, uuid.UUID],
        request_id: Optional[str] = None,
        schema_version: Optional[str] = None,
        latency_ms: Optional[float] = None,
        data: Optional[Dict[str, Any]] = None,
        level: int = logging.INFO,
    ) -> Dict[str, Any]:
        """
        Construct, serialize, and emit a structured audit log event.
        Guarantees all payload data is sanitized before emission.
        """
        now = datetime.now(timezone.utc).isoformat()
        payload_data = data.copy() if data else {}

        # If parameters are present in payload data, mask them
        if "parameters" in payload_data and isinstance(payload_data["parameters"], dict):
            payload_data["parameters"] = AuditSanitizer.sanitize_parameters(payload_data["parameters"])

        # If error message is present, sanitize it
        if "error" in payload_data and payload_data["error"]:
            _, payload_data["error"] = AuditSanitizer.sanitize_error(payload_data["error"])

        event_payload = {
            "event": event_name,
            "timestamp": now,
            "query_id": str(query_id),
            "request_id": str(request_id) if request_id else None,
            "tenant_id": str(tenant_id),
            "knowledgebase_id": str(knowledgebase_id),
            "schema_version": schema_version or "",
            "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
            "data": payload_data,
        }

        # Emit as JSON string to Python logging system
        audit_log.log(level, json.dumps(event_payload, default=str))
        return event_payload
