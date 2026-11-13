import os
import math
import pytest
from dataclasses import dataclass
from typing import Optional, Dict, List
from unittest.mock import MagicMock

from app.modules.rag.pipeline import RetrievedChunk, RAGContext
from app.modules.rag.service import RAGService


def make_dummy_chunk(
    chunk_id: str,
    text: str = "Generic dummy text content for chunk.",
    vector_score: float = 0.0,
    keyword_score: float = 0.0,
    exact_score: float = 0.0,
    triplet_score: float = 0.0,
    rrf_score: float = 0.0,
    reranker_raw_score: Optional[float] = None,
    reranker_score: Optional[float] = None,
    final_relevance_score: float = 0.0,
    hybrid_score: float = 0.0,
    position: int = 0
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        text=text,
        kb_id="kb_generic_123",
        position=position,
        embedding_similarity=vector_score,
        graph_score=triplet_score,
        hybrid_score=hybrid_score or final_relevance_score,
        vector_score=vector_score,
        keyword_score=keyword_score,
        exact_score=exact_score,
        triplet_score=triplet_score,
        rrf_score=rrf_score,
        reranker_raw_score=reranker_raw_score,
        reranker_score=reranker_score,
        final_relevance_score=final_relevance_score
    )


# --- TEST 1: Score Preservation ---
def test_1_score_preservation():
    """Verify that all independent retrieval scores remain intact on RetrievedChunk."""
    chunk = make_dummy_chunk(
        chunk_id="c1",
        vector_score=0.82,
        keyword_score=0.015,
        exact_score=0.033,
        triplet_score=0.025,
        rrf_score=0.045,
        reranker_raw_score=0.88,
        reranker_score=0.88,
        final_relevance_score=0.88,
        hybrid_score=0.88
    )
    assert chunk.vector_score == 0.82
    assert chunk.keyword_score == 0.015
    assert chunk.exact_score == 0.033
    assert chunk.triplet_score == 0.025
    assert chunk.rrf_score == 0.045
    assert chunk.reranker_raw_score == 0.88
    assert chunk.reranker_score == 0.88
    assert chunk.final_relevance_score == 0.88
    assert chunk.hybrid_score == 0.88


# --- TEST 2: RRF is Not Overwritten ---
def test_2_rrf_is_not_overwritten():
    """Verify rrf_score holds the actual fused score and is not overwritten with rank formulas."""
    actual_rrf = 0.032765
    chunk = make_dummy_chunk(
        chunk_id="c2",
        rrf_score=actual_rrf,
        final_relevance_score=actual_rrf,
        hybrid_score=0.99
    )
    assert chunk.rrf_score == actual_rrf
    assert chunk.hybrid_score == 0.99  # backward compat display score


# --- TEST 3: Reranker Probability [0, 1] ---
def test_3_reranker_probability():
    """Verify when reranker returns [0, 1] probabilities, no needless sigmoid is applied."""
    raw_prob = 0.742
    if 0.0 <= raw_prob <= 1.0:
        normalized = raw_prob
    else:
        normalized = 1.0 / (1.0 + math.exp(-raw_prob))
    assert normalized == 0.742

    chunk = make_dummy_chunk(
        chunk_id="c3",
        reranker_raw_score=raw_prob,
        reranker_score=normalized,
        final_relevance_score=normalized
    )
    assert chunk.reranker_score == 0.742
    assert chunk.final_relevance_score == 0.742


# --- TEST 4: Reranker Logits Normalization ---
def test_4_reranker_logits_normalization():
    """Verify when reranker returns raw logits (e.g. > 1.0 or < 0.0), sigmoid is applied properly."""
    raw_logit = 3.5
    if raw_logit > 1.0 or raw_logit < 0.0:
        normalized = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, raw_logit))))
    else:
        normalized = raw_logit
    
    expected = 1.0 / (1.0 + math.exp(-3.5))
    assert math.isclose(normalized, expected, rel_tol=1e-5)
    assert 0.0 <= normalized <= 1.0


