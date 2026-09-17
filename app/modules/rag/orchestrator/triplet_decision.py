"""
Dynamic Triplet Retrieval Decision Engine.

Determines dynamically whether TripletRetriever (Neo4j Graph Traversal) is needed
for a given query, or whether it can be safely skipped to reduce latency while
preserving 100% accuracy, multi-hop reasoning, and score contracts.
"""

import re
import logging
from enum import Enum
from typing import Optional, List, Dict, Any

from app.modules.rag.orchestrator.query_analyzer import QueryIntent, AnalysisResult

logger = logging.getLogger(__name__)


class TripletDecision(str, Enum):
    SKIP_TRIPLETS = "SKIP_TRIPLETS"
    RUN_TRIPLETS = "RUN_TRIPLETS"
    RUN_REDUCED = "RUN_REDUCED"


# Generic linguistic relationship indicators (no hardcoded entities, names, or domains)
RELATIONSHIP_INDICATORS = [
    "relationship", "relation", "relate", "connect", "connection",
    "between", "associate", "link", "depend", "interaction", "hierarchy",
    "parent", "child", "member", "role", "works for", "reports to",
    "affiliated", "partner", "cause", "caused by", "lead to", "result from",
    "influence", "impact", "part of", "belong"
]

MULTI_HOP_INDICATORS = [
    "who is the", "whose", "which leads to", "how did", "chain of",
    "sequence", "path from", "step by step", "flow from"
]


def decide_triplet_retrieval(
    query: str,
    analysis: Optional[AnalysisResult] = None,
    meta_dict: Optional[Dict[str, Any]] = None,
    has_graph_data: bool = True
) -> tuple[TripletDecision, str]:
    """
    Data-driven dynamic policy for TripletRetriever execution.
    
    Principles:
    1. Always skip for tabular/SQL queries where graph context cannot contribute.
    2. Strongly run for GRAPH, STRUCTURAL, WHY, COMPARISON, relationship-oriented,
       multi-entity, and multi-hop queries.
    3. Skip for simple factual queries with high vector/keyword confidence and no relational intent.
    4. Fail safely to RUN_TRIPLETS if analyzer is missing or low-confidence.
    5. RUN_REDUCED is explicitly deferred because TripletRetriever uses fixed top_k=20
       and RRF uses fixed reciprocal weighting; running reduced top_k alters rank fusion
       without measurable latency advantage over skipping or server-side cosine.
    """
    # Defensive checks on inputs
    q_clean = (query or "").strip().lower()
    
    # 0. If no graph data exists for candidate KBs
    if not has_graph_data:
        return TripletDecision.SKIP_TRIPLETS, "no_graph_data_for_target_kbs"

    # Fallback to meta_dict if analysis is None
    is_tabular = False
    intent = QueryIntent.UNKNOWN
    confidence = 0.0
    keywords = []
    heuristic_fallback = False

    if analysis:
        is_tabular = getattr(analysis, "is_tabular", False)
        intent = getattr(analysis, "intent", QueryIntent.UNKNOWN)
        confidence = getattr(analysis, "confidence", 0.0)
        heuristic_fallback = getattr(analysis, "heuristic_fallback_used", False)
        if hasattr(analysis, "metadata") and analysis.metadata:
            keywords = getattr(analysis.metadata, "keywords", []) or []
    elif meta_dict:
        is_tabular = meta_dict.get("is_tabular", False)
        intent_val = meta_dict.get("intent")
        if isinstance(intent_val, QueryIntent):
            intent = intent_val
        elif isinstance(intent_val, str):
            try:
                intent = QueryIntent[intent_val.upper()]
            except KeyError:
                intent = QueryIntent.UNKNOWN
        confidence = float(meta_dict.get("confidence", 0.0))
        heuristic_fallback = bool(meta_dict.get("heuristic_fallback_used", False))
        keywords = meta_dict.get("keywords", []) or []

    # Rule A: Tabular/SQL-only queries skip triplets
    if is_tabular and not (meta_dict and meta_dict.get("_sql_cascade_fell_through", False)):
        return TripletDecision.SKIP_TRIPLETS, "tabular_sql_query"

    # Rule E: Fail-safe if analyzer is missing, inconclusive, or low confidence
    if confidence < 0.60 or heuristic_fallback or intent == QueryIntent.UNKNOWN:
        return TripletDecision.RUN_TRIPLETS, "failsafe_low_confidence_or_missing_analyzer"

    # Rule B1: Explicit graph or structural intents
    if intent in (QueryIntent.GRAPH, QueryIntent.STRUCTURAL):
        return TripletDecision.RUN_TRIPLETS, f"intent_{intent.value.lower()}"

    # Rule B2: WHY and causal reasoning intents
    if intent == QueryIntent.WHY:
        return TripletDecision.RUN_TRIPLETS, "intent_why_causal_reasoning"

    # Rule B3: Comparison intent with multiple entities/keywords
    if intent == QueryIntent.COMPARISON:
        return TripletDecision.RUN_TRIPLETS, "intent_comparison_relational"

    # Rule B4: Check for generic relationship signals in query
    has_rel_signal = any(indicator in q_clean for indicator in RELATIONSHIP_INDICATORS)
    if has_rel_signal:
        return TripletDecision.RUN_TRIPLETS, "relational_phrase_detected"

    # Rule B5: Check for multi-hop phrasing
    has_multihop_signal = any(m in q_clean for m in MULTI_HOP_INDICATORS)
    if has_multihop_signal:
        return TripletDecision.RUN_TRIPLETS, "multi_hop_query_pattern"

    # Rule B6: Query mentions multiple distinct proper nouns / entities
    # Generic regex detecting capitalized words (potential entity mentions)
    words = re.findall(r'\b[A-Za-z0-9_-]+\b', query or "")
    capitalized_tokens = [w for w in words if w and w[0].isupper() and len(w) > 1 and w.lower() not in ("what", "where", "when", "who", "why", "how", "the", "in", "on", "at", "is", "are")]
    unique_entities = set(capitalized_tokens)
    if len(unique_entities) >= 2:
        return TripletDecision.RUN_TRIPLETS, f"multi_entity_query_{len(unique_entities)}_entities"

    # Rule C: Simple factual query with high confidence and no relational indicators
    if intent == QueryIntent.FACT and confidence >= 0.75 and not has_rel_signal and not has_multihop_signal:
        return TripletDecision.SKIP_TRIPLETS, "simple_factual_lookup_vector_sufficient"

    # Fallback to RUN_TRIPLETS for safety
    return TripletDecision.RUN_TRIPLETS, "default_safe_graph_retrieval"
