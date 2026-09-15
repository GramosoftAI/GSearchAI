"""Database Semantic Context

Encapsulates request-scoped and session-scoped semantic intelligence
for a connected database knowledgebase.
"""

from typing import Any, Dict, List, Optional, Set
import uuid
from pydantic import BaseModel, ConfigDict, Field

from .database_knowledge_profile import DatabaseKnowledgeProfile, DiscoveredEntity, DiscoveredMetric
from .models import ApprovedRelationship, BusinessRule, MetricDefinition, SemanticEntity


class DatabaseSemanticContext(BaseModel):
    """
    Unified semantic context for query planning, entity resolution,
    and validation.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    tenant_id: uuid.UUID
    knowledgebase_id: uuid.UUID
    database_id: Optional[uuid.UUID] = None
    database_name: str = "default_db"

    schema_fingerprint: str
    semantic_version: int = 1

    profile: Optional[DatabaseKnowledgeProfile] = None

    # Resolved elements for the active query
    resolved_entity: Optional[SemanticEntity] = None
    resolved_metric: Optional[MetricDefinition] = None
    applicable_rules: List[BusinessRule] = Field(default_factory=list)
    approved_joins: List[ApprovedRelationship] = Field(default_factory=list)

    # Telemetry & Diagnostics
    is_universal_mode: bool = True
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
