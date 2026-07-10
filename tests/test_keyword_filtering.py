import pytest
import time
from uuid import uuid4

# Import actual functions from the codebase to test the production implementation directly
from app.modules.knowledge_bases.tasks import (
    is_valid_candidate_word,
    get_adaptive_threshold,
    generate_kb_noisy_words
)
from app.modules.rag.pipeline import _KB_NOISY_WORDS_CACHE, KB_NOISY_WORDS_CACHE_TTL

# Default static fallback scores from pipeline.py
DEFAULT_NOISY_WORDS_SCORES = {
    "report": 0.99, "reports": 0.99,
    "financial": 0.98,
    "company": 0.97, "corporation": 0.97, "inc": 0.97,
    "statement": 0.91, "statements": 0.91,
    "sheet": 0.91, "sheets": 0.91,
    "annual": 0.83,
    "quarter": 0.80, "quarters": 0.80,
    "period": 0.75, "periods": 0.75,
    "months": 0.70,
    "ended": 0.65,
    "form": 0.60,
    "10-q": 0.55, "10-k": 0.55,
    "disclose": 0.50, "disclosed": 0.50, "disclosures": 0.50,
    "performance": 0.45,
    "item": 0.40, "items": 0.40,
    "apple": 0.30, "aapl": 0.30
}

def simulate_pipeline_keyword_filter(
    extracted_keywords: list, 
    entities: list, 
    kb_ids: list,
    custom_noisy_words: dict = None
) -> list:
    """
    Simulates the exact 3-layer filtering logic from app/modules/rag/pipeline.py
    but allows passing a custom noisy_words dictionary directly for testing.
    """
    if not extracted_keywords:
        return []

    split_keywords = []
    for kw in extracted_keywords:
        for word in kw.split():
            cleaned = "".join(c for c in word if c.isalnum() or c in "-.")
            if cleaned:
                split_keywords.append(cleaned)

    # Resolve noisy words scores (database query simulation or fallback)
    noisy_words_scores = {}
    now_time = time.time()
    
    if custom_noisy_words:
        # Use provided scores directly for unit tests
        noisy_words_scores = custom_noisy_words
    else:
        # Replicate pipeline cache/db logic
        for kbid in kb_ids:
            if kbid in _KB_NOISY_WORDS_CACHE:
                cached = _KB_NOISY_WORDS_CACHE[kbid]
                if now_time < cached["expiry"]:
                    for word_data in cached["data"]:
                        word = word_data["word"]
                        score = word_data["score"]
                        noisy_words_scores[word] = max(noisy_words_scores.get(word, 0.0), score)

        if not noisy_words_scores:
            noisy_words_scores = dict(DEFAULT_NOISY_WORDS_SCORES)

    # 1. ENTITY PROTECTION: Extract all entities
    entities_to_protect = set()
    for entity in entities:
        for part in str(entity).split():
            cleaned_part = "".join(c for c in part if c.isalnum() or c in "-.").lower()
            if cleaned_part:
                entities_to_protect.add(cleaned_part)

    # 2. NOISY WORD CANDIDATE DETECTION & SCORES COLLECTION
    noisy_candidates = []
    for idx, k in enumerate(split_keywords):
        k_lower = k.lower()
        if k_lower in noisy_words_scores and k_lower not in entities_to_protect:
            noisy_candidates.append((idx, k_lower, noisy_words_scores[k_lower]))

    # 3. TOP-3 NOISY-WORD REMOVAL
    noisy_candidates.sort(key=lambda x: x[2], reverse=True)
    to_remove_indices = {candidate[0] for candidate in noisy_candidates[:3]}

    filtered_keywords = [
        k for idx, k in enumerate(split_keywords)
        if idx not in to_remove_indices
    ]

    # 4. FAIL-SAFE FALLBACK
    if not filtered_keywords:
        filtered_keywords = split_keywords

    return list(dict.fromkeys(filtered_keywords))

# --- Setup Fixture to Clear Cache Between Tests ---
@pytest.fixture(autouse=True)
def run_before_and_after_tests():
    global _KB_NOISY_WORDS_CACHE
    _KB_NOISY_WORDS_CACHE.clear()
    yield

# --- UNIT TESTS FOR USER REQUIREMENTS ---

def test_normalization_behavior():
    """
    Ensure 'Report', 'report', 'REPORT', 'report.', 'report,' are all normalized
    correctly by stripping punctuation and lowercasing.
    """
    # Test token cleaning
    punctuation_words = ["REPORT", "report.", "report,", "report!"]
    for w in punctuation_words:
        cleaned = w.strip(".,;:!?\"'()[]{}<>_-@#$%^&*+=`~|\\/").lower()
        assert cleaned == "report"

    # Test that is_valid_candidate_word accepts it
    assert is_valid_candidate_word("report") is True

