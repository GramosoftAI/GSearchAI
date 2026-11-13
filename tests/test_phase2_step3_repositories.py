"""Test Phase 2 Step 3: Repositories and Multi-Layer Sensitivity Defense.

Validates:
1. Tenant isolation per repository (KnowledgeItemRepository, EntityValueRepository, QueryMemoryRepository).
2. Admin-lock preservation & conflict staging on KnowledgeItemRepository.
3. Source rule: declared -> confirmed; llm/inferred -> draft.
4. Multi-layer sensitive column rejection:
   a. ORM @validates layer
   b. Repository bulk_upsert layer
   c. Database trigger layer (raw SQL / bypass attempt)
5. EntityValueRepository search:
   a. Exact match
   b. Fuzzy match (pg_trgm) finds slightly misspelled names
   c. FTS match (tsvector)
6. QueryMemoryRepository invalidation by referenced_items (array overlap operator).
"""

import os
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.modules.database_knowledgebase.knowledge.models import (
    KB2KnowledgeItem,
    KB2EntityValue,
    KB2QueryMemory,
)
from app.modules.database_knowledgebase.knowledge.repositories import (
    KnowledgeItemRepository,
    EntityValueRepository,
    QueryMemoryRepository,
)

TEST_ASYNC_DB_URL = "postgresql+asyncpg://graphmind:graphmind_password@127.0.0.1:5433/test_throwaway_kb2"


