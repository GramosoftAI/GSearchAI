"""SuperAdmin Global AI Agent Governance Service.

Provides platform-wide administration for AI agents across all customer organizations:
- Global cross-tenant agent directory with search, filtering, and health assessment
- Agent configuration and associated knowledgebases inspection
- Operational health, error diagnostics, and failure rate analysis
- Agent usage telemetry and LLM cost attribution
- Identification of agents with repeated failures
- Controlled agent activation/deactivation
- Authorized agent ownership transfers across users and tenants
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status, Request
import logging

from app.modules.agents.models import Agent
from app.modules.auth.models import Tenant, User
from app.modules.knowledge_bases.models import KnowledgeBase
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseKnowledgebase
from app.modules.chats.models import ChatSession, ChatMessage
from app.modules.analytics.models import AppErrorLog, AnalyticsQueryLog, ResponseStatus
from app.modules.personalities.models import Personality
from ..models import SuperAdminUser
from ..schemas import (
    SuperAdminAgentListItem,
    SuperAdminAgentListResponse,
    SuperAdminAgentDetailResponse,
    SuperAdminAgentKBItem,
    AgentHealthResponse,
    AgentErrorItem,
    AgentUsageResponse,
    FailingAgentItem,
)
from ..dependencies import log_admin_activity

logger = logging.getLogger(__name__)


class AgentGovernanceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_agents(
        self,
        search: Optional[str] = None,
        tenant_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        is_active: Optional[bool] = None,
        agent_type: Optional[str] = None,
        has_errors: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SuperAdminAgentListResponse:
        """List all AI agents across tenants with multi-parameter filtering and operational stats."""
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        query = select(
            Agent,
            Tenant.name.label("tenant_name"),
            Tenant.slug.label("tenant_slug"),
            User.email.label("user_email"),
        ).join(
            Tenant, Agent.tenant_id == Tenant.id
        ).join(
            User, Agent.user_id == User.id
        )

        if tenant_id:
            query = query.where(Agent.tenant_id == tenant_id)
        if user_id:
            query = query.where(Agent.user_id == user_id)
        if is_active is not None:
            query = query.where(Agent.is_active == is_active)
        if agent_type:
            query = query.where(Agent.agent_type == agent_type)
        if search:
            s = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(Agent.name).like(s),
                    func.lower(Agent.description).like(s),
                    func.lower(Agent.personality).like(s),
                    func.lower(Agent.brand_persona).like(s),
                )
            )

        # Count total
        count_q = select(func.count()).select_from(query.subquery())
        total_res = await self.db.execute(count_q)
        total = total_res.scalar_one()

        # Fetch page
        query = query.order_by(desc(Agent.created_at)).offset(offset).limit(page_size)
        res = await self.db.execute(query)
        rows = res.all()

        agent_items: List[SuperAdminAgentListItem] = []
        now = datetime.now(timezone.utc)
        since_24h = now - timedelta(hours=24)

        for row in rows:
            agent_rec: Agent = row[0]
            t_name = row[1] or "Unknown Organization"
            t_slug = row[2] or "unknown"
            u_email = row[3] or "unknown"

            # 1. Count associated document KBs
            kb_count_q = select(func.count(KnowledgeBase.id)).where(
                KnowledgeBase.agent_id == agent_rec.id,
                KnowledgeBase.is_active == True,
            )
            kb_res = await self.db.execute(kb_count_q)
            kb_count = kb_res.scalar_one() or 0

            # 2. Count total sessions and queries
            session_ids_q = select(ChatSession.id).where(ChatSession.agent_id == agent_rec.id)
            total_queries_q = select(func.count(ChatMessage.id)).where(
                ChatMessage.session_id.in_(session_ids_q),
                ChatMessage.role == "user",
            )
            queries_res = await self.db.execute(total_queries_q)
            total_queries = queries_res.scalar_one() or 0

            # 3. Count errors in last 24h
            err_count_q = select(func.count(AppErrorLog.id)).where(
                AppErrorLog.tenant_id == agent_rec.tenant_id,
                AppErrorLog.created_at >= since_24h,
                func.lower(AppErrorLog.message).like(f"%{str(agent_rec.id).lower()}%")
            )
            err_res = await self.db.execute(err_count_q)
            err_count_24h = err_res.scalar_one() or 0

            # Evaluate health status
            if err_count_24h >= 5:
                health = "CRITICAL"
            elif err_count_24h > 0:
                health = "WARNING"
            else:
                health = "HEALTHY"

            if has_errors is True and err_count_24h == 0:
                continue

            agent_items.append(
                SuperAdminAgentListItem(
                    id=agent_rec.id,
                    name=agent_rec.name,
                    description=agent_rec.description,
                    personality=agent_rec.personality,
                    agent_type=agent_rec.agent_type,
                    is_active=agent_rec.is_active,
                    tenant_id=agent_rec.tenant_id,
                    tenant_name=t_name,
                    tenant_slug=t_slug,
                    user_id=agent_rec.user_id,
                    user_email=u_email,
                    knowledgebase_count=kb_count,
                    total_queries=total_queries,
                    error_count_24h=err_count_24h,
                    health_status=health,
                    created_at=agent_rec.created_at,
                    updated_at=agent_rec.updated_at,
                )
            )

        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        return SuperAdminAgentListResponse(
            agents=agent_items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def get_agent_detail(self, agent_id: UUID) -> SuperAdminAgentDetailResponse:
        """Fetch complete agent configuration, associated knowledgebases, and operational stats."""
        query = select(
            Agent,
            Tenant.name.label("tenant_name"),
            Tenant.slug.label("tenant_slug"),
            User.email.label("user_email"),
        ).join(
            Tenant, Agent.tenant_id == Tenant.id
        ).join(
            User, Agent.user_id == User.id
        ).where(Agent.id == agent_id)

        res = await self.db.execute(query)
        row = res.first()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent with ID {agent_id} not found."
            )

        agent_rec: Agent = row[0]
        tenant_name = row[1] or "Unknown Organization"
        tenant_slug = row[2] or "unknown"
        user_email = row[3] or "unknown"

        # 1. Associated Document Knowledgebases
        kb_q = select(KnowledgeBase).where(
            KnowledgeBase.agent_id == agent_rec.id,
            KnowledgeBase.is_active == True,
        ).order_by(desc(KnowledgeBase.created_at))
        kb_res = await self.db.execute(kb_q)
        kb_rows = kb_res.scalars().all()

        kb_items = [
            SuperAdminAgentKBItem(
                id=kb.id,
                name=kb.name,
                source=kb.source,
                total_chunks=kb.total_chunks or 0,
                is_active=kb.is_active,
                created_at=kb.created_at,
            )
            for kb in kb_rows
        ]

        # 2. Associated Database Knowledgebases
        db_kb_q = select(DatabaseKnowledgebase).where(
            DatabaseKnowledgebase.agent_id == agent_rec.id,
            DatabaseKnowledgebase.is_active == True,
        ).order_by(desc(DatabaseKnowledgebase.created_at))
        db_kb_res = await self.db.execute(db_kb_q)
        db_kb_rows = db_kb_res.scalars().all()

        db_kb_items = [
            {
                "id": str(dkb.id),
                "name": dkb.name,
                "database_type": dkb.database_type,
                "status": dkb.status,
                "schema_version": dkb.schema_version,
                "is_active": dkb.is_active,
                "created_at": dkb.created_at.isoformat() if dkb.created_at else None,
            }
            for dkb in db_kb_rows
        ]

        # 3. Usage & Operational Telemetry
        session_subq = select(ChatSession.id).where(ChatSession.agent_id == agent_rec.id).subquery()
        total_sessions_q = select(func.count(ChatSession.id)).where(ChatSession.agent_id == agent_rec.id)
        sess_count = (await self.db.execute(total_sessions_q)).scalar_one() or 0

        total_queries_q = select(func.count(ChatMessage.id)).where(
            ChatMessage.session_id.in_(select(session_subq)),
            ChatMessage.role == "user",
        )
        query_count = (await self.db.execute(total_queries_q)).scalar_one() or 0

        # Query analytics logs for tokens, cost, latency
        usage_q = select(
            func.coalesce(func.sum(AnalyticsQueryLog.total_tokens), 0),
            func.coalesce(func.sum(AnalyticsQueryLog.total_cost_usd), 0.0),
            func.coalesce(func.avg(AnalyticsQueryLog.latency_ms), 0.0),
        ).where(AnalyticsQueryLog.session_id.in_(select(session_subq)))
        usage_res = await self.db.execute(usage_q)
        u_row = usage_res.first()
        total_tokens = int(u_row[0]) if u_row else 0
        total_cost_usd = round(float(u_row[1]), 4) if u_row else 0.0
        avg_latency_ms = round(float(u_row[2]), 2) if u_row else 0.0

        # Errors in last 24h
        now = datetime.now(timezone.utc)
        since_24h = now - timedelta(hours=24)
        err_count_q = select(func.count(AppErrorLog.id)).where(
            AppErrorLog.tenant_id == agent_rec.tenant_id,
            AppErrorLog.created_at >= since_24h,
            func.lower(AppErrorLog.message).like(f"%{str(agent_rec.id).lower()}%")
        )
        err_24h = (await self.db.execute(err_count_q)).scalar_one() or 0

        if err_24h >= 5:
            health = "CRITICAL"
        elif err_24h > 0:
            health = "WARNING"
        else:
            health = "HEALTHY"

        return SuperAdminAgentDetailResponse(
            id=agent_rec.id,
            name=agent_rec.name,
            description=agent_rec.description,
            personality=agent_rec.personality,
            personality_id=agent_rec.personality_id,
            system_prompt=agent_rec.system_prompt,
            agent_type=agent_rec.agent_type,
            organization_name=agent_rec.organization_name,
            contact_phone=agent_rec.contact_phone,
            contact_email=agent_rec.contact_email,
            website_url=agent_rec.website_url,
            fallback_message_enabled=agent_rec.fallback_message_enabled,
            brand_persona=agent_rec.brand_persona,
            is_active=agent_rec.is_active,
            tenant_id=agent_rec.tenant_id,
            tenant_name=tenant_name,
            tenant_slug=tenant_slug,
            user_id=agent_rec.user_id,
            user_email=user_email,
            knowledgebases=kb_items,
            database_knowledgebases=db_kb_items,
            total_sessions=sess_count,
            total_queries=query_count,
            total_tokens=total_tokens,
            total_cost_usd=total_cost_usd,
            avg_latency_ms=avg_latency_ms,
            error_count_24h=err_24h,
            health_status=health,
            created_at=agent_rec.created_at,
            updated_at=agent_rec.updated_at,
        )

    async def update_agent_status(
        self,
        agent_id: UUID,
        is_active: bool,
        reason: str,
        admin: SuperAdminUser,
        request: Optional[Request] = None,
    ) -> Dict[str, Any]:
        """Activate or deactivate an AI agent with audit logging."""
        agent = await self.db.get(Agent, agent_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent with ID {agent_id} not found."
            )

        old_status = agent.is_active
        agent.is_active = is_active
        if not is_active:
            agent.deleted_at = datetime.now(timezone.utc)
        else:
            agent.deleted_at = None

        self.db.add(agent)
        await self.db.commit()

        action = "ACTIVATE_AGENT" if is_active else "DEACTIVATE_AGENT"
        await log_admin_activity(
            db=self.db,
            admin=admin,
            action=action,
            resource_type="agent",
            resource_id=str(agent_id),
            target_tenant_id=agent.tenant_id,
            details={
                "agent_name": agent.name,
                "previous_status": old_status,
                "new_status": is_active,
                "reason": reason,
            },
            status_val="SUCCESS",
            request=request,
        )

        return {
            "agent_id": str(agent_id),
            "name": agent.name,
            "is_active": is_active,
            "message": f"Agent '{agent.name}' successfully {'activated' if is_active else 'deactivated'}."
        }

    async def get_agent_health(self, agent_id: UUID) -> AgentHealthResponse:
        """Inspect agent errors and operational health."""
        agent = await self.db.get(Agent, agent_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent with ID {agent_id} not found."
            )

        tenant = await self.db.get(Tenant, agent.tenant_id)
        tenant_name = tenant.name if tenant else "Unknown"

        now = datetime.now(timezone.utc)
        since_24h = now - timedelta(hours=24)
        since_7d = now - timedelta(days=7)

        # Sessions for this agent
        session_subq = select(ChatSession.id).where(ChatSession.agent_id == agent.id).subquery()

        # 24h queries
        q_24h_q = select(func.count(AnalyticsQueryLog.id)).where(
            AnalyticsQueryLog.session_id.in_(select(session_subq)),
            AnalyticsQueryLog.created_at >= since_24h,
        )
        total_queries_24h = (await self.db.execute(q_24h_q)).scalar_one() or 0

        # 24h successful queries
        success_24h_q = select(func.count(AnalyticsQueryLog.id)).where(
            AnalyticsQueryLog.session_id.in_(select(session_subq)),
            AnalyticsQueryLog.created_at >= since_24h,
            AnalyticsQueryLog.response_status == ResponseStatus.SUCCESS,
        )
        success_24h = (await self.db.execute(success_24h_q)).scalar_one() or 0
        success_rate = round((success_24h / total_queries_24h * 100), 2) if total_queries_24h > 0 else 100.0

        # Errors in 24h and 7d from AppErrorLog
        err_24h_q = select(func.count(AppErrorLog.id)).where(
            AppErrorLog.tenant_id == agent.tenant_id,
            AppErrorLog.created_at >= since_24h,
            func.lower(AppErrorLog.message).like(f"%{str(agent.id).lower()}%")
        )
        error_count_24h = (await self.db.execute(err_24h_q)).scalar_one() or 0

        err_7d_q = select(func.count(AppErrorLog.id)).where(
            AppErrorLog.tenant_id == agent.tenant_id,
            AppErrorLog.created_at >= since_7d,
            func.lower(AppErrorLog.message).like(f"%{str(agent.id).lower()}%")
        )
        error_count_7d = (await self.db.execute(err_7d_q)).scalar_one() or 0

        # Fetch recent errors
        recent_err_q = select(AppErrorLog).where(
            AppErrorLog.tenant_id == agent.tenant_id,
            AppErrorLog.created_at >= since_7d,
            func.lower(AppErrorLog.message).like(f"%{str(agent.id).lower()}%")
        ).order_by(desc(AppErrorLog.created_at)).limit(10)

        err_res = await self.db.execute(recent_err_q)
        err_rows = err_res.scalars().all()

        last_error_at = err_rows[0].created_at if err_rows else None
        recent_error_items = [
            AgentErrorItem(
                id=e.id,
                module=e.module,
                endpoint=e.endpoint,
                error_type=e.error_type,
                message=e.message,
                stack_trace=e.stack_trace,
                created_at=e.created_at,
            )
            for e in err_rows
        ]

        if error_count_24h >= 5 or success_rate < 80.0:
            health = "CRITICAL"
        elif error_count_24h > 0 or success_rate < 95.0:
            health = "WARNING"
        else:
            health = "HEALTHY"

        return AgentHealthResponse(
            agent_id=agent.id,
            name=agent.name,
            tenant_id=agent.tenant_id,
            tenant_name=tenant_name,
            health_status=health,
            success_rate=success_rate,
            total_queries_24h=total_queries_24h,
            error_count_24h=error_count_24h,
            error_count_7d=error_count_7d,
            last_error_at=last_error_at,
            recent_errors=recent_error_items,
        )

    async def get_agent_usage(self, agent_id: UUID) -> AgentUsageResponse:
        """Fetch agent usage and query statistics."""
        agent = await self.db.get(Agent, agent_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent with ID {agent_id} not found."
            )

        tenant = await self.db.get(Tenant, agent.tenant_id)
        tenant_name = tenant.name if tenant else "Unknown"

        session_subq = select(ChatSession.id).where(ChatSession.agent_id == agent.id).subquery()
        sess_count_q = select(func.count(ChatSession.id)).where(ChatSession.agent_id == agent.id)
        total_sessions = (await self.db.execute(sess_count_q)).scalar_one() or 0

        usage_q = select(
            func.count(AnalyticsQueryLog.id),
            func.coalesce(func.sum(AnalyticsQueryLog.llm_input_tokens), 0),
            func.coalesce(func.sum(AnalyticsQueryLog.llm_output_tokens), 0),
            func.coalesce(func.sum(AnalyticsQueryLog.embedding_tokens), 0),
            func.coalesce(func.sum(AnalyticsQueryLog.total_tokens), 0),
            func.coalesce(func.sum(AnalyticsQueryLog.total_cost_usd), 0.0),
            func.coalesce(func.avg(AnalyticsQueryLog.latency_ms), 0.0),
        ).where(AnalyticsQueryLog.session_id.in_(select(session_subq)))

        u_res = await self.db.execute(usage_q)
        u_row = u_res.first()

        total_queries = int(u_row[0]) if u_row else 0
        input_tokens = int(u_row[1]) if u_row else 0
        output_tokens = int(u_row[2]) if u_row else 0
        emb_tokens = int(u_row[3]) if u_row else 0
        total_tokens = int(u_row[4]) if u_row else 0
        total_cost = round(float(u_row[5]), 4) if u_row else 0.0
        avg_latency = round(float(u_row[6]), 2) if u_row else 0.0

        return AgentUsageResponse(
            agent_id=agent.id,
            name=agent.name,
            tenant_id=agent.tenant_id,
            tenant_name=tenant_name,
            total_sessions=total_sessions,
            total_queries=total_queries,
            total_tokens=total_tokens,
            llm_input_tokens=input_tokens,
            llm_output_tokens=output_tokens,
            embedding_tokens=emb_tokens,
            total_cost_usd=total_cost,
            avg_latency_ms=avg_latency,
        )

    async def get_failing_agents(
        self,
        threshold: int = 3,
        timeframe_hours: int = 24,
        page: int = 1,
        page_size: int = 20,
    ) -> List[FailingAgentItem]:
        """Identify agents with repeated operational failures or elevated error rates."""
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        now = datetime.now(timezone.utc)
        since_time = now - timedelta(hours=timeframe_hours)

        # Find agents where error logs exist in this timeframe
        agents_q = select(
            Agent,
            Tenant.name.label("tenant_name"),
            User.email.label("user_email"),
        ).join(
            Tenant, Agent.tenant_id == Tenant.id
        ).join(
            User, Agent.user_id == User.id
        ).where(Agent.is_active == True)

        res = await self.db.execute(agents_q)
        all_agents = res.all()

        failing_items: List[FailingAgentItem] = []

        for row in all_agents:
            agent_rec: Agent = row[0]
            t_name = row[1] or "Unknown"
            u_email = row[2] or "unknown"

            # Query errors in timeframe
            err_q = select(AppErrorLog).where(
                AppErrorLog.tenant_id == agent_rec.tenant_id,
                AppErrorLog.created_at >= since_time,
                func.lower(AppErrorLog.message).like(f"%{str(agent_rec.id).lower()}%")
            ).order_by(desc(AppErrorLog.created_at))

            err_res = await self.db.execute(err_q)
            errors = err_res.scalars().all()
            err_count = len(errors)

            if err_count >= threshold:
                session_subq = select(ChatSession.id).where(ChatSession.agent_id == agent_rec.id).subquery()
                total_q = select(func.count(AnalyticsQueryLog.id)).where(
                    AnalyticsQueryLog.session_id.in_(select(session_subq)),
                    AnalyticsQueryLog.created_at >= since_time,
                )
                queries_count = (await self.db.execute(total_q)).scalar_one() or 0
                failure_rate = round((err_count / (queries_count + err_count) * 100), 2) if (queries_count + err_count) > 0 else 100.0

                last_err = errors[0] if errors else None
                error_types = list(set([e.error_type for e in errors]))[:5]

                failing_items.append(
                    FailingAgentItem(
                        agent_id=agent_rec.id,
                        name=agent_rec.name,
                        tenant_id=agent_rec.tenant_id,
                        tenant_name=t_name,
                        owner_email=u_email,
                        error_count_24h=err_count,
                        total_queries_24h=queries_count,
                        failure_rate_percent=failure_rate,
                        last_error_message=last_err.message if last_err else None,
                        last_error_at=last_err.created_at if last_err else None,
                        primary_error_types=error_types,
                    )
                )

        failing_items.sort(key=lambda x: x.error_count_24h, reverse=True)
        offset = (page - 1) * page_size
        return failing_items[offset : offset + page_size]

    async def transfer_agent_ownership(
        self,
        agent_id: UUID,
        new_user_id: UUID,
        target_tenant_id: Optional[UUID],
        reason: str,
        authorization_reference: str,
        admin: SuperAdminUser,
        request: Optional[Request] = None,
    ) -> Dict[str, Any]:
        """Manage agent ownership under authorized policies with audit verification."""
        agent = await self.db.get(Agent, agent_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent with ID {agent_id} not found."
            )

        new_user = await self.db.get(User, new_user_id)
        if not new_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Target user with ID {new_user_id} not found."
            )

        old_user_id = agent.user_id
        old_tenant_id = agent.tenant_id

        # If cross-tenant transfer
        if target_tenant_id and target_tenant_id != agent.tenant_id:
            target_tenant = await self.db.get(Tenant, target_tenant_id)
            if not target_tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Target tenant with ID {target_tenant_id} not found."
                )
            if new_user.tenant_id != target_tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Target user {new_user.email} does not belong to target tenant {target_tenant.name}."
                )
            agent.tenant_id = target_tenant_id
            
            # Cascade update associated document KBs to new tenant
            await self.db.execute(
                select(KnowledgeBase).where(KnowledgeBase.agent_id == agent.id)
            )
            # Update KBs tenant_id
            kb_list_q = select(KnowledgeBase).where(KnowledgeBase.agent_id == agent.id)
            kbs_res = await self.db.execute(kb_list_q)
            for kb in kbs_res.scalars().all():
                kb.tenant_id = target_tenant_id
                kb.user_id = new_user_id
                self.db.add(kb)

        agent.user_id = new_user_id
        self.db.add(agent)
        await self.db.commit()

        await log_admin_activity(
            db=self.db,
            admin=admin,
            action="TRANSFER_AGENT_OWNERSHIP",
            resource_type="agent",
            resource_id=str(agent_id),
            target_tenant_id=agent.tenant_id,
            details={
                "agent_name": agent.name,
                "previous_user_id": str(old_user_id),
                "new_user_id": str(new_user_id),
                "previous_tenant_id": str(old_tenant_id),
                "new_tenant_id": str(agent.tenant_id),
                "authorization_reference": authorization_reference,
                "reason": reason,
            },
            status_val="SUCCESS",
            request=request,
        )

        return {
            "agent_id": str(agent_id),
            "name": agent.name,
            "new_user_id": str(new_user_id),
            "new_tenant_id": str(agent.tenant_id),
            "authorization_reference": authorization_reference,
            "message": f"Ownership of agent '{agent.name}' successfully transferred."
        }
