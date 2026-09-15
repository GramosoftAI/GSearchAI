"""Phase 6 Semantic Intelligence & Context Layer Data Models

Strongly typed Pydantic models representing:
- Semantic entities and attributes
- Metrics with canonical definitions and formulas
- Approved semantic relationships
- Business and operational rules
- Value profile samples
- Ambiguity reports and candidates
- Verified query memory records
- Unified context fingerprints
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid

from pydantic import BaseModel, ConfigDict, Field


# ==============================================================================
# PHASE 6A: SEMANTIC ENTITIES & ATTRIBUTES
# ==============================================================================

class SensitivityLevel(str, Enum):
    """Sensitivity classification for semantic attributes."""
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class SemanticOperation(str, Enum):
    """Permitted query operations on semantic attributes."""
    SELECT = "SELECT"
    FILTER = "FILTER"
    AGGREGATE = "AGGREGATE"
    GROUP_BY = "GROUP_BY"
    ORDER_BY = "ORDER_BY"
    JOIN = "JOIN"


class SemanticAttribute(BaseModel):
    """Semantic mapping for a physical database column."""
    model_config = ConfigDict(extra="forbid")

    attribute_id: str = Field(..., description="Unique attribute identifier within entity")
    display_name: str = Field(..., description="Human-readable business name")
    description: Optional[str] = Field(default=None, description="Business context / description")
    physical_column: str = Field(..., description="Physical database column name")
    synonyms: List[str] = Field(default_factory=list, description="Business synonyms / aliases")
    is_dimension: bool = Field(default=False, description="Whether attribute is a grouping dimension")
    is_measure: bool = Field(default=False, description="Whether attribute is a numeric measure")
    is_identifier: bool = Field(default=False, description="Whether attribute is an identifier/key")
    sensitivity: SensitivityLevel = Field(default=SensitivityLevel.INTERNAL, description="Data classification")
    allowed_operations: List[SemanticOperation] = Field(
        default_factory=lambda: [
            SemanticOperation.SELECT,
            SemanticOperation.FILTER,
            SemanticOperation.AGGREGATE,
            SemanticOperation.GROUP_BY,
            SemanticOperation.ORDER_BY,
            SemanticOperation.JOIN,
        ],
        description="Allowed operations on this attribute",
    )


class SemanticEntity(BaseModel):
    """Semantic business model representing a physical database table."""
    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(..., description="Unique semantic entity identifier")
    name: str = Field(..., description="Canonical business entity name (e.g. 'Employee')")
    display_name: str = Field(..., description="Human-readable label")
    description: Optional[str] = Field(default=None, description="Detailed business description")
    physical_schema: str = Field(default="public", description="Physical database schema")
    physical_table: str = Field(..., description="Physical database table name")
    synonyms: List[str] = Field(default_factory=list, description="Synonyms for this entity")
    attributes: Dict[str, SemanticAttribute] = Field(default_factory=dict, description="Attributes mapped by name")
    primary_key_attribute: Optional[str] = Field(default=None, description="Primary key attribute name")
    tenant_id: uuid.UUID = Field(..., description="Tenant owner")
    knowledgebase_id: uuid.UUID = Field(..., description="Knowledgebase owner")
    schema_version: Optional[str] = Field(default=None, description="Compatible schema snapshot fingerprint")
    version: int = Field(default=1, description="Entity model revision version")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==============================================================================
# PHASE 6B: CANONICAL METRIC REGISTRY
# ==============================================================================

class MetricType(str, Enum):
    """Standard aggregate and calculation types for metrics."""
    COUNT = "COUNT"
    SUM = "SUM"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"
    CUSTOM = "CUSTOM"


class MetricDefinition(BaseModel):
    """Authoritative semantic metric definition."""
    model_config = ConfigDict(extra="forbid")

    metric_id: str = Field(..., description="Unique metric identifier (e.g. 'total_salary')")
    name: str = Field(..., description="Canonical metric identifier")
    display_name: str = Field(..., description="Human-friendly label (e.g. 'Total Salary')")
    description: Optional[str] = Field(default=None, description="Business description of calculation")
    expression: str = Field(..., description="Canonical formula (e.g. 'SUM(employees.salary)')")
    aggregation: MetricType = Field(..., description="Aggregation function")
    source_entity: str = Field(..., description="Source semantic entity name")
    source_column: str = Field(..., description="Source physical column name")
    filter_condition: Optional[str] = Field(default=None, description="Mandatory metric filter (e.g. status = 'active')")
    supported_dimensions: List[str] = Field(default_factory=list, description="Approved group-by dimensions")
    synonyms: List[str] = Field(default_factory=list, description="Natural language phrases for metric")
    unit: Optional[str] = Field(default=None, description="Unit of measurement (e.g. USD, count, ratio)")
    format_pattern: Optional[str] = Field(default=None, description="Formatting hint (e.g. '${:,.2f}')")
    tenant_id: uuid.UUID = Field(..., description="Tenant owner")
    knowledgebase_id: uuid.UUID = Field(..., description="Knowledgebase owner")
    schema_version: Optional[str] = Field(default=None, description="Compatible schema version")
    version: int = Field(default=1, description="Metric revision version")
    status: str = Field(default="ACTIVE", description="ACTIVE, DEPRECATED, DISABLED")
    provenance: str = Field(default="SYSTEM_VERIFIED", description="Origin: CURATED, SYSTEM_VERIFIED, LEARNED")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==============================================================================
# PHASE 6C: APPROVED RELATIONSHIP GRAPH
# ==============================================================================

class RelationshipCardinality(str, Enum):
    """Cardinality classification between entities."""
    ONE_TO_ONE = "ONE_TO_ONE"
    ONE_TO_MANY = "ONE_TO_MANY"
    MANY_TO_ONE = "MANY_TO_ONE"
    MANY_TO_MANY = "MANY_TO_MANY"


class ApprovedRelationship(BaseModel):
    """Semantically vetted relationship between database entities."""
    model_config = ConfigDict(extra="forbid")

    relationship_id: str = Field(..., description="Unique relationship identifier")
    source_entity: str = Field(..., description="Source semantic entity name")
    target_entity: str = Field(..., description="Target semantic entity name")
    source_table: str = Field(..., description="Physical source table")
    target_table: str = Field(..., description="Physical target table")
    source_columns: List[str] = Field(..., description="Source join columns")
    target_columns: List[str] = Field(..., description="Target join columns")
    cardinality: RelationshipCardinality = Field(..., description="Relational cardinality")
    business_description: str = Field(..., description="Human description (e.g. 'Employee belongs to Department')")
    approved_for: List[str] = Field(default_factory=list, description="Approved business use cases")
    confidence: float = Field(default=1.0, description="Verification confidence 0.0 - 1.0")
    tenant_id: uuid.UUID = Field(..., description="Tenant owner")
    knowledgebase_id: uuid.UUID = Field(..., description="Knowledgebase owner")
    schema_version: Optional[str] = Field(default=None, description="Compatible schema snapshot fingerprint")
    version: int = Field(default=1, description="Relationship revision version")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==============================================================================
# PHASE 6D: BUSINESS RULES REGISTRY
# ==============================================================================

class RuleScope(str, Enum):
    """Scope of application for business rule."""
    ENTITY_FILTER = "ENTITY_FILTER"
    METRIC_ADJUSTMENT = "METRIC_ADJUSTMENT"
    JOIN_RESTRICTION = "JOIN_RESTRICTION"
    COLUMN_MASKING = "COLUMN_MASKING"


class BusinessRule(BaseModel):
    """Structured, versioned operational business rule."""
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(..., description="Unique business rule identifier")
    name: str = Field(..., description="Short canonical name")
    description: str = Field(..., description="Business explanation (e.g. 'Active employee means status = active')")
    scope: RuleScope = Field(..., description="Rule application domain")
    condition_expression: str = Field(..., description="Structured predicate (e.g. \"status = 'active'\")")
    effect_description: str = Field(..., description="Operational effect")
    referenced_entities: List[str] = Field(default_factory=list, description="Entities governed by this rule")
    referenced_columns: List[str] = Field(default_factory=list, description="Columns evaluated in condition")
    priority: int = Field(default=10, description="Evaluation priority: higher runs first")
    status: str = Field(default="ACTIVE", description="ACTIVE, INACTIVE, DRAFT")
    tenant_id: uuid.UUID = Field(..., description="Tenant owner")
    knowledgebase_id: uuid.UUID = Field(..., description="Knowledgebase owner")
    version: int = Field(default=1, description="Rule version")
    provenance: str = Field(default="CURATED", description="CURATED, COMPLIANCE, SYSTEM")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==============================================================================
# PHASE 6E: PLAN VALIDATOR
# ==============================================================================

class ValidationOutcome(str, Enum):
    """PlanValidator definitive outcome."""
    PASS = "PASS"
    REJECT = "REJECT"


class ValidationReasonCode(str, Enum):
    """Machine-readable plan validation failure reason codes."""
    SEMANTIC_ENTITY_NOT_FOUND = "SEMANTIC_ENTITY_NOT_FOUND"
    METRIC_NOT_FOUND = "METRIC_NOT_FOUND"
    AMBIGUOUS_METRIC = "AMBIGUOUS_METRIC"
    RELATIONSHIP_NOT_APPROVED = "RELATIONSHIP_NOT_APPROVED"
    INVALID_JOIN_PATH = "INVALID_JOIN_PATH"
    UNAUTHORIZED_COLUMN = "UNAUTHORIZED_COLUMN"
    UNAUTHORIZED_TABLE = "UNAUTHORIZED_TABLE"
    INVALID_AGGREGATION = "INVALID_AGGREGATION"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    UNSUPPORTED_PLAN = "UNSUPPORTED_PLAN"
    SECURITY_POLICY_VIOLATION = "SECURITY_POLICY_VIOLATION"
    MISSING_REQUIRED_ENTITY = "MISSING_REQUIRED_ENTITY"
    MISSING_RELATIONSHIP_PATH = "MISSING_RELATIONSHIP_PATH"
    SEMANTIC_PLAN_VALIDATION_FAILED = "SEMANTIC_PLAN_VALIDATION_FAILED"


class PlanValidationResult(BaseModel):
    """Detailed result produced by PlanValidator."""
    model_config = ConfigDict(extra="forbid")

    outcome: ValidationOutcome = Field(..., description="PASS or REJECT")
    reason_code: Optional[ValidationReasonCode] = Field(default=None, description="Machine-readable code on reject")
    message: str = Field(..., description="Human/diagnostic explanation")
    offending_object: Optional[str] = Field(default=None, description="Identifier of the offending object")
    details: Dict[str, Any] = Field(default_factory=dict, description="Diagnostic context")


# ==============================================================================
# PHASE 6F: CONTROLLED VALUE PROFILING
# ==============================================================================

class ValueProfileSample(BaseModel):
    """Bounded, safe metadata sample for low-cardinality columns."""
    model_config = ConfigDict(extra="forbid")

    entity_name: str = Field(..., description="Semantic entity name")
    table_name: str = Field(..., description="Physical table name")
    column_name: str = Field(..., description="Physical column name")
    distinct_values: List[Any] = Field(default_factory=list, description="Bounded set of distinct values")
    cardinality_estimate: Optional[int] = Field(default=None, description="Estimated unique count")
    null_ratio: Optional[float] = Field(default=None, description="Percentage of NULL values")
    min_value: Optional[Any] = Field(default=None, description="Safe minimum value")
    max_value: Optional[Any] = Field(default=None, description="Safe maximum value")
    sample_bounded_limit: int = Field(default=20, description="Max samples fetched")
    is_sensitive: bool = Field(default=False, description="Whether flagged as sensitive (must NOT profile)")
    tenant_id: uuid.UUID = Field(..., description="Tenant owner")
    knowledgebase_id: uuid.UUID = Field(..., description="Knowledgebase owner")
    profiled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==============================================================================
# PHASE 6G: AMBIGUITY DETECTION
# ==============================================================================

class AmbiguityStatus(str, Enum):
    """Ambiguity classification of user query."""
    UNAMBIGUOUS = "UNAMBIGUOUS"
    AMBIGUOUS = "AMBIGUOUS"


class AmbiguityAction(str, Enum):
    """Prescribed action for handling semantic ambiguity."""
    PROCEED = "PROCEED"
    CLARIFICATION = "CLARIFICATION"
    SAFE_DEFAULT = "SAFE_DEFAULT"
    LLM_FALLBACK = "LLM_FALLBACK"


class CandidateMeaning(BaseModel):
    """Possible semantic interpretation of an ambiguous question."""
    model_config = ConfigDict(extra="forbid")

    meaning_id: str = Field(..., description="Unique candidate identifier")
    description: str = Field(..., description="Explanation of this interpretation")
    confidence: float = Field(..., description="Score 0.0 - 1.0")
    mapped_metric: Optional[str] = Field(default=None, description="Associated metric ID if applicable")
    mapped_entity: Optional[str] = Field(default=None, description="Associated entity ID if applicable")
    mapped_filters: List[str] = Field(default_factory=list, description="Associated filter conditions")


class AmbiguityReport(BaseModel):
    """Structured report produced by AmbiguityDetector before planning."""
    model_config = ConfigDict(extra="forbid")

    status: AmbiguityStatus = Field(..., description="UNAMBIGUOUS or AMBIGUOUS")
    candidate_meanings: List[CandidateMeaning] = Field(default_factory=list, description="Candidate interpretations")
    required_action: AmbiguityAction = Field(..., description="Required workflow action")
    selected_meaning: Optional[CandidateMeaning] = Field(default=None, description="Resolved interpretation if unambiguous or safe default")
    ambiguity_token: Optional[str] = Field(default=None, description="Word or phrase causing ambiguity")


# ==============================================================================
# PHASE 6H: VERIFIED QUERY MEMORY
# ==============================================================================

class VerifiedQueryMemoryRecord(BaseModel):
    """Memory record for queries that successfully executed and verified."""
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(..., description="Unique memory record ID")
    normalized_query: str = Field(..., description="Normalized natural language query")
    raw_query: str = Field(..., description="Original raw natural language query")
    semantic_intent: str = Field(..., description="Intent classification")
    selected_entities: List[str] = Field(default_factory=list, description="Resolved semantic entities")
    selected_metric: Optional[str] = Field(default=None, description="Resolved metric ID if any")
    selected_relationships: List[str] = Field(default_factory=list, description="Approved relationship IDs used")
    applied_rules: List[str] = Field(default_factory=list, description="Business rule IDs applied")
    compiled_sql: str = Field(..., description="Safe compiled SQL")
    context_fingerprint: str = Field(..., description="Context fingerprint when executed")
    schema_fingerprint: str = Field(..., description="Database schema fingerprint")
    grounding_status: str = Field(..., description="Grounding status (VERIFIED/REPAIRED)")
    verifier_status: str = Field(..., description="AnswerVerifier status (PASSED)")
    execution_count: int = Field(default=1, description="Times successfully matched and reused")
    tenant_id: uuid.UUID = Field(..., description="Tenant owner")
    knowledgebase_id: uuid.UUID = Field(..., description="Knowledgebase owner")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==============================================================================
# PHASE 6I: CONTEXT FINGERPRINTING
# ==============================================================================

class ContextFingerprint(BaseModel):
    """Deterministic hash bundle of all semantic context and schema versions."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(..., description="Canonical schema snapshot fingerprint")
    semantic_registry_version: str = Field(..., description="Semantic entity registry version hash")
    metric_registry_version: str = Field(..., description="Metric registry version hash")
    relationship_graph_version: str = Field(..., description="Relationship graph version hash")
    business_rules_version: str = Field(..., description="Business rules version hash")
    security_policy_version: str = Field(default="v1.0", description="Security policy version")
    combined_fingerprint: str = Field(..., description="Deterministic SHA256 of all components")
