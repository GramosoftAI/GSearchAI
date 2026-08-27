"""Users management routes"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from ..auth.dependencies import get_current_user
from ...core.database import get_db
from . import services, schemas

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/models/available", response_model=schemas.AvailableModelsResponse)
async def get_available_models(
    current_user: str = Depends(get_current_user),
):
    """List all available LLM models and default model for user preference selection"""
    from app.core.config import get_settings
    from app.core.llm.pricing import get_available_chat_models

    settings = get_settings()
    default_model = settings.model_answer
    raw_models = get_available_chat_models(default_model)
    return schemas.AvailableModelsResponse(
        default_model=default_model,
        models=[schemas.AvailableModelItem(**m) for m in raw_models],
    )


@router.get("/settings/model", response_model=schemas.UserLLMPreferenceResponse)
async def get_current_user_model_preference(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Get current authenticated user's LLM model preference"""
    return await services.get_user_llm_preference(str(current_user), db)


@router.put("/settings/model", response_model=schemas.UserLLMPreferenceResponse)
async def update_current_user_model_preference(
    pref_update: schemas.UserLLMPreferenceUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Update current authenticated user's LLM model preference"""
    return await services.update_user_llm_preference(str(current_user), pref_update, db)


@router.get("/{user_id}/settings/model", response_model=schemas.UserLLMPreferenceResponse)
async def get_user_model_preference_by_id(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Get LLM model preference for a specific user"""
    return await services.get_user_llm_preference(user_id, db)


@router.put("/{user_id}/settings/model", response_model=schemas.UserLLMPreferenceResponse)
async def update_user_model_preference_by_id(
    user_id: str,
    pref_update: schemas.UserLLMPreferenceUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Update LLM model preference for a specific user"""
    return await services.update_user_llm_preference(user_id, pref_update, db)


@router.get("/{user_id}", response_model=schemas.UserResponse)
async def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Get user by ID"""
    return await services.get_user(user_id, db)


@router.get("/", response_model=list[schemas.UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """List all users"""
    return await services.list_users(skip, limit, db)


@router.put("/{user_id}", response_model=schemas.UserResponse)
async def update_user(
    user_id: str,
    user_update: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Update user"""
    return await services.update_user(user_id, user_update, db)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Delete user"""
    return await services.delete_user(user_id, db)
