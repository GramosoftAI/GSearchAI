"""Tenants business logic"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from . import models, schemas
import uuid


async def create_tenant(tenant_data: schemas.TenantCreate, owner_id: str, db: AsyncSession):
    """Create a new tenant"""
    db_tenant = models.Tenant(
        id=str(uuid.uuid4()),
        name=tenant_data.name,
        slug=tenant_data.slug,
        owner_id=owner_id
    )
    
    db.add(db_tenant)
    await db.commit()
    await db.refresh(db_tenant)
    return db_tenant


async def get_tenant(tenant_id: str, db: AsyncSession):
    """Get tenant by ID"""
    result = await db.execute(select(models.Tenant).where(models.Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise ValueError(f"Tenant {tenant_id} not found")
    return tenant


async def list_tenants_for_user(owner_id: str, skip: int, limit: int, db: AsyncSession):
    """List tenants for a specific user"""
    result = await db.execute(
        select(models.Tenant)
        .where(models.Tenant.owner_id == owner_id)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def update_tenant(tenant_id: str, tenant_update: schemas.TenantUpdate, db: AsyncSession):
    """Update tenant"""
    tenant = await get_tenant(tenant_id, db)
    update_data = tenant_update.dict(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(tenant, field, value)
    
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def delete_tenant(tenant_id: str, db: AsyncSession):
    """Delete tenant"""
    tenant = await get_tenant(tenant_id, db)
    await db.delete(tenant)
    await db.commit()
