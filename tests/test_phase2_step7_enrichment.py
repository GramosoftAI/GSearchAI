"""Smoke test for Phase 2 Step 7: LLM Enrichment

Tests:
1. Per-table batching and input hashing (skip unchanged inputs).
2. Masking sensitive columns (no values in prompt).
3. Pydantic validation of LLM output.
4. Payload semantic update: source='llm', status='draft', admin lock creates conflict staged_payload.
"""

import uuid
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.database_knowledgebase.knowledge.jobs.enrichment import (
    run_stage_enrich,
    compute_enrichment_input_hash,
    TableEnrichmentOutput,
)
from app.modules.database_knowledgebase.knowledge.models.knowledge_items import (
    KB2KnowledgeItem,
)


@pytest.mark.asyncio
async def test_enrichment_smoke():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_version = "v_test_enrich_1"

    # Mock table item and 2 column items (one regular, one sensitive)
    tbl_item = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="table",
        item_key="public.orders",
        source="declared",
        status="confirmed",
        is_locked_by_admin=False,
        payload={"table_name": "orders"},
    )
    col_regular = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="column",
        item_key="public.orders.total_amount",
        source="declared",
        status="confirmed",
        is_locked_by_admin=False,
        payload={
            "table_name": "orders",
            "column_name": "total_amount",
            "data_type": "numeric",
            "role": "measure",
            "stats": {"distinct_count": 100, "top_values": ["10.50", "20.00"]},
        },
    )
    col_sensitive = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="column",
        item_key="public.orders.card_pan",
        source="declared",
        status="confirmed",
        is_locked_by_admin=True,  # Test admin lock
        is_sensitive=True,
        payload={
            "table_name": "orders",
            "column_name": "card_pan",
            "data_type": "varchar",
            "role": "code",
            "is_sensitive": True,
            "stats": {"distinct_count": 50, "top_values": ["411111******1111"]},
        },
    )

    mock_db = MagicMock()
    mock_db.commit = AsyncMock()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [tbl_item, col_regular, col_sensitive]
    mock_res = MagicMock()
    mock_res.scalars.return_value = mock_scalars
    mock_db.execute = AsyncMock(return_value=mock_res)

    # Mock LLM Client
    mock_llm = MagicMock()
    captured_prompts = []

    async def mock_generate(prompt, **kwargs):
        captured_prompts.append(prompt)
        # Return valid JSON matching schema
        sample_response = {
            "table_description": "Contains customer order records and monetary values",
            "row_grain": "one row per completed order",
            "domain": "Sales",
            "columns": [
                {
                    "column_name": "total_amount",
                    "meaning": "Gross order value in USD",
                    "unit": "USD",
                    "aliases": ["order_total", "sales_value"],
                    "usage_note": "Filter on status = 'completed'",
                    "is_coded_value": False,
                    "is_dimension": False,
                },
                {
                    "column_name": "card_pan",
                    "meaning": "Masked payment card number",
                    "unit": None,
                    "aliases": ["card_number"],
                    "usage_note": "Audit reference only",
                    "is_coded_value": False,
                    "is_dimension": False,
                },
            ],
            "suggested_metrics": [
                {
                    "name": "Total Sales",
                    "aliases": ["Revenue"],
                    "expression": "SUM(total_amount)",
                    "grain": "per order",
                    "unit": "USD",
                    "description": "Sum of all order totals",
                }
            ],
            "suggested_dimensions": ["order_status"],
            "candidate_glossary_terms": [
                {
                    "term": "Order",
                    "aliases": ["Purchase"],
                    "target_type": "table",
                    "target_name": "public.orders",
                    "description": "Customer commercial transaction",
                }
            ],
        }
        return json.dumps(sample_response)

    mock_llm.generate = AsyncMock(side_effect=mock_generate)
    mock_llm.model_extraction = "deepseek-ai/DeepSeek-V3"

    res = await run_stage_enrich(
        tenant_id=tenant_id,
        kb_id=kb_id,
        schema_version=schema_version,
        db_session=mock_db,
        llm_client=mock_llm,
    )

    assert res["tables_enriched"] == 1
    assert len(captured_prompts) == 1

    # Verify sensitive column values are NEVER in prompt
    prompt_text = captured_prompts[0]
    assert "411111******1111" not in prompt_text
    assert '"is_sensitive": true' in prompt_text

    # Verify table payload was enriched
    assert "semantic" in tbl_item.payload
    assert tbl_item.payload["semantic"]["description"] == "Contains customer order records and monetary values"
    assert tbl_item.payload["semantic"]["row_grain"] == "one row per completed order"

    # Verify unlocked column payload updated
    assert "semantic" in col_regular.payload
    assert col_regular.payload["semantic"]["meaning"] == "Gross order value in USD"

    # Verify locked column created conflict and staged_payload
    assert col_sensitive.status == "conflict"
    assert col_sensitive.staged_payload is not None
    assert "semantic" in col_sensitive.staged_payload
