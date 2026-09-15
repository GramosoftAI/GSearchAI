"""Universal Relationship Registry

Extracts, discovers, and categorizes relational connections between tables
directly from database foreign key constraints and schema topology.
Differentiates authoritative DECLARED foreign keys from INFERRED relationships,
computes relational cardinalities, and prevents security/system tables
from becoming join bridges.
"""

from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from ..discovery.database_discovery import DiscoveredCatalog, DiscoveredForeignKey
from ..schemas.canonical import DatabaseSchema, ForeignKeySchema
from .database_knowledge_profile import (
    DiscoveredEntity,
    DiscoveredRelationship,
    TableCategory,
    TableClassification,
)
from .models import ApprovedRelationship, RelationshipCardinality


class UniversalRelationshipRegistry:
    """
    Discovers, validates, and manages approved relationships between tables.
    Supplies vetted paths to the SemanticRelationshipGraph and PlanValidator.
    """

    def __init__(self):
        self._relationships: List[DiscoveredRelationship] = []

    def discover_relationships_from_catalog(
        self,
        catalog: DiscoveredCatalog,
        table_classifications: Dict[str, TableClassification],
        entities: Dict[str, DiscoveredEntity],
    ) -> List[DiscoveredRelationship]:
        """
        Derives DiscoveredRelationship instances from catalog foreign keys.
        Filters out forbidden bridge tables (security, system, audit, history).
        """
        discovered: List[DiscoveredRelationship] = []
        seen_edges: Set[Tuple[str, str, str, str]] = set()

        # Build lookup for table classification
        def is_forbidden_table(s: str, t: str) -> bool:
            key = f"{s}.{t}".lower()
            if key in table_classifications:
                return table_classifications[key].category in (
                    TableCategory.SYSTEM,
                    TableCategory.SECURITY,
                    TableCategory.AUDIT,
                    TableCategory.HISTORY,
                    TableCategory.CONFIGURATION,
                )
            return False

        # 1. Authoritative declared foreign keys
        for fk in catalog.foreign_keys:
            src_s = fk.source_schema.lower()
            src_t = fk.source_table.lower()
            tgt_s = fk.target_schema.lower()
            tgt_t = fk.target_table.lower()

            # Skip system/security tables
            if is_forbidden_table(src_s, src_t) or is_forbidden_table(tgt_s, tgt_t):
                continue

            edge_key = (src_s, src_t, tgt_s, tgt_t)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            # Determine cardinality
            # If source column is marked unique or PK in source table, it's ONE_TO_ONE, else MANY_TO_ONE
            cardinality = "MANY_TO_ONE"
            src_tbl = catalog.tables.get(src_t) or catalog.tables.get(f"{src_s}.{src_t}")
            if src_tbl:
                for c in fk.source_columns:
                    if c in src_tbl.primary_key_columns or c in src_tbl.unique_columns:
                        cardinality = "ONE_TO_ONE"
                        break

            rel_id = f"rel_{src_t}_{tgt_t}_{'_'.join(fk.source_columns)}".lower()
            rel = DiscoveredRelationship(
                relationship_id=rel_id,
                source_schema=fk.source_schema,
                source_table=fk.source_table,
                source_columns=fk.source_columns,
                target_schema=fk.target_schema,
                target_table=fk.target_table,
                target_columns=fk.target_columns,
                is_declared_fk=True,
                cardinality=cardinality,
                confidence=1.0,
                evidence=[
                    f"Declared foreign key constraint {fk.constraint_name or 'FK'}",
                    f"Joins {fk.source_table}.({', '.join(fk.source_columns)}) -> {fk.target_table}.({', '.join(fk.target_columns)})",
                ],
            )
            discovered.append(rel)

        # 2. Inferred relationships (for unconstrained schemas with standard naming)
        # Only check if declared FKs did not already connect the pair
        for t_name, tbl in catalog.tables.items():
            src_s = tbl.schema_name.lower()
            src_t = tbl.table_name.lower()
            if is_forbidden_table(src_s, src_t):
                continue

            for col in tbl.columns.values():
                c_name = col.name.lower()
                if c_name.endswith("_id") and len(c_name) > 3:
                    candidate_target = c_name[:-3]
                    # Check if candidate_target exists as a table
                    target_tbl = catalog.get_table(candidate_target)
                    if not target_tbl:
                        target_tbl = catalog.get_table(candidate_target + "s")
                    if not target_tbl:
                        target_tbl = catalog.get_table(candidate_target + "es")

                    if target_tbl:
                        tgt_s = target_tbl.schema_name.lower()
                        tgt_t = target_tbl.table_name.lower()
                        if is_forbidden_table(tgt_s, tgt_t) or (src_s, src_t, tgt_s, tgt_t) in seen_edges:
                            continue

                        # Match target PK
                        tgt_pk = target_tbl.primary_key_columns
                        if tgt_pk and len(tgt_pk) == 1:
                            edge_key = (src_s, src_t, tgt_s, tgt_t)
                            seen_edges.add(edge_key)

                            rel_id = f"inferred_{src_t}_{tgt_t}_{c_name}".lower()
                            inferred_rel = DiscoveredRelationship(
                                relationship_id=rel_id,
                                source_schema=tbl.schema_name,
                                source_table=tbl.table_name,
                                source_columns=[col.name],
                                target_schema=target_tbl.schema_name,
                                target_table=target_tbl.table_name,
                                target_columns=tgt_pk,
                                is_declared_fk=False,
                                cardinality="MANY_TO_ONE",
                                confidence=0.80,
                                evidence=[
                                    f"Inferred by naming convention: {col.name} matches {target_tbl.table_name}.{tgt_pk[0]}",
                                ],
                            )
                            discovered.append(inferred_rel)

        self._relationships = discovered
        return discovered

    def to_approved_relationships(
        self,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        entities: Dict[str, DiscoveredEntity],
        schema_version: Optional[str] = None,
    ) -> List[ApprovedRelationship]:
        """
        Converts discovered relationships into Phase 6 ApprovedRelationship instances
        ready for registration in SemanticRelationshipGraph.
        """
        # Map physical table -> entity semantic name
        tbl_to_ent_name: Dict[str, str] = {}
        for ent in entities.values():
            tbl_to_ent_name[ent.physical_table.lower()] = ent.semantic_name
            tbl_to_ent_name[f"{ent.physical_schema}.{ent.physical_table}".lower()] = ent.semantic_name

        approved: List[ApprovedRelationship] = []

        cardinality_map = {
            "ONE_TO_ONE": RelationshipCardinality.ONE_TO_ONE,
            "ONE_TO_MANY": RelationshipCardinality.ONE_TO_MANY,
            "MANY_TO_ONE": RelationshipCardinality.MANY_TO_ONE,
            "MANY_TO_MANY": RelationshipCardinality.MANY_TO_MANY,
        }

        for rel in self._relationships:
            src_ent = tbl_to_ent_name.get(rel.source_table.lower(), rel.source_table)
            tgt_ent = tbl_to_ent_name.get(rel.target_table.lower(), rel.target_table)

            card_enum = cardinality_map.get(rel.cardinality, RelationshipCardinality.MANY_TO_ONE)

            app_rel = ApprovedRelationship(
                relationship_id=rel.relationship_id,
                source_entity=src_ent,
                target_entity=tgt_ent,
                source_table=rel.source_table,
                target_table=rel.target_table,
                source_columns=rel.source_columns,
                target_columns=rel.target_columns,
                cardinality=card_enum,
                business_description=f"{src_ent} related to {tgt_ent} via {', '.join(rel.source_columns)}",
                approved_for=["ANALYTICAL_JOIN", "ENTITY_EXPANSION"],
                confidence=rel.confidence,
                tenant_id=tenant_id,
                knowledgebase_id=knowledgebase_id,
                schema_version=schema_version,
            )
            approved.append(app_rel)

        return approved
