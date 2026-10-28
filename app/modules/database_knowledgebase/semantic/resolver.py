"""Phase 6: Semantic Context Resolver

Orchestrates semantic resolution before QueryIntentAnalyzer and QueryPlanner:
1. Normalization
2. Ambiguity Detection
3. Metric Resolution
4. Semantic Entity Resolution
5. Applicable Business Rules
6. Approved Relationship Paths
7. Context Fingerprinting
8. Verified Query Memory Recall
"""

from typing import List, Optional, Tuple
import uuid
from pydantic import BaseModel, ConfigDict, Field

from .models import (
    AmbiguityAction,
    AmbiguityReport,
    ApprovedRelationship,
    BusinessRule,
    ContextFingerprint,
    MetricDefinition,
    SemanticEntity,
    VerifiedQueryMemoryRecord,
)
from .registry import SemanticModelRegistry
from .metrics import CanonicalMetricRegistry
from .relationships import SemanticRelationshipGraph
from .business_rules import BusinessRuleRegistry
from .ambiguity import AmbiguityDetector
from .fingerprint import ContextFingerprinter
from .memory import VerifiedQueryMemory


class SemanticResolutionResult(BaseModel):
    """Complete structured semantic resolution outcome."""
    model_config = ConfigDict(extra="forbid")

    normalized_query: str
    ambiguity_report: AmbiguityReport
    resolved_metric: Optional[MetricDefinition] = None
    resolved_entities: List[SemanticEntity] = Field(default_factory=list)
    applicable_rules: List[BusinessRule] = Field(default_factory=list)
    approved_joins: List[ApprovedRelationship] = Field(default_factory=list)
    context_fingerprint: ContextFingerprint
    recalled_memory: Optional[VerifiedQueryMemoryRecord] = None


class SemanticResolver:
    """
    Central coordinator resolving natural language intent into structured semantic context.
    Provides authoritative business meaning prior to SQL planning.
    """

    def __init__(
        self,
        semantic_registry: Optional[SemanticModelRegistry] = None,
        metric_registry: Optional[CanonicalMetricRegistry] = None,
        relationship_graph: Optional[SemanticRelationshipGraph] = None,
        business_rules: Optional[BusinessRuleRegistry] = None,
        query_memory: Optional[VerifiedQueryMemory] = None,
    ):
        self.semantic_registry = semantic_registry or SemanticModelRegistry()
        self.metric_registry = metric_registry or CanonicalMetricRegistry()
        self.relationship_graph = relationship_graph or SemanticRelationshipGraph()
        self.business_rules = business_rules or BusinessRuleRegistry()
        self.query_memory = query_memory or VerifiedQueryMemory()

    def resolve(
        self,
        query: str,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        schema_version: str,
    ) -> SemanticResolutionResult:
        """
        Execute deterministic semantic resolution.
        """
        norm_q = VerifiedQueryMemory.normalize_query(query)

        # 1. Compute unified context fingerprint
        ctx_fp = ContextFingerprinter.compute(
            tenant_id=tenant_id,
            knowledgebase_id=knowledgebase_id,
            schema_version=schema_version,
            semantic_registry=self.semantic_registry,
            metric_registry=self.metric_registry,
            relationship_graph=self.relationship_graph,
            business_rules=self.business_rules,
        )

        # 2. Check Verified Query Memory
        recalled = self.query_memory.recall_verified_query(
            query=norm_q,
            tenant_id=tenant_id,
            knowledgebase_id=knowledgebase_id,
            current_context_fingerprint=ctx_fp.combined_fingerprint,
            current_schema_fingerprint=schema_version,
        )

        # 3. Detect Ambiguity
        ambiguity = AmbiguityDetector.detect_ambiguity(
            query=query,
            tenant_id=tenant_id,
            knowledgebase_id=knowledgebase_id,
            metric_registry=self.metric_registry,
            semantic_registry=self.semantic_registry,
        )

        # 4. Resolve Metric (if unambiguous)
        resolved_metric: Optional[MetricDefinition] = None
        if ambiguity.selected_meaning and ambiguity.selected_meaning.mapped_metric:
            resolved_metric = self.metric_registry.get_metric(
                tenant_id, knowledgebase_id, ambiguity.selected_meaning.mapped_metric
            )
        else:
            metric_match = self.metric_registry.resolve_metric(query, tenant_id, knowledgebase_id)
            if metric_match:
                resolved_metric = metric_match[0]

        # 5. Resolve Semantic Entities
        matched_entities_raw = self.semantic_registry.resolve_entities(query, tenant_id, knowledgebase_id)
        resolved_entities = [item[0] for item in matched_entities_raw]

        # If a metric was resolved, ensure its source entity is included
        if resolved_metric:
            src_entity = self.semantic_registry.get_entity_by_name(
                tenant_id, knowledgebase_id, resolved_metric.source_entity
            )
            if src_entity and src_entity.entity_id not in [e.entity_id for e in resolved_entities]:
                resolved_entities.insert(0, src_entity)

        # 6. Evaluate Business Rules
        entity_names = [e.name for e in resolved_entities]
        applicable_rules = self.business_rules.get_applicable_rules(
            entities=entity_names,
            tenant_id=tenant_id,
            knowledgebase_id=knowledgebase_id,
        )

        # 7. Collect Approved Relationships for resolved tables
        approved_joins: List[ApprovedRelationship] = []
        if len(resolved_entities) >= 2:
            for i in range(len(resolved_entities)):
                for j in range(i + 1, len(resolved_entities)):
                    src_tbl = resolved_entities[i].physical_table
                    tgt_tbl = resolved_entities[j].physical_table
                    path = self.relationship_graph.find_approved_join_path(
                        source_table=src_tbl,
                        target_table=tgt_tbl,
                        tenant_id=tenant_id,
                        knowledgebase_id=knowledgebase_id,
                        schema_version=schema_version,
                    )
                    if path:
                        approved_joins.extend(path)

        return SemanticResolutionResult(
            normalized_query=norm_q,
            ambiguity_report=ambiguity,
            resolved_metric=resolved_metric,
            resolved_entities=resolved_entities,
            applicable_rules=applicable_rules,
            approved_joins=approved_joins,
            context_fingerprint=ctx_fp,
            recalled_memory=recalled,
        )
