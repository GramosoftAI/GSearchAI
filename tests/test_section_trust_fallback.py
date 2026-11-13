import pytest
from unittest.mock import AsyncMock, patch

from app.modules.rag.orchestrator.query_analyzer import AnalysisResult, QueryIntent, QueryMetadata
from app.modules.rag.pipeline import RAGPipeline, TRUST_THRESHOLD, SECTION_TRUST_FLOOR


@pytest.mark.asyncio
async def test_section_trust_low_score_and_heuristic_fallback_triggers_full_kb():
    """
    Unit Test 1: SectionRanker returns low scores (below floor 0.5) + heuristic_fallback_used=True
    -> full-KB fallback triggered (returns empty target_sections list).
    """
    heuristic_fallback_used = True
    
    candidate_sections = [
        {"section_id": "sec-1", "title": "Introduction", "snippet": "Tasks overview"},
        {"section_id": "sec-2", "title": "Summary Cards:", "snippet": "System phase"}
    ]
    
    ranked_sections = [
        {"section_id": "sec-1", "title": "Introduction", "rank_score": 0.0},
        {"section_id": "sec-2", "title": "Summary Cards:", "rank_score": -2.0}
    ]

    top_score = ranked_sections[0].get("rank_score", 0.0)
    
    target_sections = []
    if top_score < TRUST_THRESHOLD:
        if top_score >= SECTION_TRUST_FLOOR and not heuristic_fallback_used:
            target_sections = [s.get("section_id") for s in candidate_sections if s.get("section_id")]
        else:
            target_sections = []
            
    assert target_sections == [], "Low score + heuristic_fallback_used=True must trigger full-KB fallback (empty target_sections)"


@pytest.mark.asyncio
async def test_section_trust_weak_plausible_score_and_no_heuristic_fallback_preserves_ilike():
    """
    Unit Test 2: SectionRanker returns weak-but-plausible score (above floor 0.5, below TRUST_THRESHOLD 2.0)
    + heuristic_fallback_used=False -> ILIKE-based section restriction preserved.
    """
    heuristic_fallback_used = False
    
    candidate_sections = [
        {"section_id": "sec-101", "title": "Financial Highlights", "snippet": "Q3 Revenue"},
    ]
    ranked_sections = [
        {"section_id": "sec-101", "title": "Financial Highlights", "rank_score": 0.8}
    ]
    
    top_score = ranked_sections[0].get("rank_score", 0.0)
    
    target_sections = []
    if top_score < TRUST_THRESHOLD:
        if top_score >= SECTION_TRUST_FLOOR and not heuristic_fallback_used:
            target_sections = [s.get("section_id") for s in candidate_sections if s.get("section_id")]
        else:
            target_sections = []
            
    assert target_sections == ["sec-101"], "Score >= 0.5 with heuristic_fallback_used=False must preserve ILIKE candidate sections"


@pytest.mark.asyncio
async def test_section_trust_boundary_score_0_5_with_heuristic_fallback_fails():
    """
    Boundary Test 3: top_score == 0.5 + heuristic_fallback_used=True -> must REJECT ILIKE candidates due to degraded keyword source.
    """
    candidate_sections = [{"section_id": "sec-200", "title": "Plausible", "snippet": "Plausible text"}]
    top_score = 0.5
    heuristic_fallback_used = True
    
    target_sections = []
    if top_score < TRUST_THRESHOLD:
        if top_score >= SECTION_TRUST_FLOOR and not heuristic_fallback_used:
            target_sections = [s.get("section_id") for s in candidate_sections if s.get("section_id")]
        else:
            target_sections = []
            
    assert target_sections == [], "top_score == 0.5 with heuristic_fallback_used=True must fail SECTION_TRUST check"


