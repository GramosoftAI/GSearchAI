"""Relationship Graph and Join Path Finder

Loads relationships from kb2_knowledge_items (confirmed + draft above a configurable confidence)
and computes optimal join paths across tables using weighted BFS / Dijkstra:
- Confirmed edges are cheaper (default weight 1.0)
- Draft / inferred edges have higher weight (default weight 2.0)
- Supports multi-table join paths.
"""

import heapq
from typing import Dict, List, Optional, Tuple, Set, Any
from dataclasses import dataclass, field


@dataclass
class GraphEdge:
    source_table: str
    target_table: str
    child_cols: List[str]
    parent_cols: List[str]
    cardinality: str
    confidence: float
    status: str
    is_direct: bool  # True if FK goes from source -> target, False if reverse edge
    weight: float

    @property
    def join_condition(self) -> str:
        """SQL join condition fragment."""
        conds = []
        for c, p in zip(self.child_cols, self.parent_cols):
            if self.is_direct:
                conds.append(f"{self.source_table}.{c} = {self.target_table}.{p}")
            else:
                conds.append(f"{self.source_table}.{p} = {self.target_table}.{c}")
        return " AND ".join(conds)


class RelationshipGraph:
    """Graph structure of tables and relationship edges for join path discovery."""

    def __init__(self, confirmed_weight: float = 1.0, draft_weight: float = 2.0):
        self.confirmed_weight = confirmed_weight
        self.draft_weight = draft_weight
        # Adjacency list: table -> list of GraphEdge
        self.adj: Dict[str, List[GraphEdge]] = {}

    def add_relationship(
        self,
        child_table: str,
        child_cols: List[str],
        parent_table: str,
        parent_cols: List[str],
        cardinality: str = "1:N",
        confidence: float = 1.0,
        status: str = "confirmed",
    ) -> None:
        """Add a directed relationship and its bidirectional traversal edge."""
        c_tbl = child_table.lower()
        p_tbl = parent_table.lower()
        edge_weight = self.confirmed_weight if status == "confirmed" else self.draft_weight

        # Direct edge: child -> parent
        edge_direct = GraphEdge(
            source_table=c_tbl,
            target_table=p_tbl,
            child_cols=child_cols,
            parent_cols=parent_cols,
            cardinality=cardinality,
            confidence=confidence,
            status=status,
            is_direct=True,
            weight=edge_weight,
        )

        # Reverse edge: parent -> child
        edge_reverse = GraphEdge(
            source_table=p_tbl,
            target_table=c_tbl,
            child_cols=child_cols,
            parent_cols=parent_cols,
            cardinality=cardinality,
            confidence=confidence,
            status=status,
            is_direct=False,
            weight=edge_weight,
        )

        self.adj.setdefault(c_tbl, []).append(edge_direct)
        self.adj.setdefault(p_tbl, []).append(edge_reverse)

    @classmethod
    def from_knowledge_items(
        cls,
        items: List[Any],
        min_draft_confidence: float = 0.50,
        confirmed_weight: float = 1.0,
        draft_weight: float = 2.0,
    ) -> "RelationshipGraph":
        """Construct graph from KB2KnowledgeItem records (or items dicts)."""
        graph = cls(confirmed_weight=confirmed_weight, draft_weight=draft_weight)

        for it in items:
            status = getattr(it, "status", None) or (it.get("status") if isinstance(it, dict) else None)
            confidence = getattr(it, "confidence", 1.0) or (it.get("confidence", 1.0) if isinstance(it, dict) else 1.0)
            payload = getattr(it, "payload", {}) or (it.get("payload", {}) if isinstance(it, dict) else {})

            if status not in ("confirmed", "draft"):
                continue
            if status == "draft" and confidence < min_draft_confidence:
                continue

            child_table = payload.get("child_table")
            parent_table = payload.get("parent_table")
            child_cols = payload.get("child_columns", [])
            parent_cols = payload.get("parent_columns", [])
            cardinality = payload.get("cardinality", "1:N")

            if child_table and parent_table and child_cols and parent_cols:
                graph.add_relationship(
                    child_table=child_table,
                    child_cols=child_cols,
                    parent_table=parent_table,
                    parent_cols=parent_cols,
                    cardinality=cardinality,
                    confidence=confidence,
                    status=status,
                )

        return graph

    def find_path_between(self, start_table: str, end_table: str) -> Optional[List[GraphEdge]]:
        """Dijkstra / Weighted BFS shortest path between two tables."""
        start = start_table.lower()
        end = end_table.lower()

        if start == end:
            return []

        if start not in self.adj or end not in self.adj:
            return None

        # Priority queue entries: (cost, current_node, path)
        pq: List[Tuple[float, str, List[GraphEdge]]] = [(0.0, start, [])]
        min_costs: Dict[str, float] = {start: 0.0}

        while pq:
            cost, curr, path = heapq.heappop(pq)

            if curr == end:
                return path

            if cost > min_costs.get(curr, float("inf")):
                continue

            for edge in self.adj.get(curr, []):
                next_node = edge.target_table
                next_cost = cost + edge.weight

                if next_cost < min_costs.get(next_node, float("inf")):
                    min_costs[next_node] = next_cost
                    heapq.heappush(pq, (next_cost, next_node, path + [edge]))

        return None

    def find_join_path(self, tables: List[str]) -> Optional[List[GraphEdge]]:
        """Find a connected join path spanning all requested tables.
        
        For 2 tables: direct shortest path.
        For >2 tables: incrementally connects each table to the connected tree.
        """
        if not tables:
            return []
        if len(tables) == 1:
            return []

        norm_tables = [t.lower() for t in tables]

        # For 2 tables:
        if len(tables) == 2:
            return self.find_path_between(norm_tables[0], norm_tables[1])

        # For multi-table join: Steiner tree approximation / greedy connecting
        connected_tables: Set[str] = {norm_tables[0]}
        full_path: List[GraphEdge] = []
        unvisited = set(norm_tables[1:])

        while unvisited:
            best_path: Optional[List[GraphEdge]] = None
            best_cost = float("inf")
            target_to_remove = None

            for u in unvisited:
                for c in connected_tables:
                    path = self.find_path_between(c, u)
                    if path is not None:
                        path_cost = sum(e.weight for e in path)
                        if path_cost < best_cost:
                            best_cost = path_cost
                            best_path = path
                            target_to_remove = u

            if best_path is None or target_to_remove is None:
                # Disconnected components
                return None

            unvisited.remove(target_to_remove)
            for edge in best_path:
                if edge not in full_path:
                    full_path.append(edge)
                connected_tables.add(edge.source_table)
                connected_tables.add(edge.target_table)

        return full_path
