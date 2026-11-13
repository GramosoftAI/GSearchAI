"""Smoke test for Phase 2 Step 8: Business Semantics (Metrics, Glossary, Rules)

Tests:
1. Metric SQL expression parsing and column validation via sqlglot.
2. Auto-seeding glossary and metrics as draft items.
3. Marking stale metrics/rules when dependencies are dropped.
4. GlossaryResolver matching ranked confirmed over draft.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.database_knowledgebase.knowledge.semantics.business_semantics import (
    validate_metric_expression,
    seed_suggested_glossary_and_metrics,
    mark_stale_business_semantics,
    GlossaryResolver,
)
from app.modules.database_knowledgebase.knowledge.models.knowledge_items import (
    KB2KnowledgeItem,
)


def test_metric_validation_with_sqlglot():
    avail_cols = {"at_work_second", "salary", "bonus", "order_id"}

    # Valid expression
    is_valid, deps, err = validate_metric_expression("at_work_second / 3600", avail_cols)
    assert is_valid is True
    assert "at_work_second" in deps
    assert err is None

    # Multi-column aggregation
    is_valid, deps, err = validate_metric_expression("SUM(salary + bonus)", avail_cols)
    assert is_valid is True
    assert set(deps) == {"salary", "bonus"}

    # Unknown column reference
    is_valid, deps, err = validate_metric_expression("SUM(non_existent_col * 2)", avail_cols)
    assert is_valid is False
    assert "non_existent_col" in err


@pytest.mark.asyncio
async def test_business_semantics_smoke():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_version = "v_test_semantics_1"

    # 1. Test auto-seeding
    seeded_items = []
    mock_repo = MagicMock()
    mock_repo.db = MagicMock()
    mock_repo.db.commit = AsyncMock()

    async def mock_upsert(**kwargs):
        seeded_items.append(kwargs)
        return kwargs

    mock_repo.upsert_item = AsyncMock(side_effect=mock_upsert)

    suggested_metrics = [
        {
            "name": "Work Hours",
            "aliases": ["Hours Worked"],
            "expression": "at_work_second / 3600",
            "grain": "per employee per day",
            "unit": "hours",
            "description": "Total work duration in hours",
        }
    ]
    candidate_glossary = [
        {
            "term": "FTE",
            "aliases": ["Full-Time Equivalent", "Full Time"],
            "target_type": "metric",
            "target_name": "metric:work_hours",
            "description": "Full-Time Employee hour equivalent",
        }
    ]
    existing_keys = {"public.attendance.at_work_second", "public.attendance.emp_id"}

    seed_res = await seed_suggested_glossary_and_metrics(
        tenant_id=tenant_id,
        kb_id=kb_id,
        schema_version=schema_version,
        item_repo=mock_repo,
        suggested_metrics=suggested_metrics,
        candidate_glossary=candidate_glossary,
        existing_column_keys=existing_keys,
    )

    assert seed_res["metrics_seeded"] == 1
    assert seed_res["glossary_seeded"] == 1
    assert len(seeded_items) == 2

    # Check metric
    metric_item = next(i for i in seeded_items if i["item_type"] == "metric")
    assert metric_item["status"] == "draft"
    assert "public.attendance.at_work_second" in metric_item["payload"]["depends_on"]

    # 2. Test Stale check when object dropped
    stale_metric = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="metric",
        item_key="metric:old_sales",
        status="confirmed",
        payload={"depends_on": ["public.orders.deprecated_col"]},
    )
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [stale_metric]
    mock_res = MagicMock()
    mock_res.scalars.return_value = mock_scalars
    mock_session.execute = AsyncMock(return_value=mock_res)

    stale_count = await mark_stale_business_semantics(
        tenant_id=tenant_id,
        kb_id=kb_id,
        db_session=mock_session,
        current_item_keys={"public.orders.id", "public.orders.total_amount"},  # deprecated_col dropped
    )
    assert stale_count == 1
    assert stale_metric.status == "stale"

    # 3. Test GlossaryResolver: confirmed matches ranked above draft
    g_draft = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="glossary",
        item_key="glossary:fte",
        status="draft",
        payload={"term": "FTE", "aliases": ["Full-Time"], "target": "metric", "target_key": "work_hours", "description": "Draft FTE"},
    )
    g_confirmed = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="glossary",
        item_key="glossary:fte_official",
        status="confirmed",
        payload={"term": "FTE", "aliases": ["Full-Time"], "target": "metric", "target_key": "official_fte", "description": "Confirmed FTE"},
    )

    mock_scalars_g = MagicMock()
    mock_scalars_g.all.return_value = [g_draft, g_confirmed]
    mock_res_g = MagicMock()
    mock_res_g.scalars.return_value = mock_scalars_g
    mock_session.execute = AsyncMock(return_value=mock_res_g)

    resolver = GlossaryResolver(db_session=mock_session, tenant_id=tenant_id)
    resolved = await resolver.resolve(db_knowledgebase_id=kb_id, terms=["fte", "full-time"])

    assert "fte" in resolved
    matches = resolved["fte"]
    assert len(matches) == 2
    # Confirmed must be top match
    assert matches[0].status == "confirmed"
    assert matches[0].target_key == "official_fte"
    assert matches[1].status == "draft"
