"""Phase 3 Step 3.8 ContextPackBuilder

Assembles the complete grounded context pack for downstream NL-to-SQL generation.
Pipeline:
QuestionAnalyzer -> TableRetriever -> ColumnRetriever -> LiveEntityResolver -> JoinPathFinder

Output ContextPack JSON:
{
  "question": str,
  "tables": [{"name": str, "description": str, "row_grain": Optional[str]}],
  "columns": [{"table": str, "name": str, "meaning": str, "unit": Optional[str], "role": str, "aliases": List[str]}],
  "joins": [{"left_table": str, "left_col": str, "right_table": str, "right_col": str, "cardinality": str, "confidence": float}],
  "entities": [{"span": str, "status": "resolved"|"ambiguous"|"none", "table": str, "column": str, "value": str, "pk": Any, "choices": List[Dict]}],
  "literal_filters": [...],
  "time_range": Optional[Dict],
  "comparisons": [...],
  "metrics": [{"name": str, "expression": str, "unit": Optional[str]}],
  "rules": [...],
  "similar_queries": [up to 3 verified natural_query + compiled_sql from kb2_query_memory],
  "confidence": float (0-1),
  "clarifications": List[str],
  "unanswerable": {"flag": bool, "reason": Optional[str]},
  "trimmed_items": List[str],
  "tokens_used": int,
  "timings_ms": Dict[str, float]
}

Guards:
- Never includes sensitive/PII columns or top_values.
- Token budget (default 3000 tokens, estimated chars/4): drops lowest-ranked columns first, then similar queries, then rules; NEVER drops joins or resolved entities.
- If entities are ambiguous or confidence < threshold, fills clarifications with user-friendly choices.
"""

import uuid
import time
import json
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional, List, Dict, Any, Tuple
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.core.embeddings import EmbeddingGenerator
from ..adapters.phase1_adapter import Phase1Adapter
from ..models.knowledge_items import KB2QueryMemory, KB2KnowledgeItem
from ..sensitivity import is_sensitive_column, is_sensitive_for_values
from .analyzer import QuestionAnalyzer, QuestionFrame
from .table_retriever import TableRetriever, TableCandidate
from .column_retriever import ColumnRetriever, ColumnCandidate, TableColumnBundle
from .entity_resolver import LiveEntityResolver, EntityResolutionResult, ResolvedEntity
from .join_path import JoinPathFinder, JoinPathResult, JoinHop
from .cache import knowledge_cache

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_BUDGET = 3000
CONFIDENCE_THRESHOLD = 0.65


class ContextPack(BaseModel):
    question: str
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    columns: List[Dict[str, Any]] = Field(default_factory=list)
    joins: List[Dict[str, Any]] = Field(default_factory=list)
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    literal_filters: List[Dict[str, Any]] = Field(default_factory=list)
    time_range: Optional[Dict[str, Any]] = None
    comparisons: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: List[Dict[str, Any]] = Field(default_factory=list)
    rules: List[Dict[str, Any]] = Field(default_factory=list)
    similar_queries: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = 1.0
    clarifications: List[str] = Field(default_factory=list)
    unanswerable: Dict[str, Any] = Field(default_factory=lambda: {"flag": False, "reason": None})
    trimmed_items: List[str] = Field(default_factory=list)
    tokens_used: int = 0
    timings_ms: Dict[str, float] = Field(default_factory=dict)
    top1_score: float = 0.0
    margin: float = 0.0
    top3_signals: List[Dict[str, Any]] = Field(default_factory=list)


