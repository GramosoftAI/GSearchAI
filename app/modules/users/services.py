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
