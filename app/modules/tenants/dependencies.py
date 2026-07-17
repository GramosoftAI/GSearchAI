"""Tenants dependencies"""
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ...core.database import get_db
from . import models


async def get_tenant_from_header(
    x_tenant_id: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Extract and validate tenant from request header"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    
    result = await db.execute(
        select(models.Tenant).where(models.Tenant.id == x_tenant_id)
    )
    tenant = result.scalar_one_or_none()
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    return tenant
