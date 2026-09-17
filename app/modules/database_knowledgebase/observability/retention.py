"""Safe Batched Audit Log Retention & Pruning for Phase 3B

Enforces data retention policies by purging expired query execution audit logs
using non-locking batched deletions to prevent table lock contention.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Optional, Union
import uuid

from sqlalchemy import delete, select
from app.core.database import AsyncSessionLocal
from .audit_model import DatabaseQueryAuditLog

logger = logging.getLogger("database_knowledgebase.audit.retention")


class AuditLogRetentionManager:
    """Manages lifecycle retention and batched pruning for DatabaseQueryAuditLog."""

    @classmethod
    async def prune_audit_logs(
        cls,
        retention_days: int = 90,
        batch_size: int = 1000,
        tenant_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> int:
        """
        Prune audit logs older than retention_days.
        Executes in non-locking batches of `batch_size` records to avoid table lock escalation.
        Returns total number of records deleted.
        """
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1 day.")

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        total_deleted = 0

        t_filter = [DatabaseQueryAuditLog.request_timestamp < cutoff_date]
        if tenant_id:
            t_uuid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
            t_filter.append(DatabaseQueryAuditLog.tenant_id == t_uuid)

        logger.info(
            f"Starting audit log retention purge: cutoff={cutoff_date.isoformat()}, "
            f"batch_size={batch_size}, tenant={tenant_id or 'ALL'}"
        )

        while True:
            try:
                async with AsyncSessionLocal() as session:
                    # Select batch of IDs to delete
                    select_stmt = (
                        select(DatabaseQueryAuditLog.id)
                        .where(*t_filter)
                        .limit(batch_size)
                    )
                    result = await session.execute(select_stmt)
                    ids_to_delete = list(result.scalars().all())

                    if not ids_to_delete:
                        break

                    # Delete selected batch
                    del_stmt = delete(DatabaseQueryAuditLog).where(
                        DatabaseQueryAuditLog.id.in_(ids_to_delete)
                    )
                    del_res = await session.execute(del_stmt)
                    await session.commit()

                    deleted_count = del_res.rowcount or len(ids_to_delete)
                    total_deleted += deleted_count
                    logger.debug(f"Pruned batch of {deleted_count} audit logs (total so far: {total_deleted})")

                    if len(ids_to_delete) < batch_size:
                        break

            except Exception as exc:
                logger.error(f"Error during audit log retention pruning batch: {exc}", exc_info=True)
                break

        logger.info(f"Completed audit log retention purge: {total_deleted} total records pruned.")
        return total_deleted
