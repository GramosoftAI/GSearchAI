"""Phase 3 Step 3.5 ColumnRetriever

Ranks candidate columns and metrics within selected candidate tables using:
1. kb2_schema_docs Full-Text Search (FTS) & Vector Semantic Search hits.
2. QuestionFrame role & unit semantic match:
   - Duration/Unit match: (frame has numbers with units like hours/seconds/minutes -> unit='second'/'hour'/etc., or role='measure'/'duration')
   - Date/Time match: (frame has time_range/date -> role='timestamp'/'date', or type/unit has date/time)
   - Aggregation/Grouping match: (frame aggregation_cues like 'per customer', 'count', 'total' -> grouping dimensions, primary/foreign keys, or metric docs)
   - Literal/Entity candidates match: (candidate entity spans or tokens match column title/aliases)
3. Multipliers:
   - confirmed > draft
   - admin-locked
Outputs per candidate table:
- Top ranked columns (with score, role, unit, and reasons)
- Relevant metrics
- Filter/group candidates
"""

import uuid
import logging
from typing import Optional, List, Dict, Any, Set
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import EmbeddingGenerator
from ..repositories.schema_doc_repository import SchemaDocRepository
from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from .analyzer import QuestionFrame
from .table_retriever import TableCandidate

logger = logging.getLogger(__name__)

RRF_K = 60


class ColumnCandidate(BaseModel):
    table_name: str
    column_name: str
    full_key: str  # table.column
    score: float
    role: Optional[str] = None
    unit: Optional[str] = None
    is_filter_candidate: bool = False
    is_group_candidate: bool = False
    is_metric: bool = False
    reasons: List[str] = Field(default_factory=list)
    accepted_values: List[str] = Field(default_factory=list)


class TableColumnBundle(BaseModel):
    table_name: str
    table_score: float
    columns: List[ColumnCandidate] = Field(default_factory=list)
    metrics: List[ColumnCandidate] = Field(default_factory=list)
    filter_candidates: List[str] = Field(default_factory=list)
    group_candidates: List[str] = Field(default_factory=list)


