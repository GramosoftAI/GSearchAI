import pytest
from app.modules.database_knowledgebase.knowledge.retrieval.entity_resolver import (
    extract_candidate_spans,
    GENERIC_STOP_WORDS,
    LABEL_COLUMN_PRIORITY,
)

def test_extract_candidate_spans_for_progress_of_vishnu():
    question = "what is yesterday progress of vishnu"
    spans = extract_candidate_spans(question, set())
    # 'progress', 'yesterday', 'what', 'is', 'of' must not be in candidate spans
    assert "progress" not in spans
    assert "yesterday" not in spans
    assert spans == ["vishnu"]

def test_extract_candidate_spans_for_other_domain_action_terms():
    for q, expected in [
        ("what is yesterday progress of arun", ["arun"]),
        ("show latest updates of vishnu", ["vishnu"]),
        ("what tasks did vishnu work on yesterday", ["vishnu"]),
        ("give me activity report of vishnu", ["vishnu"]),
    ]:
        spans = extract_candidate_spans(q, set())
        assert expected[0] in spans
        assert "progress" not in spans
        assert "updates" not in spans
        assert "tasks" not in spans
        assert "activity" not in spans
        assert "report" not in spans

def test_generic_stop_words_contain_domain_keywords():
    keywords = [
        "progress", "update", "updates", "task", "tasks",
        "activity", "activities", "ticket", "tickets", "issue", "issues",
        "report", "reports", "detail", "details", "overview", "summary",
    ]
    for kw in keywords:
        assert kw in GENERIC_STOP_WORDS, f"Keyword '{kw}' missing from GENERIC_STOP_WORDS"
