"""Schema Graph Expander: Discovers Bridge Tables & Join Paths

Given seed candidate tables from vector/keyword search, traverses foreign key topology
to locate bridge tables and active join relationships connecting disparate entities.
"""

from typing import Dict, List, Set, Tuple
from ..schemas.canonical import DatabaseSchema, RelationshipSchema
from ..schema.graph import SchemaGraph


class GraphExpansionResult:
    """Outcome of graph expansion."""

    def __init__(
        self,
        expanded_tables: Set[str],
        bridge_tables: Set[str],
        active_relationships: List[RelationshipSchema],
        graph_boosts: Dict[str, float],
    ):
        self.expanded_tables = expanded_tables
        self.bridge_tables = bridge_tables
        self.active_relationships = active_relationships
        self.graph_boosts = graph_boosts


class SchemaGraphExpander:
    """
    Traverses FK relationships to expand seed tables and identify join topologies.
    """

    @classmethod
    def expand_seeds(
        cls,
        seed_tables: Set[str],
        schema: DatabaseSchema,
        max_hops: int = 3,
        bridge_table_boost: float = 0.85,
    ) -> GraphExpansionResult:
        """
        Find all bridge tables and join paths connecting seed_tables.

        Returns:
            GraphExpansionResult
        """
        if not seed_tables:
            return GraphExpansionResult(set(), set(), [], {})

        graph = SchemaGraph.from_database_schema(schema)
        all_tables, active_relationships = graph.find_connecting_subgraph(
            seed_tables=seed_tables,
            max_hops=max_hops,
        )

        bridge_tables = all_tables - seed_tables
        graph_boosts: Dict[str, float] = {}

        for b_tbl in bridge_tables:
            graph_boosts[b_tbl] = bridge_table_boost

        return GraphExpansionResult(
            expanded_tables=all_tables,
            bridge_tables=bridge_tables,
            active_relationships=active_relationships,
            graph_boosts=graph_boosts,
        )
