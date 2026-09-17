"""Phase 3D SSE Streaming Protocol Data Models

Defines the typed, versioned SSE event contract: exactly 20 core pipeline lifecycle events
plus 2 transport control events (stream.completed and heartbeat), totaling 22 enum event types.
Monotonically increasing event sequence numbers, and strict event-specific data allowlists
to prevent sensitive database or telemetry leakage.
"""

from datetime import datetime, timezone
from enum import Enum
import json
import logging
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DatabaseStreamEventType(str, Enum):
    """
    Typed lifecycle event types emitted during Database Knowledgebase query execution.
    Contains the 20 core lifecycle events plus terminal stream completion and heartbeat.
    """
    # 1. Query Acceptance
    QUERY_ACCEPTED = "query.accepted"

    # 2-3. Schema Retrieval
    RETRIEVAL_STARTED = "retrieval.started"
    RETRIEVAL_COMPLETED = "retrieval.completed"

    # 4-5. Query Planning
    PLANNING_STARTED = "planning.started"
    PLANNING_COMPLETED = "planning.completed"

    # 6-7. SQL Generation
    SQL_GENERATION_STARTED = "sql_generation.started"
    SQL_GENERATION_COMPLETED = "sql_generation.completed"

    # 8-9. AST Security Validation
    VALIDATION_STARTED = "validation.started"
    VALIDATION_COMPLETED = "validation.completed"

    # 10-11. Execution Authorization & Tenant Boundary
    AUTHORIZATION_STARTED = "authorization.started"
    AUTHORIZATION_COMPLETED = "authorization.completed"

    # 12-13. Read-Only DB Execution
    EXECUTION_STARTED = "execution.started"
    EXECUTION_COMPLETED = "execution.completed"

    # 14-15. Answer Synthesis
    SYNTHESIS_STARTED = "synthesis.started"
    SYNTHESIS_COMPLETED = "synthesis.completed"

    # 16-17. Grounding & Verification
    GROUNDING_STARTED = "grounding.started"
    GROUNDING_COMPLETED = "grounding.completed"

    # 18. Final Answer Ready
    ANSWER_COMPLETED = "answer.completed"

    # 19. Terminal Error
    QUERY_ERROR = "query.error"

    # 20. Terminal Cancellation
    QUERY_CANCELLED = "query.cancelled"

    # Stream Protocol Control Events
    STREAM_COMPLETED = "stream.completed"
    HEARTBEAT = "heartbeat"


# Strict per-event allowlist: ONLY permitted fields may ever appear in event 'data'
EVENT_DATA_ALLOWLIST: Dict[DatabaseStreamEventType, Set[str]] = {
    DatabaseStreamEventType.QUERY_ACCEPTED: {
        "correlation_id", "query_length", "timestamp",
    },
    DatabaseStreamEventType.RETRIEVAL_STARTED: {
        "top_k_tables", "top_k_columns_per_table",
    },
    DatabaseStreamEventType.RETRIEVAL_COMPLETED: {
        "retrieved_tables_count", "retrieved_tables", "latency_ms", "schema_version",
    },
    DatabaseStreamEventType.PLANNING_STARTED: set(),
    DatabaseStreamEventType.PLANNING_COMPLETED: {
        "intent", "tables_count", "joins_count", "has_aggregations",
        "has_ranking", "limit", "latency_ms",
    },
    DatabaseStreamEventType.SQL_GENERATION_STARTED: {
        "use_llm", "stage",
    },
    DatabaseStreamEventType.SQL_GENERATION_COMPLETED: {
        "sql_generation_mode", "deterministic_sql_compilation",
        "sql_llm_bypassed", "repair_attempts", "latency_ms",
    },
    DatabaseStreamEventType.VALIDATION_STARTED: set(),
    DatabaseStreamEventType.VALIDATION_COMPLETED: {
        "is_valid", "warnings_count", "errors_count",
    },
    DatabaseStreamEventType.AUTHORIZATION_STARTED: set(),
    DatabaseStreamEventType.AUTHORIZATION_COMPLETED: {
        "allowed", "mode", "reason",
    },
    DatabaseStreamEventType.EXECUTION_STARTED: set(),
    DatabaseStreamEventType.EXECUTION_COMPLETED: {
        "row_count", "truncated", "execution_time_ms", "columns_count",
    },
    DatabaseStreamEventType.SYNTHESIS_STARTED: {
        "use_llm", "stage",
    },
    DatabaseStreamEventType.SYNTHESIS_COMPLETED: {
        "answer_type", "deterministic", "latency_ms",
    },
    DatabaseStreamEventType.GROUNDING_STARTED: set(),
    DatabaseStreamEventType.GROUNDING_COMPLETED: {
        "grounding_status", "verification_status", "repair_attempts",
    },
    DatabaseStreamEventType.ANSWER_COMPLETED: {
        "answer_text", "answer_type", "row_count", "grounding_status",
        "verification_status", "pipeline_trace", "rows", "columns",
        "source_columns", "truncated", "warnings",
    },
    DatabaseStreamEventType.QUERY_ERROR: {
        "error_code", "stage", "retryable", "message", "correlation_id",
    },
    DatabaseStreamEventType.QUERY_CANCELLED: {
        "stage", "reason", "correlation_id",
    },
    DatabaseStreamEventType.STREAM_COMPLETED: {
        "total_duration_ms", "final_status", "events_emitted",
    },
    DatabaseStreamEventType.HEARTBEAT: {
        "timestamp", "sequence_number",
    },
}