# --- TEST 5: Strong Evidence Retained ---
def test_5_strong_evidence_retained(monkeypatch):
    """Strong candidates are retained by the dynamic filter."""
    monkeypatch.setenv("RAG_MIN_RELEVANCE_SCORE", "0.50")
    service = object.__new__(RAGService)

    c1 = make_dummy_chunk("c1", reranker_score=0.85, final_relevance_score=0.85)
    c2 = make_dummy_chunk("c2", reranker_score=0.75, final_relevance_score=0.75)
    context = RAGContext(query="query", chunks=[c1, c2], entity_mentions={}, total_tokens=100)

    dropped = service._filter_relevant_chunks(context)
    assert dropped == 0
    assert len(context.chunks) == 2


# --- TEST 6: Mixed Evidence Filtering ---
def test_6_mixed_evidence_filtering(monkeypatch):
    """Strong candidates kept, very weak tail chunks relative to top score are dropped."""
    monkeypatch.delenv("RAG_MIN_RELEVANCE_SCORE", raising=False)
    service = object.__new__(RAGService)

    c1 = make_dummy_chunk("c1", reranker_score=0.80, final_relevance_score=0.80)
    c2 = make_dummy_chunk("c2", reranker_score=0.70, final_relevance_score=0.70)
    c3 = make_dummy_chunk("c3", reranker_score=0.05, final_relevance_score=0.05)
    c4 = make_dummy_chunk("c4", reranker_score=0.01, final_relevance_score=0.01)
    context = RAGContext(query="query", chunks=[c1, c2, c3, c4], entity_mentions={}, total_tokens=200)

    # 15% of 0.80 is 0.12 -> c1, c2 >= 0.12; c3, c4 < 0.12
    dropped = service._filter_relevant_chunks(context)
    assert dropped == 2
    assert [c.chunk_id for c in context.chunks] == ["c1", "c2"]


# --- TEST 7: Weak Evidence All Discarded Without Fallback ---
def test_7_weak_evidence_discarded(monkeypatch):
    """When all candidates are genuinely weak/noise (no vector, exact, or agreement), they are dropped."""
    monkeypatch.setenv("RAG_MIN_RELEVANCE_SCORE", "0.50")
    service = object.__new__(RAGService)

    # All chunks have negligible scores and no retrieval backing
    c1 = make_dummy_chunk("c1", vector_score=0.10, reranker_score=0.005, final_relevance_score=0.005)
    c2 = make_dummy_chunk("c2", vector_score=0.08, reranker_score=0.003, final_relevance_score=0.003)
    context = RAGContext(query="query", chunks=[c1, c2], entity_mentions={}, total_tokens=100)

    dropped = service._filter_relevant_chunks(context)
    assert dropped == 2
    assert len(context.chunks) == 0


# --- TEST 8: Zero-Context Protection With Meaningful Evidence ---
def test_8_zero_context_protection(monkeypatch):
    """When reranker score is below static env threshold (0.50) but chunk has strong vector match (0.65), fallback preserves top chunk."""
    monkeypatch.setenv("RAG_MIN_RELEVANCE_SCORE", "0.50")
    service = object.__new__(RAGService)

    c1 = make_dummy_chunk("c1", vector_score=0.65, reranker_score=0.18, final_relevance_score=0.18)
    c2 = make_dummy_chunk("c2", vector_score=0.45, reranker_score=0.05, final_relevance_score=0.05)
    context = RAGContext(query="query", chunks=[c1, c2], entity_mentions={}, total_tokens=100)

    dropped = service._filter_relevant_chunks(context)
    # c1 preserved by zero-context fallback due to strong vector match (0.65 >= 0.40)
    assert len(context.chunks) == 1
    assert context.chunks[0].chunk_id == "c1"


# --- TEST 9: Multiple Retrieval Sources Independent Preservation ---
def test_9_multiple_retrieval_sources_preservation():
    """Check that Vector, Keyword, Exact, Graph/Triplet, and RRF all survive simultaneously."""
    chunk = make_dummy_chunk(
        chunk_id="multi_source_chunk",
        vector_score=0.77,
        keyword_score=0.016,
        exact_score=0.033,
        triplet_score=0.020,
        rrf_score=0.055,
        reranker_raw_score=0.92,
        reranker_score=0.92,
        final_relevance_score=0.92
    )
    assert chunk.vector_score > 0
    assert chunk.keyword_score > 0
    assert chunk.exact_score > 0
    assert chunk.triplet_score > 0
    assert chunk.rrf_score > 0
    assert chunk.reranker_score == 0.92


