"""Tenant-Scoped Database Knowledgebase Repository

Inherits from BaseRepository to guarantee strict multi-tenant isolation.
Every SQL query includes tenant_id filtering alongside PostgreSQL RLS.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc, func
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import uuid

from app.core.base_repository import BaseRepository
from ..models.database_knowledgebase import DatabaseKnowledgebase, DatabaseSchemaSnapshot
from ..observability.audit_model import DatabaseQueryAuditLog
from ..exceptions.errors import TenantMismatchError


class DatabaseKnowledgebaseRepository(BaseRepository):
    """
    Data access repository for Database Knowledgebase entities and Schema Snapshots.
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        super().__init__(db, tenant_id)

    async def create_db_kb(
        self,
        user_id: uuid.UUID,
        name: str,
        database_type: str,
        encrypted_credentials: str,
        description: Optional[str] = None,
        agent_id: Optional[uuid.UUID] = None,
    ) -> DatabaseKnowledgebase:
        """Create a new DatabaseKnowledgebase record scoped to the authenticated tenant."""
        entity = DatabaseKnowledgebase(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            name=name,
            description=description,
            database_type=database_type,
            encrypted_credentials=encrypted_credentials,
            status="configured",
            is_active=True,
        )
        self.db.add(entity)
        await self.db.flush()
        return entity

    async def get_by_id(self, kb_id: uuid.UUID) -> Optional[DatabaseKnowledgebase]:
        """Fetch active DatabaseKnowledgebase by ID with strict tenant scoping."""
        stmt = select(DatabaseKnowledgebase).where(
            DatabaseKnowledgebase.id == kb_id,
            DatabaseKnowledgebase.tenant_id == self.tenant_id,
            DatabaseKnowledgebase.is_active == True,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_kbs(
        self, skip: int = 0, limit: int = 50, agent_id: Optional[uuid.UUID] = None
    ) -> List[DatabaseKnowledgebase]:
        """List active DatabaseKnowledgebase records for current tenant."""
        stmt = select(DatabaseKnowledgebase).where(
            DatabaseKnowledgebase.tenant_id == self.tenant_id,
            DatabaseKnowledgebase.is_active == True,
        )
        if agent_id:
            stmt = stmt.where(DatabaseKnowledgebase.agent_id == agent_id)

        stmt = stmt.order_by(desc(DatabaseKnowledgebase.created_at)).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_db_kb(
        self,
        kb_id: uuid.UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        agent_id: Optional[uuid.UUID] = None,
        encrypted_credentials: Optional[str] = None,
        status: Optional[str] = None,
        schema_version: Optional[str] = None,
        last_tested_at: Optional[datetime] = None,
        last_introspected_at: Optional[datetime] = None,
        last_error: Optional[str] = None,
    ) -> Optional[DatabaseKnowledgebase]:
        """Update existing DatabaseKnowledgebase record."""
        entity = await self.get_by_id(kb_id)
        if not entity:
            return None

        if name is not None:
            entity.name = name
        if description is not None:
            entity.description = description
        if agent_id is not None:
            entity.agent_id = agent_id
        if encrypted_credentials is not None:
            entity.encrypted_credentials = encrypted_credentials
        if status is not None:
            entity.status = status
        if schema_version is not None:
            entity.schema_version = schema_version
        if last_tested_at is not None:
            entity.last_tested_at = last_tested_at
        if last_introspected_at is not None:
            entity.last_introspected_at = last_introspected_at
        if last_error is not None:
            entity.last_error = last_error

        await self.db.flush()
        return entity

    async def delete_db_kb(self, kb_id: uuid.UUID, soft: bool = True) -> bool:
        """Delete or soft-delete DatabaseKnowledgebase."""
        entity = await self.get_by_id(kb_id)
        if not entity:
            return False

        if soft:
            entity.is_active = False
            entity.deleted_at = datetime.utcnow()
            await self.db.flush()
        else:
            await self.db.delete(entity)
            await self.db.flush()
        return True

    # ============= SCHEMA SNAPSHOT OPERATIONS =============

    async def save_schema_snapshot(
        self,
        db_kb_id: uuid.UUID,
        schema_version: str,
        schema_data: Dict[str, Any],
        table_count: int,
        column_count: int,
        relationship_count: int,
    ) -> DatabaseSchemaSnapshot:
        """Store a serialized canonical schema snapshot."""
        snapshot = DatabaseSchemaSnapshot(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            db_knowledgebase_id=db_kb_id,
            schema_version=schema_version,
            schema_data=schema_data,
            table_count=table_count,
            column_count=column_count,
            relationship_count=relationship_count,
        )
        self.db.add(snapshot)
        await self.db.flush()
        return snapshot

    async def get_latest_schema_snapshot(
        self, db_kb_id: uuid.UUID
    ) -> Optional[DatabaseSchemaSnapshot]:
        """Fetch most recent schema snapshot for this knowledgebase."""
        stmt = (
            select(DatabaseSchemaSnapshot)
            .where(
                DatabaseSchemaSnapshot.db_knowledgebase_id == db_kb_id,
                DatabaseSchemaSnapshot.tenant_id == self.tenant_id,
            )
            .order_by(desc(DatabaseSchemaSnapshot.created_at))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_snapshot_by_version(
        self, db_kb_id: uuid.UUID, schema_version: str
    ) -> Optional[DatabaseSchemaSnapshot]:
        """Fetch specific schema snapshot version."""
        stmt = select(DatabaseSchemaSnapshot).where(
            DatabaseSchemaSnapshot.db_knowledgebase_id == db_kb_id,
            DatabaseSchemaSnapshot.tenant_id == self.tenant_id,
            DatabaseSchemaSnapshot.schema_version == schema_version,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_snapshots(
        self, db_kb_id: uuid.UUID, limit: int = 10
    ) -> List[DatabaseSchemaSnapshot]:
        """List historical schema snapshots for a knowledgebase."""
        stmt = (
            select(DatabaseSchemaSnapshot)
            .where(
                DatabaseSchemaSnapshot.db_knowledgebase_id == db_kb_id,
                DatabaseSchemaSnapshot.tenant_id == self.tenant_id,
            )
            .order_by(desc(DatabaseSchemaSnapshot.created_at))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_audit_logs(
        self,
        kb_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        final_status: Optional[str] = None,
        min_latency_ms: Optional[float] = None,
    ) -> Tuple[List[DatabaseQueryAuditLog], int]:
        """
        Query audit logs strictly filtered by tenant_id and knowledgebase_id.
        Guarantees cross-tenant boundary isolation.
        Returns: (items, total_count)
        """
        base_filters = [
            DatabaseQueryAuditLog.tenant_id == uuid.UUID(str(self.tenant_id)),
            DatabaseQueryAuditLog.knowledgebase_id == kb_id,
        ]

        if start_time:
            base_filters.append(DatabaseQueryAuditLog.request_timestamp >= start_time)
        if end_time:
            base_filters.append(DatabaseQueryAuditLog.request_timestamp <= end_time)
        if final_status:
            base_filters.append(DatabaseQueryAuditLog.final_status == final_status)
        if min_latency_ms is not None:
            base_filters.append(DatabaseQueryAuditLog.total_latency_ms >= min_latency_ms)

        # 1. Total count query
        count_stmt = select(func.count(DatabaseQueryAuditLog.id)).where(*base_filters)
        count_res = await self.db.execute(count_stmt)
        total_count = count_res.scalar_one()

        # 2. Paginated rows query
        stmt = (
            select(DatabaseQueryAuditLog)
            .where(*base_filters)
            .order_by(desc(DatabaseQueryAuditLog.request_timestamp))
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        items = list(result.scalars().all())

        return items, total_count