class EventDataFilter:
    """Filters incoming data dictionaries strictly against EVENT_DATA_ALLOWLIST."""

    @classmethod
    def _sanitize_val(cls, val: Any) -> Any:
        if isinstance(val, str):
            from .sanitizer import StreamingSanitizer
            return StreamingSanitizer.sanitize_text(val)
        elif isinstance(val, dict):
            return {
                k: cls._sanitize_val(v)
                for k, v in val.items()
                if not any(st in k.lower() for st in ("password", "secret", "token", "jwt", "dsn"))
            }
        elif isinstance(val, list):
            return [cls._sanitize_val(v) for v in val]
        return val

    @classmethod
    def filter_payload(cls, event_type: DatabaseStreamEventType, raw_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not raw_data:
            return {}

        allowed_keys = EVENT_DATA_ALLOWLIST.get(event_type, set())
        sanitized: Dict[str, Any] = {}

        for key, value in raw_data.items():
            if key in allowed_keys:
                # Extra safety check: do not allow raw credentials or tokens even if named coincidentally
                if any(secret_term in key.lower() for secret_term in ("password", "secret", "token", "jwt", "dsn")):
                    continue
                sanitized[key] = cls._sanitize_val(value)

        return sanitized


class DatabaseStreamEvent(BaseModel):
    """
    Canonical typed SSE event payload matching Phase 3D specification.
    Includes monotonically increasing sequence number and correlation ID.
    """
    sequence_number: int = Field(..., description="Monotonically increasing sequence number starting at 1")
    event: DatabaseStreamEventType = Field(..., description="Event lifecycle identifier")
    protocol_version: str = Field(default="1.0", description="Streaming protocol version")
    correlation_id: str = Field(..., description="Request or Query correlation identifier")
    query_id: str = Field(..., description="Unique ID for this query run")
    stage: str = Field(..., description="Current pipeline execution stage")
    status: str = Field(default="in_progress", description="Stage status: started, completed, error, cancelled")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC emission timestamp")
    elapsed_stage_ms: Optional[float] = Field(default=None, description="Elapsed stage duration in milliseconds")
    elapsed_total_ms: Optional[float] = Field(default=None, description="Total elapsed pipeline time in milliseconds")
    data: Dict[str, Any] = Field(default_factory=dict, description="Strictly allowlisted event payload")

    def to_sse_frame(self) -> str:
        """
        Format event as compliant SSE frame:
        id: <sequence_number>
        event: <event_name>
        data: <json_string>
        \\n\\n
        """
        payload = self.model_dump(mode="json", exclude_none=True)
        json_str = json.dumps(payload, separators=(',', ':'))
        return f"id: {self.sequence_number}\nevent: {self.event.value}\ndata: {json_str}\n\n"