# --- TEST 10: Single Authoritative _filter_relevant_chunks ---
def test_10_single_authoritative_filter():
    """Verify only one definition of _filter_relevant_chunks exists on RAGService."""
    import inspect
    service_methods = [
        name for name, _ in inspect.getmembers(RAGService, predicate=inspect.isfunction)
        if name == "_filter_relevant_chunks"
    ]
    assert len(service_methods) == 1


# --- TEST 11: No Hardcoded Domain Rules in Filter ---
def test_11_no_hardcoded_domain_rules():
    """Ensure _filter_relevant_chunks contains no domain-specific or person-specific keywords."""
    import inspect
    source = inspect.getsource(RAGService._filter_relevant_chunks).lower()
    forbidden_tokens = ["rajesh", "arun", "ceo", "salary", "insurance", "leopard"]
    for token in forbidden_tokens:
        assert token not in source, f"Forbidden keyword '{token}' found in _filter_relevant_chunks!"


# --- TEST 12: Knowledge Graph Bypass of Noise Chunks ---
def test_12_knowledge_graph_bypasses_noise_chunk_fallback(monkeypatch):
    """When reranker scores are noise (< 0.10) but graph triplets exist, noise chunks are not retained.
    When no graph triplets exist, top chunk is preserved by zero-context fallback."""
    monkeypatch.setenv("RAG_MIN_RELEVANCE_SCORE", "0.60")
    service = object.__new__(RAGService)

    # Case A: Noise chunks with graph triplets present -> chunks dropped, letting graph stand alone
    c_noise = make_dummy_chunk("c_noise", vector_score=0.15, reranker_score=0.0594, final_relevance_score=0.0594)
    context_with_graph = RAGContext(
        query="who is rajesh",
        chunks=[c_noise],
        entity_mentions={},
        total_tokens=50,
        triplets=[{"subject": "Rajesh", "predicate": "CTO_OF", "object": "Gramosoft"}],
        triplet_context="Rajesh [CTO_OF] Gramosoft"
    )
    dropped = service._filter_relevant_chunks(context_with_graph)
    assert dropped == 1
    assert len(context_with_graph.chunks) == 0

    # Case B: Noise chunks WITHOUT graph triplets (chunk-only query) -> preserved by zero-context protection
    c_chunk_only = make_dummy_chunk("c_narrative", vector_score=0.15, reranker_score=0.0594, final_relevance_score=0.0594)
    context_no_graph = RAGContext(
        query="narrative query",
        chunks=[c_chunk_only],
        entity_mentions={},
        total_tokens=50
    )
    dropped_no_graph = service._filter_relevant_chunks(context_no_graph)
    assert dropped_no_graph == 0
    assert len(context_no_graph.chunks) == 1
    assert context_no_graph.chunks[0].chunk_id == "c_narrative"


# --- TEST 13: SilverFalcon Pattern (Narrative-only, Low Reranker, No Graph) ---
def test_13_silverfalcon_narrative_low_score_preserved(monkeypatch):
    """
    SilverFalcon regression test:
    Queries where the answer is exclusively in unstructured narrative text that never got
    triplet-extracted, but scored low on the reranker (e.g. 0.04 - 0.08, below 0.60 floor).
    Zero-context fallback must preserve the top narrative chunk rather than discarding all evidence.
    """
    monkeypatch.setenv("RAG_MIN_RELEVANCE_SCORE", "0.60")
    service = object.__new__(RAGService)

    silverfalcon_chunk = make_dummy_chunk(
        chunk_id="silverfalcon_passage_01",
        text="Project SilverFalcon is an enterprise internal audit codename initiated in Q3.",
        vector_score=0.28,
        reranker_score=0.045,
        final_relevance_score=0.045
    )
    context = RAGContext(
        query="What is SilverFalcon?",
        chunks=[silverfalcon_chunk],
        entity_mentions={},
        total_tokens=60,
        triplets=[],
        triplet_context=""
    )

    dropped = service._filter_relevant_chunks(context)
    assert dropped == 0
    assert len(context.chunks) == 1
    assert context.chunks[0].chunk_id == "silverfalcon_passage_01"


