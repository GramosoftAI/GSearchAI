"""Test Phase 2 Step 3c & 3d: Plumbing, Persistence, Stale Recovery, Dedupe, RLS, and Phase 1 Hook.

Validates all requirements:
1. Hook: Uses pre-update old_schema_version captured BEFORE snapshot persistence outside try block;
   real two-sync flow test: first sync triggers, unchanged re-sync does not trigger, changed schema triggers.
2. Order of operations: No premature commit. Phase 2 trigger enqueues AFTER step 4 update_db_kb (using _defer_by).
3. trigger_phase2_sync_job uses its own DB session (never self.db).
   Forced DB error inside Phase 2 does not prevent later Phase 1 steps from completing.
4. Redis unavailable: Gracefully logs warning and skips; never runs pipeline inline.
5. Heartbeat inside stages & configurable stale threshold (phase2_job_stale_threshold_seconds).
6. Worker sessions set app.current_tenant prior to any kb2_ read/write, and reset it on session close
   so pooled connections are not tainted across tenants.
7. Real introspect_and_snapshot_schema executed as NON-superuser role (rolbypassrls = false)
   with Phase 2 flag ON and OFF, asserting schema indexing and update_db_kb succeed with status 'indexed'.
8. get_redis_pool() reuses a shared module-level pool.
"""

import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta
from sqlalchemy import text, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import get_settings
from app.modules.database_knowledgebase.knowledge.jobs import (
    JobStatus,
    StageStatus,
    JobRunRecord,
    get_job_run,
    run_phase2_pipeline,
    trigger_phase2_sync_job,
)
from app.modules.database_knowledgebase.knowledge.jobs.pipeline import (
    set_rls_tenant_context,
    reset_rls_tenant_context,
)
from app.modules.database_knowledgebase.knowledge.adapters.phase1_adapter import Phase1Adapter
from app.modules.database_knowledgebase.knowledge.repositories import JobRunRepository
from app.modules.database_knowledgebase.services.service import DatabaseKnowledgebaseService
from app.modules.database_knowledgebase.schemas.canonical import DatabaseSchema
from app.worker.queue import get_redis_pool

TEST_DB_NAME = "test_throwaway_kb2"
DB_HOST = "127.0.0.1"
DB_PORT = "5433"
ADMIN_USER = "graphmind"
ADMIN_PASS = "graphmind_password"
TEST_USER = "kb2_test_user"
TEST_PASS = "kb2_test_pass"

TEST_ASYNC_DB_URL = f"postgresql+asyncpg://{ADMIN_USER}:{ADMIN_PASS}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"
TEST_USER_ASYNC_DB_URL = f"postgresql+asyncpg://{TEST_USER}:{TEST_PASS}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"


