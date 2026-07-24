"""
Analytics Router - API endpoints for conversational intelligence.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from app.modules.chats.schemas import (
    FeedbackReasonsResponse,
    DrilldownFeedbackResponse,
    FeedbackOverviewResponse,
)

from ...core.database import AsyncSessionLocal
# REMOVED: from ...core.auth.middleware import get_current_tenant_id
from .schemas import (
    AnalyticsSummaryResponse, 
    AnalyticsSummaryCreate, 
    AnalyticsSummaryUpdate,
    AnalyticsQueryLogResponse,
    AnalyticsQueryLogCreate,
    DashboardMetrics,
    OperationalDashboardResponse,
    OperationalTrendResponse,
    CostGovernanceResponse,
    CapacityGovernanceResponse,
    AppErrorLogsPaginatedResponse,
    UserCostItem
)
from .repository import AnalyticsRepository
from .service import AnalyticsService

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])

# Dependency to extract tenant from request state (set by middleware)
async def get_current_tenant_id(request: Request) -> UUID:
    """
    Dependency to get tenant_id from request state.
    CRITICAL: TenantContextMiddleware MUST be active.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=401, 
            detail="Unauthorized: Missing tenant context"
        )
    return UUID(str(tenant_id))

# Dependency to get AnalyticsService
async def get_analytics_service(
    tenant_id: UUID = Depends(get_current_tenant_id),
):
    async with AsyncSessionLocal() as db:
        repo = AnalyticsRepository(db, tenant_id)
        service = AnalyticsService(repo)
        yield service
        await db.commit()

# ================= SUMMARY APIs =================