class ContextPackBuilder:
    """Orchestrates Phase 3 retrieval stages into a grounded ContextPack."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str | uuid.UUID,
        adapter: Optional[Phase1Adapter] = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        session_factory: Optional[Any] = AsyncSessionLocal,
    ):
        self.db = db
        self.session_factory = session_factory
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.adapter = adapter or Phase1Adapter(session=db)
        self.token_budget = token_budget

        self.analyzer = QuestionAnalyzer()
        self.table_retriever = TableRetriever(db=db, tenant_id=self.tenant_id)
        self.column_retriever = ColumnRetriever(db=db, tenant_id=self.tenant_id)
        self.entity_resolver = LiveEntityResolver(db=db, tenant_id=self.tenant_id, adapter=self.adapter)
        self.join_finder = JoinPathFinder(db=db, tenant_id=self.tenant_id)

    def _inject_and_prune_candidates(
        self,
        candidate_tables: List[TableCandidate],
        entity_res: EntityResolutionResult,
    ) -> List[TableCandidate]:
        """Inject entity-matched tables and prune unconnected candidate noise."""
        from app.core.config import settings

        existing_names = {c.table_name.lower() for c in candidate_tables}
        top_score = candidate_tables[0].score if candidate_tables else 0.065

        # 1. Entity-Matched Tables handling (PART C.1)
        # Remove the 0.95 x top score boost for entity-matched tables.
        # Entity-matched tables are exempt from pruning but keep their natural score.
        entity_matched_tables: Set[str] = set()
        for re_ent in entity_res.resolved_entities:
            tbl = re_ent.table_name.lower().split(".")[-1]
            if not tbl:
                continue
            entity_matched_tables.add(tbl)
            if tbl not in existing_names:
                # Add with natural baseline score
                natural_val_score = round(1.0 / (RRF_K + 10) * 1.3, 4)
                candidate_tables.append(
                    TableCandidate(
                        table_name=tbl,
                        score=natural_val_score,
                        reasons=[f"Entity value match '{re_ent.matched_value}' in {re_ent.table_name}.{re_ent.column_name}"],
                        signals={"value_index": 1.3},
                    )
                )
                existing_names.add(tbl)
            else:
                for c in candidate_tables:
                    if c.table_name.lower() == tbl:
                        c.signals["value_index"] = 1.3
                        if not any(f"'{re_ent.matched_value}'" in r for r in c.reasons):
                            c.reasons.append(f"Entity match '{re_ent.matched_value}' in {re_ent.table_name}.{re_ent.column_name}")

        candidate_tables.sort(key=lambda x: x.score, reverse=True)
        before_list = [c.table_name for c in candidate_tables]

        if not candidate_tables:
            return []

        # 2. Candidate Pruning (PART C.2)
        # Keep the top N tables by score (config, default 4), plus all entity-matched tables,
        # plus bridge tables needed to connect them (max 2 hops via relationship graph).
        # Never go below 3 tables when an entity table is present.
        top_n = getattr(settings, "candidate_pruning_top_n", 4)
        max_hops = getattr(settings, "candidate_pruning_max_hops", 2)

        # Step 2a: Keep top N tables by score
        kept_candidates = list(candidate_tables[:top_n])
        kept_tables_set = {c.table_name.lower() for c in kept_candidates}

        # Step 2b: Plus all entity-matched tables (exempt from pruning)
        for c in candidate_tables:
            if c.table_name.lower() in entity_matched_tables and c.table_name.lower() not in kept_tables_set:
                kept_tables_set.add(c.table_name.lower())
                kept_candidates.append(c)

        # Step 2c: Never go below 3 tables when an entity table is present
        has_entity_table = bool(entity_matched_tables & kept_tables_set)
        if has_entity_table and len(kept_tables_set) < 3:
            for c in candidate_tables:
                if c.table_name.lower() not in kept_tables_set:
                    kept_tables_set.add(c.table_name.lower())
                    kept_candidates.append(c)
                    if len(kept_tables_set) >= 3:
                        break

        # Step 2d: Plus bridge tables needed to connect them (max 2 hops via relationship graph)
        top_table = candidate_tables[0].table_name.lower()
        bridge_tables_to_add: Set[str] = set()

        for t in list(kept_tables_set):
            if t != top_table:
                shortest = self.join_finder._dijkstra_shortest_path(top_table, t)
                if shortest is not None:
                    cost, edges = shortest
                    hops = len(edges)
                    if hops <= max_hops:
                        for curr, edge in edges:
                            if curr != top_table and curr != t:
                                bridge_tables_to_add.add(curr)
                            if edge.target_table != top_table and edge.target_table != t:
                                bridge_tables_to_add.add(edge.target_table)

        all_kept_names = kept_tables_set | bridge_tables_to_add
        pruned_candidates = [c for c in candidate_tables if c.table_name.lower() in all_kept_names]

        # If any bridge table was not already in candidate_tables, instantiate it
        existing_pruned_names = {c.table_name.lower() for c in pruned_candidates}
        min_existing_score = min([c.score for c in pruned_candidates]) if pruned_candidates else 0.010
        for bt in bridge_tables_to_add:
            if bt not in existing_pruned_names:
                pruned_candidates.append(
                    TableCandidate(
                        table_name=bt,
                        score=round(min_existing_score * 0.9, 4),
                        reasons=[f"Bridge table connecting kept tables to {top_table}"],
                        signals={"bridge": 1.0},
                    )
                )

        pruned_candidates.sort(key=lambda x: x.score, reverse=True)
        after_list = [c.table_name for c in pruned_candidates]

        logger.info(
            f"[CandidatePruning] Before pruning ({len(before_list)}): {before_list} -> "
            f"After pruning ({len(after_list)}): {after_list}"
        )
        return pruned_candidates

    @asynccontextmanager
    async def _get_branch_session(self):
        """Yield a dedicated session if session_factory is configured, else fallback to self.db."""
        if self.session_factory:
            async with self.session_factory() as sess:
                yield sess
        else:
            yield self.db

    async def build(
        self,
        db_knowledgebase_id: uuid.UUID,
        question: str,
        reference_date: Optional[date] = None,
        clarification_answers: Optional[Dict[str, Any]] = None,
    ) -> ContextPack:
        """Run complete retrieval pipeline and produce token-bounded ContextPack."""
        timings: Dict[str, float] = {}

        # 1. Question Analyzer (Instant in-memory parsing)
        t0 = time.perf_counter()
        frame = self.analyzer.analyze(question, reference_date=reference_date)
        timings["analyzer_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        if not self.session_factory:
            # Sequential execution fallback for environments without a session pool (e.g. SQLite / single-session mocks)
            t1 = time.perf_counter()
            entity_res: EntityResolutionResult = await self.entity_resolver.resolve(
                db_knowledgebase_id=db_knowledgebase_id,
                frame=frame,
            )
            timings["entity_resolution_ms"] = round((time.perf_counter() - t1) * 1000, 2)

            if entity_res.unanswerable:
                return ContextPack(
                    question=question,
                    confidence=0.0,
                    unanswerable={"flag": True, "reason": entity_res.unanswerable_reason},
                    timings_ms=timings,
                )

            t_emb_start = time.perf_counter()
            query_embedding: Optional[List[float]] = None
            try:
                query_embedding = await EmbeddingGenerator.generate_embedding(
                    question,
                    is_query=True,
                )
            except Exception as e:
                logger.warning(f"[ContextPackBuilder] Failed to generate query embedding: {e}")
            timings["embedding_ms"] = round((time.perf_counter() - t_emb_start) * 1000, 2)

            t2 = time.perf_counter()
            raw_c_tables: List[TableCandidate] = await self.table_retriever.retrieve_tables(
                db_knowledgebase_id=db_knowledgebase_id,
                frame=frame,
                top_k=8,
                query_embedding=query_embedding,
            )
            timings["table_retrieval_ms"] = round((time.perf_counter() - t2) * 1000, 2)
            if hasattr(raw_c_tables, "stage_timings"):
                timings["table_fts_ms"] = raw_c_tables.stage_timings.get("table_fts_ms", 0.0)
                timings["table_vector_ms"] = raw_c_tables.stage_timings.get("table_vector_ms", 0.0)

            orig_top1_score = raw_c_tables.top1_score if hasattr(raw_c_tables, "top1_score") else (raw_c_tables[0].score if raw_c_tables else 0.0)
            orig_margin = raw_c_tables.margin if hasattr(raw_c_tables, "margin") else 0.0
            orig_top3_signals = raw_c_tables.top3_signals if hasattr(raw_c_tables, "top3_signals") else []

            await self.join_finder.build_graph(db_knowledgebase_id=db_knowledgebase_id)

            candidate_tables = self._inject_and_prune_candidates(
                candidate_tables=list(raw_c_tables),
                entity_res=entity_res,
            )

            t3 = time.perf_counter()
            column_bundles: List[TableColumnBundle] = await self.column_retriever.retrieve_for_tables(
                db_knowledgebase_id=db_knowledgebase_id,
                frame=frame,
                candidate_tables=candidate_tables,
                top_k_columns_per_table=5,
                query_embedding=query_embedding,
            )
            timings["column_retrieval_ms"] = round((time.perf_counter() - t3) * 1000, 2)

            t4 = time.perf_counter()
            join_target_tables = [c.table_name for c in candidate_tables]
            join_res: JoinPathResult = self.join_finder.find_join_tree(
                tables=join_target_tables,
                frame=frame,
            )
            timings["join_path_ms"] = round((time.perf_counter() - t4) * 1000, 2)

            t5 = time.perf_counter()
            similar_queries = await self._fetch_similar_queries(
                db_knowledgebase_id=db_knowledgebase_id,
                question=question,
                target_tables=join_target_tables,
                query_embedding=query_embedding,
            )
            timings["query_memory_ms"] = round((time.perf_counter() - t5) * 1000, 2)

            t_rules_start = time.perf_counter()
            rules = await self._fetch_rules(db_knowledgebase_id=db_knowledgebase_id)
            timings["rules_ms"] = round((time.perf_counter() - t_rules_start) * 1000, 2)
            schema_view = None
            try:
                schema_view = await self.adapter.get_current_schema(self.tenant_id, db_knowledgebase_id)
            except Exception:
                pass

        else:
            # Concurrent execution:
            async def _run_table_retrieval():
                t_emb_start = time.perf_counter()
                query_embedding: Optional[List[float]] = None
                try:
                    query_embedding = await EmbeddingGenerator.generate_embedding(
                        question,
                        is_query=True,
                    )
                except Exception as e:
                    logger.warning(f"[ContextPackBuilder] Failed to generate query embedding: {e}")
                timings["embedding_ms"] = round((time.perf_counter() - t_emb_start) * 1000, 2)

                t2 = time.perf_counter()
                c_tables = await self.table_retriever.retrieve_tables(
                    db_knowledgebase_id=db_knowledgebase_id,
                    frame=frame,
                    top_k=8,
                    query_embedding=query_embedding,
                )
                timings["table_retrieval_ms"] = round((time.perf_counter() - t2) * 1000, 2)
                if hasattr(c_tables, "stage_timings"):
                    timings["table_fts_ms"] = c_tables.stage_timings.get("table_fts_ms", 0.0)
                    timings["table_vector_ms"] = c_tables.stage_timings.get("table_vector_ms", 0.0)
                return c_tables, query_embedding

            async def _run_entity_resolution():
                t1 = time.perf_counter()
                try:
                    async with self._get_branch_session() as sess:
                        res = await self.entity_resolver.resolve(
                            db_knowledgebase_id=db_knowledgebase_id,
                            frame=frame,
                            session=sess,
                        )
                        timings["entity_resolution_ms"] = round((time.perf_counter() - t1) * 1000, 2)
                        return res
                except Exception as e:
                    logger.error(f"[ContextPackBuilder] Entity resolution error: {e}")
                    timings["entity_resolution_ms"] = round((time.perf_counter() - t1) * 1000, 2)
                    return EntityResolutionResult()

            async def _run_join_graph():
                try:
                    async with self._get_branch_session() as sess:
                        await self.join_finder.build_graph(
                            db_knowledgebase_id=db_knowledgebase_id,
                            session=sess,
                        )
                except Exception as e:
                    logger.warning(f"[ContextPackBuilder] Join graph build error: {e}")

            async def _run_rules():
                t_r = time.perf_counter()
                try:
                    async with self._get_branch_session() as sess:
                        r = await self._fetch_rules(
                            db_knowledgebase_id=db_knowledgebase_id,
                            session=sess,
                        )
                        timings["rules_ms"] = round((time.perf_counter() - t_r) * 1000, 2)
                        return r
                except Exception as e:
                    logger.warning(f"[ContextPackBuilder] Rules fetch error: {e}")
                    timings["rules_ms"] = round((time.perf_counter() - t_r) * 1000, 2)
                    return []

            async def _run_schema():
                try:
                    async with self._get_branch_session() as sess:
                        adapter = Phase1Adapter(session=sess)
                        return await adapter.get_current_schema(self.tenant_id, db_knowledgebase_id)
                except Exception:
                    return None

            (
                (raw_candidate_tables, query_embedding),
                entity_res,
                _,
                rules,
                schema_view,
            ) = await asyncio.gather(
                _run_table_retrieval(),
                _run_entity_resolution(),
                _run_join_graph(),
                _run_rules(),
                _run_schema(),
            )

            if entity_res.unanswerable:
                return ContextPack(
                    question=question,
                    confidence=0.0,
                    unanswerable={"flag": True, "reason": entity_res.unanswerable_reason},
                    timings_ms=timings,
                )

            orig_top1_score = raw_candidate_tables.top1_score if hasattr(raw_candidate_tables, "top1_score") else (raw_candidate_tables[0].score if raw_candidate_tables else 0.0)
            orig_margin = raw_candidate_tables.margin if hasattr(raw_candidate_tables, "margin") else 0.0
            orig_top3_signals = raw_candidate_tables.top3_signals if hasattr(raw_candidate_tables, "top3_signals") else []

            # 2. Inject entity-matched tables + Candidate Pruning
            candidate_tables = self._inject_and_prune_candidates(
                candidate_tables=list(raw_candidate_tables),
                entity_res=entity_res,
            )

            # 3. Retrieve columns for pruned candidates & Similar queries
            async def _run_columns():
                t3 = time.perf_counter()
                c_bundles = await self.column_retriever.retrieve_for_tables(
                    db_knowledgebase_id=db_knowledgebase_id,
                    frame=frame,
                    candidate_tables=candidate_tables,
                    top_k_columns_per_table=5,
                    query_embedding=query_embedding,
                )
                timings["column_retrieval_ms"] = round((time.perf_counter() - t3) * 1000, 2)
                return c_bundles

            async def _run_similar():
                t5 = time.perf_counter()
                sim_res = []
                try:
                    async with self._get_branch_session() as sess:
                        sim_res = await self._fetch_similar_queries(
                            db_knowledgebase_id=db_knowledgebase_id,
                            question=question,
                            target_tables=[c.table_name for c in candidate_tables],
                            query_embedding=query_embedding,
                            session=sess,
                        )
                except Exception as e:
                    logger.warning(f"[ContextPackBuilder] Similar queries fetch error: {e}")
                timings["query_memory_ms"] = round((time.perf_counter() - t5) * 1000, 2)
                return sim_res

            column_bundles, similar_queries = await asyncio.gather(
                _run_columns(),
                _run_similar(),
            )

            # 4. In-memory join tree computation for pruned tables
            t4 = time.perf_counter()
            join_target_tables = [c.table_name for c in candidate_tables]
            join_res = self.join_finder.find_join_tree(
                tables=join_target_tables,
                frame=frame,
            )
            timings["join_path_ms"] = round((time.perf_counter() - t4) * 1000, 2)

        # 8. Assemble Initial Context
        tables_meta = []

        for t_cand in candidate_tables:
            desc = f"Table {t_cand.table_name}"
            row_grain = None
            if schema_view and t_cand.table_name in schema_view.tables:
                t_view = schema_view.tables[t_cand.table_name]
                if t_view.comment:
                    desc = t_view.comment
            tables_meta.append({
                "name": t_cand.table_name,
                "description": desc,
                "row_grain": row_grain,
                "score": t_cand.score,
            })

        # Columns and Metrics (Strictly non-sensitive, no top_values)
        all_cols_meta = []
        metrics_meta = []
        for bundle in column_bundles:
            for col in bundle.columns:
                if is_sensitive_column(col.column_name) or is_sensitive_for_values(col.column_name):
                    continue
                all_cols_meta.append({
                    "table": col.table_name,
                    "name": col.column_name,
                    "meaning": f"{col.table_name}.{col.column_name}",
                    "unit": col.unit,
                    "role": col.role or "dimension",
                    "aliases": [],
                    "score": col.score,
                })
            for m in bundle.metrics:
                metrics_meta.append({
                    "name": m.column_name,
                    "expression": m.full_key,
                    "unit": m.unit,
                })

        # Joins
        joins_meta = []
        if join_res.success:
            for j in join_res.joins:
                joins_meta.append({
                    "left_table": j.left_table,
                    "left_col": j.left_col,
                    "right_table": j.right_table,
                    "right_col": j.right_col,
                    "cardinality": j.cardinality,
                    "confidence": j.confidence,
                })

        # Entities formatting
        entities_meta = []
        clarifications = []

        # Deduplicate / group entity matches by (table, column, matched_value) and limit to 3 candidates
        unique_entities = []
        seen_entity_keys = set()
        for re_ent in entity_res.resolved_entities:
            clean_tbl = re_ent.table_name.split(".")[-1].lower()
            k = (clean_tbl, re_ent.column_name.lower(), re_ent.matched_value.lower())
            if k not in seen_entity_keys:
                seen_entity_keys.add(k)
                unique_entities.append(re_ent)

        for re_ent in unique_entities[:3]:
            pk_val = re_ent.pk_value
            is_ambig = re_ent.ambiguous
            choices_data = [{"pk": c.pk_value, "label": c.display_label} for c in re_ent.choices]

            if clarification_answers and re_ent.matched_value in clarification_answers:
                chosen_pk = clarification_answers[re_ent.matched_value]
                pk_val = chosen_pk
                is_ambig = False

            if is_ambig:
                choices_str = ", ".join(f"'{c.display_label}' (ID {c.pk_value})" for c in re_ent.choices[:4])
                clarifications.append(
                    f"Multiple matches found for '{re_ent.matched_value}'. Did you mean: {choices_str}?"
                )

            entities_meta.append({
                "span": re_ent.matched_value,
                "status": "ambiguous" if is_ambig else "resolved",
                "table": re_ent.table_name.split(".")[-1],
                "column": re_ent.column_name,
                "value": re_ent.matched_value,
                "matched_value": re_ent.matched_value,
                "pk": pk_val,
                "choices": choices_data,
            })

        # Literal filters
        literals_meta = [
            {"literal_value": lf.literal_value, "type": lf.literal_type, "candidate_columns": lf.candidate_columns}
            for lf in entity_res.literal_filters
        ]

        # Time range & Comparisons
        time_meta = None
        if frame.time_range:
            time_meta = {
                "start_date": frame.time_range.start_date,
                "end_date": frame.time_range.end_date,
                "expression": frame.time_range.expression,
            }

        comps_meta = []
        if frame.comparison:
            comps_meta.append({
                "operator": frame.comparison.operator,
                "cue": frame.comparison.raw_cue,
                "target_value": frame.comparison.target_value,
                "target_unit": frame.comparison.target_unit,
            })

        # Calculate Confidence Score (0.0 to 1.0)
        # Based on table score margins and entity ambiguity
        confidence = 0.85
        if not candidate_tables:
            confidence = 0.2
        elif candidate_tables[0].score < 0.05:
            confidence = 0.4
        elif len(candidate_tables) >= 2:
            # margin check
            margin = candidate_tables[0].score - candidate_tables[1].score
            confidence = min(0.95, max(0.5, 0.7 + margin * 2.0))

        if any(e["status"] == "ambiguous" for e in entities_meta):
            confidence = min(confidence, 0.60)
        if not join_res.success and len(join_target_tables) > 1:
            confidence = min(confidence, 0.45)

        if confidence < CONFIDENCE_THRESHOLD and not clarifications:
            clarifications.append("The question seems ambiguous with low schema match confidence. Please clarify your specific table or entity.")

        # 9. Token Budget Trimming
        # Estimated token count ~ total characters in serialized pack // 4
        # Drops lowest-ranked columns first, then similar queries, then rules.
        # NEVER drops joins or resolved entities.
        trimmed_items = []

        def _estimate_tokens(cols, sq, rls) -> int:
            pack_sample = {
                "tables": tables_meta,
                "columns": cols,
                "joins": joins_meta,
                "entities": entities_meta,
                "similar_queries": sq,
                "rules": rls,
            }
            return len(json.dumps(pack_sample)) // 4

        current_tokens = _estimate_tokens(all_cols_meta, similar_queries, rules)
        # Sort columns ascending by score so we drop lowest score first
        ranked_cols = sorted(all_cols_meta, key=lambda x: x.get("score", 0.0))

        while current_tokens > self.token_budget and len(ranked_cols) > len(candidate_tables):
            # Drop lowest-ranked column
            dropped = ranked_cols.pop(0)
            trimmed_items.append(f"column:{dropped['table']}.{dropped['name']}")
            current_tokens = _estimate_tokens(ranked_cols, similar_queries, rules)

        while current_tokens > self.token_budget and similar_queries:
            dropped_sq = similar_queries.pop()
            trimmed_items.append(f"query:{dropped_sq['question']}")
            current_tokens = _estimate_tokens(ranked_cols, similar_queries, rules)

        while current_tokens > self.token_budget and rules:
            dropped_rule = rules.pop()
            trimmed_items.append(f"rule:{dropped_rule.get('name', 'rule')}")
            current_tokens = _estimate_tokens(ranked_cols, similar_queries, rules)

        # Final columns preserved in original priority order
        final_cols = sorted(ranked_cols, key=lambda x: x.get("score", 0.0), reverse=True)

        return ContextPack(
            question=question,
            tables=tables_meta,
            columns=final_cols,
            joins=joins_meta,
            entities=entities_meta,
            literal_filters=literals_meta,
            time_range=time_meta,
            comparisons=comps_meta,
            metrics=metrics_meta,
            rules=rules,
            similar_queries=similar_queries,
            confidence=round(confidence, 2),
            clarifications=clarifications,
            unanswerable={"flag": False, "reason": None},
            trimmed_items=trimmed_items,
            tokens_used=current_tokens,
            timings_ms=timings,
            top1_score=orig_top1_score,
            margin=orig_margin,
            top3_signals=orig_top3_signals,
        )

    async def _fetch_similar_queries(
        self,
        db_knowledgebase_id: uuid.UUID,
        question: str,
        target_tables: Optional[List[str]] = None,
        query_embedding: Optional[List[float]] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch up to 3 verified natural queries by vector similarity and table overlap."""
        results = []
        target_db = session or self.db
        try:
            q_emb = query_embedding
            if q_emb is None:
                embed_gen = EmbeddingGenerator()
                q_emb = await embed_gen.generate_embedding(question, is_query=True)
            if not q_emb:
                return []

            dist_expr = KB2QueryMemory.embedding.cosine_distance(q_emb).label("dist")
            stmt = (
                select(KB2QueryMemory, dist_expr)
                .where(
                    KB2QueryMemory.tenant_id == self.tenant_id,
                    KB2QueryMemory.db_knowledgebase_id == db_knowledgebase_id,
                    KB2QueryMemory.status == "verified",
                    KB2QueryMemory.embedding.isnot(None),
                )
                .order_by(dist_expr)
                .limit(3)
            )
            res = await target_db.execute(stmt)
            for qm, dist in res.all():
                results.append({
                    "question": qm.natural_query,
                    "compiled_sql": qm.compiled_sql,
                    "similarity": round(1.0 - float(dist), 3) if dist is not None else 0.0,
                })
        except Exception as e:
            logger.warning(f"Failed to fetch similar queries: {e}")

        return results

    async def _fetch_rules(
        self,
        db_knowledgebase_id: uuid.UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch active business rules from kb2_knowledge_items."""
        rules = []
        target_db = session or self.db
        try:
            stmt = select(KB2KnowledgeItem).where(
                KB2KnowledgeItem.tenant_id == self.tenant_id,
                KB2KnowledgeItem.db_knowledgebase_id == db_knowledgebase_id,
                KB2KnowledgeItem.item_type == "rule",
                KB2KnowledgeItem.status.in_(["confirmed", "draft"]),
            ).limit(5)
            res = await target_db.execute(stmt)
            for it in res.scalars().all():
                p = it.payload or {}
                rules.append({
                    "name": it.item_key,
                    "description": p.get("description", ""),
                    "rule_expression": p.get("rule_expression", ""),
                })
        except Exception as e:
            logger.warning(f"Failed to fetch rules: {e}")
        return rules

