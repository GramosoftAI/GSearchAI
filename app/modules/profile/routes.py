"""Profile Management API routes"""

from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, status, Request, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.core.database import get_db
from app.modules.profile import schemas, services

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


def _coerce_uuid(val: any) -> Optional[UUID]:
    if not val:
        return None
    try:
        return UUID(str(val))
    except (ValueError, TypeError):
        return None


async def _resolve_user(current_user: str, db: AsyncSession) -> User:
    """Resolve authenticated caller User object from current_user token claim"""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    u_uuid = _coerce_uuid(current_user)
    if u_uuid:
        stmt = select(User).where(or_(User.id == u_uuid, User.email == str(current_user)))
    else:
        stmt = select(User).where(User.email == str(current_user))
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Authenticated user '{current_user}' not found",
        )
    return user


async def _resolve_target_user(user_id: str, db: AsyncSession, caller: User) -> User:
    """Resolve target user ensuring caller is platform admin or accessing own profile"""
    target_uuid = _coerce_uuid(user_id)
    if target_uuid:
        stmt = select(User).where(or_(User.id == target_uuid, User.email == str(user_id)))
    else:
        stmt = select(User).where(User.email == str(user_id))
    res = await db.execute(stmt)
    target_user = res.scalar_one_or_none()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found",
        )

    # Permission check: admin or same user
    is_admin = bool(caller.is_admin or getattr(caller, "role", "") == "admin")
    if not is_admin and caller.id != target_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access another user's profile.",
        )

    return target_user


# ============================================================================
# CURRENT USER PROFILE ENDPOINTS
# ============================================================================

@router.get("/me", response_model=schemas.ProfileResponse)
@router.get("/", response_model=schemas.ProfileResponse)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Retrieve current authenticated user's profile.
    Automatically initializes profile matching registered login credentials if not yet created.
    """
    user = await _resolve_user(current_user, db)
    return await services.get_user_profile(user, db, include_summary=True)


@router.post("/", response_model=schemas.ProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_my_profile(
    data: schemas.ProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Explicitly create or initialize current user's profile with custom details.
    """
    user = await _resolve_user(current_user, db)
    return await services.create_user_profile(user, data, db)


@router.put("/me", response_model=schemas.ProfileResponse)
@router.patch("/me", response_model=schemas.ProfileResponse)
@router.put("/", response_model=schemas.ProfileResponse)
async def update_my_profile(
    data: schemas.ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Update current authenticated user's profile.
    Synchronizes first name, last name, and preferred LLM model across User and Profile models.
    """
    user = await _resolve_user(current_user, db)
    return await services.update_user_profile(user, data, db)


@router.get("/summary", response_model=schemas.UserResourceSummary)
@router.get("/me/summary", response_model=schemas.UserResourceSummary)
async def get_my_resource_summary(
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Get inventory summary of all resources owned by the current user across the platform
    (agents, knowledge bases, database knowledgebases, chat sessions, memories, API keys).
    """
    user = await _resolve_user(current_user, db)
    return await services.get_user_resource_summary(user, db)


@router.delete("/me", response_model=schemas.DeleteAccountResponse)
@router.delete("/", response_model=schemas.DeleteAccountResponse)
async def delete_my_account(
    confirmation: Optional[schemas.DeleteAccountRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    COMPLETE ACCOUNT & PROFILE DELETION:
    Permanently deletes current authenticated user's profile and all associated resources
    across the entire platform, including uploaded files, created agents, Neo4j graph nodes,
    conversations, memories, knowledge bases, configurations, and login account.
    """
    user = await _resolve_user(current_user, db)
    return await services.delete_user_account_completely(
        user, db, request=confirmation, is_admin_override=False
    )


# ============================================================================
# SPECIFIC USER PROFILE ENDPOINTS (ADMIN / SELF)
# ============================================================================

@router.get("/{user_id}", response_model=schemas.ProfileResponse)
async def get_user_profile_by_id(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Retrieve profile by user ID.
    Accessible by Platform Administrators or the account owner.
    """
    caller = await _resolve_user(current_user, db)
    target_user = await _resolve_target_user(user_id, db, caller)
    return await services.get_user_profile(target_user, db, include_summary=True)


@router.put("/{user_id}", response_model=schemas.ProfileResponse)
async def update_user_profile_by_id(
    user_id: str,
    data: schemas.ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Update profile by user ID.
    Accessible by Platform Administrators or the account owner.
    """
    caller = await _resolve_user(current_user, db)
    target_user = await _resolve_target_user(user_id, db, caller)
    return await services.update_user_profile(target_user, data, db)


@router.delete("/{user_id}", response_model=schemas.DeleteAccountResponse)
async def delete_user_account_by_id(
    user_id: str,
    confirmation: Optional[schemas.DeleteAccountRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    COMPLETE ACCOUNT & PROFILE DELETION FOR SPECIFIC USER:
    Permanently purges the target user's profile, agents, files, memories, knowledge bases,
    and login credentials from all databases, storage services, and graphs.
    Accessible by Platform Administrators or the account owner.
    """
    caller = await _resolve_user(current_user, db)
    target_user = await _resolve_target_user(user_id, db, caller)
    is_admin = bool(caller.is_admin or getattr(caller, "role", "") == "admin")
    return await services.delete_user_account_completely(
        target_user, db, request=confirmation, is_admin_override=is_admin
    )
