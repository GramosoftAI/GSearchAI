"""Tenants management routes"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from ..auth.dependencies import get_current_user
from ...core.database import get_db
from . import services, schemas

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post(
    "/", response_model=schemas.TenantResponse, status_code=status.HTTP_200_OK
)
async def create_tenant(
    tenant_data: schemas.TenantCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Create a new tenant"""
    return await services.create_tenant(tenant_data, current_user, db)


@router.get("/{tenant_id}", response_model=schemas.TenantResponse)
async def get_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Get tenant by ID"""
    return await services.get_tenant(tenant_id, db)


@router.get("/", response_model=list[schemas.TenantResponse])
async def list_tenants(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """List all tenants for current user"""
    return await services.list_tenants_for_user(current_user, skip, limit, db)


@router.put("/{tenant_id}", response_model=schemas.TenantResponse)
async def update_tenant(
    tenant_id: str,
    tenant_update: schemas.TenantUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Update tenant"""
    return await services.update_tenant(tenant_id, tenant_update, db)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Delete tenant"""
    return await services.delete_tenant(tenant_id, db)
