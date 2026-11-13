"""Smoke test for Phase 2 Step 6: Distinct Value Indexer and ValueResolver

Tests:
1. Normalization (NFKC, lowercase, whitespace collapse, length truncate).
2. run_stage_value_index picks entity columns (name, enum, code) and skips sensitive columns.
3. Bulk upsert into EntityValueRepository with frequency_count and prune_unseen.
4. ValueResolver multi-strategy resolution (exact, fuzzy, fts) with ambiguity flag.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.database_knowledgebase.knowledge.jobs.value_indexer import (
    normalize_value,
    run_stage_value_index,
)
from app.modules.database_knowledgebase.knowledge.resolver.value_resolver import (
    ValueResolver,
    ResolvedCandidate,
)
from app.modules.database_knowledgebase.knowledge.models.knowledge_items import (
    KB2KnowledgeItem,
    KB2EntityValue,
)


def test_normalization():
    assert normalize_value("  Acme   Corp  ") == "acme corp"
    assert normalize_value("Café\u00A0Au   Lait") == "café au lait"


@pytest.mark.asyncio
async def test_value_index_and_resolver_smoke():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_version = "v_test_val_1"

    # 1. Mock DB Session returning 2 column items: one 'name' role, one sensitive 'password'
    item_name = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="column",
        item_key="public.departments.name",
        is_sensitive=False,
        payload={
            "table_name": "departments",
            "column_name": "department_name",
            "role": "name",
            "stats": {"distinct_count": 5},
        },
    )
    item_sensitive = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="column",
        item_key="public.users.card_cvv",
        is_sensitive=True,
        payload={
            "table_name": "users",
            "column_name": "card_cvv",
            "role": "code",
            "stats": {"distinct_count": 10},
        },
    )

    mock_db = MagicMock()
    mock_db.commit = AsyncMock()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [item_name, item_sensitive]
    mock_res = MagicMock()
    mock_res.scalars.return_value = mock_scalars
    mock_db.execute = AsyncMock(return_value=mock_res)

    # Mock customer DB connection yielding values
    mock_adapter = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[
        {"raw_val": "Engineering", "freq": 15},
        {"raw_val": "Human Resources", "freq": 8},
        {"raw_val": "Sales", "freq": 20},
    ])
    mock_adapter.open_readonly_connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_adapter.open_readonly_connection.return_value.__aexit__ = AsyncMock(return_value=None)

    # Run stage_value_index
    # We patch EntityValueRepository.bulk_upsert_values and prune_unseen
    captured_values = []
    async def mock_bulk_upsert(self, db_knowledgebase_id, values):
        captured_values.extend(values)
        return len(values)

    async def mock_prune(self, db_knowledgebase_id, before):
        return 0

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.modules.database_knowledgebase.knowledge.jobs.value_indexer.EntityValueRepository.bulk_upsert_values",
            mock_bulk_upsert,
        )
        mp.setattr(
            "app.modules.database_knowledgebase.knowledge.jobs.value_indexer.EntityValueRepository.prune_unseen",
            mock_prune,
        )
        # Avoid external API call in smoke test
        mp.setattr(
            "app.modules.database_knowledgebase.knowledge.jobs.value_indexer.EmbeddingGenerator.generate_embeddings_batch",
            AsyncMock(return_value=[[0.1] * 768, [0.2] * 768, [0.3] * 768]),
        )

        stage_res = await run_stage_value_index(
            tenant_id=tenant_id,
            kb_id=kb_id,
            schema_version=schema_version,
            adapter=mock_adapter,
            db_session=mock_db,
        )

    assert stage_res["candidate_columns_indexed"] == 1
    assert stage_res["values_indexed"] == 3
    assert len(captured_values) == 3
    # Check normalization and frequency
    val_map = {v["normalized_value"]: v for v in captured_values}
    assert "engineering" in val_map
    assert val_map["engineering"]["frequency_count"] == 15
    assert val_map["engineering"]["embedding"] is not None

    # 2. Test ValueResolver
    mock_repo = MagicMock()
    mock_repo.tenant_id = tenant_id

    # Mock exact search
    mock_repo.search_exact = AsyncMock(return_value=None)

    # Mock fuzzy search returning close candidates -> test ambiguity flag
    mock_repo.search_fuzzy = AsyncMock(return_value=[
        {
            "table_name": "departments",
            "column_name": "department_name",
            "raw_value": "Engineering",
            "normalized_value": "engineering",
            "frequency_count": 15,
            "similarity": 0.88,
        },
        {
            "table_name": "departments",
            "column_name": "department_name",
            "raw_value": "Engineer",
            "normalized_value": "engineer",
            "frequency_count": 2,
            "similarity": 0.86,
        },
    ])
    mock_repo.search_fts = AsyncMock(return_value=[])
    mock_repo.search_semantic = AsyncMock(return_value=[])

    resolver = ValueResolver(mock_repo)
    resolution = await resolver.resolve(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        text="enginering",
        ambiguity_threshold=0.05,
    )

    assert len(resolution.candidates) == 2
    assert resolution.best_match is not None
    assert resolution.best_match.raw_value == "Engineering"
    # Score difference is 0.88 - 0.86 = 0.02 <= 0.05 -> must be flagged ambiguous
    assert resolution.ambiguous is True
