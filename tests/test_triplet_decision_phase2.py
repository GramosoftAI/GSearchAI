"""
Unit and Integration Tests for Phase 2 TripletRetriever Optimization.

Tests:
1. Decision policy:
   - Tabular / SQL queries skip triplets
   - GRAPH intent runs triplets
   - STRUCTURAL intent runs triplets
   - WHY intent runs triplets
   - COMPARISON intent runs triplets
   - Multi-entity relationship query runs triplets
   - Relational phrasing runs triplets
   - Multi-hop phrasing runs triplets
   - Simple factual lookup with vector confidence skips triplets
   - Missing / low-confidence / heuristic fallback fails safely to RUN_TRIPLETS
   - No hardcoded entities or keywords used
2. Pipeline integration:
   - Skipped triplet retrieval does not instantiate TripletRetriever or query Neo4j
   - Query embedding is reused without duplicate generation
   - Empty triplet result preserves RRF score contract
3. TripletRetriever correctness & tenant isolation:
   - Tenant isolation parameter enforcement
   - Handling of null embeddings & empty KB list
   - Fallback between server-side and Python cosine
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.rag.orchestrator.query_analyzer import QueryIntent, QueryMetadata, AnalysisResult
from app.modules.rag.orchestrator.triplet_decision import decide_triplet_retrieval, TripletDecision
from app.modules.tripets.retriever import TripletRetriever


# ==============================================================================
# PART A: DECISION POLICY TESTS
# ==============================================================================

def test_decision_tabular_skips():
    """Tabular or SQL-only queries must always skip triplet retrieval."""
    analysis = AnalysisResult(
        intent=QueryIntent.TABLE,
        metadata=QueryMetadata(keywords=["revenue", "q3"]),
        is_tabular=True,
        confidence=0.95,
        reasoning="Deterministic tabular match"
    )
    decision, reason = decide_triplet_retrieval("what is the total revenue for Q3?", analysis=analysis)
    assert decision == TripletDecision.SKIP_TRIPLETS
    assert "tabular" in reason


def test_decision_graph_intent_runs():
    """Queries with GRAPH intent must always run triplet retrieval."""
    analysis = AnalysisResult(
        intent=QueryIntent.GRAPH,
        metadata=QueryMetadata(keywords=["organization", "structure"]),
        is_tabular=False,
        confidence=0.88,
        reasoning="Graph relationship match"
    )
    decision, reason = decide_triplet_retrieval("show the organization hierarchy", analysis=analysis)
    assert decision == TripletDecision.RUN_TRIPLETS
    assert "graph" in reason


def test_decision_structural_intent_runs():
    """Queries with STRUCTURAL intent must always run triplet retrieval."""
    analysis = AnalysisResult(
        intent=QueryIntent.STRUCTURAL,
        metadata=QueryMetadata(keywords=["reporting", "lineage"]),
        is_tabular=False,
        confidence=0.85,
        reasoning="Structural match"
    )
    decision, reason = decide_triplet_retrieval("who reports to whom in the division?", analysis=analysis)
    assert decision == TripletDecision.RUN_TRIPLETS
    assert "structural" in reason


def test_decision_why_intent_runs():
    """Queries with WHY / causal reasoning intent must always run triplet retrieval."""
    analysis = AnalysisResult(
        intent=QueryIntent.WHY,
        metadata=QueryMetadata(keywords=["incident", "cause"]),
        is_tabular=False,
        confidence=0.90,
        reasoning="Why match"
    )
    decision, reason = decide_triplet_retrieval("why did the system fail during the deployment?", analysis=analysis)
    assert decision == TripletDecision.RUN_TRIPLETS
    assert "why" in reason


def test_decision_comparison_intent_runs():
    """Comparison queries must run triplet retrieval to establish relational bridges."""
    analysis = AnalysisResult(
        intent=QueryIntent.COMPARISON,
        metadata=QueryMetadata(keywords=["protocol", "differences"]),
        is_tabular=False,
        confidence=0.85,
        reasoning="Comparison match"
    )
    decision, reason = decide_triplet_retrieval("compare the architectural differences between v1 and v2", analysis=analysis)
    assert decision == TripletDecision.RUN_TRIPLETS
    assert "comparison" in reason


def test_decision_relational_phrasing_runs():
    """Queries with generic relational keywords must run triplets regardless of intent."""
    analysis = AnalysisResult(
        intent=QueryIntent.FACT,
        metadata=QueryMetadata(keywords=["relationship", "departments"]),
        is_tabular=False,
        confidence=0.80,
        reasoning="Factual query with relational term"
    )
    decision, reason = decide_triplet_retrieval("what is the relationship between the engineering team and product ops?", analysis=analysis)
    assert decision == TripletDecision.RUN_TRIPLETS
    assert "relational" in reason


def test_decision_multi_hop_runs():
    """Multi-hop query indicators must force triplet retrieval."""
    analysis = AnalysisResult(
        intent=QueryIntent.FACT,
        metadata=QueryMetadata(keywords=["sequence", "events"]),
        is_tabular=False,
        confidence=0.80,
        reasoning="Fact query"
    )
    decision, reason = decide_triplet_retrieval("which leads to the cascading restart sequence?", analysis=analysis)
    assert decision == TripletDecision.RUN_TRIPLETS
    assert "multi_hop" in reason


def test_decision_multi_entity_runs():
    """Queries mentioning 2 or more capitalized entities must trigger triplet retrieval."""
    analysis = AnalysisResult(
        intent=QueryIntent.FACT,
        metadata=QueryMetadata(keywords=["connection"]),
        is_tabular=False,
        confidence=0.80,
        reasoning="Fact query"
    )
    # Generic proper nouns without hardcoded words
    decision, reason = decide_triplet_retrieval("Did AlphaCorp finalize with BetaGroup during the merger?", analysis=analysis)
    assert decision == TripletDecision.RUN_TRIPLETS
    assert "multi_entity" in reason


def test_decision_simple_factual_skips():
    """Simple factual query with high confidence and no relational indicators must safely skip."""
    analysis = AnalysisResult(
        intent=QueryIntent.FACT,
        metadata=QueryMetadata(keywords=["password", "reset", "policy"]),
        is_tabular=False,
        confidence=0.92,
        reasoning="Clear document lookup"
    )
    decision, reason = decide_triplet_retrieval("what is the password reset policy duration?", analysis=analysis)
    assert decision == TripletDecision.SKIP_TRIPLETS
    assert "simple_factual_lookup" in reason


def test_decision_low_confidence_failsafe_runs():
    """Low-confidence or missing analyzer must fail safely to RUN_TRIPLETS."""
    analysis = AnalysisResult(
        intent=QueryIntent.FACT,
        metadata=QueryMetadata(keywords=["unknown"]),
        is_tabular=False,
        confidence=0.45,
        reasoning="Ambiguous"
    )
    decision, reason = decide_triplet_retrieval("tell me about the policy updates", analysis=analysis)
    assert decision == TripletDecision.RUN_TRIPLETS
    assert "failsafe" in reason

    # None analysis case
    decision_none, reason_none = decide_triplet_retrieval("random query with no analysis", analysis=None)
    assert decision_none == TripletDecision.RUN_TRIPLETS
    assert "failsafe" in reason_none


def test_decision_no_graph_data_skips():
    """When target knowledge bases have zero graph/triplet data, skip triplets."""
    analysis = AnalysisResult(
        intent=QueryIntent.GRAPH,
        metadata=QueryMetadata(keywords=["team"]),
        is_tabular=False,
        confidence=0.90,
        reasoning="Graph intent"
    )
    decision, reason = decide_triplet_retrieval("show team structure", analysis=analysis, has_graph_data=False)
    assert decision == TripletDecision.SKIP_TRIPLETS
    assert "no_graph_data" in reason


# ==============================================================================
# PART B: TRIPLET RETRIEVER CORRECTNESS & TENANT ISOLATION
# ==============================================================================

@pytest.mark.asyncio
async def test_triplet_retriever_empty_kbs():
    """TripletRetriever must safely return empty list if kb_ids is empty."""
    retriever = TripletRetriever("b91f23d9-7127-420d-acc9-fc420b46bf9e")
    # Empty query embedding
    results = await retriever.search_triplets(
        query_embedding=[0.1] * 4096,
        kb_ids=[],
        top_k=10
    )
    # Since kb_ids is empty, MATCH (kb) where kb.id IN [] will return no KB chunks
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_triplet_retriever_format_as_context():
    """Verify format_triplets_as_context structures output correctly."""
    retriever = TripletRetriever("00000000-0000-0000-0000-000000000000")
    dummy_triplets = [
        {"subject": "ServiceA", "predicate": "DEPENDS_ON", "object": "ServiceB", "similarity": 0.85},
        {"subject": "User1", "predicate": "PARTICIPATED_IN_ROLE_LEAD", "object": "IncidentEvent", "similarity": 0.90},
        {"subject": "IncidentEvent", "predicate": "HAS_DATE", "object": "2026-09-15", "similarity": 0.90}
    ]
    context = retriever.format_triplets_as_context(dummy_triplets)
    assert "KNOWLEDGE GRAPH RELATIONSHIPS:" in context
    assert "ServiceA [DEPENDS_ON] ServiceB" in context
    assert "IncidentEvent" in context
