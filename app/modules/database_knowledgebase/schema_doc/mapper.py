"""Relationship Topology Mapper

Builds an explicit map of relationships across all tables:
- PKs, declared FKs, self-references, and standalone tables
- Infers relationships from naming conventions (e.g. employee_id -> employees.id)
  when declared FKs are absent
- Explicitly marks standalone tables with "no relationships"
- Performs topological sort (parents before children) for ordered processing
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque
from pydantic import BaseModel, Field

from ..schemas.canonical import DatabaseSchema, TableSchema


class TableRelationshipMap(BaseModel):
    """Relationship mapping for a single table."""
    table_name: str
    schema_name: str = "public"
    is_standalone: bool = False
    outgoing_fks: List[Dict[str, Any]] = Field(default_factory=list)
    incoming_fks: List[Dict[str, Any]] = Field(default_factory=list)
    inferred_relationships: List[Dict[str, Any]] = Field(default_factory=list)
    self_references: List[Dict[str, Any]] = Field(default_factory=list)
    parent_tables: List[str] = Field(default_factory=list)
    child_tables: List[str] = Field(default_factory=list)
    relationship_summary: str = "no relationships"


class SchemaTopology(BaseModel):
    """Overall schema relationship graph and topological processing order."""
    tables: Dict[str, TableRelationshipMap]
    processing_order: List[str]  # Parents before children
    standalone_tables: List[str]


class RelationshipMapper:
    """Computes schema topology, declared & inferred relationships, and processing order."""

    @classmethod
    def build_topology(cls, schema: DatabaseSchema) -> SchemaTopology:
        """
        Analyze schema relationships:
        1. Declared FKs
        2. Inferred FK candidates from naming conventions (e.g. employee_id -> employees.id)
        3. Self references
        4. Standalone tables (no incoming or outgoing relationships)
        5. Topological sort (parents before children)
        """
        table_map: Dict[str, TableSchema] = {t.table_name: t for t in schema.all_tables}
        topology_map: Dict[str, TableRelationshipMap] = {}

        # Initialize topology map
        for t_name, tbl in table_map.items():
            topology_map[t_name] = TableRelationshipMap(
                table_name=t_name,
                schema_name=tbl.schema_name,
                outgoing_fks=[],
                incoming_fks=[],
                inferred_relationships=[],
                self_references=[],
                parent_tables=[],
                child_tables=[],
            )

        # 1. Map Declared FKs
        for t_name, tbl in table_map.items():
            for fk in tbl.foreign_keys:
                target_table = fk.referred_table
                is_self = (target_table == t_name)

                fk_entry = {
                    "constraint_name": fk.name or "fk",
                    "source_table": t_name,
                    "source_columns": fk.constrained_columns,
                    "target_table": target_table,
                    "target_columns": fk.referred_columns,
                    "type": "declared",
                    "is_self_reference": is_self,
                }

                if is_self:
                    topology_map[t_name].self_references.append(fk_entry)
                else:
                    topology_map[t_name].outgoing_fks.append(fk_entry)
                    if target_table not in topology_map[t_name].parent_tables:
                        topology_map[t_name].parent_tables.append(target_table)

                    if target_table in topology_map:
                        topology_map[target_table].incoming_fks.append(fk_entry)
                        if t_name not in topology_map[target_table].child_tables:
                            topology_map[target_table].child_tables.append(t_name)

        # 2. Infer candidate relationships if declared FKs are absent
        # Pattern: <target_singular>_id -> <target_table>.id
        for t_name, tbl in table_map.items():
            existing_targets = set(topology_map[t_name].parent_tables)
            for col_name, col in tbl.columns.items():
                c_lower = col_name.lower()
                if c_lower.endswith("_id") and len(c_lower) > 3 and not col.is_primary_key:
                    candidate = c_lower[:-3]
                    # Candidate target table names
                    candidates_to_try = [
                        candidate,
                        candidate + "s",
                        candidate + "es",
                    ]
                    # Special cases (e.g. employee -> employees, company -> companies)
                    if candidate.endswith("y"):
                        candidates_to_try.append(candidate[:-1] + "ies")

                    matched_target = None
                    for cand in candidates_to_try:
                        if cand in table_map and cand != t_name and cand not in existing_targets:
                            # Verify target has 'id' or PK
                            tgt_tbl = table_map[cand]
                            tgt_pks = tgt_tbl.primary_key_columns
                            if "id" in tgt_tbl.columns or ("id" in tgt_pks if tgt_pks else False):
                                matched_target = cand
                                break

                    if matched_target:
                        inferred_entry = {
                            "source_table": t_name,
                            "source_columns": [col_name],
                            "target_table": matched_target,
                            "target_columns": ["id"],
                            "type": "inferred",
                            "label": "inferred",
                            "is_self_reference": False,
                        }
                        topology_map[t_name].inferred_relationships.append(inferred_entry)
                        if matched_target not in topology_map[t_name].parent_tables:
                            topology_map[t_name].parent_tables.append(matched_target)
                        if matched_target in topology_map and t_name not in topology_map[matched_target].child_tables:
                            topology_map[matched_target].child_tables.append(t_name)

        # 3. Mark standalone tables
        standalone_tables = []
        for t_name, rel_map in topology_map.items():
            has_any_rel = bool(
                rel_map.outgoing_fks
                or rel_map.incoming_fks
                or rel_map.inferred_relationships
                or rel_map.self_references
            )
            if not has_any_rel:
                rel_map.is_standalone = True
                rel_map.relationship_summary = "no relationships"
                standalone_tables.append(t_name)
            else:
                rel_map.is_standalone = False
                summary_parts = []
                if rel_map.outgoing_fks:
                    summary_parts.append(f"references {', '.join([f['target_table'] for f in rel_map.outgoing_fks])}")
                if rel_map.inferred_relationships:
                    summary_parts.append(f"inferred references to {', '.join([f['target_table'] for f in rel_map.inferred_relationships])}")
                if rel_map.incoming_fks:
                    summary_parts.append(f"referenced by {', '.join([f['source_table'] for f in rel_map.incoming_fks])}")
                if rel_map.self_references:
                    summary_parts.append("self-referential")
                rel_map.relationship_summary = "; ".join(summary_parts)

        # 4. Topological Sort (Parents before children)
        # In-degree for DAG: number of parents each table has
        in_degree = {t: len(topology_map[t].parent_tables) for t in table_map}
        queue = deque([t for t, deg in in_degree.items() if deg == 0])
        ordered_tables = []

        while queue:
            node = queue.popleft()
            ordered_tables.append(node)
            for child in topology_map[node].child_tables:
                if child in in_degree:
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        queue.append(child)

        # If cycles exist, append any remaining tables
        for t in table_map:
            if t not in ordered_tables:
                ordered_tables.append(t)

        return SchemaTopology(
            tables=topology_map,
            processing_order=ordered_tables,
            standalone_tables=standalone_tables,
        )
