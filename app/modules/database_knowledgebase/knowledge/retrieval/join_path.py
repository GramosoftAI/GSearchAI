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

    def _ingest_declared_fks_from_canonical(self, schema_obj: Any) -> None:
        """Ingest declared FK relationships from canonical DatabaseSchema. Never invent relationships."""
        if not schema_obj:
            return
        tables = getattr(schema_obj, "all_tables", [])
        if not tables and hasattr(schema_obj, "schemas"):
            for s_info in schema_obj.schemas.values():
                tables.extend(s_info.tables.values())

        for table in tables:
            c_tbl = table.table_name.lower().split(".")[-1]
            fks = getattr(table, "foreign_keys", []) or []
            for fk in fks:
                p_tbl = fk.referred_table.lower().split(".")[-1]
                c_cols = fk.constrained_columns or []
                p_cols = fk.referred_columns or []
                if not c_tbl or not p_tbl or not c_cols or not p_cols:
                    continue
                c_col = c_cols[0]
                p_col = p_cols[0]

                # Avoid duplicate edges
                existing_fwd = self._graph.get(c_tbl, [])
                if not any(e.target_table == p_tbl and e.left_col == c_col and e.right_col == p_col for e in existing_fwd):
                    self._graph.setdefault(c_tbl, []).append(
                        EdgeInfo(
                            target_table=p_tbl,
                            left_col=c_col,
                            right_col=p_col,
                            cardinality="1:N",
                            confidence=1.0,
                            source="declared",
                            status="confirmed",
                            weight=1.0,
                        )
                    )

                existing_rev = self._graph.get(p_tbl, [])
                if not any(e.target_table == c_tbl and e.left_col == p_col and e.right_col == c_col for e in existing_rev):
                    self._graph.setdefault(p_tbl, []).append(
                        EdgeInfo(
                            target_table=c_tbl,
                            left_col=p_col,
                            right_col=c_col,
                            cardinality="1:N_fanout",
                            confidence=1.0,
                            source="declared",
                            status="confirmed",
                            weight=1.0,
                        )
                    )

    def _ingest_declared_fks_from_schema_dict(self, raw_data: Dict[str, Any]) -> None:
        """Ingest declared FK relationships from serialized schema dict."""
        try:
            from app.modules.database_knowledgebase.schemas.canonical import DatabaseSchema
            schema_obj = DatabaseSchema.model_validate(raw_data)
            self._ingest_declared_fks_from_canonical(schema_obj)
            return
        except Exception as e:
            logger.debug(f"[JoinPathFinder] Failed to validate DatabaseSchema from dict: {e}")

        # Fallback manual traversal
        schemas = raw_data.get("schemas", {})
        for s_val in schemas.values():
            if isinstance(s_val, dict) and "tables" in s_val:
                for t_name, t_val in s_val["tables"].items():
                    if not isinstance(t_val, dict):
                        continue
                    c_tbl = (t_val.get("table_name") or t_name).lower().split(".")[-1]
                    for fk in t_val.get("foreign_keys", []):
                        if not isinstance(fk, dict):
                            continue
                        p_tbl = (fk.get("referred_table") or "").lower().split(".")[-1]
                        c_cols = fk.get("constrained_columns") or []
                        p_cols = fk.get("referred_columns") or []
                        if not c_tbl or not p_tbl or not c_cols or not p_cols:
                            continue
                        c_col = c_cols[0]
                        p_col = p_cols[0]

                        existing_fwd = self._graph.get(c_tbl, [])
                        if not any(e.target_table == p_tbl and e.left_col == c_col and e.right_col == p_col for e in existing_fwd):
                            self._graph.setdefault(c_tbl, []).append(
                                EdgeInfo(
                                    target_table=p_tbl,
                                    left_col=c_col,
                                    right_col=p_col,
                                    cardinality="1:N",
                                    confidence=1.0,
                                    source="declared",
                                    status="confirmed",
                                    weight=1.0,
                                )
                            )
                        existing_rev = self._graph.get(p_tbl, [])
                        if not any(e.target_table == c_tbl and e.left_col == p_col and e.right_col == c_col for e in existing_rev):
                            self._graph.setdefault(p_tbl, []).append(
                                EdgeInfo(
                                    target_table=c_tbl,
                                    left_col=p_col,
                                    right_col=c_col,
                                    cardinality="1:N_fanout",
                                    confidence=1.0,
                                    source="declared",
                                    status="confirmed",
                                    weight=1.0,
                                )
                            )

    async def build_graph(
        self,
        db_knowledgebase_id: uuid.UUID,
        schema_version: Optional[str] = None,
        session: Optional[AsyncSession] = None,
        canonical_schema: Optional[Any] = None,
    ):
        """Construct weighted graph from relationship items or canonical schema declared FKs."""
        self._graph.clear()
        target_db = session or self.db

        items = []
        if target_db is not None:
            try:
                stmt = select(KB2KnowledgeItem).where(
                    KB2KnowledgeItem.tenant_id == self.tenant_id,
                    KB2KnowledgeItem.db_knowledgebase_id == db_knowledgebase_id,
                    KB2KnowledgeItem.item_type == "relationship",
                    KB2KnowledgeItem.status.in_(["confirmed", "draft"]),
                )
                res = await target_db.execute(stmt)
                if hasattr(res, "scalars"):
                    scalar_obj = res.scalars()
                    all_fn = getattr(scalar_obj, "all", None)
                    if callable(all_fn):
                        items = all_fn()
            except Exception as e:
                logger.debug(f"[JoinPathFinder] KB2 relationship query ignored: {e}")

        if not items:
            # Cold-start / Phase-2-off: use declared FKs from the canonical schema or
            # the tenant-scoped snapshot. Never invent joins from column-name heuristics.
            schema_obj = canonical_schema
            if schema_obj is None and target_db is not None:
                from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseSchemaSnapshot

                snap_stmt = (
                    select(DatabaseSchemaSnapshot.schema_data)
                    .where(
                        DatabaseSchemaSnapshot.tenant_id == self.tenant_id,
                        DatabaseSchemaSnapshot.db_knowledgebase_id == db_knowledgebase_id,
                    )
                    .order_by(DatabaseSchemaSnapshot.created_at.desc())
                    .limit(1)
                )
                snap_res = await target_db.execute(snap_stmt)
                raw_data = snap_res.scalar_one_or_none()
                if raw_data and isinstance(raw_data, dict):
                    self._ingest_declared_fks_from_schema_dict(raw_data)
            elif schema_obj is not None:
                self._ingest_declared_fks_from_canonical(schema_obj)

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
        self, start_table: str, end_table: str
    ) -> Optional[Tuple[float, List[Tuple[str, EdgeInfo]]]]:
        """Find lowest-weight path between two tables within max_hops."""
        start = start_table.lower()
        end = end_table.lower()

        if start == end:
            return (0.0, [])

        # Priority queue: (cost, hops, current_table, path_taken)
        pq: List[Tuple[float, int, str, List[Tuple[str, EdgeInfo]]]] = [(0.0, 0, start, [])]
        best_costs: Dict[str, float] = {start: 0.0}

        while pq:
            cost, hops, current, path = heapq.heappop(pq)

            if current == end:
                return (cost, path)

            if hops >= self.max_hops:
                continue

            for edge in self._graph.get(current, []):
                nxt = edge.target_table
                new_cost = cost + edge.weight
                if nxt not in best_costs or new_cost < best_costs[nxt]:
                    best_costs[nxt] = new_cost
                    new_path = path + [(current, edge)]
                    heapq.heappush(pq, (new_cost, hops + 1, nxt, new_path))

        return None

    def find_join_tree(
        self,
        tables: List[str],
        frame: Optional[QuestionFrame] = None,
    ) -> JoinPathResult:
        """Find minimum connecting tree for target tables (Steiner approximation)."""
        clean_tables = [t.lower().split(".")[-1] for t in tables]
        clean_tables = list(dict.fromkeys(clean_tables))  # preserve order & unique

        if not clean_tables:
            return JoinPathResult(success=True)

        if len(clean_tables) == 1:
            return JoinPathResult(success=True)

        # Check if all tables exist in graph
        for t in clean_tables:
            if t not in self._graph:
                return JoinPathResult(
                    success=False,
                    unreachable_tables=[t],
                )

        # 1. Pick anchor table: table with highest degree/connectivity or first target table
        anchor = max(clean_tables, key=lambda t: len(self._graph.get(t, [])))

        # 2. Shortest paths from anchor to all other tables
        visited_nodes: Set[str] = {anchor}
        all_hops: List[JoinHop] = []
        bridge_tables: Set[str] = set()
        fanout_warnings: List[str] = []
        total_cost = 0.0

        targets_to_connect = [t for t in clean_tables if t != anchor]
        has_aggregation = bool(frame and frame.aggregation_cues)

        for target in targets_to_connect:
            if target in visited_nodes:
                continue

            # Find shortest path from any currently visited node to target
            best_res = None
            best_weight = float("inf")
            for v_node in visited_nodes:
                res = self._dijkstra_shortest_path(v_node, target)
                if res and res[0] < best_weight:
                    best_weight = res[0]
                    best_res = res

            if not best_res:
                # Disconnected!
                return JoinPathResult(
                    success=False,
                    unreachable_tables=[target],
                )

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
            success=True,
            joins=all_hops,
            bridge_tables=list(bridge_tables),
            fanout_warnings=fanout_warnings,
            total_cost=round(total_cost, 3),
        )