@router.post("", response_model=AnalyticsSummaryResponse)
async def create_analytics_summary(
    data: AnalyticsSummaryCreate,
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Create a new analytics summary record."""
    return await service.create_summary(data)

@router.get("", response_model=List[AnalyticsSummaryResponse])
async def list_analytics_summaries(
    skip: int = 0,
    limit: int = 100,
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Fetch paginated analytics summaries."""
    return await service.get_all_summaries(skip, limit)

# ================= ADVANCED ANALYTICS APIs =================

@router.get("/dashboard", response_model=DashboardMetrics)
async def get_analytics_dashboard(
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Get aggregated dashboard metrics for the tenant."""
    return await service.get_dashboard_metrics()

@router.get("/unanswered", response_model=List[AnalyticsQueryLogResponse])
async def get_unanswered_queries(
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Fetch recent queries that were unanswered or failed."""
    return await service.get_unanswered_logs()

@router.get("/query-log", response_model=List[AnalyticsQueryLogResponse])
async def list_query_logs(
    skip: int = 0,
    limit: int = 100,
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Fetch paginated query analytics logs."""
    return await service.repo.get_query_logs(skip, limit)

# ================= OPERATIONAL ANALYTICS APIs =================

@router.get("/operational/dashboard", response_model=OperationalDashboardResponse)
async def get_operational_dashboard(
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Get high-level KPIs for ingestion performance and fault tolerance."""
    return await service.get_operational_dashboard()

@router.get("/operational/trends", response_model=OperationalTrendResponse)
async def get_operational_trends(
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Get time-series data for extraction quality and pipeline resilience."""
    return await service.get_operational_trends()

# ================= GOVERNANCE APIs =================

@router.get("/governance/costs", response_model=CostGovernanceResponse)
async def get_cost_governance(
    user_id: Optional[UUID] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Get LLM token consumption and estimated costs."""
    return await service.get_cost_governance(user_id=user_id, start_date=start_date, end_date=end_date)

@router.get("/governance/costs/users", response_model=List[UserCostItem])
async def get_user_cost_governance(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Get DeepInfra LLM cost and token consumption breakdown per user."""
    return await service.get_user_cost_governance(start_date=start_date, end_date=end_date)

@router.get("/governance/capacity", response_model=CapacityGovernanceResponse)
async def get_capacity_governance(
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Get capacity projections and scaling metrics."""
    return await service.get_capacity_governance()

# ================= FEEDBACK ANALYTICS ENDPOINTS =================


@router.get(
    "/feedback-overview",
    response_model=FeedbackOverviewResponse,
    summary="Get overall positive/negative feedback statistics",
)
async def get_feedback_overview(
    request: Request,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
    kb_id: Optional[str] = None,
    model: Optional[str] = None,
):
    """
    Get positive (thumbs_up) and negative (thumbs_down) feedback counts and percentages.
    """
    from sqlalchemy import select, and_, func, or_
    from app.modules.auth.models import User
    from app.modules.knowledge_bases.models import KnowledgeBase
    from app.modules.chats.repository import safe_uuid
    from app.modules.chats.models import ChatMessage, ChatSession
    
    current_tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    
    if not current_tenant_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing user or tenant context"
        )
        
    async with AsyncSessionLocal() as db:
        # Validate admin role
        user_query = select(User).where(User.id == safe_uuid(user_id))
        user_res = await db.execute(user_query)
        db_user = user_res.scalar_one_or_none()
        if not db_user or (not db_user.is_admin and db_user.role != "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can access feedback analytics."
            )
            
        is_platform_admin = db_user.is_admin
        
        target_tenant_id = None
        if tenant_id:
            if not is_platform_admin and str(tenant_id) != str(current_tenant_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to access feedback analytics for other tenants."
                )
            target_tenant_id = safe_uuid(tenant_id)
        else:
            if not is_platform_admin:
                target_tenant_id = safe_uuid(current_tenant_id)
                
        # Build filters
        filters = [
            ChatMessage.feedback_type.in_(["thumbs_up", "thumbs_down"])
        ]
        
        if target_tenant_id:
            filters.append(ChatMessage.tenant_id == target_tenant_id)
            
        if start_date:
            filters.append(ChatMessage.feedback_at >= start_date)
        if end_date:
            filters.append(ChatMessage.feedback_at <= end_date)
            
        if model:
            filters.append(
                or_(
                    ChatMessage.message_metadata['model'].astext == model,
                    ChatMessage.message_metadata['stats']['model'].astext == model
                )
            )
            
        # Build query
        query = (
            select(
                ChatMessage.feedback_type,
                func.count(ChatMessage.id).label("total")
            )
            .where(and_(*filters))
        )
        
        if kb_id:
            query = query.join(ChatSession, ChatMessage.session_id == ChatSession.id)
            query = query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            query = query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        query = query.group_by(ChatMessage.feedback_type)
        
        result = await db.execute(query)
        rows = result.all()
        
        positive_count = 0
        negative_count = 0
        for r in rows:
            if r.feedback_type == "thumbs_up":
                positive_count = r.total
            elif r.feedback_type == "thumbs_down":
                negative_count = r.total
                
        total_count = positive_count + negative_count
        
        positive_pct = round((positive_count / total_count) * 100, 2) if total_count > 0 else 0.0
        negative_pct = round((negative_count / total_count) * 100, 2) if total_count > 0 else 0.0
        
        return {
            "success": True,
            "data": {
                "positive": {
                    "count": positive_count,
                    "percentage": positive_pct
                },
                "negative": {
                    "count": negative_count,
                    "percentage": negative_pct
                },
                "total": total_count
            }
        }


@router.get(
    "/feedback-reasons",
    response_model=FeedbackReasonsResponse,
    summary="Get summary of feedback reasons for analytics dashboard",
)
async def get_feedback_reasons(
    request: Request,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
    kb_id: Optional[str] = None,
    model: Optional[str] = None,
):
    """
    Get the most common feedback reasons along with their occurrence count and percentage.
    """
    from sqlalchemy import select, and_, func, or_
    from app.modules.auth.models import User
    from app.modules.knowledge_bases.models import KnowledgeBase
    from app.modules.chats.repository import safe_uuid
    from app.modules.chats.models import ChatMessage, ChatSession
    
    current_tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    
    if not current_tenant_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing user or tenant context"
        )
        
    async with AsyncSessionLocal() as db:
        # Validate admin role
        user_query = select(User).where(User.id == safe_uuid(user_id))
        user_res = await db.execute(user_query)
        db_user = user_res.scalar_one_or_none()
        if not db_user or (not db_user.is_admin and db_user.role != "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can access feedback analytics."
            )
            
        is_platform_admin = db_user.is_admin
        
        target_tenant_id = None
        if tenant_id:
            if not is_platform_admin and str(tenant_id) != str(current_tenant_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to access feedback analytics for other tenants."
                )
            target_tenant_id = safe_uuid(tenant_id)
        else:
            if not is_platform_admin:
                target_tenant_id = safe_uuid(current_tenant_id)
                
        # Build filters
        filters = [
            ChatMessage.feedback_type.in_(["thumbs_up", "thumbs_down"]),
            ChatMessage.feedback_reason.isnot(None)
        ]
        
        if target_tenant_id:
            filters.append(ChatMessage.tenant_id == target_tenant_id)
            
        if start_date:
            filters.append(ChatMessage.feedback_at >= start_date)
        if end_date:
            filters.append(ChatMessage.feedback_at <= end_date)
            
        if model:
            filters.append(
                or_(
                    ChatMessage.message_metadata['model'].astext == model,
                    ChatMessage.message_metadata['stats']['model'].astext == model
                )
            )
            
        # Build query
        query = (
            select(
                ChatMessage.feedback_type,
                ChatMessage.feedback_reason,
                func.count(ChatMessage.id).label("total")
            )
            .where(and_(*filters))
        )
        
        if kb_id:
            query = query.join(ChatSession, ChatMessage.session_id == ChatSession.id)
            query = query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            query = query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        query = query.group_by(ChatMessage.feedback_type, ChatMessage.feedback_reason).order_by(func.count(ChatMessage.id).desc())
        
        result = await db.execute(query)
        rows = result.all()
        
        grand_total = sum(r.total for r in rows)
        
        data = []
        for r in rows:
            pct = round((r.total / grand_total) * 100, 2) if grand_total > 0 else 0.0
            data.append({
                "feedback_type": r.feedback_type,
                "reason": r.feedback_reason,
                "count": r.total,
                "percentage": pct
            })
            
        return {
            "success": True,
            "data": data,
            "meta": {
                "total_feedback_count": grand_total
            }
        }


@router.get(
    "/feedback-drilldown",
    response_model=DrilldownFeedbackResponse,
    summary="Get detailed feedback records for drill-down view",
)
async def get_feedback_drilldown(
    request: Request,
    reason: str,
    feedback_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
    kb_id: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """
    Get detailed records of a specific feedback reason for administrators to drill down and investigate.
    """
    from sqlalchemy import select, and_, func, or_
    from app.modules.auth.models import User, Tenant
    from app.modules.knowledge_bases.models import KnowledgeBase
    from app.modules.chats.repository import safe_uuid
    from app.modules.chats.models import ChatMessage, ChatSession
    from app.modules.agents.models import Agent
    
    current_tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    
    if not current_tenant_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing user or tenant context"
        )
        
    async with AsyncSessionLocal() as db:
        # Validate admin role
        user_query = select(User).where(User.id == safe_uuid(user_id))
        user_res = await db.execute(user_query)
        db_user = user_res.scalar_one_or_none()
        if not db_user or (not db_user.is_admin and db_user.role != "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can access feedback analytics."
            )
            
        is_platform_admin = db_user.is_admin
        
        target_tenant_id = None
        if tenant_id:
            if not is_platform_admin and str(tenant_id) != str(current_tenant_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to access feedback analytics for other tenants."
                )
            target_tenant_id = safe_uuid(tenant_id)
        else:
            if not is_platform_admin:
                target_tenant_id = safe_uuid(current_tenant_id)
                
        # Build filters
        filters = [
            ChatMessage.feedback_type.in_(["thumbs_up", "thumbs_down"]),
            ChatMessage.feedback_reason == reason
        ]
        
        if target_tenant_id:
            filters.append(ChatMessage.tenant_id == target_tenant_id)
            
        if feedback_type:
            filters.append(ChatMessage.feedback_type == feedback_type)
            
        if start_date:
            filters.append(ChatMessage.feedback_at >= start_date)
        if end_date:
            filters.append(ChatMessage.feedback_at <= end_date)
            
        if model:
            filters.append(
                or_(
                    ChatMessage.message_metadata['model'].astext == model,
                    ChatMessage.message_metadata['stats']['model'].astext == model
                )
            )
            
        # Base query joining ChatSession, User, Tenant, and Agent
        query = (
            select(ChatMessage, ChatSession, User, Tenant, Agent)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .join(User, ChatSession.user_id == User.id)
            .join(Tenant, ChatSession.tenant_id == Tenant.id)
            .join(Agent, ChatSession.agent_id == Agent.id)
            .where(and_(*filters))
        )
        
        if kb_id:
            query = query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            query = query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        # Get total count for metadata pagination
        count_query = select(func.count(ChatMessage.id)).where(and_(*filters))
        if kb_id:
            count_query = count_query.join(ChatSession, ChatMessage.session_id == ChatSession.id)
            count_query = count_query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            count_query = count_query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        count_res = await db.execute(count_query)
        total_count = count_res.scalar() or 0
        
        # Paginated results
        query = query.order_by(ChatMessage.feedback_at.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        rows = result.all()
        
        # Fetch corresponding user questions in bulk
        user_msg_conditions = []
        for msg, _, _, _, _ in rows:
            user_msg_conditions.append(
                and_(
                    ChatMessage.session_id == msg.session_id,
                    ChatMessage.position == msg.position - 1
                )
            )
            
        user_msgs = {}
        if user_msg_conditions:
            user_msgs_query = select(ChatMessage).where(or_(*user_msg_conditions))
            user_msgs_res = await db.execute(user_msgs_query)
            for u_msg in user_msgs_res.scalars().all():
                user_msgs[(u_msg.session_id, u_msg.position)] = u_msg.content
                
        # Fetch associated Knowledge Bases in bulk
        agent_ids = list(set(session.agent_id for _, session, _, _, _ in rows))
        agent_kbs = {}
        if agent_ids:
            kbs_query = select(KnowledgeBase).where(KnowledgeBase.agent_id.in_(agent_ids))
            kbs_res = await db.execute(kbs_query)
            from collections import defaultdict
            agent_kbs = defaultdict(list)
            for kb in kbs_res.scalars().all():
                agent_kbs[kb.agent_id].append({
                    "id": str(kb.id),
                    "name": kb.name
                })
                
        # Format records
        records = []
        for msg, session, usr, tnt, agent in rows:
            question = user_msgs.get((msg.session_id, msg.position - 1), "Question not found")
            
            user_info = {
                "id": str(usr.id),
                "email": usr.email,
                "first_name": usr.first_name or "",
                "last_name": usr.last_name or ""
            }
            
            tenant_info = {
                "id": str(tnt.id),
                "name": tnt.name
            }
            
            agent_info = {
                "id": str(agent.id),
                "name": agent.name
            }
            
            kb_list = agent_kbs.get(session.agent_id, [])
            
            metadata = msg.message_metadata or {}
            retrieved_chunks = metadata.get("sources", [])
            citations = [c.get("source") for c in retrieved_chunks if c.get("source")]
            citations = list(set(citations))
            
            view_detail = {
                "session_id": str(session.id),
                "message_id": str(msg.id),
                "agent_id": str(session.agent_id),
                "retrieved_chunks": retrieved_chunks,
                "citations": citations,
                "metadata": metadata
            }
            
            records.append({
                "time": (msg.feedback_at or msg.created_at).isoformat(),
                "user": user_info,
                "tenant": tenant_info,
                "agent": agent_info,
                "knowledge_base": kb_list,
                "feedback_type": msg.feedback_type,
                "feedback_reason": msg.feedback_reason,
                "question": question,
                "ai_response": msg.content,
                "rating": msg.feedback_score,
                "view": view_detail
            })
            
        return {
            "success": True,
            "data": records,
            "meta": {
                "total": total_count,
                "limit": limit,
                "offset": offset
            }
        }


@router.get(
    "/error-logs",
    response_model=AppErrorLogsPaginatedResponse,
    summary="Get list of application error logs with filters",
)
async def get_error_logs(
    request: Request,
    module: Optional[str] = None,
    error_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """
    Retrieve application runtime and ingestion error logs with filtering and pagination.
    """
    from sqlalchemy import select, and_, func
    from app.modules.auth.models import User
    from app.modules.analytics.models import AppErrorLog
    from app.modules.chats.repository import safe_uuid
    
    current_tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    
    if not current_tenant_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing user or tenant context"
        )
        
    async with AsyncSessionLocal() as db:
        # Validate admin role
        user_query = select(User).where(User.id == safe_uuid(user_id))
        user_res = await db.execute(user_query)
        db_user = user_res.scalar_one_or_none()
        if not db_user or (not db_user.is_admin and db_user.role != "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can access diagnostic error logs."
            )
            
        is_platform_admin = db_user.is_admin
        
        target_tenant_id = None
        if tenant_id:
            if not is_platform_admin and str(tenant_id) != str(current_tenant_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to access logs for other tenants."
                )
            target_tenant_id = safe_uuid(tenant_id)
        else:
            if not is_platform_admin:
                target_tenant_id = safe_uuid(current_tenant_id)
                
        # Build filters
        filters = []
        if target_tenant_id:
            filters.append(AppErrorLog.tenant_id == target_tenant_id)
        elif not is_platform_admin:
            filters.append(AppErrorLog.tenant_id == safe_uuid(current_tenant_id))
            
        if module:
            filters.append(AppErrorLog.module == module)
        if error_type:
            filters.append(AppErrorLog.error_type == error_type)
        if start_date:
            filters.append(AppErrorLog.created_at >= start_date)
        if end_date:
            filters.append(AppErrorLog.created_at <= end_date)
            
        # Count query
        count_query = select(func.count(AppErrorLog.id))
        if filters:
            count_query = count_query.where(and_(*filters))
            
        count_res = await db.execute(count_query)
        total_count = count_res.scalar() or 0
        
        # Select query
        query = select(AppErrorLog)
        if filters:
            query = query.where(and_(*filters))
            
        query = query.order_by(AppErrorLog.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        rows = result.scalars().all()
        
        return {
            "success": True,
            "data": [
                {
                    "id": row.id,
                    "tenant_id": row.tenant_id,
                    "user_id": row.user_id,
                    "module": row.module,
                    "endpoint": row.endpoint,
                    "error_type": row.error_type,
                    "message": row.message,
                    "stack_trace": row.stack_trace,
                    "request_metadata": row.request_metadata,
                    "created_at": row.created_at
                }
                for row in rows
            ],
            "meta": {
                "total": total_count,
                "limit": limit,
                "offset": offset
            }
        }


@router.get(
    "/feedback-messages",
    response_model=DrilldownFeedbackResponse,
    summary="Get detailed feedback messages with filters",
)
async def get_feedback_messages(
    request: Request,
    feedback_reason: Optional[str] = None,
    feedback_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
    kb_id: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """
    Get list of chat messages where feedback_type is present, with filtering capabilities.
    """
    from sqlalchemy import select, and_, func, or_
    from app.modules.auth.models import User, Tenant
    from app.modules.knowledge_bases.models import KnowledgeBase
    from app.modules.chats.repository import safe_uuid
    from app.modules.chats.models import ChatMessage, ChatSession
    from app.modules.agents.models import Agent
    
    current_tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    
    if not current_tenant_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing user or tenant context"
        )
        
    async with AsyncSessionLocal() as db:
        # Validate admin role
        user_query = select(User).where(User.id == safe_uuid(user_id))
        user_res = await db.execute(user_query)
        db_user = user_res.scalar_one_or_none()
        if not db_user or (not db_user.is_admin and db_user.role != "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can access feedback analytics."
            )
            
        is_platform_admin = db_user.is_admin
        
        target_tenant_id = None
        if tenant_id:
            if not is_platform_admin and str(tenant_id) != str(current_tenant_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to access feedback analytics for other tenants."
                )
            target_tenant_id = safe_uuid(tenant_id)
        else:
            if not is_platform_admin:
                target_tenant_id = safe_uuid(current_tenant_id)
                
        # Build filters
        filters = [
            ChatMessage.feedback_type.isnot(None)
        ]
        
        if target_tenant_id:
            filters.append(ChatMessage.tenant_id == target_tenant_id)
            
        if feedback_type:
            filters.append(ChatMessage.feedback_type == feedback_type)
            
        if feedback_reason:
            filters.append(ChatMessage.feedback_reason == feedback_reason)
            
        if start_date:
            filters.append(ChatMessage.feedback_at >= start_date)
        if end_date:
            filters.append(ChatMessage.feedback_at <= end_date)
            
        if model:
            filters.append(
                or_(
                    ChatMessage.message_metadata['model'].astext == model,
                    ChatMessage.message_metadata['stats']['model'].astext == model
                )
            )
            
        # Base query joining ChatSession, User, Tenant, and Agent
        query = (
            select(ChatMessage, ChatSession, User, Tenant, Agent)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .join(User, ChatSession.user_id == User.id)
            .join(Tenant, ChatSession.tenant_id == Tenant.id)
            .join(Agent, ChatSession.agent_id == Agent.id)
            .where(and_(*filters))
        )
        
        if kb_id:
            query = query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            query = query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        # Get total count for metadata pagination
        count_query = select(func.count(ChatMessage.id)).where(and_(*filters))
        if kb_id:
            count_query = count_query.join(ChatSession, ChatMessage.session_id == ChatSession.id)
            count_query = count_query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            count_query = count_query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        count_res = await db.execute(count_query)
        total_count = count_res.scalar() or 0
        
        # Paginated results
        query = query.order_by(ChatMessage.feedback_at.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        rows = result.all()
        
        # Fetch corresponding user questions in bulk
        user_msg_conditions = []
        for msg, _, _, _, _ in rows:
            user_msg_conditions.append(
                and_(
                    ChatMessage.session_id == msg.session_id,
                    ChatMessage.position == msg.position - 1
                )
            )
            
        user_msgs = {}
        if user_msg_conditions:
            user_msgs_query = select(ChatMessage).where(or_(*user_msg_conditions))
            user_msgs_res = await db.execute(user_msgs_query)
            for u_msg in user_msgs_res.scalars().all():
                user_msgs[(u_msg.session_id, u_msg.position)] = u_msg.content
                
        # Fetch associated Knowledge Bases in bulk
        agent_ids = list(set(session.agent_id for _, session, _, _, _ in rows))
        agent_kbs = {}
        if agent_ids:
            kbs_query = select(KnowledgeBase).where(KnowledgeBase.agent_id.in_(agent_ids))
            kbs_res = await db.execute(kbs_query)
            from collections import defaultdict
            agent_kbs = defaultdict(list)
            for kb in kbs_res.scalars().all():
                agent_kbs[kb.agent_id].append({
                    "id": str(kb.id),
                    "name": kb.name
                })
                
        # Format records
        records = []
        for msg, session, usr, tnt, agent in rows:
            question = user_msgs.get((msg.session_id, msg.position - 1), "Question not found")
            
            user_info = {
                "id": str(usr.id),
                "email": usr.email,
                "first_name": usr.first_name or "",
                "last_name": usr.last_name or ""
            }
            
            tenant_info = {
                "id": str(tnt.id),
                "name": tnt.name
            }
            
            agent_info = {
                "id": str(agent.id),
                "name": agent.name
            }
            
            kb_list = agent_kbs.get(session.agent_id, [])
            
            metadata = msg.message_metadata or {}
            retrieved_chunks = metadata.get("sources", [])
            citations = [c.get("source") for c in retrieved_chunks if c.get("source")]
            citations = list(set(citations))
            
            view_detail = {
                "session_id": str(session.id),
                "message_id": str(msg.id),
                "agent_id": str(session.agent_id),
                "retrieved_chunks": retrieved_chunks,
                "citations": citations,
                "metadata": metadata
            }
            
            records.append({
                "time": (msg.feedback_at or msg.created_at).isoformat(),
                "user": user_info,
                "tenant": tenant_info,
                "agent": agent_info,
                "knowledge_base": kb_list,
                "feedback_type": msg.feedback_type,
                "feedback_reason": msg.feedback_reason,
                "question": question,
                "ai_response": msg.content,
                "rating": msg.feedback_score,
                "view": view_detail
            })
            
        return {
            "success": True,
            "data": records,
            "meta": {
                "total": total_count,
                "limit": limit,
                "offset": offset
            }
        }


# ================= SUMMARY APIs =================

@router.get("/{id}", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    id: UUID,
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Fetch a single analytics summary by ID."""
    summary = await service.get_summary(id)
    if not summary:
        raise HTTPException(status_code=404, detail="Analytics summary not found")
    return summary

@router.put("/{id}", response_model=AnalyticsSummaryResponse)
async def update_analytics_summary(
    id: UUID,
    data: AnalyticsSummaryUpdate,
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Update an existing analytics summary."""
    summary = await service.update_summary(id, data)
    if not summary:
        raise HTTPException(status_code=404, detail="Analytics summary not found")
    return summary

@router.delete("/{id}")
async def delete_analytics_summary(
    id: UUID,
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Soft delete (remove) an analytics summary."""
    success = await service.delete_summary(id)
    if not success:
        raise HTTPException(status_code=404, detail="Analytics summary not found")
    return {"status": "deleted"}

# ================= QUERY LOG APIs =================

@router.post("/query-log", response_model=AnalyticsQueryLogResponse)
async def log_query_analytics(
    data: AnalyticsQueryLogCreate,
    service: AnalyticsService = Depends(get_analytics_service)
):
    """Log an individual query's analytics."""
    return await service.log_query(data)




