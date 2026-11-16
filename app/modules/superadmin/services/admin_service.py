"""SuperAdmin Staff & Identity Management Service.

Handles dedicated SuperAdmin authentication, password management,
role assignments, permission validation, and administrative accounts CRUD.
"""

from typing import List, Optional, Tuple
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
import logging

from ..models import SuperAdminUser, SuperAdminRole
from ..schemas import SuperAdminCreateRequest, SuperAdminUpdateRequest
from ..security import hash_password, verify_password, create_superadmin_access_token

logger = logging.getLogger(__name__)


class AdminService:
    """Service handling platform-level administrative identity and staff management."""

    @staticmethod
    async def bootstrap_initial_admin(db: AsyncSession) -> SuperAdminUser:
        """
        Ensure platform SuperAdmin accounts exist on the platform.
        Bootstraps superadmin@gsearch.ai and admin@gsearch.ai with SUPERADMIN_ROOT.
        """
        # 1. Ensure superadmin@gsearch.ai exists
        q1 = await db.execute(select(SuperAdminUser).where(SuperAdminUser.email == "superadmin@gsearch.ai"))
        root_admin = q1.scalar_one_or_none()
        if not root_admin:
            root_admin = SuperAdminUser(
                email="superadmin@gsearch.ai",
                hashed_password=hash_password("SuperAdminPassword123!"),
                first_name="Platform",
                last_name="Owner",
                role=SuperAdminRole.SUPERADMIN_ROOT.value,
                permissions=["*"],
                is_active=True,
                mfa_enabled=False,
                ip_allowlist_enabled=False,
                allowed_ips=[],
            )
            db.add(root_admin)

        # 2. Ensure admin@gsearch.ai exists
        q2 = await db.execute(select(SuperAdminUser).where(SuperAdminUser.email == "admin@gsearch.ai"))
        doc_admin = q2.scalar_one_or_none()
        if not doc_admin:
            doc_admin = SuperAdminUser(
                email="admin@gsearch.ai",
                hashed_password=hash_password("SecurePassword123!"),
                first_name="SuperAdmin",
                last_name="Administrator",
                role=SuperAdminRole.SUPERADMIN_ROOT.value,
                permissions=["*"],
                is_active=True,
                mfa_enabled=False,
                ip_allowlist_enabled=False,
                allowed_ips=[],
            )
            db.add(doc_admin)

        await db.commit()
        logger.info("[SUPERADMIN] Initial platform admin accounts verified.")
        return root_admin or doc_admin

    @staticmethod
    async def authenticate(
        email: str, password: str, db: AsyncSession
    ) -> Tuple[SuperAdminUser, str]:
        """
        Authenticate a SuperAdmin with email and password.
        Returns the SuperAdminUser and a signed SuperAdmin JWT access token.
        """
        await AdminService.bootstrap_initial_admin(db)

        query = select(SuperAdminUser).where(SuperAdminUser.email == email.lower().strip())
        result = await db.execute(query)
        admin = result.scalar_one_or_none()

        if not admin or not verify_password(password, admin.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid administrative email or password.",
            )

        if not admin.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="SuperAdmin account has been deactivated. Please contact platform owner.",
            )

        admin.last_login_at = datetime.now(timezone.utc)
        db.add(admin)
        await db.commit()
        await db.refresh(admin)

        token = create_superadmin_access_token(
            admin_id=str(admin.id),
            email=admin.email,
            role=admin.role,
            permissions=admin.permissions,
        )

        return admin, token

    @staticmethod
    async def list_admins(
        db: AsyncSession, limit: int = 50, offset: int = 0
    ) -> List[SuperAdminUser]:
        """List platform SuperAdmin staff accounts."""
        query = (
            select(SuperAdminUser)
            .order_by(SuperAdminUser.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_admin_by_id(db: AsyncSession, admin_id: UUID) -> SuperAdminUser:
        """Fetch SuperAdmin user by UUID."""
        query = select(SuperAdminUser).where(SuperAdminUser.id == admin_id)
        result = await db.execute(query)
        admin = result.scalar_one_or_none()
        if not admin:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SuperAdmin staff account {admin_id} not found",
            )
        return admin

    @staticmethod
    async def create_admin(
        db: AsyncSession, req: SuperAdminCreateRequest
    ) -> SuperAdminUser:
        """Create a new platform SuperAdmin account."""
        clean_email = req.email.lower().strip()
        existing = await db.execute(
            select(SuperAdminUser).where(SuperAdminUser.email == clean_email)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SuperAdmin account with email {clean_email} already exists.",
            )

        new_admin = SuperAdminUser(
            email=clean_email,
            hashed_password=hash_password(req.password),
            first_name=req.first_name,
            last_name=req.last_name,
            role=req.role.value if isinstance(req.role, SuperAdminRole) else req.role,
            permissions=req.permissions or ["*"],
            is_active=True,
            ip_allowlist_enabled=req.ip_allowlist_enabled,
            allowed_ips=req.allowed_ips or [],
        )
        db.add(new_admin)
        await db.commit()
        await db.refresh(new_admin)
        return new_admin

    @staticmethod
    async def update_admin(
        db: AsyncSession, admin_id: UUID, req: SuperAdminUpdateRequest
    ) -> SuperAdminUser:
        """Update an existing SuperAdmin account."""
        admin = await AdminService.get_admin_by_id(db, admin_id)
        update_dict = req.dict(exclude_unset=True)

        if "password" in update_dict and update_dict["password"]:
            admin.hashed_password = hash_password(update_dict.pop("password"))

        if "role" in update_dict and update_dict["role"]:
            r = update_dict["role"]
            admin.role = r.value if isinstance(r, SuperAdminRole) else r

        for field, value in update_dict.items():
            if field != "role":
                setattr(admin, field, value)

        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        return admin

    @staticmethod
    async def delete_admin(db: AsyncSession, admin_id: UUID) -> None:
        """Deactivate or delete a SuperAdmin account."""
        admin = await AdminService.get_admin_by_id(db, admin_id)
        total_admins = await db.execute(select(func.count(SuperAdminUser.id)))
        if (total_admins.scalar() or 0) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the sole remaining SuperAdmin account on the platform.",
            )
        await db.delete(admin)
        await db.commit()

    @staticmethod
    async def change_password(
        db: AsyncSession, admin: SuperAdminUser, old_pass: str, new_pass: str
    ) -> None:
        """Change current SuperAdmin password with verification of old password."""
        if not verify_password(old_pass, admin.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect.",
            )

        admin.hashed_password = hash_password(new_pass)
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
