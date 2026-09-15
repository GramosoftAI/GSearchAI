"""Schema Relationship Graph & Path Traversal

Provides deterministic, bounded graph traversal across relational database foreign keys.
Enables finding connecting join paths and bridge tables between disparate entities
(e.g., customers -> orders -> order_items -> products).
"""

import logging
from typing import Dict, List, Set, Tuple, Optional
from collections import deque

from ..schemas.canonical import DatabaseSchema, RelationshipSchema

logger = logging.getLogger(__name__)


class SchemaGraph:
    """
    In-memory graph representation of foreign key relationships across database tables.
    Uses bounded BFS / Dijkstra to find multi-hop join paths.
    """

    def __init__(self, relationships: List[RelationshipSchema]):
        self.relationships = relationships
        # Adjacency list: table -> list of (neighbor_table, relationship)
        self.adj: Dict[str, List[Tuple[str, RelationshipSchema]]] = {}
        self._build_graph()

    _GRAPH_CACHE: Dict[str, "SchemaGraph"] = {}

    @classmethod
    def from_database_schema(cls, schema: DatabaseSchema) -> "SchemaGraph":
        """Build SchemaGraph from canonical DatabaseSchema with fingerprint caching."""
        fp = schema.fingerprint
        if fp and fp in cls._GRAPH_CACHE:
            return cls._GRAPH_CACHE[fp]

        from ..schemas.canonical import RelationshipType
        all_rels: List[RelationshipSchema] = []
        seen_keys = set()
        for s_info in schema.schemas.values():
            for table in s_info.tables.values():
                for rel in table.relationships:
                    rel_key = f"{rel.source_schema}.{rel.source_table}->{rel.target_schema}.{rel.target_table}:{rel.foreign_key_name}"
                    if rel_key not in seen_keys:
                        seen_keys.add(rel_key)
                        all_rels.append(rel)
                for fk in table.foreign_keys:
                    rel_key = f"{table.schema_name}.{table.table_name}->{fk.referred_schema}.{fk.referred_table}:{fk.name}"
                    if rel_key not in seen_keys:
                        seen_keys.add(rel_key)
                        all_rels.append(
                            RelationshipSchema(
                                source_schema=table.schema_name,
                                source_table=table.table_name,
                                source_columns=fk.constrained_columns,
                                target_schema=fk.referred_schema,
                                target_table=fk.referred_table,
                                target_columns=fk.referred_columns,
                                foreign_key_name=fk.name,
                                relationship_type=RelationshipType.MANY_TO_ONE,
                            )
                        )
        instance = cls(all_rels)
        if fp:
            cls._GRAPH_CACHE[fp] = instance
        return instance

    def _normalize_table_key(self, schema_name: str, table_name: str) -> str:
        return f"{schema_name}.{table_name}" if schema_name else table_name

    def _build_graph(self):
        """Construct bidirectional adjacency list from foreign key relationships."""
        for rel in self.relationships:
            src = self._normalize_table_key(rel.source_schema, rel.source_table)
            tgt = self._normalize_table_key(rel.target_schema, rel.target_table)

            if src not in self.adj:
                self.adj[src] = []
            if tgt not in self.adj:
                self.adj[tgt] = []

            # Add forward link
            self.adj[src].append((tgt, rel))
            # Add reverse link
            self.adj[tgt].append((src, rel))

    def get_neighbors(self, table_key: str) -> List[Tuple[str, RelationshipSchema]]:
        """Get all directly connected adjacent tables."""
        return self.adj.get(table_key, [])

    def find_shortest_path(
        self,
        start_table: str,
        end_table: str,
        max_hops: int = 3,
        allowed_tables: Optional[Set[str]] = None,
        forbidden_hops: Optional[Set[Tuple[str, str]]] = None,
    ) -> Optional[List[str]]:
        """
        Find shortest path of tables between start_table and end_table using BFS.
        Returns list of table names along path (e.g. ['customers', 'orders', 'payments']),
        or None if no path within max_hops exists.
        """
        start = self._resolve_table_name(start_table)
        end = self._resolve_table_name(end_table)

        if not start or not end:
            return None
        if start == end:
            return [start]

        queue = deque([(start, [start])])
        visited = {start}

        ADMIN_TABLES = {"auth_user", "auth_group", "django_content_type", "base_company", "django_migrations", "django_session", "base_company_id"}
        start_clean = start.split(".")[-1].lower()
        end_clean = end.split(".")[-1].lower()
        allowed_clean = {t.split(".")[-1].lower() for t in allowed_tables} if allowed_tables else None

        while queue:
            current, path = queue.popleft()

            if len(path) - 1 >= max_hops:
                continue

            c_base = current.split(".")[-1].lower()

            def _neighbor_priority(item):
                n_name, _ = item
                if n_name == end:
                    return (-1, -1)
                n_base = n_name.split(".")[-1].lower()
                is_admin = 1 if (n_base in ADMIN_TABLES or any(a in n_base for a in ("auth_", "django_"))) else 0
                has_domain_tokens = 0 if any(tok in n_base for tok in (start_clean, end_clean)) else 1
                return (is_admin, has_domain_tokens)

            sorted_neighbors = sorted(self.adj.get(current, []), key=_neighbor_priority)
            for neighbor, _ in sorted_neighbors:
                n_base = neighbor.split(".")[-1].lower()

                # Guard against explicitly forbidden edge hops (e.g. bypassing asset assignment directly to employee owner)
                if forbidden_hops and ((c_base, n_base) in forbidden_hops or (n_base, c_base) in forbidden_hops):
                    continue

                if neighbor == end:
                    return path + [neighbor]

                # Never traverse admin, audit, historical, or backup tables as intermediate bridges
                if (
                    n_base in ADMIN_TABLES
                    or any(a in n_base for a in ("auth_", "django_", "historical", "backup", "_bak", "audit", "history_"))
                ):
                    continue

                # If allowed_tables is constrained, bridge tables must be in allowed_clean
                if allowed_clean is not None and n_base not in allowed_clean:
                    continue

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None

    def find_connecting_subgraph(
        self,
        seed_tables: Set[str],
        max_hops: int = 3,
    ) -> Tuple[Set[str], List[RelationshipSchema]]:
        """
        Given a set of seed tables (e.g. {'customers', 'products'}),
        computes the minimal connective set of bridge tables and relationships
        connecting all pairs of seed tables.

        Returns:
            Tuple of (all_tables_in_subgraph, active_relationships)
        """
        resolved_seeds = set()
        for t in seed_tables:
            r = self._resolve_table_name(t)
            if r:
                resolved_seeds.add(r)

        if not resolved_seeds:
            return set(), []

        if len(resolved_seeds) == 1:
            seed = next(iter(resolved_seeds))
            return {seed}, []

        all_tables: Set[str] = set(resolved_seeds)
        active_relationships: List[RelationshipSchema] = []
        seen_rel_keys = set()

        seed_list = sorted(list(resolved_seeds))
        for i in range(len(seed_list)):
            for j in range(i + 1, len(seed_list)):
                t1 = seed_list[i]
                t2 = seed_list[j]

                path = self.find_shortest_path(t1, t2, max_hops=max_hops)
                if path:
                    for tbl in path:
                        all_tables.add(tbl)

                    # Collect edges along this path
                    for step_idx in range(len(path) - 1):
                        u = path[step_idx]
                        v = path[step_idx + 1]
                        # Find relationship between u and v
                        for neighbor, rel in self.adj.get(u, []):
                            if neighbor == v:
                                rel_key = (
                                    f"{rel.source_schema}.{rel.source_table}:"
                                    f"{rel.target_schema}.{rel.target_table}:"
                                    f"{rel.foreign_key_name}"
                                )
                                if rel_key not in seen_rel_keys:
                                    seen_rel_keys.add(rel_key)
                                    active_relationships.append(rel)
                                break

        return all_tables, active_relationships

    def _resolve_table_name(self, table_name: str) -> Optional[str]:
        """Resolves table name whether provided with or without schema prefix."""
        if table_name in self.adj:
            return table_name

        # Search for matching base table name
        for full_name in self.adj:
            if full_name.endswith(f".{table_name}") or full_name == table_name:
                return full_name

        return None