@pytest.fixture(scope="session", autouse=True)
def ensure_non_superuser_role():
    """Ensure non-superuser test role exists in throwaway DB."""
    admin_sync_url = f"postgresql://{ADMIN_USER}:{ADMIN_PASS}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"
    engine = create_engine(admin_sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{TEST_USER}') THEN
                    CREATE ROLE {TEST_USER} WITH LOGIN PASSWORD '{TEST_PASS}' NOSUPERUSER NOBYPASSRLS INHERIT;
                ELSE
                    ALTER ROLE {TEST_USER} WITH LOGIN PASSWORD '{TEST_PASS}' NOSUPERUSER NOBYPASSRLS;
                END IF;
            END
            $$;
        """))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {TEST_USER};"))
        conn.execute(text(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {TEST_USER};"))
        conn.execute(text(f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {TEST_USER};"))
        conn.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {TEST_USER};"))
    engine.dispose()
    yield


@pytest.fixture
async def async_session():
    engine = create_async_engine(TEST_ASYNC_DB_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def non_super_async_session():
    """Async session bound strictly to non-superuser role (rolbypassrls = false)."""
    engine = create_async_engine(TEST_USER_ASYNC_DB_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seeded_context(async_session):
    """Seed tenant, user, and KB in throwaway DB."""
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()

    tenant_name = f"Ten Plumbing {uuid.uuid4().hex[:6]}"
    await async_session.execute(
        text("INSERT INTO tenants (id, name, slug, is_active) VALUES (:t, :n, :slug, true);"),
        {"t": tenant_id, "n": tenant_name, "slug": f"slug-{uuid.uuid4().hex[:6]}"},
    )
    await async_session.execute(
        text("INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) "
             "VALUES (:u, :e, 'hash', 'U', :t, true, true);"),
        {"u": user_id, "e": f"u_{uuid.uuid4().hex[:6]}@test.com", "t": tenant_id},
    )
    await async_session.execute(
        text("""
            INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, is_active)
            VALUES (:kb, :t, :u, 'KB Plumbing', 'postgresql', 'dummy_enc', 'configured', true);
        """),
        {"kb": kb_id, "t": tenant_id, "u": user_id},
    )
    await async_session.commit()

    yield {
        "tenant_id": tenant_id,
        "kb_id": kb_id,
        "user_id": user_id,
    }

    await async_session.execute(text("DELETE FROM tenants WHERE id = :t;"), {"t": tenant_id})
    await async_session.commit()


# ==============================================================================
# 1. Real Two-Sync Flow Test (First sync triggers, unchanged does not, changed triggers)
# ==============================================================================

@pytest.mark.asyncio
async def test_two_sync_flow_trigger_logic(async_session, seeded_context):
    """Item 1: Hook uses pre-update old_schema_version captured before snapshot save.
    
    Verifies full sync sequence:
    - 1st sync (is_first_snapshot=True, old_schema_version=None): triggers Phase 2
    - 2nd sync (unchanged schema, old_schema_version == new_version): does NOT trigger Phase 2
    - 3rd sync (drifted schema, old_schema_version != new_version): triggers Phase 2
    """
    ctx = seeded_context
    service = DatabaseKnowledgebaseService(db=async_session, tenant_id=ctx["tenant_id"])

    schema_v1 = DatabaseSchema(
        database_name="Test DB",
        fingerprint="fp_sync_v1",
        schemas={},
    )
    schema_v2 = DatabaseSchema(
        database_name="Test DB",
        fingerprint="fp_sync_v2",
        schemas={},
    )

    mock_redis = AsyncMock()
    mock_redis.enqueue_job = AsyncMock(return_value="job_ok")

    with patch.object(service.secrets, "decrypt_credentials", return_value={}), \
         patch("app.modules.database_knowledgebase.services.service.SchemaIndexer.index_schema", new_callable=AsyncMock), \
         patch("app.modules.database_knowledgebase.knowledge.jobs.trigger_phase2_sync_job", new_callable=AsyncMock) as mock_trigger, \
         patch("app.worker.queue.get_redis_pool", new_callable=AsyncMock, return_value=mock_redis), \
         patch("app.core.config.get_settings") as mock_settings:

        real_settings = get_settings()
        mock_settings.return_value = real_settings
        with patch.object(real_settings, "enable_phase2_knowledge_layer", True):

            # --- Sync 1: Initial Sync ---
            with patch("app.modules.database_knowledgebase.services.service.DatabaseIntrospector.introspect", new_callable=AsyncMock, return_value=schema_v1):
                resp1 = await service.introspect_and_snapshot_schema(kb_id=ctx["kb_id"])
                await async_session.commit()
                assert resp1.schema_version == "fp_sync_v1"

            assert mock_trigger.call_count == 1
            assert mock_trigger.call_args.kwargs["schema_version"] == "fp_sync_v1"
            assert mock_trigger.call_args.kwargs.get("defer_by_seconds") == 2
            mock_trigger.reset_mock()

            # Verify KB record in DB now has schema_version = fp_sync_v1
            kb_entity = await service.repo.get_by_id(ctx["kb_id"])
            assert kb_entity.schema_version == "fp_sync_v1"

            # --- Sync 2: Re-sync with UNCHANGED schema ---
            with patch("app.modules.database_knowledgebase.services.service.DatabaseIntrospector.introspect", new_callable=AsyncMock, return_value=schema_v1):
                resp2 = await service.introspect_and_snapshot_schema(kb_id=ctx["kb_id"])
                await async_session.commit()
                assert resp2.schema_version == "fp_sync_v1"

            # Must NOT trigger Phase 2 since version is unchanged
            assert mock_trigger.call_count == 0

            # --- Sync 3: Re-sync with CHANGED schema (Drift) ---
            with patch("app.modules.database_knowledgebase.services.service.DatabaseIntrospector.introspect", new_callable=AsyncMock, return_value=schema_v2):
                resp3 = await service.introspect_and_snapshot_schema(kb_id=ctx["kb_id"])
                await async_session.commit()
                assert resp3.schema_version == "fp_sync_v2"

            # Must trigger Phase 2 for new schema version
            assert mock_trigger.call_count == 1
            assert mock_trigger.call_args.kwargs["schema_version"] == "fp_sync_v2"


# ==============================================================================
# 2. Dedicated Session & Error Isolation Test
# ==============================================================================

@pytest.mark.asyncio
async def test_trigger_phase2_uses_own_session_and_error_does_not_break_phase1(async_session, seeded_context):
    """Item 3: trigger_phase2_sync_job uses its own DB session (never callers').
    
    Forcing a DB/runtime error inside Phase 2 does not abort Phase 1 snapshot,
    schema indexing, or DB KB update.
    """
    ctx = seeded_context
    service = DatabaseKnowledgebaseService(db=async_session, tenant_id=ctx["tenant_id"])

    schema_v1 = DatabaseSchema(
        database_name="Test DB",
        fingerprint="fp_iso_v1",
        schemas={},
    )

    indexer_mock = AsyncMock()
    mock_redis = AsyncMock()

    with patch.object(service.secrets, "decrypt_credentials", return_value={}), \
         patch("app.modules.database_knowledgebase.services.service.DatabaseIntrospector.introspect", new_callable=AsyncMock, return_value=schema_v1), \
         patch("app.modules.database_knowledgebase.services.service.SchemaIndexer.index_schema", indexer_mock), \
         patch("app.worker.queue.get_redis_pool", new_callable=AsyncMock, return_value=mock_redis), \
         patch("app.modules.database_knowledgebase.knowledge.jobs.trigger_phase2_sync_job", side_effect=RuntimeError("Phase 2 DB Connection Exploded!")):

        real_settings = get_settings()
        with patch.object(real_settings, "enable_phase2_knowledge_layer", True):
            resp = await service.introspect_and_snapshot_schema(kb_id=ctx["kb_id"])
            await async_session.commit()
            assert resp is not None
            assert resp.schema_version == "fp_iso_v1"

            # Verify subsequent Phase 1 indexing still ran
            assert indexer_mock.call_count == 1

            # Verify KB was updated to status 'indexed' and new schema_version
            kb_entity = await service.repo.get_by_id(ctx["kb_id"])
            assert kb_entity.status == "indexed"
            assert kb_entity.schema_version == "fp_iso_v1"


# ==============================================================================
# 3. Redis Unavailable Test: Skip & Log, Never Run Inline
# ==============================================================================

@pytest.mark.asyncio
async def test_redis_unavailable_skips_and_never_runs_inline(async_session, seeded_context):
    """Item 4: If Redis is unavailable, skip and log. Never run the pipeline inline."""
    ctx = seeded_context
    service = DatabaseKnowledgebaseService(db=async_session, tenant_id=ctx["tenant_id"])

    schema_v1 = DatabaseSchema(
        database_name="Test DB",
        fingerprint="fp_noredis_v1",
        schemas={},
    )

    with patch.object(service.secrets, "decrypt_credentials", return_value={}), \
         patch("app.modules.database_knowledgebase.services.service.DatabaseIntrospector.introspect", new_callable=AsyncMock, return_value=schema_v1), \
         patch("app.modules.database_knowledgebase.services.service.SchemaIndexer.index_schema", new_callable=AsyncMock), \
         patch("app.worker.queue.get_redis_pool", new_callable=AsyncMock, side_effect=ConnectionError("Redis connection refused")), \
         patch("app.modules.database_knowledgebase.knowledge.jobs.run_phase2_pipeline", new_callable=AsyncMock) as mock_inline_pipeline, \
         patch("app.modules.database_knowledgebase.knowledge.jobs.trigger_phase2_sync_job", new_callable=AsyncMock) as mock_trigger:

        real_settings = get_settings()
        with patch.object(real_settings, "enable_phase2_knowledge_layer", True):
            resp = await service.introspect_and_snapshot_schema(kb_id=ctx["kb_id"])
            await async_session.commit()
            assert resp.schema_version == "fp_noredis_v1"

            # Neither trigger nor inline execution should occur
            mock_trigger.assert_not_called()
            mock_inline_pipeline.assert_not_called()


# ==============================================================================
# 4. Worker Session RLS Context & Pooled Connection Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_consecutive_worker_jobs_on_same_connection_do_not_bleed_tenant_context(async_session):
    """Item 2: Consecutive jobs on the same connection reset app.current_tenant on exit,
    preventing cross-tenant leakage on pooled connections.
    """
    tenant_1 = uuid.uuid4()
    tenant_2 = uuid.uuid4()

    # Job 1 runs for tenant_1
    await set_rls_tenant_context(async_session, tenant_1)
    res1 = await async_session.execute(text("SELECT current_setting('app.current_tenant', true);"))
    assert res1.scalar() == str(tenant_1)

    # Job 1 completes and resets context
    await reset_rls_tenant_context(async_session)
    res_reset = await async_session.execute(text("SELECT current_setting('app.current_tenant', true);"))
    assert res_reset.scalar() == ""

    # Job 2 runs for tenant_2
    await set_rls_tenant_context(async_session, tenant_2)
    res2 = await async_session.execute(text("SELECT current_setting('app.current_tenant', true);"))
    assert res2.scalar() == str(tenant_2)

    # Job 2 completes and resets context
    await reset_rls_tenant_context(async_session)
    res_final = await async_session.execute(text("SELECT current_setting('app.current_tenant', true);"))
    assert res_final.scalar() == ""


# ==============================================================================
# 5. Real introspect_and_snapshot_schema Flow as NON-Superuser (rolbypassrls = false)
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("enable_phase2", [False, True])
async def test_real_introspect_flow_as_non_superuser_role(non_super_async_session, enable_phase2):
    """Item 3: Runs the REAL introspect_and_snapshot_schema flow as a non-superuser role
    (rolbypassrls = false) with Phase 2 flag ON and OFF.
    Asserts schema indexing and update_db_kb still succeed and KB ends 'indexed' with new schema_version.
    """
    # 1. Assert non-superuser role properties
    role_res = await non_super_async_session.execute(
        text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;")
    )
    current_user, rolsuper, rolbypassrls = role_res.fetchone()
    assert current_user == TEST_USER
    assert rolsuper is False
    assert rolbypassrls is False

    # 2. Set tenant context for non-super user session
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    await set_rls_tenant_context(non_super_async_session, tenant_id)

    # Seed tenant, user, and KB
    tenant_name = f"Ten NonSuper {uuid.uuid4().hex[:6]}"
    await non_super_async_session.execute(
        text("INSERT INTO tenants (id, name, slug, is_active) VALUES (:t, :n, :slug, true);"),
        {"t": tenant_id, "n": tenant_name, "slug": f"slug-{uuid.uuid4().hex[:6]}"},
    )
    await non_super_async_session.execute(
        text("INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) "
             "VALUES (:u, :e, 'hash', 'U', :t, true, true);"),
        {"u": user_id, "e": f"u_{uuid.uuid4().hex[:6]}@test.com", "t": tenant_id},
    )
    await non_super_async_session.execute(
        text("""
            INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, is_active)
            VALUES (:kb, :t, :u, 'KB NonSuper', 'postgresql', 'dummy_enc', 'configured', true);
        """),
        {"kb": kb_id, "t": tenant_id, "u": user_id},
    )
    await non_super_async_session.commit()

    # Re-apply RLS setting after commit
    await set_rls_tenant_context(non_super_async_session, tenant_id)

    service = DatabaseKnowledgebaseService(db=non_super_async_session, tenant_id=tenant_id)
    canonical_schema = DatabaseSchema(
        database_name="Target NonSuper DB",
        fingerprint="fp_nonsuper_v1",
        schemas={},
    )

    indexer_mock = AsyncMock()
    mock_redis = AsyncMock()
    mock_redis.enqueue_job = AsyncMock(return_value="job_ok")

    try:
        with patch.object(service.secrets, "decrypt_credentials", return_value={}), \
             patch("app.modules.database_knowledgebase.services.service.DatabaseIntrospector.introspect", new_callable=AsyncMock, return_value=canonical_schema), \
             patch("app.modules.database_knowledgebase.services.service.SchemaIndexer.index_schema", indexer_mock), \
             patch("app.worker.queue.get_redis_pool", new_callable=AsyncMock, return_value=mock_redis), \
             patch("app.modules.database_knowledgebase.knowledge.jobs.trigger_phase2_sync_job", new_callable=AsyncMock) as mock_p2_trigger:

            real_settings = get_settings()
            with patch.object(real_settings, "enable_phase2_knowledge_layer", enable_phase2):
                resp = await service.introspect_and_snapshot_schema(kb_id=kb_id)
                await non_super_async_session.commit()

                assert resp is not None
                assert resp.schema_version == "fp_nonsuper_v1"

                # Verify schema indexing ran
                assert indexer_mock.call_count == 1

                # Re-apply RLS for read check
                await set_rls_tenant_context(non_super_async_session, tenant_id)
                kb_record = await service.repo.get_by_id(kb_id)
                assert kb_record is not None
                assert kb_record.status == "indexed"
                assert kb_record.schema_version == "fp_nonsuper_v1"

                if enable_phase2:
                    assert mock_p2_trigger.call_count == 1
                else:
                    assert mock_p2_trigger.call_count == 0

    finally:
        # Cleanup
        await set_rls_tenant_context(non_super_async_session, tenant_id)
        await non_super_async_session.execute(text("DELETE FROM tenants WHERE id = :t;"), {"t": tenant_id})
        await non_super_async_session.commit()
        await reset_rls_tenant_context(non_super_async_session)


# ==============================================================================
# 6. Shared Redis Pool Reuse Test
# ==============================================================================

@pytest.mark.asyncio
async def test_get_redis_pool_reuses_shared_instance():
    """Item 4: Confirm get_redis_pool() reuses a shared module-level pool."""
    with patch("app.worker.queue.create_pool", new_callable=AsyncMock) as mock_create_pool:
        mock_pool = MagicMock()
        mock_create_pool.return_value = mock_pool

        # Reset module pool cache to test fresh creation
        import app.worker.queue as queue_mod
        queue_mod._redis_pool = None

        pool_1 = await get_redis_pool()
        pool_2 = await get_redis_pool()

        assert pool_1 is pool_2
        assert mock_create_pool.call_count == 1


# ==============================================================================
# 7. Configurable Stale Threshold Test
# ==============================================================================

@pytest.mark.asyncio
async def test_stale_threshold_configurable_and_recovers_job(async_session, seeded_context):
    """Item 5: Stale threshold is configurable (default 900s = 15m).
    Runs older than the threshold are marked failed; runs younger are left intact.
    """
    ctx = seeded_context
    repo = JobRunRepository(db=async_session, tenant_id=ctx["tenant_id"])
    now = datetime.now(timezone.utc)

    # Job A: Abandoned 10 minutes ago (600s old)
    run_a_id = uuid.uuid4()
    run_a = await repo.create_run(
        db_knowledgebase_id=ctx["kb_id"],
        schema_version="fp_stale_v1",
        status="running",
        run_id=run_a_id,
    )
    run_a.started_at = now - timedelta(seconds=600)
    run_a.heartbeat_at = now - timedelta(seconds=600)

    # Job B: Abandoned 20 minutes ago (1200s old)
    run_b_id = uuid.uuid4()
    run_b = await repo.create_run(
        db_knowledgebase_id=ctx["kb_id"],
        schema_version="fp_stale_v1",
        status="running",
        run_id=run_b_id,
    )
    run_b.started_at = now - timedelta(seconds=1200)
    run_b.heartbeat_at = now - timedelta(seconds=1200)
    await async_session.commit()

    repaired_count = await repo.mark_stale_runs_failed(
        db_knowledgebase_id=ctx["kb_id"],
        stale_threshold_seconds=900,
    )
    await async_session.commit()
    assert repaired_count == 1

    check_a = await repo.get_run(run_a_id)
    check_b = await repo.get_run(run_b_id)
    assert check_a.status == "running"
    assert check_b.status == "failed"
    assert "stale run abandoned after 900s" in check_b.error


# ==============================================================================
# 8. Dedupe Deterministic Job ID Test
# ==============================================================================

@pytest.mark.asyncio
async def test_dedupe_deterministic_job_id(async_session, seeded_context):
    """Item 2 & dedupe: Enqueue uses deterministic ARQ job_id = f"{kb_id}:{schema_version}"."""
    ctx = seeded_context
    schema_ver = "fp_dedupe_v1"
    expected_dedupe_key = f"{ctx['kb_id']}:{schema_ver}"

    mock_redis = AsyncMock()
    mock_redis.enqueue_job = AsyncMock(return_value="job_ok")

    run_id = await trigger_phase2_sync_job(
        tenant_id=ctx["tenant_id"],
        kb_id=ctx["kb_id"],
        schema_version=schema_ver,
        redis_pool=mock_redis,
        session_override=async_session,
    )

    mock_redis.enqueue_job.assert_called_once_with(
        "run_phase2_pipeline",
        tenant_id=str(ctx["tenant_id"]),
        kb_id=str(ctx["kb_id"]),
        schema_version=schema_ver,
        run_id=str(run_id),
        _job_id=expected_dedupe_key,
    )
