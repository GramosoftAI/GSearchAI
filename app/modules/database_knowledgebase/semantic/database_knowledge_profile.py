"""Canonical Database Knowledge Profile

Provides the unified, database-adaptive semantic representation of a client database.
Derived dynamically from actual schema metadata, topological constraints, and controlled profiling.
Zero domain hardcoding.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Set
import uuid
from pydantic import BaseModel, ConfigDict, Field

from ..schemas.canonical import ColumnDataType


class TableCategory(str, Enum):
    """Universal classification of database tables based on structure and topology."""
    ENTITY = "ENTITY"                      # Primary business entity (e.g. employees, customers, patients)
    TRANSACTION = "TRANSACTION"            # Financial / state-changing transactions (orders, payments, invoices)
    EVENT = "EVENT"                        # Temporal logs / occurrences (attendance, audit_log, visits, telemetry)
    REFERENCE = "REFERENCE"                # Lookup / domain reference (departments, categories, status_codes)
    RELATIONSHIP = "RELATIONSHIP"          # Pure junction / association table (employee_project, role_user)
    HISTORY = "HISTORY"                    # Historical versions / temporal snapshots
    AUDIT = "AUDIT"                        # Change auditing / revision tracking
    SYSTEM = "SYSTEM"                      # Engine / framework metadata (migrations, auth_permission, celery)
    SECURITY = "SECURITY"                  # Credentials, auth tokens, passwords, sessions
    CONFIGURATION = "CONFIGURATION"        # System settings, feature flags
    UNKNOWN = "UNKNOWN"


class ColumnSemanticRole(str, Enum):
    """High-level semantic role of a column."""
    IDENTITY = "IDENTITY"                  # Uniquely or descriptively identifies an entity
    TEMPORAL = "TEMPORAL"                  # Time, date, timestamp, duration
    NUMERIC = "NUMERIC"                    # Measurable or aggregatable quantity, price, score
    REFERENCE = "REFERENCE"                # Foreign key or external code
    STATUS = "STATUS"                      # State or status code
    CATEGORY = "CATEGORY"                  # Low-cardinality classifier / grouping
    DESCRIPTIVE = "DESCRIPTIVE"            # Free-text, notes, comments
    UNKNOWN = "UNKNOWN"


class ColumnSemanticSubtype(str, Enum):
    """Granular semantic classification for columns."""
    # Identity subtypes
    PRIMARY_KEY = "PRIMARY_KEY"
    PERSON_FIRST_NAME = "PERSON_FIRST_NAME"
    PERSON_LAST_NAME = "PERSON_LAST_NAME"
    PERSON_FULL_NAME = "PERSON_FULL_NAME"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    USERNAME = "USERNAME"
    BUSINESS_CODE = "BUSINESS_CODE"
    ORGANIZATION_NAME = "ORGANIZATION_NAME"

    # Temporal subtypes
    DATE = "DATE"
    DATETIME = "DATETIME"
    TIME_OF_DAY = "TIME_OF_DAY"
    CREATED_AT = "CREATED_AT"
    UPDATED_AT = "UPDATED_AT"
    DURATION = "DURATION"

    # Numeric subtypes
    CURRENCY = "CURRENCY"
    AMOUNT = "AMOUNT"
    QUANTITY = "QUANTITY"
    PERCENTAGE = "PERCENTAGE"
    COUNTABLE = "COUNTABLE"
    SCORE = "SCORE"

    # Reference & structural
    FOREIGN_KEY = "FOREIGN_KEY"
    STATUS_CODE = "STATUS_CODE"
    BOOLEAN_FLAG = "BOOLEAN_FLAG"
    CATEGORY_TAG = "CATEGORY_TAG"
    GENERIC = "GENERIC"


class CertificationStatus(str, Enum):
    """Readiness lifecycle state of database knowledge profile."""
    DISCOVERING = "DISCOVERING"
    PROFILING = "PROFILING"
    MODELING = "MODELING"
    VALIDATING = "VALIDATING"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class TableClassification(BaseModel):
    """Detailed classification of a single table."""
    model_config = ConfigDict(extra="forbid")

    schema_name: str
    table_name: str
    category: TableCategory
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    primary_key_columns: List[str] = Field(default_factory=list)
    outgoing_fk_count: int = 0
    incoming_fk_count: int = 0
    is_bridge: bool = False
    is_system_or_security: bool = False


class ColumnSemanticProfile(BaseModel):
    """Detailed semantic profile of a single column."""
    model_config = ConfigDict(extra="forbid")

    schema_name: str
    table_name: str
    column_name: str
    data_type: ColumnDataType
    role: ColumnSemanticRole
    subtype: ColumnSemanticSubtype
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_unique: bool = False
    is_nullable: bool = True
    is_sensitive: bool = False


class DiscoveredEntity(BaseModel):
    """Primary business concept derived from one or more physical tables."""
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    semantic_name: str
    display_name: str
    physical_schema: str = "public"
    physical_table: str
    category: TableCategory
    primary_key_columns: List[str]
    identity_columns: List[str] = Field(default_factory=list)
    name_columns: List[str] = Field(default_factory=list)
    attributes: Dict[str, str] = Field(default_factory=dict, description="Attribute name -> physical column")
    synonyms: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    evidence: List[str] = Field(default_factory=list)


class DiscoveredRelationship(BaseModel):
    """Relational connection between tables with confidence and provenance."""
    model_config = ConfigDict(extra="forbid")

    relationship_id: str
    source_schema: str
    source_table: str
    source_columns: List[str]
    target_schema: str
    target_table: str
    target_columns: List[str]
    is_declared_fk: bool = True
    cardinality: str = "MANY_TO_ONE"  # ONE_TO_ONE, ONE_TO_MANY, MANY_TO_ONE, MANY_TO_MANY
    confidence: float = 1.0
    evidence: List[str] = Field(default_factory=list)


class DiscoveredMetric(BaseModel):
    """Calculable business metric discovered from numeric columns."""
    model_config = ConfigDict(extra="forbid")

    metric_id: str
    name: str
    display_name: str
    source_schema: str
    source_table: str
    source_column: str
    metric_subtype: ColumnSemanticSubtype
    default_aggregation: str = "SUM"  # SUM, AVG, COUNT, MIN, MAX
    expression: str
    unit: Optional[str] = None
    synonyms: List[str] = Field(default_factory=list)
    confidence: float = 0.8
    evidence: List[str] = Field(default_factory=list)


class TemporalColumnProfile(BaseModel):
    """Temporal capability of a column."""
    model_config = ConfigDict(extra="forbid")

    schema_name: str
    table_name: str
    column_name: str
    temporal_subtype: ColumnSemanticSubtype
    supports_time_filter: bool = True
    supports_date_range: bool = True


class IdentityField(BaseModel):
    """Likely identity field for entity lookup."""
    model_config = ConfigDict(extra="forbid")

    schema_name: str
    table_name: str
    column_name: str
    identity_subtype: ColumnSemanticSubtype
    confidence: float
    is_primary_key: bool = False
    evidence: List[str] = Field(default_factory=list)


class DatabaseKnowledgeProfile(BaseModel):
    """
    Authoritative database-specific semantic intelligence profile.
    Versioned, explainable, cacheable, and tenant-isolated.
    """
    model_config = ConfigDict(extra="forbid")

    database_id: uuid.UUID
    tenant_id: uuid.UUID
    knowledgebase_id: uuid.UUID

    database_name: str
    schema_fingerprint: str
    semantic_version: int = 1

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    certification_status: CertificationStatus = CertificationStatus.DISCOVERING
    certification_report: Dict[str, Any] = Field(default_factory=dict)

    # Core Registries
    tables: Dict[str, TableClassification] = Field(default_factory=dict, description="Keyed by schema.table")
    columns: Dict[str, ColumnSemanticProfile] = Field(default_factory=dict, description="Keyed by schema.table.column")
    entities: Dict[str, DiscoveredEntity] = Field(default_factory=dict, description="Keyed by entity_id")
    relationships: List[DiscoveredRelationship] = Field(default_factory=list)
    identity_fields: Dict[str, List[IdentityField]] = Field(default_factory=dict, description="Keyed by entity_id")
    metrics: Dict[str, DiscoveredMetric] = Field(default_factory=dict, description="Keyed by metric_id")
    temporal_fields: Dict[str, TemporalColumnProfile] = Field(default_factory=dict, description="Keyed by schema.table.column")

    # Security & System boundaries
    system_tables: Set[str] = Field(default_factory=set)
    security_tables: Set[str] = Field(default_factory=set)
    excluded_tables: Set[str] = Field(default_factory=set)

    # Telemetry
    confidence_summary: Dict[str, float] = Field(default_factory=dict)

    def get_entity_for_table(self, table_name: str, schema_name: str = "public") -> Optional[DiscoveredEntity]:
        """Find the DiscoveredEntity corresponding to physical table."""
        for ent in self.entities.values():
            if ent.physical_table.lower() == table_name.lower() and ent.physical_schema.lower() == schema_name.lower():
                return ent
        return None

    def get_identity_columns(self, table_name: str) -> List[str]:
        """Get column names suitable for entity value / name lookups."""
        ent = self.get_entity_for_table(table_name)
        if ent and ent.identity_columns:
            return ent.identity_columns
        # Fallback to identity_fields registry
        res = []
        for fields in self.identity_fields.values():
            for f in fields:
                if f.table_name.lower() == table_name.lower():
                    res.append(f.column_name)
        return list(dict.fromkeys(res))

    def compute_profile_fingerprint(self) -> str:
        """Deterministic hash of all semantic components."""
        summary = {
            "fp": self.schema_fingerprint,
            "v": self.semantic_version,
            "entities": sorted(list(self.entities.keys())),
            "metrics": sorted(list(self.metrics.keys())),
            "relationships": len(self.relationships),
            "status": self.certification_status.value,
        }
        raw = json.dumps(summary, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()
