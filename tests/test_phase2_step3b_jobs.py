"""Test Phase 2 Step 3b: Background Job Scaffolding & Idempotency / Supersession.

Validates:
1. Enqueue and execution of run_phase2_pipeline:
   - Calls all 4 stage stubs (profile, relationships, value_index, enrich)
   - Emits structured job run and stage execution records
   - Marks run as SUCCEEDED
2. Idempotent re-run:
   - Re-running for the same schema_version is safe and succeeds
3. Supersession handling:
   - If a newer schema_version exists at start, run aborts immediately with SUPERSEDED
   - If a newer schema_version is detected mid-run, run terminates with SUPERSEDED
4. Trigger helper (trigger_phase2_sync_job):
   - Enqueues/registers the pipeline orchestrator with resolved schema version
"""

import uuid
import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.modules.database_knowledgebase.knowledge.jobs import (
    JobStatus,
    StageStatus,
    JobRunRecord,
    get_job_run,
    run_phase2_pipeline,
    trigger_phase2_sync_job,
)
from app.modules.database_knowledgebase.knowledge.adapters.phase1_adapter import Phase1Adapter

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
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()

    tenant_name = f"Ten Jobs {uuid.uuid4().hex[:6]}"
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
            VALUES (:kb, :t, :u, 'KB Jobs', 'postgresql', 'dummy_enc', 'configured', true);
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


@pytest.mark.asyncio
async def test_job_pipeline_execution_and_stubs(async_session, seeded_context):
    """Test full execution of run_phase2_pipeline through all 4 stubs."""
    ctx = seeded_context
    schema_version = "fp_initial_v1"

    # Mock Phase1Adapter.get_schema_version to return the same version
    with patch.object(Phase1Adapter, "get_schema_version", new_callable=AsyncMock) as mock_ver:
        mock_ver.return_value = schema_version

        run_id = uuid.uuid4()
        record = await run_phase2_pipeline(
            ctx=None,
            tenant_id=ctx["tenant_id"],
            kb_id=ctx["kb_id"],
            schema_version=schema_version,
            run_id=run_id,
            session_override=async_session,
        )

        assert record.status == JobStatus.SUCCEEDED
        assert record.run_id == run_id
        assert record.schema_version == schema_version
        assert record.finished_at is not None
        assert record.error is None

        # Verify all stages executed and recorded metrics
        assert len(record.stages) >= 4
        assert StageStatus.PROFILE.value in record.stages
        assert StageStatus.RELATIONSHIPS.value in record.stages
        assert StageStatus.VALUE_INDEX.value in record.stages
        assert StageStatus.ENRICH.value in record.stages

        for stage_name, stage_rec in record.stages.items():
            assert stage_rec.status == JobStatus.SUCCEEDED
            assert stage_rec.finished_at is not None
            assert stage_rec.metrics is not None

        # Verify lookup via get_job_run
        retrieved = await get_job_run(ctx["tenant_id"], run_id, session_override=async_session)
        assert retrieved is not None
        assert retrieved.run_id == run_id


@pytest.mark.asyncio
async def test_job_pipeline_idempotent_rerun(async_session, seeded_context):
    """Test that running the pipeline repeatedly for the same schema version is safe and idempotent."""
    ctx = seeded_context
    schema_version = "fp_stable_v1"

    with patch.object(Phase1Adapter, "get_schema_version", new_callable=AsyncMock) as mock_ver:
        mock_ver.return_value = schema_version

        # Run 1
        run1 = await run_phase2_pipeline(
            ctx=None,
            tenant_id=ctx["tenant_id"],
            kb_id=ctx["kb_id"],
            schema_version=schema_version,
            session_override=async_session,
        )
        assert run1.status == JobStatus.SUCCEEDED

        # Run 2 (Idempotent re-run)
        run2 = await run_phase2_pipeline(
            ctx=None,
            tenant_id=ctx["tenant_id"],
            kb_id=ctx["kb_id"],
            schema_version=schema_version,
            session_override=async_session,
        )
        assert run2.status == JobStatus.SUCCEEDED
        assert run2.schema_version == schema_version


@pytest.mark.asyncio
async def test_job_pipeline_superseded_at_start(async_session, seeded_context):
    """Test that if a newer schema version already exists, the pipeline marks run SUPERSEDED and stops."""
    ctx = seeded_context
    old_version = "fp_old_v1"
    newer_version = "fp_new_v2"

    with patch.object(Phase1Adapter, "get_schema_version", new_callable=AsyncMock) as mock_ver:
        mock_ver.return_value = newer_version  # Adapter reports newer version in Phase 1

        run = await run_phase2_pipeline(
            ctx=None,
            tenant_id=ctx["tenant_id"],
            kb_id=ctx["kb_id"],
            schema_version=old_version,  # Pipeline requested with old version
            session_override=async_session,
        )

        assert run.status == JobStatus.SUPERSEDED
        assert "Superseded by newer schema version" in run.error
        # Stages must not have executed
        assert len(run.stages) == 0


@pytest.mark.asyncio
async def test_job_pipeline_superseded_mid_run(async_session, seeded_context):
    """Test that if a newer schema version appears mid-run, pipeline stops and marks SUPERSEDED."""
    ctx = seeded_context
    initial_version = "fp_v1"
    newer_version = "fp_v2"

    # Return initial_version on start check and first stage, then newer_version mid-run
    version_sequence = [initial_version, initial_version, newer_version]

    with patch.object(Phase1Adapter, "get_schema_version", new_callable=AsyncMock) as mock_ver:
        mock_ver.side_effect = version_sequence

        run = await run_phase2_pipeline(
            ctx=None,
            tenant_id=ctx["tenant_id"],
            kb_id=ctx["kb_id"],
            schema_version=initial_version,
            session_override=async_session,
        )

        assert run.status == JobStatus.SUPERSEDED
        assert "Superseded mid-run" in run.error
        # Stage 1 executed, but later stages were aborted
        assert len(run.stages) < 4


@pytest.mark.asyncio
async def test_trigger_phase2_sync_job_dispatcher(async_session, seeded_context):
    """Test trigger_phase2_sync_job enqueuing helper."""
    ctx = seeded_context
    schema_version = "fp_v1"

    # Test standalone fallback
    run_id = await trigger_phase2_sync_job(
        tenant_id=ctx["tenant_id"],
        kb_id=ctx["kb_id"],
        schema_version=schema_version,
        session_override=async_session,
    )
    assert isinstance(run_id, uuid.UUID)
    rec = await get_job_run(ctx["tenant_id"], run_id, session_override=async_session)
    assert rec is not None
    assert rec.status == JobStatus.QUEUED

    # Test with mock redis_pool
    mock_redis = AsyncMock()
    mock_redis.enqueue_job = AsyncMock(return_value="job_123")

    run_id_arq = await trigger_phase2_sync_job(
        tenant_id=ctx["tenant_id"],
        kb_id=ctx["kb_id"],
        schema_version=schema_version,
        redis_pool=mock_redis,
        session_override=async_session,
    )
    assert isinstance(run_id_arq, uuid.UUID)
    mock_redis.enqueue_job.assert_called_once_with(
        "run_phase2_pipeline",
        tenant_id=str(ctx["tenant_id"]),
        kb_id=str(ctx["kb_id"]),
        schema_version=schema_version,
        run_id=str(run_id_arq),
        _job_id=f"{ctx['kb_id']}:{schema_version}",
    )