class ColumnRetriever:
    """Retrieves and ranks columns and metrics within candidate tables."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str | uuid.UUID,
    ):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.schema_doc_repo = SchemaDocRepository(db=db, tenant_id=self.tenant_id)
        self.item_repo = KnowledgeItemRepository(db=db, tenant_id=self.tenant_id)

    async def retrieve_for_tables(
        self,
        db_knowledgebase_id: uuid.UUID,
        frame: QuestionFrame,
        candidate_tables: List[TableCandidate],
        top_k_columns_per_table: int = 5,
        query_embedding: Optional[List[float]] = None,
    ) -> List[TableColumnBundle]:
        """Rank columns and metrics within candidate tables."""
        if not candidate_tables:
            return []

        target_table_names = {t.table_name.lower(): t for t in candidate_tables}

        # 1. Full-text search on column and metric docs
        search_query = " ".join(frame.tokens) if frame.tokens else frame.normalized_question
        fts_hits: List[Dict[str, Any]] = []
        if search_query:
            try:
                fts_hits = await self.schema_doc_repo.search_fts(
                    db_knowledgebase_id=db_knowledgebase_id,
                    query=search_query,
                    doc_types=["column", "metric"],
                    limit=50,
                )
            except Exception as e:
                logger.warning(f"Column FTS search failed: {e}")

        # 2. Vector search on column and metric docs
        vector_hits: List[Dict[str, Any]] = []
        try:
            q_emb = query_embedding
            if q_emb is None:
                embed_gen = EmbeddingGenerator()
                q_emb = await embed_gen.generate_embedding(frame.normalized_text or frame.original_question, is_query=True)
            if q_emb:
                vector_hits = await self.schema_doc_repo.search_vector(
                    db_knowledgebase_id=db_knowledgebase_id,
                    embedding=q_emb,
                    doc_types=["column", "metric"],
                    limit=50,
                )
        except Exception as e:
            logger.warning(f"Column Vector search failed: {e}")

        # Fetch all column docs for candidate tables to ensure coverage even if not in top hits
        # We also inspect knowledge items for role, unit, and semantic details
        all_table_items = await self.item_repo.list_items(
            db_knowledgebase_id=db_knowledgebase_id,
            limit=500,
        )
        
        # Organize items by table
        table_columns_map: Dict[str, List[Dict[str, Any]]] = {t: [] for t in target_table_names}
        table_metrics_map: Dict[str, List[Dict[str, Any]]] = {t: [] for t in target_table_names}

        for item in all_table_items:
            payload = item.payload or {}
            item_key = item.item_key or ""
            status = item.status or "draft"
            admin_locked = bool(getattr(item, "is_locked_by_admin", False))

            if item.item_type == "column":
                parts = item_key.split(".")
                if len(parts) >= 2:
                    t_name = parts[-2].lower()
                    col_name = parts[-1]
                    if t_name in target_table_names:
                        table_columns_map[t_name].append({
                            "key": item_key,
                            "table": t_name,
                            "column": col_name,
                            "role": payload.get("role") or "dimension",
                            "unit": payload.get("unit"),
                            "status": status,
                            "admin_locked": admin_locked,
                            "description": payload.get("description", ""),
                            "meaning": payload.get("meaning", ""),
                            "aliases": payload.get("aliases") or [],
                            "accepted_values": payload.get("accepted_values") or payload.get("stats", {}).get("top_values") or [],
                        })
            elif item.item_type == "metric":
                depends_on = payload.get("depends_on_tables") or []
                for dep in depends_on:
                    dep_lower = dep.lower()
                    if dep_lower in target_table_names:
                        table_metrics_map[dep_lower].append({
                            "key": item_key,
                            "table": dep_lower,
                            "column": item_key,
                            "role": "metric",
                            "unit": payload.get("unit"),
                            "status": status,
                            "admin_locked": admin_locked,
                            "description": payload.get("description", ""),
                            "meaning": payload.get("meaning", ""),
                            "aliases": payload.get("aliases") or [],
                        })

        # Rank maps per table
        bundles: List[TableColumnBundle] = []

        # RRF tracking per table: item_key -> score, reasons, meta
        for cand_table in candidate_tables:
            t_name = cand_table.table_name.lower()
            t_score = cand_table.score
            col_list = table_columns_map.get(t_name, [])
            metric_list = table_metrics_map.get(t_name, [])

            col_scores: Dict[str, float] = {}
            col_reasons: Dict[str, List[str]] = {}
            col_meta: Dict[str, Dict[str, Any]] = {}

            for c in col_list:
                col_scores[c["key"]] = 0.0
                col_reasons[c["key"]] = []
                col_meta[c["key"]] = c

            for m in metric_list:
                col_scores[m["key"]] = 0.0
                col_reasons[m["key"]] = []
                col_meta[m["key"]] = m

            # 1. FTS RRF
            matching_fts = [
                h for h in fts_hits 
                if (h.get("item_key") in col_scores or 
                    any(h.get("item_key", "").lower().startswith(f"{t_name}.") for t in [t_name]))
            ]
            for rank, hit in enumerate(matching_fts):
                k = hit["item_key"]
                if k in col_scores:
                    col_scores[k] += 1.0 / (RRF_K + rank + 1)
                    col_reasons[k].append(f"fts_rank_{rank+1}")

            # 2. Vector RRF
            matching_vec = [
                h for h in vector_hits 
                if (h.get("item_key") in col_scores or 
                    any(h.get("item_key", "").lower().startswith(f"{t_name}.") for t in [t_name]))
            ]
            for rank, hit in enumerate(matching_vec):
                k = hit["item_key"]
                if k in col_scores:
                    col_scores[k] += 1.0 / (RRF_K + rank + 1)
                    col_reasons[k].append(f"vector_rank_{rank+1}")

            # 3. Role & Unit matching from QuestionFrame
            for k, meta in col_meta.items():
                col_name_lower = meta["column"].lower()
                role = (meta.get("role") or "").lower()
                unit = (meta.get("unit") or "").lower()
                aliases = [a.lower() for a in meta.get("aliases") or []]

                # Direct token match with column name or aliases
                token_match = any(t in col_name_lower or any(t in a for a in aliases) for t in frame.tokens)
                if token_match:
                    col_scores[k] += 0.05
                    col_reasons[k].append("name_token_match")

                # Frame has time range / date cues
                if frame.time_range:
                    if role in ("timestamp", "date") or "date" in col_name_lower or "created_at" in col_name_lower:
                        col_scores[k] += 0.08
                        col_reasons[k].append("time_range_match")

                # Frame has numbers with units (e.g., hours, seconds, duration)
                if frame.unit_values:
                    has_duration_unit = any(u.unit in ("hours", "seconds", "minutes") for u in frame.unit_values)
                    if has_duration_unit:
                        if "hour" in unit or "second" in unit or "duration" in role or "duration" in col_name_lower or "hours" in col_name_lower:
                            col_scores[k] += 0.08
                            col_reasons[k].append("duration_unit_match")

                # Frame comparison cues (kela / less than / more than) -> measure/numeric/duration boost
                if frame.comparison:
                    if role in ("measure", "duration") or unit in ("hour", "second", "usd", "inr"):
                        col_scores[k] += 0.04
                        col_reasons[k].append("comparison_target_match")

                # Frame aggregation cues (count, average, per, total)
                if frame.aggregation_cues:
                    for agg in frame.aggregation_cues:
                        agg_lower = agg.lower()
                        if agg_lower in ("group_by", "per"):
                            if "id" in col_name_lower or role in ("dimension", "entity_key"):
                                col_scores[k] += 0.04
                                col_reasons[k].append("group_by_dimension")
                        elif agg_lower in ("sum", "avg", "total", "max", "min", "count", "average", "highest"):
                            if role in ("measure", "metric") or "amount" in col_name_lower or "total" in col_name_lower:
                                col_scores[k] += 0.05
                                col_reasons[k].append("aggregation_measure")

                # Entity candidates match
                if frame.entity_candidates:
                    for ec in frame.entity_candidates:
                        if any(t in col_name_lower for t in ec.lower().split()):
                            col_scores[k] += 0.06
                            col_reasons[k].append("entity_span_match")

                # Apply multipliers: confirmed > draft, admin-locked
                mult = 1.0
                if meta.get("status") == "confirmed":
                    mult *= 1.2
                if meta.get("admin_locked"):
                    mult *= 1.5
                col_scores[k] *= mult

            # Separate into ranked columns and metrics
            ranked_cols: List[ColumnCandidate] = []
            ranked_metrics: List[ColumnCandidate] = []
            filter_cands: List[str] = []
            group_cands: List[str] = []

            for k, score in sorted(col_scores.items(), key=lambda x: x[1], reverse=True):
                meta = col_meta[k]
                is_metric = meta.get("role") == "metric"
                reasons = col_reasons.get(k, [])
                
                # Filter / Group candidate heuristics
                role = (meta.get("role") or "").lower()
                is_filter = any(r in reasons for r in ("time_range_match", "duration_unit_match", "comparison_target_match", "entity_span_match"))
                is_group = "group_by_dimension" in reasons or "id" in meta["column"].lower()

                cand = ColumnCandidate(
                    table_name=t_name,
                    column_name=meta["column"],
                    full_key=k,
                    score=round(score, 4),
                    role=meta.get("role"),
                    unit=meta.get("unit"),
                    is_filter_candidate=is_filter,
                    is_group_candidate=is_group,
                    is_metric=is_metric,
                    reasons=reasons,
                    accepted_values=meta.get("accepted_values") or [],
                )

                if is_metric:
                    ranked_metrics.append(cand)
                else:
                    ranked_cols.append(cand)

                if is_filter and meta["column"] not in filter_cands:
                    filter_cands.append(meta["column"])
                if is_group and meta["column"] not in group_cands:
                    group_cands.append(meta["column"])

            bundles.append(
                TableColumnBundle(
                    table_name=cand_table.table_name,
                    table_score=cand_table.score,
                    columns=ranked_cols[:top_k_columns_per_table],
                    metrics=ranked_metrics[:top_k_columns_per_table],
                    filter_candidates=filter_cands[:top_k_columns_per_table],
                    group_candidates=group_cands[:top_k_columns_per_table],
                )
            )

        return bundles
