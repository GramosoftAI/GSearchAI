"""Users management routes"""

from typing import Union, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, status, Response, Query, Request, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from ..auth.dependencies import get_current_user
from ..auth.models import User
from ...core.database import get_db
from . import services, schemas
from ..profile import services as profile_services, schemas as profile_schemas

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def _coerce_uuid(val: any) -> Optional[UUID]:
    if not val:
        return None
    try:
        return UUID(str(val))
    except (ValueError, TypeError):
        return None


async def _get_caller_user(current_user: str, db: Session) -> Optional[User]:
    """Resolve caller user by UUID id or email"""
    if not current_user:
        return None
    u_uuid = _coerce_uuid(current_user)
    if u_uuid:
        stmt = select(User).where(or_(User.id == u_uuid, User.email == str(current_user)))
    else:
        stmt = select(User).where(User.email == str(current_user))
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def _get_caller_tenant_id(request: Request, current_user: str, db: Session) -> Optional[str]:
    """Retrieve tenant_id from request.state or fallback to querying user's tenant"""
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return str(tenant_id)
    if current_user:
        u_uuid = _coerce_uuid(current_user)
        if u_uuid:
            stmt = select(User.tenant_id).where(or_(User.id == u_uuid, User.email == str(current_user)))
        else:
            stmt = select(User.tenant_id).where(User.email == str(current_user))
        result = await db.execute(stmt)
        tid = result.scalar_one_or_none()
        if tid:
            return str(tid)
    return None


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


@router.get("/me/profile", response_model=profile_schemas.ProfileResponse)
@router.get("/profile", response_model=profile_schemas.ProfileResponse)
async def get_my_profile_alias(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Retrieve current authenticated user's profile (alias under /users)"""
    user = await _get_caller_user(current_user, db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return await profile_services.get_user_profile(user, db, include_summary=True)


@router.put("/me/profile", response_model=profile_schemas.ProfileResponse)
@router.put("/profile", response_model=profile_schemas.ProfileResponse)
async def update_my_profile_alias(
    data: profile_schemas.ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Update current authenticated user's profile (alias under /users)"""
    user = await _get_caller_user(current_user, db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return await profile_services.update_user_profile(user, data, db)


@router.delete("/me", response_model=profile_schemas.DeleteAccountResponse)
async def delete_my_account_alias(
    confirmation: Optional[profile_schemas.DeleteAccountRequest] = None,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Permanently delete user account and all resources (alias under /users/me)"""
    user = await _get_caller_user(current_user, db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return await profile_services.delete_user_account_completely(user, db, request=confirmation, is_admin_override=False)


@router.get("/count")
async def get_users_count(
    request: Request,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Get total count of valid registered users (platform-wide for admins, tenant-scoped for regular users)"""
    caller_user = await _get_caller_user(current_user, db)
    is_admin = bool(caller_user and (caller_user.is_admin or getattr(caller_user, "role", "") == "admin"))

    req_tenant_id = request.query_params.get("tenant_id")
    if req_tenant_id:
        target_tenant_id = req_tenant_id
        is_platform_admin = False
    elif is_admin:
        target_tenant_id = None
        is_platform_admin = True
    else:
        target_tenant_id = await _get_caller_tenant_id(request, current_user, db)
        is_platform_admin = False

    total = await services.count_users(db, tenant_id=target_tenant_id, is_platform_admin=is_platform_admin)
    return {"total": total, "count": total}


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
    request: Request,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Get user by ID within caller's tenant (or platform-wide for admin)"""
    caller_user = await _get_caller_user(current_user, db)
    is_admin = bool(caller_user and (caller_user.is_admin or getattr(caller_user, "role", "") == "admin"))
    tenant_id = None if is_admin else await _get_caller_tenant_id(request, current_user, db)
    return await services.get_user(user_id, db, tenant_id=tenant_id)


@router.get(
    "/",
    response_model=Union[schemas.PaginatedUsersResponse, list[schemas.UserResponse]],
)
async def list_users(
    request: Request,
    response: Response,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    include_total: bool = Query(False, description="Wrap response in a paginated object with total count"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    List all valid registered users (platform-wide for admins, tenant-scoped for regular users).
    Excludes anonymous visitors, widget users, and synthetic test accounts.
    """
    caller_user = await _get_caller_user(current_user, db)
    is_admin = bool(caller_user and (caller_user.is_admin or getattr(caller_user, "role", "") == "admin"))

    req_tenant_id = request.query_params.get("tenant_id")
    if req_tenant_id:
        target_tenant_id = req_tenant_id
        is_platform_admin = False
    elif is_admin:
        target_tenant_id = None
        is_platform_admin = True
    else:
        target_tenant_id = await _get_caller_tenant_id(request, current_user, db)
        is_platform_admin = False

    users, total = await services.list_users(skip, limit, db, tenant_id=target_tenant_id, is_platform_admin=is_platform_admin)

    # Expose total count in response headers for pagination visibility
    response.headers["X-Total-Count"] = str(total)
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"

    if include_total:
        return schemas.PaginatedUsersResponse(
            data=[schemas.UserResponse.model_validate(u) for u in users],
            total=total,
            skip=skip,
            limit=limit,
        )

    return users


@router.post("/", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: schemas.UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Create a new user within caller's tenant"""
    tenant_id = await _get_caller_tenant_id(request, current_user, db)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant context required")
    return await services.create_user_for_tenant(db, tenant_id, data)


@router.put("/{user_id}", response_model=schemas.UserResponse)
async def update_user(
    user_id: str,
    user_update: schemas.UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Update user within caller's tenant (or platform-wide for admin)"""
    caller_user = await _get_caller_user(current_user, db)
    is_admin = bool(caller_user and (caller_user.is_admin or getattr(caller_user, "role", "") == "admin"))
    tenant_id = None if is_admin else await _get_caller_tenant_id(request, current_user, db)
    return await services.update_user(user_id, user_update, db, tenant_id=tenant_id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Delete user within caller's tenant (or platform-wide for admin)"""
    caller_user = await _get_caller_user(current_user, db)
    is_admin = bool(caller_user and (caller_user.is_admin or getattr(caller_user, "role", "") == "admin"))
    tenant_id = None if is_admin else await _get_caller_tenant_id(request, current_user, db)
    return await services.delete_user(user_id, db, tenant_id=tenant_id)