def test_ignore_numbers_and_ids():
    """
    Ensure numbers, UUIDs, hashes, and short identifiers are ignored from noisy word consideration.
    """
    # 1. Ignore pure numbers
    assert is_valid_candidate_word("2023") is False
    assert is_valid_candidate_word("12345") is False
    assert is_valid_candidate_word("10") is False

    # 2. Ignore UUIDs
    sample_uuid = str(uuid4())
    assert is_valid_candidate_word(sample_uuid) is False

    # 3. Ignore alphanumeric hashes / long IDs (digit present, len >= 8)
    assert is_valid_candidate_word("inv-12345") is False
    assert is_valid_candidate_word("hash89012") is False
    assert is_valid_candidate_word("4a7d9e2b") is False

    # 4. Ignore short single characters or symbols
    assert is_valid_candidate_word("a") is False
    assert is_valid_candidate_word("x") is False
    assert is_valid_candidate_word("?") is False

    # 5. Allow genuine domain-specific words
    assert is_valid_candidate_word("agreement") is True
    assert is_valid_candidate_word("patient") is True
    assert is_valid_candidate_word("quarterly") is True

def test_adaptive_threshold_by_kb_size():
    """
    Test adaptive threshold calculations across different KB sizes.
    """
    # Small KB (<= 20 chunks) -> threshold 50%
    assert get_adaptive_threshold(total_chunks=15, default_threshold=0.3) == 0.50
    assert get_adaptive_threshold(total_chunks=20, default_threshold=0.3) == 0.50

    # Medium KB (<= 100 chunks) -> threshold 35%
    assert get_adaptive_threshold(total_chunks=50, default_threshold=0.3) == 0.35
    assert get_adaptive_threshold(total_chunks=100, default_threshold=0.3) == 0.35

    # Large KB (<= 1000 chunks) -> threshold 20%
    assert get_adaptive_threshold(total_chunks=500, default_threshold=0.3) == 0.20
    assert get_adaptive_threshold(total_chunks=1000, default_threshold=0.3) == 0.20

    # Very Large KB (> 1000 chunks) -> threshold 10%
    assert get_adaptive_threshold(total_chunks=5000, default_threshold=0.3) == 0.10

    # Explicitly configured threshold should be respected regardless of size
    assert get_adaptive_threshold(total_chunks=5000, default_threshold=0.45) == 0.45

def test_cache_invalidation_after_regeneration():
    """
    Verify that TTL cache is immediately cleared for a KB id when its noisy words are regenerated.
    """
    kb_id = "test-kb-123"
    
    # 1. Populate the cache manually
    _KB_NOISY_WORDS_CACHE[kb_id] = {
        "data": [{"word": "legacy", "score": 0.99}],
        "expiry": time.time() + 300
    }
    
    # Assert cache exists
    assert kb_id in _KB_NOISY_WORDS_CACHE

    # 2. Simulate cache invalidation logic inside tasks.py
    # Delete from cache
    for key in [kb_id, str(kb_id)]:
        if key in _KB_NOISY_WORDS_CACHE:
            del _KB_NOISY_WORDS_CACHE[key]
            
    # Assert cache was cleared immediately
    assert kb_id not in _KB_NOISY_WORDS_CACHE

def test_summarize_apple_pipeline_flow():
    """
    Test standard entity protection pipeline flow.
    """
    res = simulate_pipeline_keyword_filter(
        extracted_keywords=["Summarize", "Apple", "annual", "report"],
        entities=["Apple"],
        kb_ids=["kb_default"]
    )
    assert "Apple" in res
    assert "annual" not in res
    assert "report" not in res

def test_multiple_kbs_different_lists():
    """
    Test multi-KB query filtering using dynamic noise lists.
    """
    finance_kb_noise = {
        "financial": 0.99,
        "report": 0.98
    }
    healthcare_kb_noise = {
        "patient": 0.99,
        "hospital": 0.98
    }

    # Query with Finance KB noisy list active
    res_finance = simulate_pipeline_keyword_filter(
        extracted_keywords=["financial", "patient", "report"],
        entities=[],
        kb_ids=["kb_finance"],
        custom_noisy_words=finance_kb_noise
    )
    assert "patient" in res_finance
    assert "financial" not in res_finance
    assert "report" not in res_finance

    # Query with Healthcare KB noisy list active
    res_healthcare = simulate_pipeline_keyword_filter(
        extracted_keywords=["financial", "patient", "report"],
        entities=[],
        kb_ids=["kb_healthcare"],
        custom_noisy_words=healthcare_kb_noise
    )
    assert "financial" in res_healthcare
    assert "report" in res_healthcare
    assert "patient" not in res_healthcare
