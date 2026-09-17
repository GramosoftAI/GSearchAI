"""Phase 6G: Explicit Ambiguity Detector

Detects semantic ambiguity in user queries before SQL planning or compilation.
Identifies underspecified metrics (e.g., bare "salary" vs "total salary" / "average salary")
and underspecified entities without blindly guessing or inventing definitions.
"""

from typing import List, Optional, Tuple
import uuid
import re

from .models import (
    AmbiguityAction,
    AmbiguityReport,
    AmbiguityStatus,
    CandidateMeaning,
)
from .registry import SemanticModelRegistry
from .metrics import CanonicalMetricRegistry


class AmbiguityDetector:
    """
    Evaluates natural language questions against registered metrics and entities
    to detect semantic collisions, underspecified terms, or multiple conflicting interpretations.
    """

    # Ambiguity score threshold: if top candidates are closer than this, flag as ambiguous
    CONFIDENCE_DELTA_THRESHOLD = 0.15

    @classmethod
    def detect_ambiguity(
        cls,
        query: str,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        metric_registry: Optional[CanonicalMetricRegistry] = None,
        semantic_registry: Optional[SemanticModelRegistry] = None,
    ) -> AmbiguityReport:
        """
        Analyze query for ambiguity across metrics and entities.
        Returns an AmbiguityReport containing structured candidate meanings and required action.
        """
        query_clean = query.strip().lower()
        candidates: List[CandidateMeaning] = []

        # 1. Evaluate Metric Ambiguity
        if metric_registry:
            all_metrics = metric_registry.list_metrics(tenant_id, knowledgebase_id)
            words = set(re.findall(r"\b[a-zA-Z0-9_]+\b", query_clean))

            for m in all_metrics:
                if m.status != "ACTIVE":
                    continue

                best_m_score = 0.0
                best_syn = None

                # Check exact name or display name match
                if m.name.lower() in query_clean or m.display_name.lower() in query_clean:
                    best_m_score = 0.95
                    best_syn = m.display_name
                else:
                    # Check synonyms
                    for syn in m.synonyms:
                        syn_lower = syn.lower()
                        if syn_lower in query_clean:
                            syn_words_count = len(syn_lower.split())
                            # Multi-word exact phrase match gets higher score than single word
                            syn_score = 0.70 + min(0.25, syn_words_count * 0.12)
                            if syn_score > best_m_score:
                                best_m_score = syn_score
                                best_syn = syn

                if best_m_score > 0:
                    # Check aggregate alignment
                    agg_str = m.aggregation.value.lower()
                    agg_keywords = {
                        "count": {"count", "headcount", "how many", "number"},
                        "sum": {"sum", "total"},
                        "avg": {"avg", "average", "mean"},
                        "min": {"min", "minimum", "lowest"},
                        "max": {"max", "maximum", "highest", "top"},
                    }.get(agg_str, {agg_str})

                    has_matching_agg = bool(agg_keywords.intersection(words))
                    # Check if query has a conflicting aggregate keyword
                    all_other_aggs = set()
                    for other_k, kws in [("count", {"count", "headcount"}), ("sum", {"sum", "total"}), ("avg", {"avg", "average"}), ("min", {"min", "minimum"}), ("max", {"max", "maximum"})]:
                        if other_k != agg_str:
                            all_other_aggs.update(kws)
                    has_conflicting_agg = bool(all_other_aggs.intersection(words))

                    if has_matching_agg:
                        best_m_score = min(1.0, best_m_score + 0.15)
                    elif has_conflicting_agg:
                        best_m_score = max(0.2, best_m_score - 0.35)

                    candidates.append(
                        CandidateMeaning(
                            meaning_id=f"metric:{m.metric_id}",
                            description=f"Metric: {m.display_name} ({m.expression})",
                            confidence=round(best_m_score, 2),
                            mapped_metric=m.metric_id,
                            mapped_entity=m.source_entity,
                        )
                    )

        # 2. Check for bare concept ambiguity (e.g. "salary" when both avg and total salary exist)
        words = set(re.findall(r"\b[a-zA-Z0-9_]+\b", query_clean))
        if metric_registry and candidates:
            # If query contains no explicit aggregate keywords like "average", "total", "sum", "count", "min", "max"
            has_explicit_agg = bool({"total", "sum", "average", "avg", "mean", "count", "min", "minimum", "max", "maximum", "lowest", "highest"}.intersection(words))
            if not has_explicit_agg and len(candidates) > 1:
                # Multiple metrics matched a generic term like "salary"
                return AmbiguityReport(
                    status=AmbiguityStatus.AMBIGUOUS,
                    candidate_meanings=candidates,
                    required_action=AmbiguityAction.CLARIFICATION,
                    selected_meaning=None,
                    ambiguity_token="unspecified aggregate",
                )

        # 3. Evaluate Entity Ambiguity
        if semantic_registry:
            resolved_entities = semantic_registry.resolve_entities(query, tenant_id, knowledgebase_id)
            for entity, conf, tokens in resolved_entities:
                candidates.append(
                    CandidateMeaning(
                        meaning_id=f"entity:{entity.entity_id}",
                        description=f"Entity: {entity.name} matching {tokens}",
                        confidence=conf,
                        mapped_entity=entity.name,
                    )
                )

        # If no candidates, unambiguous (proceed with standard parser/planner)
        if not candidates:
            return AmbiguityReport(
                status=AmbiguityStatus.UNAMBIGUOUS,
                candidate_meanings=[],
                required_action=AmbiguityAction.PROCEED,
                selected_meaning=None,
            )

        # Sort candidates by confidence descending
        candidates.sort(key=lambda c: -c.confidence)

        # Check if top candidate is a clear winner
        if len(candidates) == 1:
            return AmbiguityReport(
                status=AmbiguityStatus.UNAMBIGUOUS,
                candidate_meanings=candidates,
                required_action=AmbiguityAction.PROCEED,
                selected_meaning=candidates[0],
            )

        top1 = candidates[0]
        top2 = candidates[1]

        # If top 2 are distinct and close in confidence, flag as AMBIGUOUS
        if top1.meaning_id != top2.meaning_id and (top1.confidence - top2.confidence) < cls.CONFIDENCE_DELTA_THRESHOLD:
            return AmbiguityReport(
                status=AmbiguityStatus.AMBIGUOUS,
                candidate_meanings=[top1, top2],
                required_action=AmbiguityAction.CLARIFICATION,
                selected_meaning=None,
                ambiguity_token=f"{top1.description} vs {top2.description}",
            )

        # Clear winner exists
        return AmbiguityReport(
            status=AmbiguityStatus.UNAMBIGUOUS,
            candidate_meanings=candidates,
            required_action=AmbiguityAction.PROCEED,
            selected_meaning=top1,
        )
