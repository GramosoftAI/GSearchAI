"""Users business logic"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.models import User
from . import schemas


async def get_user(user_id: str, db: AsyncSession):
    """Get user by ID"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")
    return user


async def list_users(skip: int, limit: int, db: AsyncSession):
    """List users with pagination"""
    result = await db.execute(select(User).offset(skip).limit(limit))
    return result.scalars().all()


async def update_user(user_id: str, user_update: schemas.UserUpdate, db: AsyncSession):
    """Update user"""
    user = await get_user(user_id, db)
    update_data = user_update.dict(exclude_unset=True)

    for field, value in update_data.items():
        setattr(user, field, value)

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(user_id: str, db: AsyncSession):
    """Delete user"""
    user = await get_user(user_id, db)
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
