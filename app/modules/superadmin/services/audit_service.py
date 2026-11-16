"""SuperAdmin Audit Logging Service.

Provides query, search, filtering, and creation of administrative audit records.
"""

from typing import List, Optional, Tuple
from uuid import UUID
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
import logging

from ..models import SuperAdminAuditLog, SuperAdminUser
from ..schemas import AuditLogCreateRequest

logger = logging.getLogger(__name__)


class AuditService:
    """Service providing search, filter, and management of administrative audit records."""

    @staticmethod
    async def list_logs(
        db: AsyncSession,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        admin_email: Optional[str] = None,
        target_tenant_id: Optional[UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[SuperAdminAuditLog], int]:
        """Query and paginate administrative audit logs with dynamic filters."""
        query = select(SuperAdminAuditLog)
        count_query = select(func.count(SuperAdminAuditLog.id))

        if start_date:
            query = query.where(SuperAdminAuditLog.created_at >= start_date)
            count_query = count_query.where(SuperAdminAuditLog.created_at >= start_date)

        if end_date:
            query = query.where(SuperAdminAuditLog.created_at <= end_date)
            count_query = count_query.where(SuperAdminAuditLog.created_at <= end_date)

        if action:
            query = query.where(SuperAdminAuditLog.action == action)
            count_query = count_query.where(SuperAdminAuditLog.action == action)

        if resource_type:
            query = query.where(SuperAdminAuditLog.resource_type == resource_type)
            count_query = count_query.where(SuperAdminAuditLog.resource_type == resource_type)

        if admin_email:
            query = query.where(SuperAdminAuditLog.admin_email.ilike(f"%{admin_email}%"))
            count_query = count_query.where(SuperAdminAuditLog.admin_email.ilike(f"%{admin_email}%"))

        if target_tenant_id:
            query = query.where(SuperAdminAuditLog.target_tenant_id == target_tenant_id)
            count_query = count_query.where(SuperAdminAuditLog.target_tenant_id == target_tenant_id)

        # Count total
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # Fetch records
        query = query.order_by(SuperAdminAuditLog.created_at.desc()).offset(offset).limit(limit)
        result = await db.execute(query)
        items = list(result.scalars().all())

        return items, total

    @staticmethod
    async def get_log(db: AsyncSession, log_id: UUID) -> SuperAdminAuditLog:
        """Fetch a specific audit log record by UUID."""
        query = select(SuperAdminAuditLog).where(SuperAdminAuditLog.id == log_id)
        result = await db.execute(query)
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Audit log entry with ID {log_id} not found",
            )
        return entry

    @staticmethod
    async def record_log(
        db: AsyncSession,
        admin: SuperAdminUser,
        req: AuditLogCreateRequest,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> SuperAdminAuditLog:
        """Create a custom administrative audit log entry."""
        entry = SuperAdminAuditLog(
            admin_id=admin.id,
            admin_email=admin.email,
            action=req.action,
            resource_type=req.resource_type,
            resource_id=req.resource_id,
            target_tenant_id=req.target_tenant_id,
            status=req.status,
            details=req.details or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry

