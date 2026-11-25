"""Admin Router - Endpoints for Admin Overview, System Health, and Diagnostics"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.modules.auth.models import User
from .schemas import (
    AdminOverviewResponse,
    SystemHealthDetails,
    EndpointItem,
    AnnouncementCreate,
    AnnouncementUpdate,
    AnnouncementResponse,
)
from .services import (
    get_admin_overview_metrics,
    get_system_health,
    _extract_app_endpoints,
    list_announcements,
    create_announcement,
    update_announcement,
    delete_announcement,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


def _get_caller_tenant_id(request: Request) -> Optional[UUID]:
    """Extract tenant_id safely from request state."""
    tid = getattr(request.state, "tenant_id", None)
    if not tid and hasattr(request, "state"):
        user = getattr(request.state, "user", None)
        if isinstance(user, dict):
            tid = user.get("tenant_id")
    if tid:
        try:
            return UUID(str(tid))
        except (ValueError, TypeError):
            pass
    return None


async def _verify_admin_access(request: Request, db: AsyncSession) -> User:
    """Ensure the calling user is authenticated and has administrative privileges."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        # Check fallback user dictionary if present
        user_dict = getattr(request.state, "user", None)
        if isinstance(user_dict, dict):
            user_id = user_dict.get("id") or user_dict.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        user_uuid = UUID(str(user_id))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity",
        )

    user_query = select(User).where(User.id == user_uuid)
    result = await db.execute(user_query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    is_admin = bool(user.is_admin or getattr(user, "role", "") == "admin")
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return user


# ============================================================================
# OVERVIEW & DIAGNOSTICS ENDPOINTS
# ============================================================================


@router.get(
    "/overview",
    response_model=AdminOverviewResponse,
    summary="Get aggregated Overview statistics for the Admin Overview dashboard",
)
async def get_overview(
    request: Request,
    tenant_id: Optional[UUID] = Query(None, description="Optional tenant_id to scope metrics to a single workspace"),
    refresh: bool = Query(False, description="Force real-time recalculation of overview metrics"),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns aggregated metrics for the modernized Admin Overview dashboard:
    - total_users (count): Total registered users platform-wide (excl. widget & visitors)
    - total_agents (count): Total registered AI agents across all workspaces
    - active_endpoints (count): Total active API and agent endpoints
    - system_health: System health score in percentage (e.g. 99.4%)
    - total_knowledgebases: Total document and database knowledgebases
    - Detailed breakdowns, subsystem health statuses, and announcements
    """
    await _verify_admin_access(request, db)
    return await get_admin_overview_metrics(
        db=db,
        tenant_id=tenant_id,
        fastapi_app=request.app,
        force_refresh=refresh,
    )


@router.get(
    "/overview/health",
    response_model=SystemHealthDetails,
    summary="Get detailed real-time health diagnostics for platform subsystems",
)
async def get_health_diagnostics(
    request: Request,
    tenant_id: Optional[UUID] = Query(None, description="Optional tenant_id to scope diagnostics"),
    db: AsyncSession = Depends(get_db),
):
    """Probe PostgreSQL, Neo4j, Redis, LLM gateway and error logs for detailed health status."""
    await _verify_admin_access(request, db)
    return await get_system_health(db, tenant_id=tenant_id)


@router.get(
    "/overview/endpoints",
    response_model=List[EndpointItem],
    summary="List and search all active endpoints across the platform",
)
async def list_endpoints(
    request: Request,
    q: Optional[str] = Query(None, description="Search term for endpoint path or name"),
    tag: Optional[str] = Query(None, description="Filter endpoints by tag/category"),
    db: AsyncSession = Depends(get_db),
):
    """List active endpoints available in the system with optional search and tag filters."""
    await _verify_admin_access(request, db)
    endpoints = _extract_app_endpoints(request.app)

    results = endpoints
    if tag:
        tag_lower = tag.lower()
        results = [ep for ep in results if ep.tag.lower() == tag_lower]
    if q:
        q_lower = q.lower()
        results = [
            ep for ep in results
            if q_lower in ep.path.lower() or q_lower in ep.name.lower() or q_lower in ep.tag.lower()
        ]

    return results


# ============================================================================
# ANNOUNCEMENTS & BULLETINS CRUD
# ============================================================================


@router.get(
    "/announcements",
    response_model=List[AnnouncementResponse],
    summary="List all announcements and admin bulletins",
)
async def get_announcements(
    request: Request,
    tenant_id: Optional[UUID] = Query(None, description="Optional tenant_id filter"),
    db: AsyncSession = Depends(get_db),
):
    """List all active announcements for the platform or specific workspace."""
    await _verify_admin_access(request, db)
    records = await list_announcements(db, tenant_id)
    return [
        AnnouncementResponse(
            id=str(r.id),
            title=r.title,
            message=r.message,
            priority=r.priority,
            is_active=r.is_active,
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )
        for r in records
    ]


@router.post(
    "/announcements",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new admin announcement or bulletin",
)
async def post_announcement(
    data: AnnouncementCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new announcement."""
    await _verify_admin_access(request, db)
    tenant_id = _get_caller_tenant_id(request)
    record = await create_announcement(db, tenant_id, data)
    return AnnouncementResponse(
        id=str(record.id),
        title=record.title,
        message=record.message,
        priority=record.priority,
        is_active=record.is_active,
        created_at=record.created_at.isoformat() if record.created_at else "",
        updated_at=record.updated_at.isoformat() if record.updated_at else "",
    )


@router.put(
    "/announcements/{announcement_id}",
    response_model=AnnouncementResponse,
    summary="Update an existing admin announcement",
)
async def put_announcement(
    announcement_id: UUID,
    data: AnnouncementUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update an announcement by ID."""
    await _verify_admin_access(request, db)
    tenant_id = _get_caller_tenant_id(request)
    record = await update_announcement(db, tenant_id, announcement_id, data)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    return AnnouncementResponse(
        id=str(record.id),
        title=record.title,
        message=record.message,
        priority=record.priority,
        is_active=record.is_active,
        created_at=record.created_at.isoformat() if record.created_at else "",
        updated_at=record.updated_at.isoformat() if record.updated_at else "",
    )


@router.delete(
    "/announcements/{announcement_id}",
    summary="Delete an admin announcement",
)
async def remove_announcement(
    announcement_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete an announcement by ID."""
    await _verify_admin_access(request, db)
    tenant_id = _get_caller_tenant_id(request)
    deleted = await delete_announcement(db, tenant_id, announcement_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    return {"success": True, "message": "Announcement deleted successfully"}

