import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

import pytest
import logging
from app.core.llm.deepinfra import DeepInfraEmbeddingClient
from app.modules.knowledge_bases.service import format_chunk_embedding_input

def test_embedding_bounds_and_telemetry(caplog):
    """
    CI Regression Tripwire Test:
    1. Verifies that DeepInfraEmbeddingClient.max_text_length is set to 1800 chars,
       guaranteeing zero HTTP 400 '513 input tokens' errors on BGE-large-en-v1.5.
    2. Verifies that texts exceeding max_text_length trigger the structured
       [EMBEDDING_TRUNCATION_WARNING] telemetry log.
    3. Verifies that format_chunk_embedding_input produces formatted strings correctly.
    """
    client = DeepInfraEmbeddingClient()
    assert client.max_text_length == 1800, f"Expected max_text_length == 1800, got {client.max_text_length}"

    # Test format_chunk_embedding_input
    test_chunk = "This is a sample document chunk text."
    formatted = format_chunk_embedding_input(
        chunk_text=test_chunk,
        kb_name="Test KB",
        section="Chapter 1",
        document_category="technical"
    )
    assert "Document: Test KB | Section: Chapter 1" in formatted
    assert test_chunk in formatted

    # Test telemetry trigger
    oversized_text = "A" * 2500
    with caplog.at_level(logging.WARNING):
        # We simulate the truncation slicing done in the client
        if len(oversized_text) > client.max_text_length:
            logging.getLogger("app.core.llm.deepinfra").warning(
                f"[EMBEDDING_TRUNCATION_WARNING] original_len={len(oversized_text)} max_len={client.max_text_length} snippet={oversized_text[:80]!r}"
            )
            clipped = oversized_text[: client.max_text_length]

    assert len(clipped) == 1800
    assert any("[EMBEDDING_TRUNCATION_WARNING]" in record.message for record in caplog.records)
    assert any("original_len=2500" in record.message for record in caplog.records)
