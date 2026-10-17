"""Phase 3 Step 3.7 JoinPathFinder

Builds a join graph per KB and schema_version from relationship items:
1. Dijkstra edge weights:
   - declared: 1.0
   - confirmed inferred: 1.5
   - draft inferred: 2.5
   - N:M cardinality penalty: 2.0 multiplier
2. Minimal connecting tree (Steiner approximation by shortest paths from an anchor table):
   - Connects 3+ tables through optimal bridge tables.
3. Output:
   - Ordered joins as list of dicts: {left_table, left_col, right_table, right_col, cardinality, confidence}
   - List of added bridge tables.
4. Fan-out warning:
   - Triggered when a 1:N hop goes from one-side to many-side while QuestionFrame has aggregation cues.
5. Disconnected tables:
   - Returns clear failure with unreachable tables; never invents a join.
   - Configurable max hops (default 4).
"""

import uuid
import heapq
import logging
from typing import Optional, List, Dict, Any, Set, Tuple
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models.knowledge_items import KB2KnowledgeItem
from .analyzer import QuestionFrame

logger = logging.getLogger(__name__)


class JoinHop(BaseModel):
    left_table: str
    left_col: str
    right_table: str
    right_col: str
    cardinality: str  # 1:1, 1:N, N:M
    confidence: float
    source: str       # declared, inferred
    status: str       # confirmed, draft
    is_fanout: bool = False


class JoinPathResult(BaseModel):
    success: bool
    joins: List[JoinHop] = Field(default_factory=list)
    bridge_tables: List[str] = Field(default_factory=list)
    fanout_warnings: List[str] = Field(default_factory=list)
    unreachable_tables: List[str] = Field(default_factory=list)
    total_cost: float = 0.0


class TraversedNeighbor(BaseModel):
    """Result of entity ID traversal along foreign key graph."""
    table_name: str
    anchor_table: str
    left_col: str
    right_col: str
    relevance_score: float
    matched_concept: str
    hops: int = 1


class EdgeInfo:
    def __init__(
        self,
        target_table: str,
        left_col: str,
        right_col: str,
        cardinality: str,
        confidence: float,
        source: str,
        status: str,
        weight: float,
    ):
        self.target_table = target_table
        self.left_col = left_col
        self.right_col = right_col
        self.cardinality = cardinality
        self.confidence = confidence
        self.source = source
        self.status = status
        self.weight = weight


