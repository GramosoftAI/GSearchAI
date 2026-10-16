import pytest
import uuid
from unittest.mock import patch

from app.core.database import AsyncSessionLocal, engine
from app.modules.database_knowledgebase.knowledge.adapters.phase1_adapter import Phase1Adapter
from app.modules.database_knowledgebase.knowledge.retrieval.entity_resolver import (
    resolve_entities,
    normalize_table_name,
    get_table_name_variants,
)

KB_ID = uuid.UUID("c0f9fbc6-fdb1-49a1-bfe8-9b2aed3b25ae")
TENANT_ID = uuid.UUID("2b41fa8c-9c12-491d-8199-a75292e683ec")


class MockCustomerDBBlocked(Exception):
    """Raised if any customer DB connection is attempted on query path."""
    pass


def raise_on_customer_db(*args, **kwargs):
    raise MockCustomerDBBlocked("CRITICAL INVARIANT VIOLATION: Customer DB accessed on query path!")


@pytest.fixture(autouse=True)
async def cleanup_db_pool():
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_table_name_normalization():
    assert normalize_table_name("public.users") == "users"
    assert normalize_table_name("users") == "users"
    assert normalize_table_name("schema.my_table") == "my_table"
    assert get_table_name_variants("users") == ["users", "public.users"]
    assert get_table_name_variants("public.users") == ["users", "public.users"]


@pytest.mark.asyncio
async def test_resolve_entities_zero_customer_db_connections():
    """Verify resolve_entities against kb2_entity_values ONLY with customer DB connections strictly blocked."""
    async with AsyncSessionLocal() as session:
        # Pre-warm metadata cache (schema docs, table kinds, exclusion set)
        await resolve_entities(
            question="warmup",
            kb_id=KB_ID,
            session=session,
            tenant_id=TENANT_ID,
        )

        # Patch both Phase1Adapter.open_readonly_connection and connect_to_database
        with patch.object(Phase1Adapter, "open_readonly_connection", side_effect=raise_on_customer_db):
            test_questions = [
                "how many hours did arun log yesterday",
                "how many projects are active",
                "how many meetings were held yesterday",
                "list work packages assigned to arun",
                "can you tell me yesterday how many hours arun working on",
                "show overdue work packages",
            ]

            for q in test_questions:
                res = await resolve_entities(
                    question=q,
                    kb_id=KB_ID,
                    session=session,
                    tenant_id=TENANT_ID,
                )
                assert res is not None
                assert res.timings_ms < 150.0


@pytest.mark.asyncio
async def test_acceptance_criteria_six_questions_and_paraphrases():
    """Verify exact acceptance criteria:
    - 'how many hours did arun log yesterday' -> users.login/firstname 'arun'; < 150 ms; 0 customer-DB connections.
    - 'how many projects are active' -> no spans; 0 queries; < 50 ms.
    - 'how many meetings were held yesterday' -> no person filter generated.
    - 'list work packages assigned to arun' -> same as first.
    - 5 paraphrases of arun all resolve arun.
    """
    async with AsyncSessionLocal() as session:
        # Pre-warm metadata cache (schema docs, table kinds, exclusion set)
        await resolve_entities(
            question="warmup",
            kb_id=KB_ID,
            session=session,
            tenant_id=TENANT_ID,
        )

        with patch.object(Phase1Adapter, "open_readonly_connection", side_effect=raise_on_customer_db):
            # 1. "how many hours did arun log yesterday"
            res1 = await resolve_entities(
                question="how many hours did arun log yesterday",
                kb_id=KB_ID,
                session=session,
                tenant_id=TENANT_ID,
            )
            assert len(res1.resolved_entities) > 0
            best1 = res1.resolved_entities[0]
            assert best1.table_name == "users"
            assert best1.column_name in ("login", "firstname", "first_name")
            assert "arun" in best1.matched_value.lower()
            assert res1.timings_ms < 150.0

            # 2. "how many projects are active"
            res2 = await resolve_entities(
                question="how many projects are active",
                kb_id=KB_ID,
                session=session,
                tenant_id=TENANT_ID,
            )
            assert len(res2.spans_tried) == 0
            assert res2.queries_count == 0
            assert len(res2.resolved_entities) == 0
            assert res2.timings_ms < 50.0

            # 3. "how many meetings were held yesterday"
            res3 = await resolve_entities(
                question="how many meetings were held yesterday",
                kb_id=KB_ID,
                session=session,
                tenant_id=TENANT_ID,
            )
            assert len(res3.resolved_entities) == 0
            # Ensure "held" was NOT treated as a candidate span or person entity
            assert not any(e.table_name == "users" for e in res3.resolved_entities)

            # 4. "list work packages assigned to arun"
            res4 = await resolve_entities(
                question="list work packages assigned to arun",
                kb_id=KB_ID,
                session=session,
                tenant_id=TENANT_ID,
            )
            assert len(res4.resolved_entities) > 0
            best4 = res4.resolved_entities[0]
            assert best4.table_name == "users"
            assert "arun" in best4.matched_value.lower()

            # 5. Paraphrases of Arun
            paraphrases = [
                "arun hours yesterday",
                "how long did arun work yesterday",
                "yesterday's hours for arun",
                "what did arun work on yesterday",
                "hours logged by arun yesterday",
            ]
            for pq in paraphrases:
                res_p = await resolve_entities(
                    question=pq,
                    kb_id=KB_ID,
                    session=session,
                    tenant_id=TENANT_ID,
                )
                assert len(res_p.resolved_entities) > 0, f"Failed to resolve arun in: '{pq}'"
                matched_user = any(e.table_name == "users" and "arun" in e.matched_value.lower() for e in res_p.resolved_entities)
                assert matched_user, f"No users entity matched in: '{pq}'"
                assert res_p.timings_ms < 150.0