@pytest.fixture
async def async_session():
    engine = create_async_engine(TEST_ASYNC_DB_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seeded_context(async_session):
    """Seed tenant, user, and KB in throwaway DB."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    kb_a = uuid.uuid4()
    kb_b = uuid.uuid4()
    user_id = uuid.uuid4()

    name_a = f"Ten A {uuid.uuid4().hex[:6]}"
    name_b = f"Ten B {uuid.uuid4().hex[:6]}"
    await async_session.execute(
        text("INSERT INTO tenants (id, name, slug, is_active) VALUES (:t_a, :n_a, :slug_a, true), (:t_b, :n_b, :slug_b, true);"),
        {"t_a": tenant_a, "n_a": name_a, "slug_a": f"a-{uuid.uuid4().hex[:6]}", "t_b": tenant_b, "n_b": name_b, "slug_b": f"b-{uuid.uuid4().hex[:6]}"},
    )
    await async_session.execute(
        text("INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) "
             "VALUES (:u, :e, 'hash', 'U', :t_a, true, true);"),
        {"u": user_id, "e": f"u_{uuid.uuid4().hex[:6]}@test.com", "t_a": tenant_a},
    )
    await async_session.execute(
        text("""
            INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, is_active)
            VALUES (:kb_a, :t_a, :u, 'KB A', 'postgresql', 'dummy_enc', 'configured', true),
                   (:kb_b, :t_b, :u, 'KB B', 'postgresql', 'dummy_enc', 'configured', true);
        """),
        {"kb_a": kb_a, "t_a": tenant_a, "kb_b": kb_b, "t_b": tenant_b, "u": user_id},
    )
    await async_session.commit()

    yield {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "kb_a": kb_a,
        "kb_b": kb_b,
    }

    # Cleanup
    await async_session.execute(text("DELETE FROM tenants WHERE id IN (:t_a, :t_b);"), {"t_a": tenant_a, "t_b": tenant_b})
    await async_session.commit()


@pytest.mark.asyncio
async def test_knowledge_item_admin_lock_and_source_rules(async_session, seeded_context):
    """Test KnowledgeItemRepository admin-lock payload preservation, conflict staging, and source rules."""
    ctx = seeded_context
    repo = KnowledgeItemRepository(db=async_session, tenant_id=ctx["tenant_a"])

    # 1. Source='declared' creates with confirmed status
    item1 = await repo.upsert_item(
        db_knowledgebase_id=ctx["kb_a"],
        item_type="table",
        item_key="public.orders",
        valid_from_version="v1",
        object_hash="hash_orders_v1",
        source="declared",
        payload={"description": "Orders master table"},
    )
    await async_session.commit()
    assert item1.status == "confirmed"

    # 2. Source='llm' is forced to draft even if requested as confirmed
    item2 = await repo.upsert_item(
        db_knowledgebase_id=ctx["kb_a"],
        item_type="column",
        item_key="public.orders.total",
        valid_from_version="v1",
        object_hash="hash_col_v1",
        source="llm",
        status="confirmed",
        payload={"description": "LLM generated description"},
    )
    await async_session.commit()
    assert item2.status == "draft"

    # 3. Admin lock rule: lock item1
    item1.is_locked_by_admin = True
    await async_session.commit()

    # Attempt to upsert item1 with different object_hash
    updated_item1 = await repo.upsert_item(
        db_knowledgebase_id=ctx["kb_a"],
        item_type="table",
        item_key="public.orders",
        valid_from_version="v2",
        object_hash="hash_orders_v2_DIFFERENT",
        source="inferred",
        payload={"description": "Incoming changed payload"},
    )
    await async_session.commit()

    # Verify admin lock was preserved: original payload unchanged, incoming placed in staged_payload, status='conflict'
    assert updated_item1.is_locked_by_admin is True
    assert updated_item1.payload == {"description": "Orders master table"}
    assert updated_item1.staged_payload == {"description": "Incoming changed payload"}
    assert updated_item1.status == "conflict"


@pytest.mark.asyncio
async def test_sensitive_column_multi_layer_defense(async_session, seeded_context):
    """Test 3 layers of defense rejecting sensitive column names:
    Layer 1: ORM @validates
    Layer 2: Repository bulk_upsert_values pre-check
    Layer 3: PostgreSQL Database Trigger on raw SQL insert
    """
    ctx = seeded_context
    repo = EntityValueRepository(db=async_session, tenant_id=ctx["tenant_a"])

    # Layer 1: ORM model instantiation fails
    with pytest.raises(ValueError, match="identified as sensitive"):
        KB2EntityValue(
            tenant_id=ctx["tenant_a"],
            db_knowledgebase_id=ctx["kb_a"],
            table_name="users",
            column_name="user_password_hash",
            raw_value="raw",
            normalized_value="norm",
        )

    # Layer 2: Repository bulk_upsert_values pre-check catches sensitive column
    bulk_data = [
        {"table_name": "orders", "column_name": "order_status", "raw_value": "SHIPPED", "normalized_value": "shipped"},
        {"table_name": "users", "column_name": "account_api_key", "raw_value": "secret", "normalized_value": "secret"},
    ]
    with pytest.raises(ValueError, match="account_api_key"):
        await repo.bulk_upsert_values(db_knowledgebase_id=ctx["kb_a"], values=bulk_data)

    # Layer 3: Direct RAW SQL insert attempting to bypass ORM & Repository is blocked by DB trigger
    raw_insert_sql = text("""
        INSERT INTO kb2_entity_values (
            id, tenant_id, db_knowledgebase_id, table_name, column_name, raw_value, normalized_value
        ) VALUES (
            gen_random_uuid(), :t, :kb, 'employees', 'employee_salary', '100000', '100000'
        );
    """)
    with pytest.raises(Exception, match=r"contains sensitive token|CheckViolationError|sensitive"):
        try:
            await async_session.execute(raw_insert_sql, {"t": ctx["tenant_a"], "kb": ctx["kb_a"]})
        finally:
            await async_session.rollback()


@pytest.mark.asyncio
async def test_entity_value_repository_search_and_fuzzy(async_session, seeded_context):
    """Test EntityValueRepository bulk_upsert, exact lookup, and fuzzy search on misspelled term."""
    ctx = seeded_context
    repo = EntityValueRepository(db=async_session, tenant_id=ctx["tenant_a"])

    # Bulk insert valid values
    values = [
        {"table_name": "products", "column_name": "category", "raw_value": "Electronics", "normalized_value": "electronics", "frequency_count": 10},
        {"table_name": "products", "column_name": "category", "raw_value": "Furniture", "normalized_value": "furniture", "frequency_count": 5},
        {"table_name": "products", "column_name": "category", "raw_value": "Stationery", "normalized_value": "stationery", "frequency_count": 2},
    ]
    inserted = await repo.bulk_upsert_values(db_knowledgebase_id=ctx["kb_a"], values=values)
    await async_session.commit()
    assert inserted >= 3

    # Exact search
    exact = await repo.search_exact(db_knowledgebase_id=ctx["kb_a"], table_name="products", column_name="category", value="electronics")
    assert exact is not None
    assert exact.raw_value == "Electronics"

    # Fuzzy search with slight misspelling ("electrnic" instead of "electronics")
    fuzzy_matches = await repo.search_fuzzy(
        db_knowledgebase_id=ctx["kb_a"],
        query_text="electrnic",
        min_similarity=0.4,
    )
    assert len(fuzzy_matches) > 0
    best_match = fuzzy_matches[0]
    assert best_match["normalized_value"] == "electronics"
    assert best_match["similarity"] > 0.4

    # Full-text search
    fts_matches = await repo.search_fts(db_knowledgebase_id=ctx["kb_a"], query_text="furniture")
    assert len(fts_matches) == 1
    assert fts_matches[0].normalized_value == "furniture"


@pytest.mark.asyncio
async def test_query_memory_invalidation_by_referenced_items(async_session, seeded_context):
    """Test QueryMemoryRepository persistence and invalidation via array overlap."""
    ctx = seeded_context
    repo = QueryMemoryRepository(db=async_session, tenant_id=ctx["tenant_a"])

    # 1. Save two verified queries
    q1 = await repo.save_verified(
        db_knowledgebase_id=ctx["kb_a"],
        schema_version="fp_v1",
        natural_query="List all customer orders",
        normalized_query="list all customer orders",
        compiled_sql="SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id",
        plan_ir={"intent": "orders"},
        referenced_items=["public.orders", "public.customers"],
    )

    q2 = await repo.save_verified(
        db_knowledgebase_id=ctx["kb_a"],
        schema_version="fp_v1",
        natural_query="Count total products",
        normalized_query="count total products",
        compiled_sql="SELECT count(*) FROM products",
        plan_ir={"intent": "products"},
        referenced_items=["public.products"],
    )
    await async_session.commit()

    assert q1.status == "verified"
    assert q2.status == "verified"

    # 2. Invalidate when "public.orders" is modified/dropped
    invalidated_count = await repo.invalidate_by_referenced_items(
        db_knowledgebase_id=ctx["kb_a"],
        item_keys=["public.orders"],
    )
    await async_session.commit()

    assert invalidated_count == 1

    # Verify q1 is deprecated, while q2 remains verified
    q1_reloaded = await repo.find_by_normalized_query(
        db_knowledgebase_id=ctx["kb_a"],
        schema_version="fp_v1",
        normalized_query="list all customer orders",
        status="deprecated",
    )
    assert q1_reloaded is not None
    assert q1_reloaded.status == "deprecated"

    q2_reloaded = await repo.find_by_normalized_query(
        db_knowledgebase_id=ctx["kb_a"],
        schema_version="fp_v1",
        normalized_query="count total products",
        status="verified",
    )
    assert q2_reloaded is not None
    assert q2_reloaded.status == "verified"


@pytest.mark.asyncio
async def test_repository_tenant_isolation(async_session, seeded_context):
    """Test that all three repositories strictly isolate Tenant A from Tenant B."""
    ctx = seeded_context
    repo_a_ki = KnowledgeItemRepository(db=async_session, tenant_id=ctx["tenant_a"])
    repo_b_ki = KnowledgeItemRepository(db=async_session, tenant_id=ctx["tenant_b"])

    repo_a_ev = EntityValueRepository(db=async_session, tenant_id=ctx["tenant_a"])
    repo_b_ev = EntityValueRepository(db=async_session, tenant_id=ctx["tenant_b"])

    repo_a_qm = QueryMemoryRepository(db=async_session, tenant_id=ctx["tenant_a"])
    repo_b_qm = QueryMemoryRepository(db=async_session, tenant_id=ctx["tenant_b"])

    # 1. Seed Tenant A items
    await repo_a_ki.upsert_item(
        db_knowledgebase_id=ctx["kb_a"],
        item_type="table",
        item_key="public.alpha_only",
        valid_from_version="v1",
        object_hash="hash_a",
        source="declared",
        payload={},
    )
    await repo_a_ev.bulk_upsert_values(
        db_knowledgebase_id=ctx["kb_a"],
        values=[{"table_name": "t_a", "column_name": "status", "raw_value": "VAL_A", "normalized_value": "val_a"}],
    )
    await repo_a_qm.save_verified(
        db_knowledgebase_id=ctx["kb_a"],
        schema_version="v1",
        natural_query="Query A",
        normalized_query="query a",
        compiled_sql="SELECT 1",
        plan_ir={},
        referenced_items=["public.alpha_only"],
    )
    await async_session.commit()

    # 2. Tenant B repositories MUST see 0 records
    assert await repo_b_ki.get_item(db_knowledgebase_id=ctx["kb_a"], item_type="table", item_key="public.alpha_only") is None
    assert len(await repo_b_ki.list_items(db_knowledgebase_id=ctx["kb_a"])) == 0

    assert await repo_b_ev.search_exact(db_knowledgebase_id=ctx["kb_a"], table_name="t_a", column_name="status", value="val_a") is None
    assert len(await repo_b_ev.search_fuzzy(db_knowledgebase_id=ctx["kb_a"], query_text="val_a")) == 0

    assert await repo_b_qm.find_by_normalized_query(db_knowledgebase_id=ctx["kb_a"], schema_version="v1", normalized_query="query a") is None


def test_sensitive_tokens_python_sql_parity():
    """Verify that Python sensitive-token list and PostgreSQL SQL trigger tokens list are identical."""
    import re
    from app.modules.database_knowledgebase.knowledge.sensitivity import SENSITIVE_TOKENS
    from migrations.versions.f6a7b8c9d0e1_update_sensitive_tokens_trigger import SENSITIVE_TOKENS_SQL

    # Extract all single-quoted tokens from SENSITIVE_TOKENS_SQL
    sql_tokens = set(re.findall(r"'([a-zA-Z0-9]+)'", SENSITIVE_TOKENS_SQL))

    assert sql_tokens == SENSITIVE_TOKENS, (
        f"Parity mismatch between Python and SQL sensitive tokens!\n"
        f"In SQL but not in Python: {sql_tokens - SENSITIVE_TOKENS}\n"
        f"In Python but not in SQL: {SENSITIVE_TOKENS - sql_tokens}"
    )


@pytest.mark.asyncio
async def test_knowledge_item_lifecycle_transitions(async_session, seeded_context):
    """Test lifecycle status rules:
    - A 'rejected' item stays rejected after re-enrichment.
    - An unlocked 'confirmed' item whose object_hash changes goes back to 'draft'.
    """
    ctx = seeded_context
    repo = KnowledgeItemRepository(db=async_session, tenant_id=ctx["tenant_a"])

    # 1. Rejected item stays rejected
    item_rej = await repo.upsert_item(
        db_knowledgebase_id=ctx["kb_a"],
        item_type="table",
        item_key="public.rejected_table",
        valid_from_version="v1",
        object_hash="hash_orig",
        source="declared",
        status="rejected",
        payload={"note": "User rejected this table"},
    )
    # Explicitly set status to rejected (e.g. user rejected it in UI)
    item_rej.status = "rejected"
    await async_session.commit()
    assert item_rej.status == "rejected"

    # Re-enrich with LLM / newer version
    re_enriched = await repo.upsert_item(
        db_knowledgebase_id=ctx["kb_a"],
        item_type="table",
        item_key="public.rejected_table",
        valid_from_version="v2",
        object_hash="hash_new_v2",
        source="llm",
        payload={"note": "LLM tries to re-enrich"},
    )
    await async_session.commit()
    assert re_enriched.status == "rejected"
    assert re_enriched.valid_from_version == "v2"

    # 2. Unlocked 'confirmed' item whose object_hash changes goes back to 'draft'
    item_conf = await repo.upsert_item(
        db_knowledgebase_id=ctx["kb_a"],
        item_type="table",
        item_key="public.confirmed_table",
        valid_from_version="v1",
        object_hash="hash_conf_v1",
        source="declared",
        payload={"title": "Original Confirmed Title"},
    )
    await async_session.commit()
    assert item_conf.status == "confirmed"
    assert item_conf.is_locked_by_admin is False

    # Schema changes -> object_hash changes
    updated_conf = await repo.upsert_item(
        db_knowledgebase_id=ctx["kb_a"],
        item_type="table",
        item_key="public.confirmed_table",
        valid_from_version="v2",
        object_hash="hash_conf_v2_CHANGED",
        source="inferred",
        payload={"title": "Updated Title After DDL Change"},
    )
    await async_session.commit()
    assert updated_conf.status == "draft"
    assert updated_conf.object_hash == "hash_conf_v2_CHANGED"


@pytest.mark.asyncio
async def test_knowledge_item_parallel_concurrent_upserts(seeded_context):
    """Test atomic concurrency: parallel upserts of the same key in separate DB sessions."""
    import asyncio
    ctx = seeded_context
    engine = create_async_engine(TEST_ASYNC_DB_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def concurrent_upsert_worker(worker_id: int):
        async with session_factory() as session:
            repo = KnowledgeItemRepository(db=session, tenant_id=ctx["tenant_a"])
            item = await repo.upsert_item(
                db_knowledgebase_id=ctx["kb_a"],
                item_type="table",
                item_key="public.concurrent_contention",
                valid_from_version=f"v_{worker_id}",
                object_hash=f"hash_{worker_id}",
                source="declared" if worker_id == 0 else "inferred",
                payload={"worker": worker_id},
            )
            await session.commit()
            return item.valid_from_version

    # Launch 6 concurrent upserts targeting the exact same key
    results = await asyncio.gather(
        *[concurrent_upsert_worker(i) for i in range(6)],
        return_exceptions=False,
    )
    assert len(results) == 6

    # Verify single record exists in DB without duplicates or unique constraint violations
    async with session_factory() as verify_session:
        repo = KnowledgeItemRepository(db=verify_session, tenant_id=ctx["tenant_a"])
        final_item = await repo.get_item(
            db_knowledgebase_id=ctx["kb_a"],
            item_type="table",
            item_key="public.concurrent_contention",
        )
        assert final_item is not None
        assert final_item.item_key == "public.concurrent_contention"

    await engine.dispose()