class JoinPathFinder:
    """Computes optimal schema join trees and paths using Dijkstra and Steiner approximation."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str | uuid.UUID,
        max_hops: int = 4,
    ):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.max_hops = max_hops
        # graph: table_name -> list of EdgeInfo
        self._graph: Dict[str, List[EdgeInfo]] = {}

    async def build_graph(
        self,
        db_knowledgebase_id: uuid.UUID,
        schema_version: Optional[str] = None,
        session: Optional[AsyncSession] = None,
    ):
        """Construct weighted graph from relationship items."""
        self._graph.clear()
        target_db = session or self.db

        stmt = select(KB2KnowledgeItem).where(
            KB2KnowledgeItem.tenant_id == self.tenant_id,
            KB2KnowledgeItem.db_knowledgebase_id == db_knowledgebase_id,
            KB2KnowledgeItem.item_type == "relationship",
            KB2KnowledgeItem.status.in_(["confirmed", "draft"]),
        )
        res = await target_db.execute(stmt)
        items = res.scalars().all()

        for it in items:
            p = it.payload or {}
            c_tbl = (p.get("child_table") or "").lower().split(".")[-1]
            p_tbl = (p.get("parent_table") or "").lower().split(".")[-1]
            c_cols = p.get("child_columns") or []
            p_cols = p.get("parent_columns") or []
            card = p.get("cardinality") or "1:N"
            conf = float(p.get("confidence") or 1.0)
            src = it.source or "inferred"
            stat = it.status or "draft"

            if not c_tbl or not p_tbl or not c_cols or not p_cols:
                continue

            c_col = c_cols[0]
            p_col = p_cols[0]

            # Compute Dijkstra edge weight
            # declared: 1.0, confirmed inferred: 1.5, draft inferred: 2.5, N:M: 2.0x multiplier
            if src == "declared":
                base_w = 1.0
            elif stat == "confirmed":
                base_w = 1.5
            else:
                base_w = 2.5

            if card == "N:M":
                base_w *= 2.0

            # Forward edge (child -> parent, typically many-to-one)
            self._graph.setdefault(c_tbl, []).append(
                EdgeInfo(
                    target_table=p_tbl,
                    left_col=c_col,
                    right_col=p_col,
                    cardinality=card,
                    confidence=conf,
                    source=src,
                    status=stat,
                    weight=base_w,
                )
            )

            # Reverse edge (parent -> child, one-to-many: potential fanout)
            rev_card = "1:N_fanout" if card == "1:N" else card
            self._graph.setdefault(p_tbl, []).append(
                EdgeInfo(
                    target_table=c_tbl,
                    left_col=p_col,
                    right_col=c_col,
                    cardinality=rev_card,
                    confidence=conf,
                    source=src,
                    status=stat,
                    weight=base_w,
                )
            )

    def _dijkstra_shortest_path(
        self,
        start_table: str,
        end_table: str,
        query_text: Optional[str] = None,
    ) -> Optional[Tuple[float, List[Tuple[str, EdgeInfo]]]]:
        """Find lowest-weight path between two tables within max_hops, preferring query-aligned FK columns."""
        start = start_table.lower()
        end = end_table.lower()

        if start == end:
            return (0.0, [])

        # Priority queue: (cost, hops, current_table, path_taken)
        pq: List[Tuple[float, int, str, List[Tuple[str, EdgeInfo]]]] = [(0.0, 0, start, [])]
        best_costs: Dict[str, float] = {start: 0.0}

        q_low = query_text.lower() if query_text else ""

        while pq:
            cost, hops, current, path = heapq.heappop(pq)

            if current == end:
                return (cost, path)

            if hops >= self.max_hops:
                continue

            for edge in self._graph.get(current, []):
                nxt = edge.target_table
                edge_weight = edge.weight

                # Semantic FK intent discount when query_text is present:
                # E.g. "assigned" query prioritizes assigned_to_id over author_id
                if q_low:
                    col_str = f"{edge.left_col} {edge.right_col}".lower()
                    if "assign" in q_low and "assigned" in col_str:
                        edge_weight *= 0.5
                    elif "assign" in q_low and (nxt == "members" or current == "members"):
                        edge_weight *= 0.5
                    elif "assign" in q_low and any(w in col_str for w in ("creator", "author", "created_by")):
                        edge_weight *= 10.0
                    elif any(w in q_low for w in ("create", "created", "author", "opened", "reported")) and "author" in col_str:
                        edge_weight *= 0.5
                    elif any(w in q_low for w in ("manager", "managed", "lead")) and "manager" in col_str:
                        edge_weight *= 0.5

                new_cost = cost + edge_weight
                if nxt not in best_costs or new_cost < best_costs[nxt]:
                    best_costs[nxt] = new_cost
                    new_path = path + [(current, edge)]
                    heapq.heappush(pq, (new_cost, hops + 1, nxt, new_path))

        return None

    def find_join_tree(
        self,
        tables: List[str],
        frame: Optional[QuestionFrame] = None,
        query_text: Optional[str] = None,
    ) -> JoinPathResult:
        """Find minimum connecting tree for target tables (Steiner approximation)."""
        clean_tables = [t.lower().split(".")[-1] for t in tables]
        clean_tables = list(dict.fromkeys(clean_tables))  # preserve order & unique

        if not clean_tables:
            return JoinPathResult(success=True)

        if len(clean_tables) == 1:
            return JoinPathResult(success=True)

        # Separate tables present in graph vs disconnected/unindexed tables
        graph_tables = [t for t in clean_tables if t in self._graph]
        unreachable_nodes: List[str] = [t for t in clean_tables if t not in self._graph]

        if not graph_tables:
            return JoinPathResult(
                success=len(clean_tables) <= 1,
                unreachable_tables=unreachable_nodes,
            )

        if len(graph_tables) == 1:
            return JoinPathResult(
                success=True,
                unreachable_tables=unreachable_nodes,
            )

        # 1. Pick anchor table: table with highest degree/connectivity or first target table
        anchor = max(graph_tables, key=lambda t: len(self._graph.get(t, [])))

        # 2. Shortest paths from anchor to all other tables
        visited_nodes: Set[str] = {anchor}
        all_hops: List[JoinHop] = []
        bridge_tables: Set[str] = set()
        fanout_warnings: List[str] = []
        total_cost = 0.0

        targets_to_connect = [t for t in graph_tables if t != anchor]
        has_aggregation = bool(frame and frame.aggregation_cues)
        q_text = query_text or (frame.original_question if frame else None)

        for target in targets_to_connect:
            if target in visited_nodes:
                continue

            # Find shortest path from any currently visited node to target
            best_res = None
            best_weight = float("inf")
            for v_node in visited_nodes:
                res = self._dijkstra_shortest_path(v_node, target, query_text=q_text)
                if res and res[0] < best_weight:
                    best_weight = res[0]
                    best_res = res

            if not best_res:
                unreachable_nodes.append(target)
                continue

            path_cost, edges = best_res
            total_cost += path_cost

            for curr, edge in edges:
                nxt = edge.target_table
                is_fanout = "fanout" in edge.cardinality
                
                # Check for fanout warning
                if is_fanout and has_aggregation:
                    fanout_warnings.append(
                        f"Fan-out hop from '{curr}' (1) to '{nxt}' (N) with query aggregation cues ({', '.join(frame.aggregation_cues)}). Risk of inflated counts/sums."
                    )

                # Add bridge table if intermediate node is not in original target tables
                if curr not in clean_tables:
                    bridge_tables.add(curr)
                if nxt not in clean_tables:
                    bridge_tables.add(nxt)

                # Dedup identical joins
                already_joined = any(
                    (j.left_table == curr and j.right_table == nxt) or
                    (j.left_table == nxt and j.right_table == curr)
                    for j in all_hops
                )
                if not already_joined:
                    all_hops.append(
                        JoinHop(
                            left_table=curr,
                            left_col=edge.left_col,
                            right_table=nxt,
                            right_col=edge.right_col,
                            cardinality="1:N" if is_fanout else edge.cardinality,
                            confidence=edge.confidence,
                            source=edge.source,
                            status=edge.status,
                            is_fanout=is_fanout,
                        )
                    )

                visited_nodes.add(nxt)

        return JoinPathResult(
            success=bool(all_hops or len(clean_tables) <= 1),
            joins=all_hops,
            bridge_tables=list(bridge_tables),
            fanout_warnings=fanout_warnings,
            unreachable_tables=unreachable_nodes,
            total_cost=round(total_cost, 3),
        )

    def traverse_entity_neighborhood(
        self,
        anchor_tables: List[str],
        query_text: str,
        max_hops: int = 2,
    ) -> List[TraversedNeighbor]:
        """
        Traverse graph from entity anchor tables (e.g. 'users') and score connected
        neighbor tables based on query keywords, table synonyms, and FK column semantics.
        Enables Graph/ID Traversal Search to directly locate the target table and join path.
        """
        if not anchor_tables or not query_text:
            return []

        import re
        q_lower = query_text.lower()
        q_tokens = set(re.findall(r"\b[a-zA-Z0-9_]+\b", q_lower))

        DOMAIN_SYNONYMS: Dict[str, Set[str]] = {
            "work_packages": {"task", "tasks", "ticket", "tickets", "issue", "issues", "bug", "bugs", "work_package", "work_packages", "item", "items", "work", "package", "packages", "todo", "assign", "assigned", "assignee", "assignment"},
            "time_entries": {"time", "timesheet", "timesheets", "hour", "hours", "spent", "logged", "log", "duration", "work", "entry", "entries"},
            "projects": {"project", "projects", "program", "programs"},
            "versions": {"version", "versions", "sprint", "sprints", "milestone", "milestones", "release", "releases"},
            "meetings": {"meeting", "meetings", "call", "calls", "agenda", "discussion"},
            "meeting_participants": {"meeting", "meetings", "participant", "participants", "attendee", "attendees"},
            "messages": {"message", "messages", "post", "posts", "comment", "comments", "forum", "chat"},
            "documents": {"document", "documents", "doc", "docs", "file", "files"},
            "attachments": {"attachment", "attachments", "file", "files"},
            "budgets": {"budget", "budgets", "cost", "costs", "expense", "expenses"},
            "cost_entries": {"cost", "costs", "expense", "expenses", "rate", "rates", "billing"},
            "members": {"member", "members", "membership", "memberships", "assign", "assigned", "assignment", "assignments", "project_member"},
            "roles": {"role", "roles", "permission", "permissions"},
            "statuses": {"status", "state", "phases", "phase"},
            "users": {"user", "users", "employee", "employees", "person", "staff", "member"},
        }

        results: Dict[str, TraversedNeighbor] = {}

        for anchor in anchor_tables:
            anchor_clean = anchor.lower().split(".")[-1]
            if anchor_clean not in self._graph:
                continue

            # 1-hop traversal
            for edge in self._graph.get(anchor_clean, []):
                target = edge.target_table
                if target in anchor_tables or target == anchor_clean:
                    continue
                if target.endswith(("_storages", "_queries", "_modules", "_hierarchies", "_settings", "_attachments")):
                    continue

                # Check relevance of target table to user query
                target_parts = set(re.split(r"[_\W]+", target))
                synonyms = DOMAIN_SYNONYMS.get(target, set()) | target_parts
                
                # Check column relevance (e.g. "assigned" matching assigned_to_id)
                col_tokens = (
                    (set(re.split(r"[_\W]+", edge.left_col.lower())) | set(re.split(r"[_\W]+", edge.right_col.lower())))
                    - {"id", "pk", "fk", "to", "by", "on"}
                )
                
                col_match = bool(col_tokens & q_tokens)
                table_match = bool(synonyms & q_tokens)

                matched_tokens = list((synonyms | col_tokens) & q_tokens)
                concept_str = ", ".join(matched_tokens) if matched_tokens else target

                if table_match or col_match:
                    score = 1.0
                    if table_match:
                        score += 1.5
                    if col_match:
                        score += 1.0

                    # Specific verb/FK alignment bonuses
                    col_str = f"{edge.left_col} {edge.right_col}".lower()
                    if "assign" in q_lower and "assigned" in col_str:
                        score += 1.0
                    elif any(w in q_lower for w in ("create", "created", "author", "opened", "reported")) and "author" in col_str:
                        score += 1.0

                    if target not in results or score > results[target].relevance_score:
                        results[target] = TraversedNeighbor(
                            table_name=target,
                            anchor_table=anchor_clean,
                            left_col=edge.left_col,
                            right_col=edge.right_col,
                            relevance_score=score,
                            matched_concept=concept_str,
                            hops=1,
                        )

            # 2-hop traversal if max_hops >= 2
            if max_hops >= 2:
                for edge1 in self._graph.get(anchor_clean, []):
                    hop1_table = edge1.target_table
                    if hop1_table in anchor_tables or hop1_table == anchor_clean:
                        continue
                    for edge2 in self._graph.get(hop1_table, []):
                        target2 = edge2.target_table
                        if target2 in anchor_tables or target2 == anchor_clean or target2 == hop1_table:
                            continue
                        if target2.endswith(("_storages", "_queries", "_modules", "_hierarchies", "_settings", "_attachments")):
                            continue
                        if target2 in results and results[target2].hops == 1:
                            continue

                        target_parts = set(re.split(r"[_\W]+", target2))
                        synonyms = DOMAIN_SYNONYMS.get(target2, set()) | target_parts
                        table_match = bool(synonyms & q_tokens)
                        if table_match:
                            matched_tokens = list(synonyms & q_tokens)
                            concept_str = ", ".join(matched_tokens)
                            score = 1.2
                            if target2 not in results or score > results[target2].relevance_score:
                                results[target2] = TraversedNeighbor(
                                    table_name=target2,
                                    anchor_table=anchor_clean,
                                    left_col=edge2.left_col,
                                    right_col=edge2.right_col,
                                    relevance_score=score,
                                    matched_concept=concept_str,
                                    hops=2,
                                )

        sorted_results = sorted(results.values(), key=lambda x: x.relevance_score, reverse=True)
        return sorted_results
