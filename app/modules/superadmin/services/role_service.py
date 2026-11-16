"""SuperAdmin Role Hierarchy & Configurable Scopes Service.

Defines:
- SUPERADMIN_ROOT and standard role hierarchy
- Master catalog of fine-grained permission scopes
- Dynamic CRUD for platform roles and permissions
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
import logging

from ..models import SuperAdminRoleDefinition, SuperAdminRole
from ..schemas import RoleDefinitionCreate, RoleDefinitionUpdate, PermissionScopeItem

logger = logging.getLogger(__name__)


PERMISSION_SCOPES = [
    # Wildcard
    PermissionScopeItem(scope="*", category="Root", description="Unrestricted platform control across all resources and operations"),
    
    # Organizations (Tenants)
    PermissionScopeItem(scope="orgs:read", category="Organizations", description="View customer organizations and status"),
    PermissionScopeItem(scope="orgs:write", category="Organizations", description="Create and modify customer organizations"),
    PermissionScopeItem(scope="orgs:suspend", category="Organizations", description="Suspend or reactivate customer organizations"),
    PermissionScopeItem(scope="orgs:delete", category="Organizations", description="Delete customer organizations"),
    
    # Users
    PermissionScopeItem(scope="users:read", category="Users", description="View users across all customer organizations"),
    PermissionScopeItem(scope="users:write", category="Users", description="Update user status and preferences"),
    PermissionScopeItem(scope="users:impersonate", category="Users", description="Generate temporary scoped impersonation tokens"),
    PermissionScopeItem(scope="users:delete", category="Users", description="Delete or deactivate user accounts"),
    
    # AI Agents
    PermissionScopeItem(scope="agents:read", category="AI Agents", description="View all AI agents across tenants"),
    PermissionScopeItem(scope="agents:write", category="AI Agents", description="Modify system prompts, personalities, and settings"),
    PermissionScopeItem(scope="agents:transfer", category="AI Agents", description="Transfer agent ownership across tenants or users"),
    PermissionScopeItem(scope="agents:delete", category="AI Agents", description="Deactivate or remove AI agents"),
    
    # Knowledgebases
    PermissionScopeItem(scope="kb:read", category="KnowledgeBases", description="Inspect document KBs, database KBs, and chunk counts"),
    PermissionScopeItem(scope="kb:read_content", category="KnowledgeBases", description="View raw document chunks, table data, and sensitive knowledge content (strictly audited)"),
    PermissionScopeItem(scope="kb:write", category="KnowledgeBases", description="Trigger re-indexing, re-parsing, or sync"),
    PermissionScopeItem(scope="kb:maintenance", category="KnowledgeBases", description="Execute database maintenance, vector vacuuming, and cleanup operations"),
    PermissionScopeItem(scope="kb:delete", category="KnowledgeBases", description="Remove knowledgebases or documents"),
    
    # Integrations
    PermissionScopeItem(scope="integrations:read", category="Integrations", description="Inspect Google Drive, Slack, and SharePoint connections"),
    PermissionScopeItem(scope="integrations:manage", category="Integrations", description="Configure OAuth credentials and enterprise connectors"),
    
    # Usage & Billing
    PermissionScopeItem(scope="usage:read", category="Usage & Billing", description="View API request volume, token throughput, and spend"),
    PermissionScopeItem(scope="quotas:manage", category="Usage & Billing", description="Adjust tenant LLM token quotas and rate limits"),
    PermissionScopeItem(scope="billing:manage", category="Usage & Billing", description="Configure plans, tiers, and pricing models"),
    
    # System Operations
    PermissionScopeItem(scope="system:read", category="System Operations", description="Inspect database, Neo4j, Redis, and API health"),
    PermissionScopeItem(scope="system:config", category="System Operations", description="View and update platform configuration flags"),
    PermissionScopeItem(scope="system:maintenance", category="System Operations", description="Trigger background workers and system diagnostics"),
    
    # Audit Logs
    PermissionScopeItem(scope="audit:read", category="Audit Trail", description="Search, view, and filter platform administrative audit logs"),
    PermissionScopeItem(scope="audit:export", category="Audit Trail", description="Export compliance audit records to CSV/JSON"),
    
    # Security & Staff
    PermissionScopeItem(scope="security:manage", category="Security", description="Enforce platform MFA, password policies, and IP allowlists"),
    PermissionScopeItem(scope="admins:read", category="Security", description="List platform SuperAdmin staff accounts"),
    PermissionScopeItem(scope="admins:write", category="Security", description="Create, update, or revoke SuperAdmin staff accounts"),
    PermissionScopeItem(scope="roles:manage", category="Security", description="Create and modify custom roles and permission scopes"),
]

SYSTEM_ROLES = [
    {
        "role_name": SuperAdminRole.SUPERADMIN_ROOT.value,
        "description": "Complete platform-level control (all scopes, sensitive actions, and root access).",
        "is_system": True,
        "permissions": ["*"],
    },
    {
        "role_name": SuperAdminRole.SUPER_ADMIN.value,
        "description": "Standard platform administrator with broad day-to-day administrative privileges.",
        "is_system": True,
        "permissions": [
            "orgs:read", "orgs:write", "orgs:suspend",
            "users:read", "users:write", "users:impersonate",
            "agents:read", "agents:write",
            "kb:read", "kb:write",
            "integrations:read", "integrations:manage",
            "usage:read", "quotas:manage",
            "system:read",
            "audit:read",
            "admins:read",
        ],
    },
    {
        "role_name": SuperAdminRole.PLATFORM_OPERATOR.value,
        "description": "Infrastructure, monitoring, job queues, and operational health management.",
        "is_system": True,
        "permissions": [
            "system:read", "system:config", "system:maintenance",
            "agents:read",
            "kb:read", "kb:write",
            "usage:read",
            "audit:read",
        ],
    },
    {
        "role_name": SuperAdminRole.SUPPORT_AUDITOR.value,
        "description": "Read-only access for customer support investigation, analytics, and audit inspection.",
        "is_system": True,
        "permissions": [
            "orgs:read", "users:read", "agents:read", "kb:read",
            "usage:read", "system:read", "audit:read",
        ],
    },
    {
        "role_name": SuperAdminRole.BILLING_ADMIN.value,
        "description": "Tenant quotas, token usage, plan tiers, and LLM cost governance.",
        "is_system": True,
        "permissions": [
            "orgs:read", "usage:read", "quotas:manage", "billing:manage",
        ],
    },
]


class RoleService:
    """Service providing role and permission management."""

    @staticmethod
    def get_permissions_catalog() -> List[PermissionScopeItem]:
        """Return full catalog of supported permission scopes."""
        return PERMISSION_SCOPES

    @staticmethod
    async def list_roles(db: AsyncSession) -> List[SuperAdminRoleDefinition]:
        """List all platform roles (auto-seeds default system roles if empty)."""
        res = await db.execute(select(SuperAdminRoleDefinition).order_by(SuperAdminRoleDefinition.created_at.asc()))
        roles = res.scalars().all()

        if not roles:
            logger.info("Seeding default SuperAdmin system roles...")
            seeded: List[SuperAdminRoleDefinition] = []
            for r in SYSTEM_ROLES:
                role_def = SuperAdminRoleDefinition(
                    role_name=r["role_name"],
                    description=r["description"],
                    is_system=r["is_system"],
                    permissions=r["permissions"],
                )
                db.add(role_def)
                seeded.append(role_def)
            await db.commit()
            for r in seeded:
                await db.refresh(r)
            return seeded

        return list(roles)

    @staticmethod
    async def get_role(role_id: UUID, db: AsyncSession) -> SuperAdminRoleDefinition:
        """Fetch role by UUID."""
        role = await db.get(SuperAdminRoleDefinition, role_id)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found.")
        return role

    @staticmethod
    async def create_role(data: RoleDefinitionCreate, db: AsyncSession) -> SuperAdminRoleDefinition:
        """Create a custom role with configurable scopes."""
        clean_name = data.role_name.strip().upper()
        existing = await db.execute(
            select(SuperAdminRoleDefinition).where(SuperAdminRoleDefinition.role_name == clean_name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Role with name '{clean_name}' already exists.")

        role = SuperAdminRoleDefinition(
            role_name=clean_name,
            description=data.description,
            is_system=False,
            permissions=data.permissions,
        )
        db.add(role)
        await db.commit()
        await db.refresh(role)
        return role

    @staticmethod
    async def update_role(
        role_id: UUID, data: RoleDefinitionUpdate, db: AsyncSession
    ) -> SuperAdminRoleDefinition:
        """Update description or permissions of a role."""
        role = await RoleService.get_role(role_id, db)
        update_data = data.dict(exclude_unset=True)

        if role.is_system and "permissions" in update_data and role.role_name == SuperAdminRole.SUPERADMIN_ROOT.value:
            # SUPERADMIN_ROOT must always retain wildcard
            if "*" not in update_data["permissions"]:
                update_data["permissions"].append("*")

        for k, v in update_data.items():
            setattr(role, k, v)

        db.add(role)
        await db.commit()
        await db.refresh(role)
        return role

    @staticmethod
    async def delete_role(role_id: UUID, db: AsyncSession) -> None:
        """Delete custom role (system roles cannot be deleted)."""
        role = await RoleService.get_role(role_id, db)
        if role.is_system:
            raise HTTPException(status_code=400, detail="System roles cannot be deleted.")

        await db.delete(role)
        await db.commit()

