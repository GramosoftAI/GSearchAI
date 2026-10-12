"""Value Resolver for NL-to-SQL Grounding

Resolves user text (entity names, categories, codes) to actual database values
using multi-strategy matching:
1. Exact match (case/space-normalized) -> score 1.0
2. Fuzzy similarity (pg_trgm % operator with similarity score)
3. Full-text search (tsvector with ts_rank)
4. Semantic vector search (cosine similarity via pgvector)

Ranks candidates and sets `ambiguous=True` when top candidates have closely matching scores.
"""

import uuid
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from app.core.embeddings import EmbeddingGenerator
from ..repositories.entity_value_repository import EntityValueRepository
from ..jobs.value_indexer import normalize_value

logger = logging.getLogger(__name__)


@dataclass
class ResolvedCandidate:
    table_name: str
    column_name: str
    raw_value: str
    normalized_value: str
    score: float
    match_type: str  # 'exact', 'fuzzy', 'fts', 'semantic'
    frequency_count: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValueResolutionResult:
    query_text: str
    candidates: List[ResolvedCandidate]
    ambiguous: bool = False
    best_match: Optional[ResolvedCandidate] = None
    matching_columns: List[str] = field(default_factory=list)
    match_count: int = 1


class ValueResolver:
    """Multi-strategy database entity value resolver."""

    def __init__(self, entity_repo: EntityValueRepository):
        self.entity_repo = entity_repo

    async def resolve(
        self,
        tenant_id: uuid.UUID,
        db_knowledgebase_id: uuid.UUID,
        text: str,
        table_filter: Optional[str] = None,
        column_filter: Optional[str] = None,
        limit: int = 5,
        min_score: float = 0.3,
        ambiguity_threshold: float = 0.05,
    ) -> ValueResolutionResult:
        """Resolve query text against indexed entity values across strategies."""
        norm_text = normalize_value(text)
        if not norm_text:
            return ValueResolutionResult(query_text=text, candidates=[], ambiguous=False)

        candidates_map: Dict[str, ResolvedCandidate] = {}

        # ----------------------------------------------------------------------
        # 1. Exact Match
        # ----------------------------------------------------------------------
        if table_filter and column_filter:
            exact_hit = await self.entity_repo.search_exact(
                db_knowledgebase_id=db_knowledgebase_id,
                table_name=table_filter,
                column_name=column_filter,
                value=norm_text,
            )
            if exact_hit:
                cand = ResolvedCandidate(
                    table_name=exact_hit.table_name,
                    column_name=exact_hit.column_name,
                    raw_value=exact_hit.raw_value,
                    normalized_value=exact_hit.normalized_value,
                    score=1.0,
                    match_type="exact",
                    frequency_count=exact_hit.frequency_count,
                )
                candidates_map[f"{cand.table_name}.{cand.column_name}.{cand.normalized_value}"] = cand

        # ----------------------------------------------------------------------
        # 2. Fuzzy Match (pg_trgm) - query text and tokens
        # ----------------------------------------------------------------------
        search_terms = [norm_text]
        for token in norm_text.split():
            if len(token) >= 3 and token not in search_terms:
                search_terms.append(token)

        for term in search_terms:
            try:
                fuzzy_hits = await self.entity_repo.search_fuzzy(
                    db_knowledgebase_id=db_knowledgebase_id,
                    query_text=term,
                    table_name=table_filter,
                    column_name=column_filter,
                    limit=limit * 2,
                    min_similarity=min_score,
                )
                for f_hit in fuzzy_hits:
                    key = f"{f_hit['table_name']}.{f_hit['column_name']}.{f_hit['normalized_value']}"
                    sim = round(float(f_hit["similarity"]), 4)
                    if f_hit["normalized_value"] == term:
                        sim = 1.0
                        mtype = "exact"
                    else:
                        mtype = "fuzzy"

                    if key not in candidates_map or sim > candidates_map[key].score:
                        candidates_map[key] = ResolvedCandidate(
                            table_name=f_hit["table_name"],
                            column_name=f_hit["column_name"],
                            raw_value=f_hit["raw_value"],
                            normalized_value=f_hit["normalized_value"],
                            score=sim,
                            match_type=mtype,
                            frequency_count=f_hit["frequency_count"],
                        )
            except Exception as fz_exc:
                logger.debug(f"[ValueResolver] Fuzzy search error: {fz_exc}")

        # ----------------------------------------------------------------------
        # 3. FTS Match (PostgreSQL tsvector)
        # ----------------------------------------------------------------------
        try:
            fts_hits = await self.entity_repo.search_fts(
                db_knowledgebase_id=db_knowledgebase_id,
                query_text=norm_text,
                table_name=table_filter,
                column_name=column_filter,
                limit=limit,
            )
            for hit in fts_hits:
                key = f"{hit.table_name}.{hit.column_name}.{hit.normalized_value}"
                score = 0.85 if hit.normalized_value == norm_text else 0.70
                if key not in candidates_map or score > candidates_map[key].score:
                    candidates_map[key] = ResolvedCandidate(
                        table_name=hit.table_name,
                        column_name=hit.column_name,
                        raw_value=hit.raw_value,
                        normalized_value=hit.normalized_value,
                        score=score,
                        match_type="fts",
                        frequency_count=hit.frequency_count,
                    )
        except Exception as fts_exc:
            logger.debug(f"[ValueResolver] FTS search error: {fts_exc}")

        # ----------------------------------------------------------------------
        # 4. Semantic Search (pgvector cosine similarity)
        # ----------------------------------------------------------------------
        try:
            query_vector = await EmbeddingGenerator.generate_embedding(norm_text, is_query=True)
            sem_hits = await self.entity_repo.search_semantic(
                db_knowledgebase_id=db_knowledgebase_id,
                query_embedding=query_vector,
                table_name=table_filter,
                column_name=column_filter,
                limit=limit,
            )
            for hit in sem_hits:
                key = f"{hit.table_name}.{hit.column_name}.{hit.normalized_value}"
                score = 0.80  # semantic match baseline
                if key not in candidates_map:
                    candidates_map[key] = ResolvedCandidate(
                        table_name=hit.table_name,
                        column_name=hit.column_name,
                        raw_value=hit.raw_value,
                        normalized_value=hit.normalized_value,
                        score=score,
                        match_type="semantic",
                        frequency_count=hit.frequency_count,
                    )
        except Exception as sem_exc:
            logger.debug(f"[ValueResolver] Semantic search skipped/error: {sem_exc}")

        # ----------------------------------------------------------------------
        # Ranking and Ambiguity Check
        # ----------------------------------------------------------------------
        ranked = sorted(
            candidates_map.values(),
            key=lambda c: (c.score, c.frequency_count or 0),
            reverse=True,
        )[:limit]

        if not ranked:
            return ValueResolutionResult(query_text=text, candidates=[], ambiguous=False)

        best = ranked[0]
        ambiguous = False
        matching_columns = [f"{best.table_name}.{best.column_name}"]
        match_count = best.frequency_count or 1

        if len(ranked) > 1:
            diff = abs(best.score - ranked[1].score)
            if diff <= ambiguity_threshold and ranked[0].raw_value.lower() != ranked[1].raw_value.lower():
                ambiguous = True

        # X1: Set ambiguous=true when matched value has frequency_count > 1 in a name-like column
        name_indicators = ("name", "first_name", "last_name", "full_name", "username")
        if any(ind in best.column_name.lower() for ind in name_indicators):
            if (best.frequency_count or 1) > 1:
                ambiguous = True
                match_count = best.frequency_count

        return ValueResolutionResult(
            query_text=text,
            candidates=ranked,
            ambiguous=ambiguous,
            best_match=best,
            matching_columns=matching_columns,
            match_count=match_count,
        )
