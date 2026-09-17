"""Semantic Model Builder

Master orchestrator that derives the full DatabaseKnowledgeProfile directly from
a discovered database catalog or canonical schema.
Performs classification, entity mapping, relationship discovery, metric formulation,
and temporal cataloging with zero domain hardcoding.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from ..discovery.database_discovery import DiscoveredCatalog
from ..discovery.postgres_discovery import PostgresDiscoveryService
from ..schemas.canonical import DatabaseSchema
from .column_semantics import ColumnSemanticResolver
from .database_knowledge_profile import (
    CertificationStatus,
    ColumnSemanticProfile,
    DatabaseKnowledgeProfile,
    DiscoveredEntity,
    DiscoveredMetric,
    DiscoveredRelationship,
    IdentityField,
    TableCategory,
    TableClassification,
    TemporalColumnProfile,
)
from .entity_registry import DynamicEntityRegistry
from .identity_registry import IdentityRegistry
from .metric_discovery import UniversalMetricDiscovery
from .relationship_registry import UniversalRelationshipRegistry
from .table_classifier import TableClassifier
from .temporal_registry import UniversalTemporalRegistry


class SemanticModelBuilder:
    """
    Automated semantic model builder for universal database understanding.
    """

    def __init__(self):
        self.entity_registry = DynamicEntityRegistry()
        self.relationship_registry = UniversalRelationshipRegistry()
        self.identity_registry = IdentityRegistry()
        self.temporal_registry = UniversalTemporalRegistry()

    def build_profile(
        self,
        catalog: DiscoveredCatalog,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        database_id: Optional[uuid.UUID] = None,
        database_name: str = "client_database",
        schema_fingerprint: str = "",
        semantic_version: int = 1,
    ) -> DatabaseKnowledgeProfile:
        """
        Builds a comprehensive DatabaseKnowledgeProfile from discovered catalog.
        """
        if not database_id:
            database_id = uuid.uuid4()

        # 1. Classify all tables
        table_classifications = TableClassifier.classify_catalog(catalog)

        # Separate system, security, and excluded tables
        system_tables: Set[str] = set()
        security_tables: Set[str] = set()
        excluded_tables: Set[str] = set()

        for key, tc in table_classifications.items():
            if tc.category == TableCategory.SYSTEM:
                system_tables.add(key)
                excluded_tables.add(key)
            elif tc.category == TableCategory.SECURITY:
                security_tables.add(key)
                excluded_tables.add(key)
            elif tc.category in (TableCategory.AUDIT, TableCategory.HISTORY, TableCategory.CONFIGURATION):
                excluded_tables.add(key)

        # 2. Classify all columns semantically
        column_profiles = ColumnSemanticResolver.resolve_all_columns(catalog)

        # 3. Build business entities
        discovered_entities = self.entity_registry.build_entities_from_profile(
            tables=table_classifications,
            columns=column_profiles,
        )

        # 4. Discover relationships (declared and inferred)
        discovered_relationships = self.relationship_registry.discover_relationships_from_catalog(
            catalog=catalog,
            table_classifications=table_classifications,
            entities=discovered_entities,
        )

        # 5. Build identity fields registry
        identity_fields = self.identity_registry.register_from_profile(
            entities=discovered_entities,
            columns=column_profiles,
        )

        # 6. Discover business metrics
        discovered_metrics = UniversalMetricDiscovery.discover_metrics(
            entities=discovered_entities,
            columns=column_profiles,
        )

        # 7. Register temporal fields
        temporal_fields = self.temporal_registry.register_from_columns(column_profiles)

        # 8. Compute confidence summary
        confidence_summary = {
            "table_classification_avg": (
                sum(t.confidence for t in table_classifications.values()) / max(1, len(table_classifications))
            ),
            "column_semantic_avg": (
                sum(c.confidence for c in column_profiles.values()) / max(1, len(column_profiles))
            ),
            "relationships_avg": (
                sum(r.confidence for r in discovered_relationships) / max(1, len(discovered_relationships))
            ),
            "total_entities": len(discovered_entities),
            "total_metrics": len(discovered_metrics),
        }

        profile = DatabaseKnowledgeProfile(
            database_id=database_id,
            tenant_id=tenant_id,
            knowledgebase_id=knowledgebase_id,
            database_name=database_name,
            schema_fingerprint=schema_fingerprint or "dynamic_fingerprint",
            semantic_version=semantic_version,
            certification_status=CertificationStatus.MODELING,
            tables=table_classifications,
            columns=column_profiles,
            entities=discovered_entities,
            relationships=discovered_relationships,
            identity_fields=identity_fields,
            metrics=discovered_metrics,
            temporal_fields=temporal_fields,
            system_tables=system_tables,
            security_tables=security_tables,
            excluded_tables=excluded_tables,
            confidence_summary=confidence_summary,
        )

        return profile

    def build_profile_from_canonical_schema(
        self,
        schema: DatabaseSchema,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        database_id: Optional[uuid.UUID] = None,
        database_name: str = "client_database",
        schema_fingerprint: str = "",
        semantic_version: int = 1,
    ) -> DatabaseKnowledgeProfile:
        """
        Adapter: builds profile directly from canonical DatabaseSchema.
        """
        catalog = PostgresDiscoveryService.from_canonical_schema(schema)
        fp = schema_fingerprint or getattr(schema, "fingerprint", None)
        if not fp:
            try:
                from ..schema.fingerprint import SchemaFingerprinter
                fp = SchemaFingerprinter.generate_fingerprint(schema)
            except Exception:
                fp = "default_fingerprint"

        return self.build_profile(
            catalog=catalog,
            tenant_id=tenant_id,
            knowledgebase_id=knowledgebase_id,
            database_id=database_id,
            database_name=database_name,
            schema_fingerprint=fp,
            semantic_version=semantic_version,
        )

    def sync_to_registries(
        self,
        profile: DatabaseKnowledgeProfile,
        semantic_model_registry: Any,
        relationship_graph: Any,
        metric_registry: Any,
    ) -> None:
        """
        Converts profile components into Phase 6 models and populates
        the legacy/in-memory registries for complete backward compatibility.
        """
        tenant_id = profile.tenant_id
        kb_id = profile.knowledgebase_id

        # 1. Sync Entities
        sem_entities = self.entity_registry.to_semantic_entities(
            tenant_id=tenant_id,
            knowledgebase_id=kb_id,
            columns=profile.columns,
            schema_version=profile.schema_fingerprint,
        )
        for ent in sem_entities:
            try:
                semantic_model_registry.register_entity(ent)
            except Exception:
                pass  # Entity already registered or exists

        # 2. Sync Relationships
        app_relationships = self.relationship_registry.to_approved_relationships(
            tenant_id=tenant_id,
            knowledgebase_id=kb_id,
            entities=profile.entities,
            schema_version=profile.schema_fingerprint,
        )
        for rel in app_relationships:
            try:
                relationship_graph.register_relationship(rel)
            except Exception:
                pass

        # 3. Sync Metrics
        metric_defns = UniversalMetricDiscovery.to_metric_definitions(
            discovered_metrics=profile.metrics,
            tenant_id=tenant_id,
            knowledgebase_id=kb_id,
            entities=profile.entities,
            schema_version=profile.schema_fingerprint,
        )
        for m in metric_defns:
            try:
                metric_registry.register_metric(m)
            except Exception:
                pass
