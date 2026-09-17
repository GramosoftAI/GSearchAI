"""Domain Models for Phase 3A: Pipeline Observability & Query Traceability

Provides structured telemetry capturing decisions across retrieval, query planning,
SQL generation, AST validation, execution, and grounded answer synthesis.
Ensures zero leakage of credentials, passwords, or connection strings.
"""

from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class RetrievalTrace(BaseModel):
    """Telemetry capturing Phase 2A semantic schema retrieval."""
    model_config = ConfigDict(extra="forbid")

    retrieved_tables: List[str] = Field(default_factory=list, description="Tables selected by retriever")
    table_scores: Dict[str, float] = Field(default_factory=dict, description="Relevance scores per table")
    omitted_tables: List[str] = Field(default_factory=list, description="Tables evaluated but excluded")
    retrieved_columns: Dict[str, List[str]] = Field(default_factory=dict, description="Columns preserved per table")
    selected_relationships: List[str] = Field(default_factory=list, description="Join paths / relationships selected")
    latency_ms: float = Field(default=0.0, ge=0.0, description="Retrieval latency in milliseconds")


class PlanningTrace(BaseModel):
    """Telemetry capturing Phase 2B query planning and IR construction."""
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(default="UNKNOWN", description="Classified user query intent")
    tables: List[str] = Field(default_factory=list, description="Tables incorporated into QueryPlanIR")
    joins: List[str] = Field(default_factory=list, description="Join conditions planned")
    filters: List[str] = Field(default_factory=list, description="Filter predicates extracted")
    aggregations: List[str] = Field(default_factory=list, description="Aggregation expressions planned")
    group_by: List[str] = Field(default_factory=list, description="Group by columns planned")
    order_by: List[str] = Field(default_factory=list, description="Order by planned")
    limit: Optional[int] = Field(default=None, description="Planned query row limit")
    latency_ms: float = Field(default=0.0, ge=0.0, description="Planning duration in milliseconds")


class SQLGenerationTrace(BaseModel):
    """Telemetry capturing Phase 2B candidate SQL generation, parameterization, and AST security policy."""
    model_config = ConfigDict(extra="forbid")

    candidate_sql: str = Field(default="", description="Generated candidate SQL query")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Extracted parameter literals")
    ast_valid: bool = Field(default=True, description="Whether AST security inspection passed")
    ast_errors: List[str] = Field(default_factory=list, description="AST policy errors if any")
    ast_warnings: List[str] = Field(default_factory=list, description="AST policy warnings")
    repair_attempts: int = Field(default=0, ge=0, description="Number of SQL repair iterations executed")
    validation_latency_ms: float = Field(default=0.0, ge=0.0, description="AST security validation latency in ms")
    latency_ms: float = Field(default=0.0, ge=0.0, description="SQL generation and validation latency in ms")
    sql_generation_mode: str = Field(default="llm", description="'deterministic' or 'llm'")
    deterministic_sql_compilation: bool = Field(default=False, description="Whether SQL was deterministically compiled")
    sql_llm_bypassed: bool = Field(default=False, description="Whether SQL LLM was bypassed")


class ExecutionTrace(BaseModel):
    """Telemetry capturing Phase 2C safe read-only database execution."""
    model_config = ConfigDict(extra="forbid")

    executed: bool = Field(default=False, description="Whether query was executed against driver")
    row_count: int = Field(default=0, ge=0, description="Number of rows returned from driver")
    truncated: bool = Field(default=False, description="Whether result exceeded result limiter bounds")
    execution_time_ms: float = Field(default=0.0, ge=0.0, description="Driver-level execution duration in ms")
    normalization_latency_ms: float = Field(default=0.0, ge=0.0, description="Result normalization latency in ms")
    column_count: int = Field(default=0, ge=0, description="Number of columns in result set")
    error: Optional[str] = Field(default=None, description="Sanitized driver error if execution failed")


class SynthesisTrace(BaseModel):
    """Telemetry capturing Phase 2D answer synthesis, fast-paths, and grounding verification."""
    model_config = ConfigDict(extra="forbid")

    answer_type: str = Field(default="UNKNOWN", description="Classification of generated answer")
    deterministic: bool = Field(default=False, description="Whether answer bypassed LLM via deterministic fast-path")
    grounding_status: str = Field(default="UNKNOWN", description="Outcome of grounding gate")
    verification_status: str = Field(default="UNKNOWN", description="Status of verifier gate")
    fallback_used: bool = Field(default=False, description="Whether deterministic fallback presentation was used")
    repair_attempts: int = Field(default=0, ge=0, description="Answer repair iterations executed")
    grounding_latency_ms: float = Field(default=0.0, ge=0.0, description="Grounding verification latency in ms")
    latency_ms: float = Field(default=0.0, ge=0.0, description="Answer synthesis latency in milliseconds")


class PipelineTrace(BaseModel):
    """Comprehensive end-to-end trace aggregating telemetry from all pipeline stages."""
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(..., description="Unique query execution trace ID")
    request_id: Optional[str] = Field(default=None, description="HTTP correlation request ID")
    tenant_id: Optional[str] = Field(default=None, description="Tenant UUID string")
    user_id: Optional[str] = Field(default=None, description="User UUID string")
    database_knowledgebase_id: uuid.UUID = Field(..., description="Target database knowledgebase ID")
    schema_version: str = Field(default="", description="Schema fingerprint version")
    user_query: str = Field(..., description="User's original natural-language question")
    success: bool = Field(default=True, description="Overall pipeline success status")
    final_status: str = Field(default="SUCCESS", description="Final lifecycle status code")
    total_latency_ms: float = Field(default=0.0, ge=0.0, description="Total pipeline latency in milliseconds")
    error: Optional[str] = Field(default=None, description="Sanitized pipeline error if failed")

    # Stage Traces
    retrieval: RetrievalTrace = Field(default_factory=RetrievalTrace)
    planning: PlanningTrace = Field(default_factory=PlanningTrace)
    sql_generation: SQLGenerationTrace = Field(default_factory=SQLGenerationTrace)
    execution: ExecutionTrace = Field(default_factory=ExecutionTrace)
    synthesis: SynthesisTrace = Field(default_factory=SynthesisTrace)
