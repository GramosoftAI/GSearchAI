"""SuperAdmin Customer User Management Service across all tenants.

Provides:
- Cross-tenant user search, filtering, and profile inspection
- Activation, deactivation, temporary locking, and unlocking
- Password reset trigger and session/refresh token revocation
- Tenant role adjustment and authorized cross-organization transfers
- User-specific AI usage, costs, and comprehensive activity history
- Strict audit logging for all customer account interventions
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple, Dict, Any
from uuid import UUID
from sqlalchemy import select, func, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status, Request
import logging

from app.modules.auth.models import (
    User,
    Tenant,
    APIKey,
    TokenBlacklist,
    PasswordResetToken,
)
from app.modules.superadmin.models import SuperAdminUser
from app.modules.superadmin.schemas import (
    CustomerUserListItem,
    CustomerUserProfileResponse,
    CustomerUserStats,
    CustomerUserAIUsageResponse,
    CustomerUserActivityItem,
    CustomerUserActivityResponse,
    ModelUsageBreakdown,
)
from app.modules.superadmin.dependencies import log_admin_activity
from app.modules.superadmin.security import hash_token

logger = logging.getLogger(__name__)


class CustomerUserService:
    """Service providing global user administration across all customer organizations."""

    @staticmethod
    async def list_users(
        db: AsyncSession,
        search: Optional[str] = None,
        tenant_id: Optional[UUID] = None,
        role: Optional[str] = None,
        status_filter: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[CustomerUserListItem], int]:
        """
        Global cross-tenant user query with search, tenant filter, role filter,
        and status filter (active, inactive, locked).
        """
        now = datetime.now(timezone.utc)
        query = (
            select(
                User,
                Tenant.name.label("tenant_name"),
                Tenant.slug.label("tenant_slug"),
            )
            .join(Tenant, User.tenant_id == Tenant.id)
        )
        count_query = select(func.count(User.id)).join(Tenant, User.tenant_id == Tenant.id)

        # 1. Search Filter (email, name, or UUID)
        if search:
            clean_search = search.strip()
            # Check if valid UUID string
            try:
                search_uuid = UUID(clean_search)
                query = query.where(User.id == search_uuid)
                count_query = count_query.where(User.id == search_uuid)
            except ValueError:
                search_like = f"%{clean_search}%"
                search_condition = (
                    User.email.ilike(search_like)
                    | User.first_name.ilike(search_like)
                    | User.last_name.ilike(search_like)
                    | Tenant.name.ilike(search_like)
                )
                query = query.where(search_condition)
                count_query = count_query.where(search_condition)

        # 2. Tenant Filter
        if tenant_id:
            query = query.where(User.tenant_id == tenant_id)
            count_query = count_query.where(User.tenant_id == tenant_id)

        # 3. Role Filter ("admin", "user")
        if role:
            clean_role = role.strip().lower()
            if clean_role == "admin":
                query = query.where(User.is_admin == True)
                count_query = count_query.where(User.is_admin == True)
            elif clean_role == "user":
                query = query.where(User.is_admin == False)
                count_query = count_query.where(User.is_admin == False)

        # 4. Status Filter ("active", "inactive", "locked")
        if status_filter:
            clean_status = status_filter.strip().lower()
            if clean_status == "active":
                query = query.where(
                    User.is_active == True,
                    (User.locked_until == None) | (User.locked_until <= now),
                )
                count_query = count_query.where(
                    User.is_active == True,
                    (User.locked_until == None) | (User.locked_until <= now),
                )
            elif clean_status == "inactive":
                query = query.where(User.is_active == False)
                count_query = count_query.where(User.is_active == False)
            elif clean_status == "locked":
                query = query.where(User.locked_until > now)
                count_query = count_query.where(User.locked_until > now)

        # Execute total count
        total_res = await db.execute(count_query)
        total = total_res.scalar() or 0

        # Execute paginated query
        query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        rows = result.all()

        items: List[CustomerUserListItem] = []
        for user_obj, t_name, t_slug in rows:
            is_locked = bool(user_obj.locked_until and user_obj.locked_until > now)
            items.append(
                CustomerUserListItem(
                    id=user_obj.id,
                    email=user_obj.email,
                    first_name=user_obj.first_name,
                    last_name=user_obj.last_name,
                    role="admin" if user_obj.is_admin else "user",
                    is_active=user_obj.is_active,
                    is_locked=is_locked,
                    locked_until=user_obj.locked_until,
                    lock_reason=getattr(user_obj, "lock_reason", None),
                    tenant_id=user_obj.tenant_id,
                    tenant_name=t_name or "Unknown Organization",
                    tenant_slug=t_slug or "unknown",
                    preferred_llm_model=user_obj.preferred_llm_model,
                    created_at=user_obj.created_at,
                    last_login_at=getattr(user_obj, "last_login_at", None),
                )
            )

        return items, total

    @staticmethod
    async def get_user_profile(user_id: UUID, db: AsyncSession) -> CustomerUserProfileResponse:
        """Fetch complete customer user profile, tenant information, and cross-system stats."""
        query = (
            select(
                User,
                Tenant.name.label("tenant_name"),
                Tenant.slug.label("tenant_slug"),
                Tenant.is_active.label("tenant_is_active"),
            )
            .join(Tenant, User.tenant_id == Tenant.id)
            .where(User.id == user_id)
        )
        result = await db.execute(query)
        row = result.first()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer user with ID {user_id} not found across any organization.",
            )

        user_obj, t_name, t_slug, t_active = row
        now = datetime.now(timezone.utc)
        is_locked = bool(user_obj.locked_until and user_obj.locked_until > now)

        # 1. Chat Sessions & Messages Count
        chat_sess_count = 0
        chat_msg_count = 0
        try:
            sess_q = await db.execute(
                text("SELECT COUNT(*) FROM chat_sessions WHERE user_id = :u_id"),
                {"u_id": str(user_id)},
            )
            chat_sess_count = sess_q.scalar() or 0

            msg_q = await db.execute(
                text("""
                    SELECT COUNT(*) 
                    FROM chat_messages m
                    JOIN chat_sessions s ON m.session_id = s.id
                    WHERE s.user_id = :u_id
                """),
                {"u_id": str(user_id)},
            )
            chat_msg_count = msg_q.scalar() or 0
        except Exception as e:
            logger.warning(f"Error reading chat stats for user {user_id}: {e}")

        # 2. AI Usage & Token Spend
        total_queries = 0
        total_tokens = 0
        total_cost_usd = 0.0
        try:
            usage_q = await db.execute(
                text("""
                    SELECT 
                        COUNT(*), 
                        COALESCE(SUM(total_tokens), 0), 
                        COALESCE(SUM(total_cost_usd), 0)
                    FROM analytics_query_logs
                    WHERE user_id = :u_id
                """),
                {"u_id": str(user_id)},
            )
            u_row = usage_q.fetchone()
            if u_row:
                total_queries = u_row[0] or 0
                total_tokens = int(u_row[1] or 0)
                total_cost_usd = round(float(u_row[2] or 0.0), 4)
        except Exception as e:
            logger.warning(f"Error reading AI usage for user {user_id}: {e}")

        # 3. Active API Keys
        active_api_keys = 0
        try:
            key_q = await db.execute(
                select(func.count(APIKey.id)).where(APIKey.user_id == user_id, APIKey.is_active == True)
            )
            active_api_keys = key_q.scalar() or 0
        except Exception:
            pass

        stats = CustomerUserStats(
            total_chat_sessions=chat_sess_count,
            total_messages=chat_msg_count,
            total_queries=total_queries,
            total_tokens=total_tokens,
            total_cost_usd=total_cost_usd,
            active_api_keys_count=active_api_keys,
        )

        return CustomerUserProfileResponse(
            id=user_obj.id,
            email=user_obj.email,
            first_name=user_obj.first_name,
            last_name=user_obj.last_name,
            role="admin" if user_obj.is_admin else "user",
            is_active=user_obj.is_active,
            is_locked=is_locked,
            locked_until=user_obj.locked_until,
            lock_reason=getattr(user_obj, "lock_reason", None),
            tenant_id=user_obj.tenant_id,
            tenant_name=t_name or "Unknown Organization",
            tenant_slug=t_slug or "unknown",
            tenant_is_active=bool(t_active),
            preferred_llm_model=user_obj.preferred_llm_model,
            created_at=user_obj.created_at,
            updated_at=user_obj.updated_at,
            last_login_at=getattr(user_obj, "last_login_at", None),
            stats=stats,
        )

    # ========================================================================
    # LIFECYCLE & STATUS ACTIONS (ACTIVATE, DEACTIVATE, LOCK, UNLOCK)
    # ========================================================================

    @staticmethod
    async def update_user_status(
        user_id: UUID,
        is_active: bool,
        reason: str,
        admin: SuperAdminUser,
        request: Optional[Request],
        db: AsyncSession,
    ) -> None:
        """Activate or deactivate a customer user account with audit logging."""
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Customer user not found.")

        old_status = user.is_active
        user.is_active = is_active
        db.add(user)
        await db.commit()

        # If deactivating, invalidate user's active API keys
        if not is_active:
            await db.execute(
                update(APIKey).where(APIKey.user_id == user_id).values(is_active=False)
            )
            await db.commit()

        await log_admin_activity(
            db=db,
            admin=admin,
            action="ACTIVATE_USER" if is_active else "DEACTIVATE_USER",
            resource_type="customer_user",
            resource_id=str(user_id),
            target_tenant_id=user.tenant_id,
            details={
                "target_email": user.email,
                "previous_is_active": old_status,
                "new_is_active": is_active,
                "reason": reason,
            },
            status_val="SUCCESS",
            request=request,
        )

    @staticmethod
    async def lock_user_account(
        user_id: UUID,
        duration_hours: Optional[int],
        lock_until: Optional[datetime],
        reason: str,
        admin: SuperAdminUser,
        request: Optional[Request],
        db: AsyncSession,
    ) -> datetime:
        """Temporarily lock a customer user account and revoke sessions."""
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Customer user not found.")

        now = datetime.now(timezone.utc)
        effective_until = lock_until or (now + timedelta(hours=duration_hours or 24))

        user.locked_until = effective_until
        user.lock_reason = reason
        db.add(user)
        await db.commit()

        # Invalidate sessions via blacklist
        bl = TokenBlacklist(
            tenant_id=user.tenant_id,
            user_id=user.id,
            jti=f"lockout:{user.id}:{int(now.timestamp())}",
            token_type="access",
            reason=f"Account locked by SuperAdmin: {reason}",
            expires_at=effective_until,
        )
        db.add(bl)
        await db.commit()

        await log_admin_activity(
            db=db,
            admin=admin,
            action="LOCK_USER_ACCOUNT",
            resource_type="customer_user",
            resource_id=str(user_id),
            target_tenant_id=user.tenant_id,
            details={
                "target_email": user.email,
                "locked_until": effective_until.isoformat(),
                "reason": reason,
            },
            status_val="SUCCESS",
            request=request,
        )
        return effective_until

    @staticmethod
    async def unlock_user_account(
        user_id: UUID,
        reason: str,
        admin: SuperAdminUser,
        request: Optional[Request],
        db: AsyncSession,
    ) -> None:
        """Unlock a previously locked customer user account."""
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Customer user not found.")

        user.locked_until = None
        user.lock_reason = None
        db.add(user)
        await db.commit()

        await log_admin_activity(
            db=db,
            admin=admin,
            action="UNLOCK_USER_ACCOUNT",
            resource_type="customer_user",
            resource_id=str(user_id),
            target_tenant_id=user.tenant_id,
            details={"target_email": user.email, "reason": reason},
            status_val="SUCCESS",
            request=request,
        )

    # ========================================================================
    # CREDENTIALS, SESSIONS & TOKENS REVOCATION
    # ========================================================================

    @staticmethod
    async def trigger_password_reset(
        user_id: UUID,
        reason: str,
        admin: SuperAdminUser,
        request: Optional[Request],
        db: AsyncSession,
    ) -> str:
        """Generate a password recovery token and invalidate active user tokens."""
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Customer user not found.")

        raw_token = secrets.token_urlsafe(32)
        hashed_token = hash_token(raw_token)
        now = datetime.now(timezone.utc)

        token_entry = PasswordResetToken(
            tenant_id=user.tenant_id,
            user_id=user.id,
            token_hash=hashed_token,
            is_used=False,
            expires_at=now + timedelta(hours=24),
        )
        db.add(token_entry)
        await db.commit()

        # Invalidate active user tokens
        await CustomerUserService.revoke_user_sessions(
            user_id=user_id,
            reason=f"Password reset triggered: {reason}",
            admin=admin,
            request=request,
            db=db,
        )

        await log_admin_activity(
            db=db,
            admin=admin,
            action="TRIGGER_PASSWORD_RESET",
            resource_type="customer_user",
            resource_id=str(user_id),
            target_tenant_id=user.tenant_id,
            details={"target_email": user.email, "reason": reason},
            status_val="SUCCESS",
            request=request,
        )
        return raw_token

    @staticmethod
    async def revoke_user_sessions(
        user_id: UUID,
        reason: str,
        admin: SuperAdminUser,
        request: Optional[Request],
        db: AsyncSession,
    ) -> None:
        """Revoke all active sessions, JWT tokens, and API keys for a customer user."""
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Customer user not found.")

        now = datetime.now(timezone.utc)

        # 1. Deactivate API keys
        await db.execute(
            update(APIKey).where(APIKey.user_id == user_id).values(is_active=False)
        )

        # 2. Add revocation barrier to TokenBlacklist
        bl = TokenBlacklist(
            tenant_id=user.tenant_id,
            user_id=user.id,
            jti=f"revoke_all:{user.id}:{int(now.timestamp())}",
            token_type="access",
            reason=f"Revoked by SuperAdmin: {reason}",
            expires_at=now + timedelta(days=7),
        )
        db.add(bl)
        await db.commit()

        await log_admin_activity(
            db=db,
            admin=admin,
            action="REVOKE_USER_SESSIONS",
            resource_type="customer_user",
            resource_id=str(user_id),
            target_tenant_id=user.tenant_id,
            details={"target_email": user.email, "reason": reason},
            status_val="SUCCESS",
            request=request,
        )

    # ========================================================================
    # ROLES & CROSS-ORGANIZATION TRANSFERS
    # ========================================================================

    @staticmethod
    async def change_user_role(
        user_id: UUID,
        new_role: str,
        reason: str,
        admin: SuperAdminUser,
        request: Optional[Request],
        db: AsyncSession,
    ) -> None:
        """Change customer user role (admin vs user) within their organization."""
        clean_role = new_role.strip().lower()
        if clean_role not in ("admin", "user"):
            raise HTTPException(
                status_code=400, detail="Permitted tenant roles are 'admin' and 'user'."
            )

        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Customer user not found.")

        old_role = "admin" if user.is_admin else "user"
        user.is_admin = (clean_role == "admin")
        db.add(user)
        await db.commit()

        await log_admin_activity(
            db=db,
            admin=admin,
            action="CHANGE_USER_ROLE",
            resource_type="customer_user",
            resource_id=str(user_id),
            target_tenant_id=user.tenant_id,
            details={
                "target_email": user.email,
                "previous_role": old_role,
                "new_role": clean_role,
                "reason": reason,
            },
            status_val="SUCCESS",
            request=request,
        )

    @staticmethod
    async def transfer_user_tenant(
        user_id: UUID,
        target_tenant_id: UUID,
        authorization_reference: str,
        reason: str,
        admin: SuperAdminUser,
        request: Optional[Request],
        db: AsyncSession,
    ) -> None:
        """
        Move a customer user from their current organization to a target organization.
        Requires explicit authorization reference.
        Revokes previous tenant sessions and API keys to prevent cross-tenant data leakage.
        """
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Customer user not found.")

        if user.tenant_id == target_tenant_id:
            raise HTTPException(
                status_code=400,
                detail="User is already a member of the target organization.",
            )

        target_tenant = await db.get(Tenant, target_tenant_id)
        if not target_tenant:
            raise HTTPException(status_code=404, detail="Target customer organization not found.")

        previous_tenant_id = user.tenant_id

        # 1. Revoke existing credentials/tokens from previous tenant
        await db.execute(
            update(APIKey).where(APIKey.user_id == user_id).values(is_active=False)
        )

        now = datetime.now(timezone.utc)
        bl = TokenBlacklist(
            tenant_id=previous_tenant_id,
            user_id=user.id,
            jti=f"transfer:{user.id}:{int(now.timestamp())}",
            token_type="access",
            reason=f"Transferred to tenant {target_tenant_id}",
            expires_at=now + timedelta(days=7),
        )
        db.add(bl)

        # 2. Update user tenant affiliation
        user.tenant_id = target_tenant_id
        db.add(user)
        await db.commit()

        await log_admin_activity(
            db=db,
            admin=admin,
            action="TRANSFER_USER_TENANT",
            resource_type="customer_user",
            resource_id=str(user_id),
            target_tenant_id=target_tenant_id,
            details={
                "target_email": user.email,
                "from_tenant_id": str(previous_tenant_id),
                "to_tenant_id": str(target_tenant_id),
                "to_tenant_name": target_tenant.name,
                "authorization_reference": authorization_reference,
                "reason": reason,
            },
            status_val="SUCCESS",
            request=request,
        )

    # ========================================================================
    # USAGE & ACTIVITY AUDIT TRAIL
    # ========================================================================

    @staticmethod
    async def get_user_ai_usage(user_id: UUID, db: AsyncSession) -> CustomerUserAIUsageResponse:
        """Retrieve user-specific AI query volume, token consumption, and cost breakdown."""
        query = (
            select(
                User,
                Tenant.name.label("tenant_name"),
            )
            .join(Tenant, User.tenant_id == Tenant.id)
            .where(User.id == user_id)
        )
        result = await db.execute(query)
        row = result.first()
        if not row:
            raise HTTPException(status_code=404, detail="Customer user not found.")

        user_obj, t_name = row

        totals_q = await db.execute(
            text("""
                SELECT 
                    COUNT(*),
                    COALESCE(SUM(total_tokens), 0),
                    COALESCE(SUM(llm_input_tokens), 0),
                    COALESCE(SUM(llm_output_tokens), 0),
                    COALESCE(SUM(embedding_tokens), 0),
                    COALESCE(SUM(total_cost_usd), 0),
                    COALESCE(AVG(latency_ms), 0)
                FROM analytics_query_logs
                WHERE user_id = :u_id
            """),
            {"u_id": str(user_id)},
        )
        tot_row = totals_q.fetchone()

        total_queries = tot_row[0] or 0
        total_tokens = int(tot_row[1] or 0)
        llm_in = int(tot_row[2] or 0)
        llm_out = int(tot_row[3] or 0)
        emb_tok = int(tot_row[4] or 0)
        total_cost = round(float(tot_row[5] or 0.0), 4)
        avg_lat = round(float(tot_row[6] or 0.0), 2)

        # Model breakdown
        model_q = await db.execute(
            text("""
                SELECT 
                    COALESCE(model_name, 'Unknown') AS m_name,
                    COUNT(*),
                    COALESCE(SUM(llm_input_tokens), 0),
                    COALESCE(SUM(llm_output_tokens), 0),
                    COALESCE(SUM(total_tokens), 0),
                    COALESCE(SUM(total_cost_usd), 0)
                FROM analytics_query_logs
                WHERE user_id = :u_id
                GROUP BY m_name
                ORDER BY COUNT(*) DESC
            """),
            {"u_id": str(user_id)},
        )
        model_items: List[ModelUsageBreakdown] = []
        for mr in model_q.fetchall():
            model_items.append(
                ModelUsageBreakdown(
                    model_name=mr[0],
                    requests=mr[1] or 0,
                    input_tokens=int(mr[2] or 0),
                    output_tokens=int(mr[3] or 0),
                    total_tokens=int(mr[4] or 0),
                    cost_usd=round(float(mr[5] or 0.0), 4),
                )
            )

        return CustomerUserAIUsageResponse(
            user_id=user_obj.id,
            email=user_obj.email,
            tenant_id=user_obj.tenant_id,
            tenant_name=t_name or "Unknown Organization",
            total_queries=total_queries,
            total_tokens=total_tokens,
            llm_input_tokens=llm_in,
            llm_output_tokens=llm_out,
            embedding_tokens=emb_tok,
            total_cost_usd=total_cost,
            avg_latency_ms=avg_lat,
            model_breakdown=model_items,
        )

    @staticmethod
    async def get_user_activity(
        user_id: UUID, limit: int, db: AsyncSession
    ) -> CustomerUserActivityResponse:
        """
        Aggregate comprehensive activity history:
        - Recent queries from analytics_query_logs
        - Chat sessions created
        - SuperAdmin interventions and security audit records targeting this user
        """
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Customer user not found.")

        activities: List[CustomerUserActivityItem] = []

        # 1. Queries from analytics_query_logs
        try:
            q_res = await db.execute(
                text("""
                    SELECT id, query, response_status, model_name, created_at
                    FROM analytics_query_logs
                    WHERE user_id = :u_id
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"u_id": str(user_id), "lim": limit},
            )
            for r in q_res.fetchall():
                activities.append(
                    CustomerUserActivityItem(
                        id=str(r[0]),
                        activity_type="QUERY",
                        title=f"AI Query ({r[2]})",
                        description=str(r[1])[:200] if r[1] else "Query executed",
                        details={"model": r[3], "status": r[2]},
                        created_at=r[4],
                    )
                )
        except Exception as e:
            logger.warning(f"Error reading queries for activity: {e}")

        # 2. Chat sessions
        try:
            s_res = await db.execute(
                text("""
                    SELECT id, title, created_at
                    FROM chat_sessions
                    WHERE user_id = :u_id
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"u_id": str(user_id), "lim": limit},
            )
            for r in s_res.fetchall():
                activities.append(
                    CustomerUserActivityItem(
                        id=str(r[0]),
                        activity_type="CHAT_SESSION",
                        title="Chat Session Created",
                        description=r[1] or "Untitled Conversation",
                        details={"session_id": str(r[0])},
                        created_at=r[2],
                    )
                )
        except Exception as e:
            logger.warning(f"Error reading sessions for activity: {e}")

        # 3. SuperAdmin Audit Log actions targeting this user
        try:
            from app.modules.superadmin.models import SuperAdminAuditLog

            audit_res = await db.execute(
                select(SuperAdminAuditLog)
                .where(
                    SuperAdminAuditLog.resource_type == "customer_user",
                    SuperAdminAuditLog.resource_id == str(user_id),
                )
                .order_by(SuperAdminAuditLog.created_at.desc())
                .limit(limit)
            )
            for a in audit_res.scalars().all():
                activities.append(
                    CustomerUserActivityItem(
                        id=str(a.id),
                        activity_type="SUPERADMIN_ACTION",
                        title=f"Admin: {a.action}",
                        description=f"Action by {a.admin_email}. Reason: {a.details.get('reason', 'N/A') if a.details else 'N/A'}",
                        details=a.details or {},
                        created_at=a.created_at,
                    )
                )
        except Exception as e:
            logger.warning(f"Error reading audit log for activity: {e}")

        # Sort combined activity timeline descending
        activities.sort(key=lambda x: x.created_at, reverse=True)
        trimmed = activities[:limit]

        return CustomerUserActivityResponse(
            user_id=user_id,
            activities=trimmed,
            total=len(trimmed),
        )

