"""Hybrid Score Fusion for Schema Retrieval

Combines vector similarity, keyword matching, and relationship graph signals into
an explicit, observable, and deterministic final score per table.
"""

from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field, ConfigDict

from .keyword_matcher import KeywordMatchResult
from .vector_search import VectorMatchResult


class TableRetrievalScore(BaseModel):
    """Detailed observable scoring and explainability for a retrieved table."""
    model_config = ConfigDict(extra="forbid")

    table_name: str
    schema_name: str = "public"
    vector_score: float = Field(default=0.0, ge=0.0, le=1.0)
    keyword_score: float = Field(default=0.0, ge=0.0, le=1.0)
    graph_score: float = Field(default=0.0, ge=0.0, le=1.0)
    final_score: float = Field(default=0.0, ge=0.0, le=1.0)
    matched_columns: List[str] = Field(default_factory=list)
    matched_tokens: List[str] = Field(default_factory=list)
    retrieval_reason: str = ""
    retrieval_source: str = ""  # e.g. "hybrid (vector + keyword)", "graph expansion", "keyword fallback"


class HybridScorer:
    """Fuses multi-signal retrieval scores with clear provenance and explainability."""

    DEFAULT_VECTOR_WEIGHT = 0.50
    DEFAULT_KEYWORD_WEIGHT = 0.35
    DEFAULT_GRAPH_WEIGHT = 0.15

    FALLBACK_KEYWORD_WEIGHT = 0.70
    FALLBACK_GRAPH_WEIGHT = 0.30

    @classmethod
    def filter_canonical_tables(
        cls,
        tables: List[Any],
        allow_non_canonical: bool = False,
    ) -> List[Any]:
        """
        Filter candidate tables to canonical tables (is_canonical=True) by default.
        Relaxes the filter only if allow_non_canonical is explicitly enabled
        (e.g., query expresses explicit historical/audit intent).
        """
        if allow_non_canonical:
            return tables

        from ..semantic_glossary.canonicality import is_canonical_table
        return [t for t in tables if is_canonical_table(t)]

    @classmethod
    def fuse_scores(
        cls,
        vector_results: Dict[str, VectorMatchResult],
        keyword_results: Dict[str, KeywordMatchResult],
        graph_boosts: Optional[Dict[str, float]] = None,
        is_vector_available: bool = True,
        allowed_table_keys: Optional[Set[str]] = None,
    ) -> Dict[str, TableRetrievalScore]:
        """
        Compute deterministic final score for each candidate table.

        Returns:
            Dictionary of table_key -> TableRetrievalScore
        """
        graph_boosts = graph_boosts or {}
        raw_keys = set(vector_results.keys()) | set(keyword_results.keys()) | set(graph_boosts.keys())
        if allowed_table_keys is not None:
            raw_keys = {
                k for k in raw_keys
                if k in allowed_table_keys or k.split(".")[-1] in allowed_table_keys
            }

        # Canonicalize keys: if both "schema.table" and "table" exist, prefer qualified "schema.table"
        all_table_keys: Set[str] = set()
        unqualified_to_qualified: Dict[str, str] = {}
        for k in raw_keys:
            if "." in k:
                all_table_keys.add(k)
                unqualified_to_qualified[k.split(".")[-1]] = k
            else:
                all_table_keys.add(k)

        final_keys: Set[str] = set()
        for k in all_table_keys:
            if "." not in k and k in unqualified_to_qualified:
                continue
            final_keys.add(k)

        fused_scores: Dict[str, TableRetrievalScore] = {}

        for t_key in final_keys:
            bare_key = t_key.split(".")[-1] if "." in t_key else t_key
            v_res = vector_results.get(t_key) or vector_results.get(bare_key)
            k_res = keyword_results.get(t_key) or keyword_results.get(bare_key)
            g_boost = graph_boosts.get(t_key, graph_boosts.get(bare_key, 0.0))

            v_score = v_res.combined_vector_score if v_res else 0.0
            k_score = k_res.score if k_res else 0.0
            g_score = min(1.0, g_boost)

            ordered_matched_cols: List[str] = []
            matched_toks = set()
            reasons = []
            sources = []

            if k_res and k_score > 0:
                for col in k_res.matched_columns:
                    if col not in ordered_matched_cols:
                        ordered_matched_cols.append(col)
                matched_toks.update(k_res.matched_tokens)
                reasons.append(k_res.retrieval_reason)
                sources.append("keyword")

            if v_res and v_score > 0:
                for col in v_res.matched_columns:
                    if col not in ordered_matched_cols:
                        ordered_matched_cols.append(col)
                reasons.append(v_res.retrieval_reason)
                sources.append("vector")

            if g_score > 0:
                reasons.append(f"Bridge / Graph connected table (score={g_score:.2f})")
                sources.append("graph")

            if is_vector_available:
                final = (
                    cls.DEFAULT_VECTOR_WEIGHT * v_score
                    + cls.DEFAULT_KEYWORD_WEIGHT * k_score
                    + cls.DEFAULT_GRAPH_WEIGHT * g_score
                )
            else:
                final = (
                    cls.FALLBACK_KEYWORD_WEIGHT * k_score
                    + cls.FALLBACK_GRAPH_WEIGHT * g_score
                )

            # Extract schema and table name
            parts = t_key.split(".")
            s_name = parts[0] if len(parts) > 1 else "public"
            t_name = parts[1] if len(parts) > 1 else parts[0]

            fused_scores[t_key] = TableRetrievalScore(
                table_name=t_name,
                schema_name=s_name,
                vector_score=round(v_score, 4),
                keyword_score=round(k_score, 4),
                graph_score=round(g_score, 4),
                final_score=round(final, 4),
                matched_columns=ordered_matched_cols,
                matched_tokens=sorted(list(matched_toks)),
                retrieval_reason="; ".join(reasons) if reasons else "No direct matches",
                retrieval_source=" + ".join(sources) if sources else "unknown",
            )

        return fused_scores
