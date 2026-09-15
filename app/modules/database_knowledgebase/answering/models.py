"""Domain Models for Phase 2D: Grounded Database Answer Synthesis

Provides strict Pydantic v2 schemas for evidence representation, verification reports,
grounding status, and the terminal output contract: GroundedDatabaseAnswer.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid
from pydantic import BaseModel, ConfigDict, Field

from ..execution.models import CanonicalQueryResult
from ..observability.models import PipelineTrace


class AnswerType(str, Enum):
    """Classification of the synthesized answer format."""
    SCALAR = "SCALAR"              # Single metric or scalar (e.g. COUNT(*), SUM(total))
    COUNT = "COUNT"                # Discrete count of items
    AGGREGATION = "AGGREGATION"    # Grouped aggregate summary
    SINGLE_ROW = "SINGLE_ROW"      # Detailed representation of one entity record
    MULTI_ROW = "MULTI_ROW"        # Tabular or structured multiple entities
    RANKING = "RANKING"            # Ordered top-N list
    EMPTY = "EMPTY"                # Zero records found
    TRUNCATED = "TRUNCATED"        # Results truncated at system bounds
    NARRATIVE = "NARRATIVE"        # Complex multi-entity explanatory synthesis


class GroundingStatus(str, Enum):
    """Grounding verification result status."""
    VERIFIED = "VERIFIED"                        # Successfully verified against evidence
    REPAIRED = "REPAIRED"                        # Verified after 1 targeted repair attempt
    FALLBACK_DETERMINISTIC = "FALLBACK_DETERMINISTIC"  # Failed LLM validation; failed closed to deterministic formatter


class VerificationStatus(str, Enum):
    """Status of the deterministic verification gate."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    BYPASSED_DETERMINISTIC = "BYPASSED_DETERMINISTIC"


class EvidenceModel(BaseModel):
    """
    Lossless representation of database query evidence.
    Preserves exact Decimal representations, dates, column types, and allowed derivations.
    """
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(..., description="Unique query execution trace ID")
    database_knowledgebase_id: uuid.UUID = Field(..., description="Target database knowledgebase ID")
    schema_version: str = Field(..., description="Schema fingerprint version")
    columns: List[str] = Field(default_factory=list, description="Projected column names")
    column_types: Dict[str, str] = Field(default_factory=dict, description="Column data types")
    rows: List[Dict[str, Any]] = Field(default_factory=list, description="Normalized database rows")
    row_count: int = Field(default=0, ge=0, description="Total number of returned rows")
    truncated: bool = Field(default=False, description="Whether the result was truncated")
    execution_time_ms: float = Field(default=0.0, ge=0.0, description="Query execution duration in ms")
    
    # Supported Facts for Verification Gate
    supported_numbers: List[str] = Field(
        default_factory=list,
        description="All literal and validly derived numerical strings supported by evidence",
    )
    supported_entities: List[str] = Field(
        default_factory=list,
        description="All named entities, email strings, categories, and identifiers present in rows",
    )
    summary_metrics: Dict[str, str] = Field(
        default_factory=dict,
        description="Deterministic pre-calculated aggregates (sums, counts, min, max) preserving exact string precision",
    )


class GroundingReport(BaseModel):
    """Detailed audit report produced by the AnswerVerifier."""
    model_config = ConfigDict(extra="forbid")

    is_grounded: bool = Field(..., description="Whether answer satisfies all grounding and numerical checks")
    verification_status: VerificationStatus = Field(..., description="Overall verification outcome")
    unsupported_numbers: List[str] = Field(default_factory=list, description="Numbers in answer not supported by evidence")
    unsupported_entities: List[str] = Field(default_factory=list, description="Entities/names in answer not found in evidence")
    unsupported_claims: List[str] = Field(default_factory=list, description="Unsupported rankings, causal claims, or totals")
    warnings: List[str] = Field(default_factory=list, description="Audit warnings or truncation notices")
    repair_feedback: Optional[str] = Field(default=None, description="Actionable instruction for repair loop if failed")


class GroundedDatabaseAnswer(BaseModel):
    """
    Terminal output contract of Phase 2D.
    Safe, verifiable, natural-language database answer grounded in database evidence.
    """
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(..., description="Execution trace query UUID")
    database_knowledgebase_id: uuid.UUID = Field(..., description="Target database knowledgebase UUID")
    schema_version: str = Field(..., description="Schema version against which the answer is grounded")
    answer_text: str = Field(..., description="Synthesized and verified natural language answer")
    answer_type: AnswerType = Field(..., description="Classification of the answer format")
    evidence: EvidenceModel = Field(..., description="Structured lossless evidence supporting the answer")
    source_columns: List[str] = Field(default_factory=list, description="Database columns used in the answer")
    row_count: int = Field(default=0, ge=0, description="Total matching database rows")
    truncated: bool = Field(default=False, description="Whether the underlying query result was truncated")
    grounding_status: GroundingStatus = Field(..., description="Status of grounding verification")
    verification_status: VerificationStatus = Field(..., description="Verification gate outcome")
    warnings: List[str] = Field(default_factory=list, description="Disclaimers, audit warnings, or truncation notices")
    generation_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Safe generation telemetry (latency, repair attempts, deterministic path)",
    )
    rows: List[Dict[str, Any]] = Field(default_factory=list, description="Database rows for backwards compatibility")
    columns: List[str] = Field(default_factory=list, description="Projected column names for backwards compatibility")
    raw_result: Optional[CanonicalQueryResult] = Field(
        default=None,
        description="Attached CanonicalQueryResult for backwards-compatible consumers",
    )
    pipeline_trace: Optional[PipelineTrace] = Field(
        default=None,
        description="Phase 3A End-to-end pipeline trace and observability telemetry",
    )
