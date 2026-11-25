"""Users business logic"""

import uuid
from uuid import UUID
from typing import Optional, Any
from sqlalchemy import select, func, or_, and_, not_
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.models import User
from . import schemas


def _coerce_uuid(val):
    if not val:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return val


def is_anonymous_or_widget_user():
    """
    SQLAlchemy binary expression that evaluates to TRUE if a user record is
    an anonymous visitor, an automatically generated widget user, or a synthetic benchmark test user.
    """
    email_clean = func.lower(func.coalesce(User.email, ""))
    first_clean = func.lower(func.trim(func.coalesce(User.first_name, "")))
    last_clean = func.lower(func.trim(func.coalesce(User.last_name, "")))
    full_name_clean = func.lower(func.trim(func.concat(first_clean, " ", last_clean)))

    return or_(
        email_clean.like("widget_%"),
        email_clean.like("%widget_user%"),
        email_clean.like("%@graphmind.local%"),
        and_(first_clean == "anonymous", last_clean == "visitor"),
        full_name_clean == "anonymous visitor",
        first_clean == "anonymous visitor",
        last_clean == "anonymous visitor",
        email_clean.like("golden_%"),
        email_clean.like("api_%"),
        email_clean.like("mock%@phase6.com"),
        email_clean.like("%@example.com"),
        email_clean.like("%@test.com"),
    )


async def get_user(user_id: str, db: AsyncSession, tenant_id: Optional[str] = None):
    """Get user by ID (excluding anonymous visitor and widget users, scoped to tenant if provided)"""
    stmt = select(User).where(User.id == _coerce_uuid(user_id), not_(is_anonymous_or_widget_user()))
    if tenant_id:
        stmt = stmt.where(User.tenant_id == _coerce_uuid(tenant_id))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")
    return user


async def count_users(
    db: AsyncSession,
    tenant_id: Optional[str] = None,
    is_platform_admin: bool = False,
) -> int:
    """Count total valid registered users excluding anonymous visitors, widget users, and benchmark accounts"""
    conditions = [not_(is_anonymous_or_widget_user())]
    if tenant_id and not is_platform_admin:
        conditions.append(User.tenant_id == _coerce_uuid(tenant_id))
    stmt = select(func.count(User.id)).where(and_(*conditions))
    result = await db.execute(stmt)
    return result.scalar() or 0


async def list_users(
    skip: int,
    limit: int,
    db: AsyncSession,
    tenant_id: Optional[str] = None,
    is_platform_admin: bool = False,
):
    """List valid registered users with pagination, scoped to tenant (or platform-wide for admins)"""
    conditions = [not_(is_anonymous_or_widget_user())]
    if tenant_id and not is_platform_admin:
        conditions.append(User.tenant_id == _coerce_uuid(tenant_id))
    stmt = select(User).where(and_(*conditions)).order_by(User.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    users = result.scalars().all()
    total = await count_users(db, tenant_id=tenant_id, is_platform_admin=is_platform_admin)
    return users, total


async def update_user(user_id: str, user_update: schemas.UserUpdate, db: AsyncSession, tenant_id: Optional[str] = None):
    """Update user"""
    user = await get_user(user_id, db, tenant_id=tenant_id)
    update_data = user_update.dict(exclude_unset=True)

    for field, value in update_data.items():
        setattr(user, field, value)

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(user_id: str, db: AsyncSession, tenant_id: Optional[str] = None):
    """Delete user"""
    user = await get_user(user_id, db, tenant_id=tenant_id)
    await db.delete(user)
    await db.commit()


async def get_user_llm_preference(user_id: str, db: AsyncSession) -> schemas.UserLLMPreferenceResponse:
    """Get LLM model preference for a user with available models catalog"""
    from app.core.config import get_settings
    from app.core.llm.pricing import get_available_chat_models

    settings = get_settings()
    default_model = settings.model_answer
    user = await get_user(user_id, db)

    available_models_raw = get_available_chat_models(default_model)
    available_models = [
        schemas.AvailableModelItem(**m) for m in available_models_raw
    ]

    active_model = user.preferred_llm_model.strip() if (user.preferred_llm_model and user.preferred_llm_model.strip()) else default_model

    return schemas.UserLLMPreferenceResponse(
        user_id=user.id,
        email=user.email,
        preferred_llm_model=user.preferred_llm_model,
        active_model=active_model,
        default_model=default_model,
        available_models=available_models,
    )


async def update_user_llm_preference(
    user_id: str,
    pref_update: schemas.UserLLMPreferenceUpdate,
    db: AsyncSession
) -> schemas.UserLLMPreferenceResponse:
    """Update preferred LLM model for a user"""
    from app.core.config import get_settings
    from app.core.llm.pricing import get_available_chat_models, SUPPORTED_MODELS

    settings = get_settings()
    default_model = settings.model_answer
    user = await get_user(user_id, db)

    target_model = pref_update.preferred_llm_model
    if target_model:
        target_model = target_model.strip()
        if target_model == "" or target_model.lower() == "default":
            target_model = None

    user.preferred_llm_model = target_model
    db.add(user)
    await db.commit()
    await db.refresh(user)

    available_models_raw = get_available_chat_models(default_model)
    available_models = [
        schemas.AvailableModelItem(**m) for m in available_models_raw
    ]

    active_model = user.preferred_llm_model if user.preferred_llm_model else default_model

    return schemas.UserLLMPreferenceResponse(
        user_id=user.id,
        email=user.email,
        preferred_llm_model=user.preferred_llm_model,
        active_model=active_model,
        default_model=default_model,
        available_models=available_models,
    )


async def create_user_for_tenant(
    db: AsyncSession,
    tenant_id: UUID,
    data: Any,
) -> User:
    """Create a new user belonging directly to caller's tenant."""
    from fastapi import HTTPException
    from app.core.security import hash_password
    
    existing = await db.execute(
        select(User).where(User.email == data.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"User with email '{data.email}' already exists",
        )

    coerced_tenant_id = _coerce_uuid(tenant_id)
    user = User(
        tenant_id=coerced_tenant_id,
        email=data.email,
        first_name=data.first_name,
        last_name=data.last_name,
        hashed_password=hash_password(data.password or "TempPass123!"),
        is_admin=bool(data.is_admin or getattr(data, "role", "") == "admin"),
        is_active=data.is_active if data.is_active is not None else True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

