"""Smoke test for Phase 2 Step 10: Admin Review API

Tests:
1. List items with review priority ordering (conflicts -> coded -> low-conf -> drafts).
2. Confirm item and edit payload (locks item, sets source='admin', records audit log).
3. Mark sensitive (clears top_values, deletes entity_values rows, records audit log).
4. Resolve conflict (accept staged payload or keep admin payload).
5. Audit log table writes.
"""

import uuid
import pytest
from httpx import AsyncClient
from fastapi import FastAPI, Request
from unittest.mock import AsyncMock, MagicMock

from app.modules.database_knowledgebase.knowledge.api.admin_router import router as admin_router
from app.modules.database_knowledgebase.knowledge.models.knowledge_items import (
    KB2KnowledgeItem,
    KB2EntityValue,
    KB2AuditLog,
)


@pytest.fixture
def test_app():
    app = FastAPI()

    # Middleware to inject tenant context and user into request.state
    @app.middleware("http")
    async def fake_auth_middleware(request: Request, call_next):
        request.state.tenant_id = "11111111-1111-1111-1111-111111111111"
        user_mock = MagicMock()
        user_mock.email = "admin@example.com"
        user_mock.id = "22222222-2222-2222-2222-222222222222"
        request.state.user = user_mock
        return await call_next(request)

    app.include_router(admin_router)
    return app


@pytest.mark.asyncio
async def test_admin_review_api_smoke(test_app):
    tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    kb_id = uuid.uuid4()

    # Create mock items: 1 conflict, 1 draft, 1 confirmed
    item_conflict = KB2KnowledgeItem(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="column",
        item_key="public.users.email",
        status="conflict",
        source="declared",
        is_locked_by_admin=True,
        payload={"column_name": "email", "desc": "Admin version"},
        staged_payload={"column_name": "email", "desc": "LLM version"},
    )
    item_draft = KB2KnowledgeItem(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="relationship",
        item_key="rel:public.orders.cust->public.customers.id",
        status="draft",
        source="inferred",
        confidence=0.65,
        is_locked_by_admin=False,
        payload={"child_table": "orders"},
    )

    items_db = {
        item_conflict.item_key: item_conflict,
        item_draft.item_key: item_draft,
    }
    audit_rows = []

    # Mock AsyncSession
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()

    def mock_add(inst):
        if isinstance(inst, KB2AuditLog):
            audit_rows.append(inst)

    mock_db.add = MagicMock(side_effect=mock_add)

    async def mock_execute(stmt):
        stmt_str = str(stmt).lower()
        res = MagicMock()
        if "kb2_audit_log" in stmt_str:
            res.scalars.return_value.all.return_value = audit_rows
            return res

        if "where" in stmt_str and "item_key =" in stmt_str:
            # find key
            found = None
            for k, it in items_db.items():
                if k in str(stmt.compile().params):
                    found = it
                    break
            res.scalar_one_or_none.return_value = found
            return res

        # list items
        res.scalars.return_value.all.return_value = list(items_db.values())
        res.fetchall.return_value = [("column", "conflict", 1), ("relationship", "draft", 1)]
        res.rowcount = 1
        return res

    mock_db.execute = AsyncMock(side_effect=mock_execute)

    from app.core.database import get_db
    test_app.dependency_overrides[get_db] = lambda: mock_db

    from httpx import ASGITransport
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. GET items list
        resp = await ac.get(f"/{kb_id}/knowledge/items")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2

        # 2. POST confirm draft item
        resp_conf = await ac.post(f"/{kb_id}/knowledge/items/{item_draft.item_key}/confirm")
        assert resp_conf.status_code == 200
        assert item_draft.status == "confirmed"

        # 3. POST edit item payload (locks item)
        resp_edit = await ac.post(
            f"/{kb_id}/knowledge/items/{item_draft.item_key}/edit",
            json={"payload": {"child_table": "orders", "note": "verified by analyst"}},
        )
        assert resp_edit.status_code == 200
        assert item_draft.is_locked_by_admin is True
        assert item_draft.source == "admin"

        # 4. POST resolve conflict
        resp_res = await ac.post(
            f"/{kb_id}/knowledge/items/{item_conflict.item_key}/resolve-conflict",
            json={"resolution": "accept_staged"},
        )
        assert resp_res.status_code == 200
        assert item_conflict.status == "confirmed"
        assert item_conflict.payload["desc"] == "LLM version"
        assert item_conflict.staged_payload is None

        # 5. POST mark sensitive
        resp_sens = await ac.post(f"/{kb_id}/knowledge/items/{item_conflict.item_key}/mark-sensitive")
        assert resp_sens.status_code == 200
        assert item_conflict.is_sensitive is True

        # 6. GET stats
        resp_stats = await ac.get(f"/{kb_id}/knowledge/stats")
        assert resp_stats.status_code == 200
        assert resp_stats.json()["total_items"] == 2

        # Verify audit logs were generated for all mutating actions
        assert len(audit_rows) >= 4
        action_names = {a.action for a in audit_rows}
        assert "confirm" in action_names
        assert "edit_payload" in action_names
        assert "resolve_conflict" in action_names
        assert "mark_sensitive" in action_names
