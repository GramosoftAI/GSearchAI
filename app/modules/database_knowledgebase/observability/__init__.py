"""Phase 3A: Production Observability & Audit Logging Package

Provides stage-by-stage tracing, diagnostic telemetry, structured audit logging,
anti-leakage parameter sanitization, and production operational metrics.
"""

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
from .tracer import PipelineTracer
from .writer import AuditWriter
from .retention import AuditLogRetentionManager

__all__ = [
    "RetrievalTrace",
    "PlanningTrace",
    "SQLGenerationTrace",
    "ExecutionTrace",
    "SynthesisTrace",
    "PipelineTrace",
    "PipelineTracer",
    "DatabaseQueryAuditLog",
    "AuditSanitizer",
    "AuditEventNames",
    "DatabaseAuditLogger",
    "DatabaseKnowledgebaseMetrics",
    "AuditWriter",
    "AuditLogRetentionManager",
]
