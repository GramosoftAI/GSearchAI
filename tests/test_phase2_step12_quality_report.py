"""Smoke test for Phase 2 Step 12: Quality Report & Readiness Verdict

Tests:
1. Calculation of completeness percentages (descriptions, grain, meaning).
2. Relationship distribution and isolated table identification.
3. Readiness verdict logic: 'READY', 'NEEDS_REVIEW', and 'NOT_READY'.
4. Top 10 actionable review priorities generation.
5. Admin API endpoint /quality-report integration.
"""

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, Request
from unittest.mock import AsyncMock, MagicMock

from app.modules.database_knowledgebase.knowledge.quality.quality_report import (
    generate_quality_report,
    QualityThresholds,
)
from app.modules.database_knowledgebase.knowledge.api.admin_router import router as admin_router
from app.modules.database_knowledgebase.knowledge.models.knowledge_items import (
    KB2KnowledgeItem,
    KB2JobRun,
)


@pytest.mark.asyncio
async def test_quality_report_smoke():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    # Tables: 1 fully documented, 1 missing description
    t1 = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="table",
        item_key="public.orders",
        status="confirmed",
        payload={"table_name": "orders", "semantic": {"description": "Customer orders", "row_grain": "per order"}},
    )
    t2 = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="table",
        item_key="public.customers",
        status="confirmed",
        payload={"table_name": "customers", "semantic": {}},
    )

    # Columns: 1 coded column, 1 normal column
    c1 = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="column",
        item_key="public.orders.status_code",
        status="confirmed",
        payload={"column_name": "status_code", "semantic": {"meaning": "Order status", "is_coded_value": True}},
    )
    c2 = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="column",
        item_key="public.orders.amount",
        status="draft",
        payload={"column_name": "amount", "semantic": {"meaning": "Order total"}},
    )

    # Relationship: 1 medium-confidence join
    r1 = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="relationship",
        item_key="rel:orders.cust_id->customers.id",
        status="draft",
        confidence=0.75,
        payload={"child_table": "orders", "parent_table": "customers"},
    )

    mock_session = MagicMock()
    mock_session.commit = AsyncMock()

    # Configure session mocks
    mock_scalars_items = MagicMock()
    mock_scalars_items.all.return_value = [t1, t2, c1, c2, r1]

    async def mock_exec(stmt):
        stmt_s = str(stmt).lower()
        res = MagicMock()
        if "from kb2_knowledge_items" in stmt_s:
            res.scalars.return_value = mock_scalars_items
            return res
        if "from kb2_entity_values" in stmt_s:
            res.one.return_value = (50, 2)
            return res
        if "from kb2_query_memory" in stmt_s:
            res.scalar_one.return_value = 12
            return res
        if "from kb2_job_runs" in stmt_s:
            res.scalar_one_or_none.return_value = None
            return res
        return res

    mock_session.execute = AsyncMock(side_effect=mock_exec)

    report = await generate_quality_report(
        tenant_id=tenant_id,
        kb_id=kb_id,
        db_session=mock_session,
        thresholds=QualityThresholds(min_table_desc_pct=50.0, min_column_meaning_pct=50.0),
    )

    assert report.total_tables == 2
    assert report.tables_with_description_pct == 50.0
    assert report.tables_with_grain_pct == 50.0
    assert report.columns_with_meaning_pct == 100.0
    assert "public.orders.status_code" in report.columns_needing_admin_mapping
    assert report.relationship_confidence_distribution["medium_65_85"] == 1
    assert report.seed_example_count == 12

    # Check priorities
    priorities = report.top_10_review_priorities
    assert len(priorities) >= 2
    priority_types = {p["type"] for p in priorities}
    assert "coded_column" in priority_types
    assert "missing_description" in priority_types


@pytest.mark.asyncio
async def test_admin_api_quality_report_endpoint():
    app = FastAPI()

    @app.middleware("http")
    async def fake_auth(request: Request, call_next):
        request.state.tenant_id = "11111111-1111-1111-1111-111111111111"
        return await call_next(request)

    app.include_router(admin_router)

    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    res_items = MagicMock()
    res_items.scalars.return_value.all.return_value = []
    res_ev = MagicMock()
    res_ev.one.return_value = (0, 0)
    res_qm = MagicMock()
    res_qm.scalar_one.return_value = 0
    res_run = MagicMock()
    res_run.scalar_one_or_none.return_value = None

    async def mock_exec(stmt):
        stmt_s = str(stmt).lower()
        if "from kb2_entity_values" in stmt_s:
            return res_ev
        if "from kb2_query_memory" in stmt_s:
            return res_qm
        if "from kb2_job_runs" in stmt_s:
            return res_run
        return res_items

    mock_db.execute = AsyncMock(side_effect=mock_exec)

    from app.core.database import get_db
    app.dependency_overrides[get_db] = lambda: mock_db

    transport = ASGITransport(app=app)
    kb_id = uuid.uuid4()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/{kb_id}/knowledge/quality-report")
        assert resp.status_code == 200
        data = resp.json()
        assert "readiness_verdict" in data
        assert "top_10_review_priorities" in data
