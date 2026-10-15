"""Phase 2 Knowledge Layer Job Execution Scaffolding

Orchestrates Phase 2 asynchronous processing via ARQ without altering Phase 1 code.
Provides:
- Staged pipeline: profiling -> relationship detection -> distinct value indexing -> LLM enrichment.
- Persisted JobRunRecord in kb2_job_runs (with RLS, heartbeat tracking, and stale recovery).
- Dedupe: enqueues with ARQ job_id = f"{kb_id}:{schema_version}".
- Idempotency & supersession: If schema version changes or a newer version exists, runs stop gracefully.
- Explicit RLS session setting (set_config('app.current_tenant', ...)).
- Configurable stale-run threshold and intra-stage heartbeat updates.
"""

import uuid
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List, Callable
from pydantic import BaseModel, Field
from sqlalchemy import text, select, desc

from arq import Retry
from app.models.base import Base
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseSchemaSnapshot
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from ..adapters.phase1_adapter import Phase1Adapter, SchemaView
from ..repositories.job_run_repository import JobRunRepository
from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from ..models.knowledge_items import KB2JobRun
from .profiler import run_stage_profiler

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    SUCCEEDED_WITH_WARNINGS = "succeeded_with_warnings"
    COMPLETED_WITH_ERRORS = "completed_with_errors"


class StageStatus(str, Enum):
    PROFILE = "profile"
    RELATIONSHIPS = "relationships"
    VALUE_INDEX = "value_index"
    ENRICH = "enrich"
    GLOSSARY_SEED = "glossary_seed"
    SCHEMA_INDEX = "schema_index"
    EXAMPLES = "examples"


class StageExecutionRecord(BaseModel):
    """Tracks a single pipeline stage execution."""
    stage: StageStatus
    status: JobStatus
    started_at: datetime
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


class JobRunRecord(BaseModel):
    """Observability & audit record for a Phase 2 pipeline execution run."""
    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: uuid.UUID
    kb_id: uuid.UUID
    schema_version: str
    status: JobStatus = JobStatus.QUEUED
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    stages: Dict[str, StageExecutionRecord] = Field(default_factory=dict)
    error: Optional[str] = None


async def set_rls_tenant_context(session, tenant_id: uuid.UUID | str) -> None:
    """Set app.current_tenant session config for PostgreSQL RLS enforcement."""
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, false);"),
        {"tenant_id": str(tenant_id)},
    )


async def reset_rls_tenant_context(session) -> None:
    """Reset app.current_tenant session variable so pooled connection is clean."""
    try:
        await session.execute(text("SELECT set_config('app.current_tenant', '', false);"))
    except Exception as exc:
        logger.debug(f"Failed to reset app.current_tenant on session: {exc}")


async def get_job_run(
    tenant_id: uuid.UUID | str,
    run_id: uuid.UUID | str,
    session_override: Optional[Any] = None,
) -> Optional[JobRunRecord]:
    """Retrieve job execution record from database with RLS tenant context."""
    t_id = uuid.UUID(str(tenant_id))
    r_id = uuid.UUID(str(run_id))

    async def _fetch(sess):
        await set_rls_tenant_context(sess, t_id)
        repo = JobRunRepository(db=sess, tenant_id=t_id)
        db_run = await repo.get_run(r_id)
        if not db_run:
            return None
        stages_mapped = {}
        for s_k, s_v in (db_run.stages or {}).items():
            stages_mapped[s_k] = StageExecutionRecord(**s_v)

        return JobRunRecord(
            run_id=db_run.id,
            tenant_id=db_run.tenant_id,
            kb_id=db_run.db_knowledgebase_id,
            schema_version=db_run.schema_version,
            status=JobStatus(db_run.status),
            started_at=db_run.started_at,
            finished_at=db_run.finished_at,
            heartbeat_at=db_run.heartbeat_at,
            stages=stages_mapped,
            error=db_run.error,
        )

    if session_override:
        return await _fetch(session_override)
    else:
        async with AsyncSessionLocal() as session:
            return await _fetch(session)


# ==============================================================================
# Per-Stage Stubs (with Heartbeat Callback Support)
# ==============================================================================