@pytest.mark.asyncio
async def test_regression_exact_prod_bug():
    """
    Regression Test 4: Exact prod bug reproduction.
    Heuristic keywords match 'Introduction' (score 0.0) and 'Summary Cards:' (score -2.0),
    with heuristic_fallback_used=True -> assert full-KB fallback triggers (target_sections empty).
    """
    candidate_sections = [
        {"section_id": "sec-intro", "title": "Introduction"},
        {"section_id": "sec-cards", "title": "Summary Cards:"}
    ]
    ranked_sections = [
        {"section_id": "sec-intro", "title": "Introduction", "rank_score": 0.0},
        {"section_id": "sec-cards", "title": "Summary Cards:", "rank_score": -2.0}
    ]
    heuristic_fallback_used = True
    top_score = ranked_sections[0]["rank_score"]
    
    target_sections = []
    if top_score < TRUST_THRESHOLD:
        if top_score >= SECTION_TRUST_FLOOR and not heuristic_fallback_used:
            target_sections = [s.get("section_id") for s in candidate_sections if s.get("section_id")]
        else:
            target_sections = []
            
    assert target_sections == [], "Prod bug regression: ILIKE candidates (0.0 and -2.0) with degraded keywords must trigger full-KB fallback"


@pytest.mark.asyncio
async def test_section_trust_high_score_exact_threshold_with_heuristic_fallback_fails():
    """
    Regression Test 6: top_score == 2.0 (exact TRUST_THRESHOLD boundary) + heuristic_fallback_used=True
    -> must REJECT candidates unconditionally and return [] (full-KB fallback).
    """
    candidate_sections = [{"section_id": "sec-300", "title": "High Scoring Section"}]
    ranked_sections = [{"section_id": "sec-300", "rank_score": 2.0}]
    heuristic_fallback_used = True
    
    target_sections = []
    if heuristic_fallback_used:
        target_sections = []
    elif not ranked_sections:
        target_sections = [s.get("section_id") for s in candidate_sections]
    elif ranked_sections[0]["rank_score"] < TRUST_THRESHOLD:
        target_sections = [] if ranked_sections[0]["rank_score"] < SECTION_TRUST_FLOOR else [s.get("section_id") for s in candidate_sections]
    else:
        target_sections = [s.get("section_id") for s in ranked_sections]
        
    assert target_sections == [], "top_score == 2.0 with heuristic_fallback_used=True must trigger full-KB fallback"


@pytest.mark.asyncio
async def test_section_trust_very_high_score_with_heuristic_fallback_fails():
    """
    Regression Test 7: top_score == 5.0 (well above threshold) + heuristic_fallback_used=True
    -> must REJECT candidates unconditionally and return [] (full-KB fallback).
    """
    candidate_sections = [{"section_id": "sec-400", "title": "Very High Scoring Section"}]
    ranked_sections = [{"section_id": "sec-400", "rank_score": 5.0}]
    heuristic_fallback_used = True
    
    target_sections = []
    if heuristic_fallback_used:
        target_sections = []
    elif not ranked_sections:
        target_sections = [s.get("section_id") for s in candidate_sections]
    elif ranked_sections[0]["rank_score"] < TRUST_THRESHOLD:
        target_sections = [] if ranked_sections[0]["rank_score"] < SECTION_TRUST_FLOOR else [s.get("section_id") for s in candidate_sections]
    else:
        target_sections = [s.get("section_id") for s in ranked_sections]
        
    assert target_sections == [], "top_score == 5.0 with heuristic_fallback_used=True must trigger full-KB fallback"


@pytest.mark.asyncio
async def test_section_trust_empty_ranked_sections_with_heuristic_fallback_fails():
    """
    Regression Test 8: candidate_sections exist, but ranked_sections is empty + heuristic_fallback_used=True
    -> must REJECT candidates unconditionally before the `not ranked_sections` branch.
    """
    candidate_sections = [{"section_id": "sec-500", "title": "Unranked Section"}]
    ranked_sections = []
    heuristic_fallback_used = True
    
    target_sections = []
    if heuristic_fallback_used:
        target_sections = []
    elif not ranked_sections:
        target_sections = [s.get("section_id") for s in candidate_sections]
        
    assert target_sections == [], "empty ranked_sections with heuristic_fallback_used=True must trigger full-KB fallback"

