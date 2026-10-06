"""Job Run Repository for Phase 2 (kb2_job_runs)

Follows BaseRepository pattern:
- Strictly scoped by tenant_id on every operation.
- Supports RLS session setting.
- Lifecycle states: queued, running, succeeded, failed, superseded.
- Heartbeat tracking and stale run recovery.
"""

import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_repository import BaseRepository
from ..models.knowledge_items import KB2JobRun


class JobRunRepository(BaseRepository):
    """Data access repository for kb2_job_runs."""

    def __init__(self, db: AsyncSession, tenant_id: str | uuid.UUID):
        super().__init__(db, str(tenant_id))

    async def create_run(
        self,
        db_knowledgebase_id: uuid.UUID,
        schema_version: str,
        status: str = "queued",
        stages: Optional[Dict[str, Any]] = None,
        run_id: Optional[uuid.UUID] = None,
    ) -> KB2JobRun:
        """Create a new job run record."""
        now_utc = datetime.now(timezone.utc)
        run = KB2JobRun(
            id=run_id or uuid.uuid4(),
            tenant_id=self.tenant_id,
            db_knowledgebase_id=db_knowledgebase_id,
            schema_version=schema_version,
            status=status,
            stages=stages or {},
            started_at=now_utc if status == "running" else None,
            heartbeat_at=now_utc if status == "running" else None,
            created_at=now_utc,
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def get_run(self, run_id: uuid.UUID) -> Optional[KB2JobRun]:
        """Fetch a specific job run by id within tenant scope."""
        stmt = select(KB2JobRun).where(
            KB2JobRun.tenant_id == self.tenant_id,
            KB2JobRun.id == run_id,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_active_run(
        self,
        db_knowledgebase_id: uuid.UUID,
        schema_version: Optional[str] = None,
    ) -> Optional[KB2JobRun]:
        """Fetch an active (queued or running) run for KB and schema_version."""
        conditions = [
            KB2JobRun.tenant_id == self.tenant_id,
            KB2JobRun.db_knowledgebase_id == db_knowledgebase_id,
            KB2JobRun.status.in_(["queued", "running"]),
        ]
        if schema_version:
            conditions.append(KB2JobRun.schema_version == schema_version)

        stmt = select(KB2JobRun).where(and_(*conditions)).order_by(KB2JobRun.created_at.desc())
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def update_heartbeat(
        self,
        run_id: uuid.UUID,
        stages: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update the heartbeat timestamp and stage state for an active run."""
        now_utc = datetime.now(timezone.utc)
        values: Dict[str, Any] = {"heartbeat_at": now_utc}
        if stages is not None:
            values["stages"] = stages

        stmt = (
            update(KB2JobRun)
            .where(
                KB2JobRun.tenant_id == self.tenant_id,
                KB2JobRun.id == run_id,
                KB2JobRun.status == "running",
            )
            .values(**values)
        )
        res = await self.db.execute(stmt)
        await self.db.flush()
        return res.rowcount > 0

    async def finish_run(
        self,
        run_id: uuid.UUID,
        status: str,
        stages: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[KB2JobRun]:
        """Mark a run finished with succeeded, failed, or superseded."""
        now_utc = datetime.now(timezone.utc)
        run = await self.get_run(run_id)
        if not run:
            return None

        run.status = status
        run.finished_at = now_utc
        run.heartbeat_at = now_utc
        if stages is not None:
            run.stages = stages
        if error is not None:
            run.error = error

        await self.db.flush()
        return run

    async def mark_stale_runs_failed(
        self,
        db_knowledgebase_id: uuid.UUID,
        stale_threshold_seconds: int = 300,
    ) -> int:
        """Mark running jobs with expired heartbeats as 'failed' for recovery / retry."""
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(seconds=stale_threshold_seconds)

        stmt = (
            update(KB2JobRun)
            .where(
                KB2JobRun.tenant_id == self.tenant_id,
                KB2JobRun.db_knowledgebase_id == db_knowledgebase_id,
                KB2JobRun.status == "running",
                KB2JobRun.heartbeat_at < cutoff,
            )
            .values(
                status="failed",
                finished_at=now_utc,
                error=f"Heartbeat expired (stale run abandoned after {stale_threshold_seconds}s)",
            )
        )
        res = await self.db.execute(stmt)
        await self.db.flush()
        return res.rowcount