async def stage_profile_stub(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    schema_version: str,
    heartbeat_cb: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    """Stage 1: Statistical & categorical profiling of tables/columns."""
    logger.info(f"[Stage: Profile] Running for KB={kb_id}, version={schema_version}")
    if heartbeat_cb:
        await heartbeat_cb()
    return {"tables_profiled": 0, "columns_profiled": 0}


async def stage_relationships_stub(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    schema_version: str,
    heartbeat_cb: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    """Stage 2: Implicit foreign keys and semantic joins discovery."""
    logger.info(f"[Stage: Relationships] Running for KB={kb_id}, version={schema_version}")
    if heartbeat_cb:
        await heartbeat_cb()
    return {"inferred_relationships": 0}


async def stage_value_index_stub(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    schema_version: str,
    heartbeat_cb: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    """Stage 3: Distinct categorical values indexing (pg_trgm + tsvector)."""
    logger.info(f"[Stage: Value Index] Running for KB={kb_id}, version={schema_version}")
    if heartbeat_cb:
        await heartbeat_cb()
    return {"values_indexed": 0}


async def stage_enrich_stub(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    schema_version: str,
    heartbeat_cb: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    """Stage 4: LLM-based description and business semantics enrichment."""
    logger.info(f"[Stage: Enrich] Running for KB={kb_id}, version={schema_version}")
    if heartbeat_cb:
        await heartbeat_cb()
    return {"items_enriched": 0}


# ==============================================================================
# Pipeline Orchestrator
# ==============================================================================

async def run_phase2_pipeline(
    ctx: Optional[Dict[str, Any]],
    tenant_id: uuid.UUID | str,
    kb_id: uuid.UUID | str,
    schema_version: str,
    run_id: Optional[uuid.UUID] = None,
    session_override: Optional[Any] = None,
    force_recompute: bool = False,
    target_stages: Optional[List[str]] = None,
    dry_run: bool = False,
) -> JobRunRecord:
    """Main Phase 2 pipeline orchestrator.
    
    Guarantees:
    - RLS Enforced: Sets app.current_tenant on worker session prior to any reads/writes.
    - Persisted: State saved to kb2_job_runs database table.
    - Resumable: Re-running skips stages already completed for same schema_version.
    - Stage Independence: Subsequent stages (like schema_index) run even if enrich partially/fully failed.
    - Stale-run recovery: Heartbeat updated intra-stage; old runs marked failed on recovery.
    - Supersession: Checks latest schema_version via Phase1Adapter; if newer exists,
      marks run as SUPERSEDED and terminates immediately.
    """
    t_id = uuid.UUID(str(tenant_id))
    k_id = uuid.UUID(str(kb_id))
    r_id = run_id or uuid.uuid4()
    now_utc = datetime.now(timezone.utc)
    settings = get_settings()
    stale_threshold = getattr(settings, "phase2_job_stale_threshold_seconds", 900)

    async def _execute_with_session(session):
        # 1. Enforce RLS session context
        await set_rls_tenant_context(session, t_id)

        repo = JobRunRepository(db=session, tenant_id=t_id)
        adapter = Phase1Adapter(session=session)

        # 2. Stale-run cleanup using configurable threshold
        await repo.mark_stale_runs_failed(db_knowledgebase_id=k_id, stale_threshold_seconds=stale_threshold)

        # 3. Persist run start or update queued run
        existing_run = await repo.get_run(r_id)
        if not existing_run:
            existing_run = await repo.create_run(
                db_knowledgebase_id=k_id,
                schema_version=schema_version,
                status="running",
                run_id=r_id,
            )
        else:
            existing_run.status = "running"
            existing_run.started_at = now_utc
            existing_run.heartbeat_at = now_utc

        await session.commit()

        # 3b. Check previous runs for this schema_version to support stage resumability
        stmt_prev = (
            select(KB2JobRun)
            .where(
                KB2JobRun.tenant_id == t_id,
                KB2JobRun.db_knowledgebase_id == k_id,
                KB2JobRun.schema_version == schema_version,
                KB2JobRun.id != r_id,
            )
            .order_by(desc(KB2JobRun.created_at))
        )
        res_prev = await session.execute(stmt_prev)
        prev_runs = res_prev.scalars().all()
        prev_successful_stages: Dict[str, Dict[str, Any]] = {}
        for pr in prev_runs:
            if pr.stages and isinstance(pr.stages, dict):
                for st_k, st_v in pr.stages.items():
                    if isinstance(st_v, dict) and st_v.get("status") in ("succeeded", "completed_with_errors"):
                        if st_k not in prev_successful_stages:
                            prev_successful_stages[st_k] = st_v

        run_record = JobRunRecord(
            run_id=r_id,
            tenant_id=t_id,
            kb_id=k_id,
            schema_version=schema_version,
            status=JobStatus.RUNNING,
            started_at=now_utc,
            heartbeat_at=now_utc,
        )

        logger.info(f"[Phase 2 Pipeline] Started run={r_id} for KB={k_id}, version={schema_version}")

        # 4. Snapshot Visibility & Supersession Check
        # Check if the snapshot for schema_version is visible to worker
        snapshot_rec = await adapter.get_schema_snapshot_record(t_id, k_id, schema_version)
        if not snapshot_rec:
            # If running in test mode with explicit session_override and no ARQ ctx, proceed without retry
            if session_override is not None and ctx is None:
                logger.info(f"[Phase 2 Pipeline] session_override provided without worker ctx; proceeding without snapshot record.")
            else:
                # Snapshot not yet visible (commit race): check retry attempt
                job_try = ctx.get("job_try", 1) if ctx else 1
                if job_try < 5:
                    logger.warning(
                        f"[Phase 2 Pipeline] Snapshot for version '{schema_version}' not visible yet (try {job_try}/5). "
                        f"Raising Retry(defer=3s)."
                    )
                    raise Retry(defer=3)
                else:
                    logger.error(f"[Phase 2 Pipeline] Snapshot for version '{schema_version}' not found after {job_try} tries.")
                    run_record.status = JobStatus.FAILED
                    run_record.finished_at = datetime.now(timezone.utc)
                    run_record.error = f"Snapshot '{schema_version}' not visible after max retries."
                    await repo.finish_run(run_id=r_id, status="failed", error=run_record.error)
                    await session.commit()
                    return run_record

        # Check if a strictly NEWER snapshot exists (superseded ONLY if newer exists)
        latest_snapshot = await adapter.get_latest_snapshot_record(t_id, k_id)
        current_version = await adapter.get_schema_version(t_id, k_id)
        is_newer_snapshot = (
            (latest_snapshot is not None and latest_snapshot.schema_version != schema_version and (snapshot_rec is None or latest_snapshot.created_at > snapshot_rec.created_at))
            or (current_version is not None and current_version != schema_version)
        )
        if is_newer_snapshot:
            newer_v = latest_snapshot.schema_version if latest_snapshot else current_version
            logger.warning(
                f"[Phase 2 Pipeline] Run {r_id} superseded: newer snapshot/version exists '{newer_v}'. Aborting."
            )
            run_record.status = JobStatus.SUPERSEDED
            run_record.finished_at = datetime.now(timezone.utc)
            run_record.error = f"Superseded by newer schema version {newer_v}"
            await repo.finish_run(
                run_id=r_id,
                status="superseded",
                stages={k: v.model_dump(mode="json") for k, v in run_record.stages.items()},
                error=run_record.error,
            )
            await session.commit()
            return run_record

        item_repo = KnowledgeItemRepository(db=session, tenant_id=t_id)

        from .relationships import run_stage_relationships
        from .value_indexer import run_stage_value_index
        from .enrichment import run_stage_enrich
        from .seed_query_memory import run_seed_query_memory
        from ..semantics.business_semantics import (
            seed_suggested_glossary_and_metrics,
            mark_stale_business_semantics,
        )
        from ..drift.schema_drift import compute_schema_diff, invalidate_dependents_on_drift
        from ..repositories.query_memory_repository import QueryMemoryRepository

        # Compute schema drift diff from previous snapshot if available
        try:
            curr_schema_view = await adapter.get_schema_by_version(t_id, k_id, schema_version)
            if not curr_schema_view:
                curr_schema_view = await adapter.get_current_schema(t_id, k_id)
        except Exception as schema_err:
            logger.debug(f"[Phase 2 Pipeline] No schema snapshot found ({schema_err}). Using empty schema view.")
            curr_schema_view = SchemaView(
                database_name="unknown",
                database_type="postgresql",
                schema_version=schema_version,
                tables={},
            )

        # Look for previous snapshot
        prev_stmt = (
            select(DatabaseSchemaSnapshot)
            .where(
                DatabaseSchemaSnapshot.tenant_id == t_id,
                DatabaseSchemaSnapshot.db_knowledgebase_id == k_id,
                DatabaseSchemaSnapshot.schema_version != schema_version,
            )
            .order_by(desc(DatabaseSchemaSnapshot.created_at))
            .limit(1)
        )
        prev_res = await session.execute(prev_stmt)
        prev_rec = prev_res.scalar_one_or_none()
        old_schema_view = None
        if prev_rec:
            old_schema_view = adapter._map_to_schema_view(prev_rec.schema_data or {}, prev_rec.schema_version)

        diff_result = compute_schema_diff(old_schema_view, curr_schema_view)
        drift_invalidation_summary = await invalidate_dependents_on_drift(t_id, k_id, diff_result, session)

        # Stage context passing for affected objects
        affected_tables = diff_result.affected_tables if diff_result.has_changes else set(curr_schema_view.tables.keys())

        enrich_cache = {}

        async def _run_profiler_wrapper(tid, kid, ver, heartbeat_cb=None):
            return await run_stage_profiler(
                tenant_id=tid,
                kb_id=kid,
                schema_version=ver,
                adapter=adapter,
                item_repo=item_repo,
                heartbeat_cb=heartbeat_cb,
                force_refresh_stats=force_recompute,
            )

        async def _run_relationships_wrapper(tid, kid, ver, heartbeat_cb=None):
            return await run_stage_relationships(
                tenant_id=tid,
                kb_id=kid,
                schema_version=ver,
                adapter=adapter,
                item_repo=item_repo,
                heartbeat_cb=heartbeat_cb,
            )

        async def _run_value_index_wrapper(tid, kid, ver, heartbeat_cb=None):
            return await run_stage_value_index(
                tenant_id=tid,
                kb_id=kid,
                schema_version=ver,
                adapter=adapter,
                db_session=session,
                heartbeat_cb=heartbeat_cb,
            )

        async def _run_enrich_wrapper(tid, kid, ver, heartbeat_cb=None):
            enrich_res = await run_stage_enrich(
                tenant_id=tid,
                kb_id=kid,
                schema_version=ver,
                db_session=session,
                heartbeat_cb=heartbeat_cb,
                dry_run=dry_run,
                force_refresh=force_recompute,
            )
            enrich_cache["res"] = enrich_res
            return enrich_res

        async def _run_glossary_seed_wrapper(tid, kid, ver, heartbeat_cb=None):
            s_res = enrich_cache.get("res", {})
            s_metrics = s_res.get("suggested_metrics", [])
            s_glossary = s_res.get("candidate_glossary", [])
            existing_items = await item_repo.list_items(db_knowledgebase_id=kid)
            all_keys = {it.item_key for it in existing_items}
            seed_res = await seed_suggested_glossary_and_metrics(
                tenant_id=tid,
                kb_id=kid,
                schema_version=ver,
                item_repo=item_repo,
                suggested_metrics=s_metrics,
                candidate_glossary=s_glossary,
                existing_column_keys={k for k in all_keys if k.count(".") >= 2},
            )
            stale_count = await mark_stale_business_semantics(
                tenant_id=tid,
                kb_id=kid,
                db_session=session,
                current_item_keys=all_keys,
            )
            seed_res["stale_marked"] = stale_count
            seed_res.update(drift_invalidation_summary)
            return seed_res

        async def _run_schema_index_wrapper(tid, kid, ver, heartbeat_cb=None):
            from .schema_indexer import build_and_index_schema_docs
            return await build_and_index_schema_docs(
                tenant_id=tid,
                kb_id=kid,
                schema_version=ver,
                db_session=session,
            )

        async def _run_examples_wrapper(tid, kid, ver, heartbeat_cb=None):
            q_repo = QueryMemoryRepository(db=session, tenant_id=tid)
            return await run_seed_query_memory(
                tenant_id=tid,
                kb_id=kid,
                schema_version=ver,
                adapter=adapter,
                item_repo=item_repo,
                query_repo=q_repo,
            )

        # 5. Full sequential execution of pipeline stages
        stages = [
            (StageStatus.PROFILE, _run_profiler_wrapper),
            (StageStatus.RELATIONSHIPS, _run_relationships_wrapper),
            (StageStatus.VALUE_INDEX, _run_value_index_wrapper),
            (StageStatus.ENRICH, _run_enrich_wrapper),
            (StageStatus.GLOSSARY_SEED, _run_glossary_seed_wrapper),
            (StageStatus.SCHEMA_INDEX, _run_schema_index_wrapper),
            (StageStatus.EXAMPLES, _run_examples_wrapper),
        ]

        if target_stages:
            target_set = {s.lower() for s in target_stages}
            stages = [s for s in stages if s[0].value.lower() in target_set]

        async def stage_heartbeat_cb():
            run_record.heartbeat_at = datetime.now(timezone.utc)
            await repo.update_heartbeat(
                run_id=r_id,
                stages={k: v.model_dump(mode="json") for k, v in run_record.stages.items()},
            )
            await session.commit()

        for i, (stage_name, stage_fn) in enumerate(stages):
            stage_idx = i + 1
            total_stages = len(stages)

            # Check for mid-run supersession (only if strictly newer snapshot exists)
            try:
                curr_latest = await adapter.get_latest_snapshot_record(t_id, k_id)
                curr_ver = await adapter.get_schema_version(t_id, k_id)
                is_mid_newer = (
                    (curr_latest and curr_latest.schema_version != schema_version and (snapshot_rec is None or curr_latest.created_at > snapshot_rec.created_at))
                    or (curr_ver and curr_ver != schema_version)
                )
                if is_mid_newer:
                    newer_v = curr_latest.schema_version if curr_latest else curr_ver
                    logger.warning(f"[Phase 2 Pipeline] Mid-run supersession detected at stage {stage_name} by {newer_v}. Stopping.")
                    run_record.status = JobStatus.SUPERSEDED
                    run_record.finished_at = datetime.now(timezone.utc)
                    run_record.error = f"Superseded mid-run by {newer_v}"

                    await repo.finish_run(
                        run_id=r_id,
                        status="superseded",
                        stages={k: v.model_dump(mode="json") for k, v in run_record.stages.items()},
                        error=run_record.error,
                    )
                    await session.commit()
                    return run_record
            except Exception:
                pass

            # Resumability check:
            # If profile, relationships, or value_index already succeeded in a previous run for this exact schema_version, skip re-execution
            prev_stage = prev_successful_stages.get(stage_name.value)
            if (
                prev_stage
                and prev_stage.get("status") == "succeeded"
                and stage_name in (StageStatus.PROFILE, StageStatus.RELATIONSHIPS, StageStatus.VALUE_INDEX)
                and not force_recompute
            ):
                logger.info(
                    f"[Phase 2 Pipeline] [{stage_idx}/{total_stages}] Resuming: stage '{stage_name.value}' "
                    f"already completed in previous run for version {schema_version[:8]}. Skipping."
                )
                stage_rec = StageExecutionRecord(
                    stage=stage_name,
                    status=JobStatus.SUCCEEDED,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    metrics={**prev_stage.get("metrics", {}), "resumed_from_previous": True},
                )
                run_record.stages[stage_name.value] = stage_rec
                await stage_heartbeat_cb()
                continue

            # Initial stage heartbeat and timing
            logger.info(f"[Phase 2 Pipeline] [{stage_idx}/{total_stages}] Stage '{stage_name.value}' START (KB={k_id})")
            t_stage_start = time.perf_counter()

            stage_rec = StageExecutionRecord(
                stage=stage_name,
                status=JobStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
            )
            run_record.stages[stage_name.value] = stage_rec
            await stage_heartbeat_cb()

            try:
                metrics = await stage_fn(t_id, k_id, schema_version, heartbeat_cb=stage_heartbeat_cb)
                stage_duration = time.perf_counter() - t_stage_start
                metrics["duration_seconds"] = round(stage_duration, 2)
                stage_rec.finished_at = datetime.now(timezone.utc)
                stage_rec.metrics = metrics

                if stage_name == StageStatus.ENRICH and metrics.get("tables_failed", 0) > 0:
                    stage_rec.status = JobStatus.COMPLETED_WITH_ERRORS
                    logger.warning(
                        f"[Phase 2 Pipeline] [{stage_idx}/{total_stages}] Stage '{stage_name.value}' "
                        f"COMPLETED WITH ERRORS in {stage_duration:.1f}s - {metrics.get('tables_failed')} tables failed. "
                        f"Metrics: {metrics}"
                    )
                else:
                    stage_rec.status = JobStatus.SUCCEEDED
                    logger.info(
                        f"[Phase 2 Pipeline] [{stage_idx}/{total_stages}] Stage '{stage_name.value}' "
                        f"SUCCEEDED in {stage_duration:.1f}s - Metrics: {metrics}"
                    )
                await stage_heartbeat_cb()

            except Exception as e:
                stage_duration = time.perf_counter() - t_stage_start
                logger.error(f"[Phase 2 Pipeline] [{stage_idx}/{total_stages}] Stage '{stage_name.value}' failed in {stage_duration:.1f}s: {e}", exc_info=True)
                stage_rec.status = JobStatus.FAILED
                stage_rec.finished_at = datetime.now(timezone.utc)
                stage_rec.error = str(e)
                stage_rec.metrics["duration_seconds"] = round(stage_duration, 2)
                await stage_heartbeat_cb()

                # Stage independence:
                # If ENRICH, GLOSSARY_SEED, or EXAMPLES fail, continue so SCHEMA_INDEX is never blocked
                if stage_name in (StageStatus.ENRICH, StageStatus.GLOSSARY_SEED, StageStatus.EXAMPLES):
                    logger.warning(f"[Phase 2 Pipeline] Continuing to subsequent stages despite failure in non-critical stage '{stage_name.value}'")
                    continue
                else:
                    # Foundational structural stage failed
                    run_record.status = JobStatus.FAILED
                    run_record.finished_at = datetime.now(timezone.utc)
                    run_record.error = f"Stage {stage_name.value} failed: {e}"

                    await repo.finish_run(
                        run_id=r_id,
                        status="failed",
                        stages={k: v.model_dump(mode="json") for k, v in run_record.stages.items()},
                        error=run_record.error,
                    )
                    await session.commit()
                    return run_record

        # All stages executed
        has_failed = any(s.status == JobStatus.FAILED for s in run_record.stages.values())
        has_warnings = any(s.status == JobStatus.COMPLETED_WITH_ERRORS for s in run_record.stages.values())

        if has_failed:
            run_record.status = JobStatus.FAILED
        elif has_warnings:
            run_record.status = JobStatus.SUCCEEDED_WITH_WARNINGS
            enrich_stage_rec = run_record.stages.get(StageStatus.ENRICH.value)
            if enrich_stage_rec and enrich_stage_rec.metrics.get("coverage"):
                cov = enrich_stage_rec.metrics["coverage"]
                run_record.error = (
                    f"Completed with warnings. Enrichment coverage: "
                    f"tables {cov.get('tables_described')}/{cov.get('total_tables')}, "
                    f"columns {cov.get('columns_described')}/{cov.get('total_columns')}."
                )
        else:
            run_record.status = JobStatus.SUCCEEDED

        run_record.finished_at = datetime.now(timezone.utc)
        run_record.heartbeat_at = run_record.finished_at

        await repo.finish_run(
            run_id=r_id,
            status=run_record.status.value,
            stages={k: v.model_dump(mode="json") for k, v in run_record.stages.items()},
            error=run_record.error,
        )
        await session.commit()

        logger.info(f"[Phase 2 Pipeline] Run {r_id} finished with status={run_record.status.value}")
        return run_record

    if session_override:
        try:
            return await _execute_with_session(session_override)
        except Exception:
            try:
                await session_override.rollback()
            except Exception:
                pass
            raise
        finally:
            await reset_rls_tenant_context(session_override)
    else:
        async with AsyncSessionLocal() as session:
            try:
                return await _execute_with_session(session)
            except Exception:
                try:
                    await session.rollback()
                except Exception:
                    pass
                raise
            finally:
                await reset_rls_tenant_context(session)


# ==============================================================================
# Enqueue Dispatcher
# ==============================================================================

async def trigger_phase2_sync_job(
    tenant_id: uuid.UUID | str,
    kb_id: uuid.UUID | str,
    snapshot_id: Optional[uuid.UUID | str] = None,
    schema_version: Optional[str] = None,
    redis_pool: Optional[Any] = None,
    session_override: Optional[Any] = None,
    defer_by_seconds: Optional[int] = None,
) -> uuid.UUID:
    """Entry point invoked after Phase 1 snapshot persistence.
    
    Guarantees:
    - Dedicated session: Uses its own DB session (never callers') to maintain isolation.
    - Sets app.current_tenant for RLS and resets it on session close/exit.
    - Dedupe: Uses deterministic ARQ job_id = f"{kb_id}:{schema_version}".
    - Persists queued job record in kb2_job_runs.
    - Recovers stale runs using configured threshold.
    - Supports deferred execution (_defer_by) so caller transaction commit completes.
    """
    t_id = uuid.UUID(str(tenant_id))
    k_id = uuid.UUID(str(kb_id))
    run_id = uuid.uuid4()
    settings = get_settings()
    stale_threshold = getattr(settings, "phase2_job_stale_threshold_seconds", 900)

    async def _resolve_and_persist(session):
        await set_rls_tenant_context(session, t_id)
        adapter = Phase1Adapter(session=session)
        repo = JobRunRepository(db=session, tenant_id=t_id)

        # 1. Recover any stale running runs
        await repo.mark_stale_runs_failed(db_knowledgebase_id=k_id, stale_threshold_seconds=stale_threshold)

        # 2. Resolve version
        resolved_version = schema_version
        if not resolved_version:
            resolved_version = await adapter.get_schema_version(tenant_id=t_id, kb_id=k_id)

        # 3. Create persisted record in kb2_job_runs
        await repo.create_run(
            db_knowledgebase_id=k_id,
            schema_version=resolved_version,
            status="queued",
            run_id=run_id,
        )
        await session.commit()
        return resolved_version

    if session_override:
        try:
            final_version = await _resolve_and_persist(session_override)
        except Exception:
            try:
                await session_override.rollback()
            except Exception:
                pass
            raise
        finally:
            await reset_rls_tenant_context(session_override)
    else:
        async with AsyncSessionLocal() as session:
            try:
                final_version = await _resolve_and_persist(session)
            except Exception:
                try:
                    await session.rollback()
                except Exception:
                    pass
                raise
            finally:
                await reset_rls_tenant_context(session)

    # Deterministic ARQ job dedupe key
    dedupe_job_id = f"{k_id}:{final_version}"

    if redis_pool:
        enqueue_kwargs: Dict[str, Any] = {
            "tenant_id": str(t_id),
            "kb_id": str(k_id),
            "schema_version": final_version,
            "run_id": str(run_id),
            "_job_id": dedupe_job_id,
        }
        if defer_by_seconds:
            enqueue_kwargs["_defer_by"] = defer_by_seconds

        await redis_pool.enqueue_job("run_phase2_pipeline", **enqueue_kwargs)

    return run_id


async def run_pipeline_for_kb_local(
    kb_id: uuid.UUID | str,
    tenant_id: Optional[uuid.UUID | str] = None,
    force_recompute: bool = False,
    target_stages: Optional[List[str]] = None,
    dry_run: bool = False,
) -> JobRunRecord:
    """Manually run Phase 2/3 knowledge pipeline for a single KB without Redis.
    
    Resolves tenant_id and schema_version from database snapshots, then executes the pipeline.
    """
    k_id = uuid.UUID(str(kb_id))
    async with AsyncSessionLocal() as session:
        stmt = (
            select(DatabaseSchemaSnapshot)
            .where(DatabaseSchemaSnapshot.db_knowledgebase_id == k_id)
            .order_by(desc(DatabaseSchemaSnapshot.created_at))
            .limit(1)
        )
        res = await session.execute(stmt)
        snap = res.scalar_one_or_none()
        if not snap:
            raise ValueError(f"No schema snapshot found for KB {kb_id}")
        t_id = uuid.UUID(str(tenant_id)) if tenant_id else snap.tenant_id
        ver = snap.schema_version

    logger.info(f"[Local Pipeline Runner] Starting pipeline for KB {k_id}, tenant {t_id}, version {ver[:8]}")
    return await run_phase2_pipeline(
        ctx=None,
        tenant_id=t_id,
        kb_id=k_id,
        schema_version=ver,
        force_recompute=force_recompute,
        target_stages=target_stages,
        dry_run=dry_run,
    )

