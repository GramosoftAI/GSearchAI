"""Repository layer for Knowledge Base (PostgreSQL)"""



from app.modules.knowledge_bases.models import DocumentChunk

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, and_, delete

from typing import Optional, List

import logging

import uuid

from datetime import datetime



from .models import KnowledgeBase

from ...core.base_repository import BaseRepository



logger = logging.getLogger(__name__)





class KnowledgeBaseRepository(BaseRepository):

    """

    Repository for Knowledge Base CRUD operations.



    CRITICAL: All queries include tenant_id filtering (RLS enforcement).

    """



    def __init__(self, db: AsyncSession, tenant_id: str):

        """

        Initialize KB repository with tenant context.



        Args:

            db: Database session

            tenant_id: Tenant UUID (for RLS filtering)

        """

        super().__init__(db, tenant_id)

        self.model = KnowledgeBase



    async def create(

        self,

        name: str,

        agent_id: str,

        user_id: str,

        description: Optional[str] = None,

        source: str = "user_upload",

        s3_path: Optional[str] = None,

        dataset_schema: Optional[dict] = None,

        file_hash: Optional[str] = None,

    ) -> KnowledgeBase:

        """

        Create a new knowledge base.



        CRITICAL:

        - tenant_id is ALWAYS set from context

        - agent_id must exist and belong to this tenant

        - Returns KB for immediate Neo4j node creation



        Args:

            name: KB name

            agent_id: Agent UUID (KB owner)

            user_id: User UUID (who created KB)

            description: Optional description

            source: Source type

            s3_path: Optional S3 URL/path

            file_hash: Optional SHA-256 hash of the uploaded document



        Returns:

            Created KnowledgeBase model instance

        """

        kb = KnowledgeBase(

            id=uuid.uuid4(),

            tenant_id=self.tenant_id,

            user_id=uuid.UUID(user_id),

            agent_id=uuid.UUID(agent_id),

            name=name,

            description=description,

            source=source,

            total_chunks=0,

            is_active=True,

            s3_path=s3_path,
            dataset_schema=dataset_schema,
            file_hash=file_hash,
        )




        self.db.add(kb)

        await self.db.flush()



        logger.info(

            f" Created KB in PostgreSQL: {kb.id} (agent: {agent_id}, tenant: {self.tenant_id})"

        )

        return kb



    async def get_by_id(self, kb_id: str) -> Optional[KnowledgeBase]:

        """

        Get KB by ID with tenant_id filtering (RLS).



        Args:

            kb_id: KB UUID



        Returns:

            KnowledgeBase model or None



        GUARANTEE: Cannot return KB from other tenants (RLS enforced)

        """

        result = await self.db.execute(

            select(KnowledgeBase).where(

                and_(

                    KnowledgeBase.id == uuid.UUID(kb_id),

                    KnowledgeBase.tenant_id == self.tenant_id,

                    KnowledgeBase.is_active == True,

                )

            )

        )

        kb = result.scalar_one_or_none()



        if kb:

            logger.debug(f"Found KB: {kb_id}")

        else:

            logger.debug(f"KB not found: {kb_id}")



        return kb



    async def list_kbs(

        self, limit: int = 50, offset: int = 0

    ) -> tuple[List[KnowledgeBase], int]:

        """

        List all KBs for tenant with pagination.



        Args:

            limit: Max results

            offset: Pagination offset



        Returns:

            Tuple of (kbs, total_count)



        GUARANTEE: Only returns KBs for this tenant (RLS enforced)

        """

        # Get count

        count_result = await self.db.execute(

            select(KnowledgeBase).where(

                and_(

                    KnowledgeBase.tenant_id == self.tenant_id,

                    KnowledgeBase.is_active == True,

                )

            )

        )

        total = len(count_result.all())



        # Get paginated results

        result = await self.db.execute(

            select(KnowledgeBase)

            .where(

                and_(

                    KnowledgeBase.tenant_id == self.tenant_id,

                    KnowledgeBase.is_active == True,

                )

            )

            .order_by(KnowledgeBase.created_at.desc())

            .limit(limit)

            .offset(offset)

        )

        kbs = result.scalars().all()



        logger.info(

            f"Listed {len(kbs)} KBs for tenant {self.tenant_id} (total: {total})"

        )

        return kbs, total



    async def list_by_agent(

        self, agent_id: str, limit: int = 50, offset: int = 0

    ) -> tuple[List[KnowledgeBase], int]:

        """

        List all KBs for a specific agent (within tenant).

        """

        # Get count

        count_result = await self.db.execute(

            select(KnowledgeBase).where(

                and_(

                    KnowledgeBase.tenant_id == self.tenant_id,

                    KnowledgeBase.agent_id == uuid.UUID(agent_id),

                    KnowledgeBase.is_active == True,

                )

            )

        )

        total = len(count_result.all())



        # Get paginated results

        result = await self.db.execute(

            select(KnowledgeBase)

            .where(

                and_(

                    KnowledgeBase.tenant_id == self.tenant_id,

                    KnowledgeBase.agent_id == uuid.UUID(agent_id),

                    KnowledgeBase.is_active == True,

                )

            )

            .order_by(KnowledgeBase.created_at.desc())

            .limit(limit)

            .offset(offset)

        )

        kbs = result.scalars().all()



        logger.info(f"Listed {len(kbs)} KBs for agent {agent_id} (total: {total})")

        return kbs, total





    async def update(self, kb_id: str, **kwargs) -> Optional[KnowledgeBase]:

        """

        Update KB fields (PATCH).



        CRITICAL:

        - tenant_id filtering prevents cross-tenant updates

        - Only updates fields provided in kwargs



        Args:

            kb_id: KB UUID

            **kwargs: Fields to update (name, description, is_active)



        Returns:

            Updated KnowledgeBase or None if not found



        GUARANTEE: Cannot update KB from other tenants (RLS enforced)

        """

        kb = await self.get_by_id(kb_id)

        if not kb:

            logger.warning(f"Cannot update: KB not found: {kb_id}")

            return None



        # Update provided fields

        update_fields = {

            k: v for k, v in kwargs.items() if v is not None and hasattr(kb, k)

        }



        for field, value in update_fields.items():

            setattr(kb, field, value)



        await self.db.flush()



        logger.info(f"Updated KB: {kb_id} with fields: {list(update_fields.keys())}")

        return kb



    async def increment_chunks(self, kb_id: str, count: int = 1) -> bool:

        """

        Increment chunk count (called when chunks are added).



        Args:

            kb_id: KB UUID

            count: Number of chunks to add (default 1)



        Returns:

            True if updated, False if not found

        """

        kb = await self.get_by_id(kb_id)

        if not kb:

            logger.warning(f"Cannot increment chunks: KB not found: {kb_id}")

            return False



        kb.total_chunks += count

        await self.db.flush()



        logger.info(f"Updated KB {kb_id}: total_chunks = {kb.total_chunks}")

        return True



    async def soft_delete(self, kb_id: str) -> bool:

        """

        Soft delete KB (set is_active = False, deleted_at = now()).



        CRITICAL:

        - Does NOT delete from PostgreSQL (keeps history)

        - Neo4j deletion handled by service layer

        - tenant_id filtering prevents cross-tenant deletion



        Args:

            kb_id: KB UUID



        Returns:

            True if deleted, False if not found



        GUARANTEE: Cannot delete KB from other tenants (RLS enforced)

        """

        kb = await self.get_by_id(kb_id)

        if not kb:

            logger.warning(f"Cannot soft delete: KB not found: {kb_id}")

            return False



        kb.is_active = False

        kb.deleted_at = datetime.utcnow()

        await self.db.flush()



        logger.info(f"Soft deleted KB: {kb_id} (deleted_at={kb.deleted_at})")

        return True



    async def hard_delete(self, kb_id: str) -> bool:

        """

        Hard delete KB (actually remove from database).



        CRITICAL:

        - Only use for testing/cleanup

        - Production: use soft_delete()

        - tenant_id filtering prevents cross-tenant deletion



        Args:

            kb_id: KB UUID



        Returns:

            True if deleted, False if not found

        """

        result = await self.db.execute(

            delete(KnowledgeBase).where(

                and_(

                    KnowledgeBase.id == uuid.UUID(kb_id),

                    KnowledgeBase.tenant_id == self.tenant_id,

                )

            )

        )



        if result.rowcount > 0:

            logger.info(f"Hard deleted KB: {kb_id}")

            return True

        else:

            logger.warning(f"Cannot hard delete: KB not found: {kb_id}")

            return False

  



    async def list_knowledge_source(self, agent_id: str) -> List[dict]:

        """

        List all unique non-null names (sources) from KnowledgeBase for a given agent_id

        along with their earliest created_at timestamp.

        """

        from sqlalchemy import func

        result = await self.db.execute(

            select(

                KnowledgeBase.source.label("source"),

                func.min(KnowledgeBase.created_at).label("created_at")

            )

            .where(

                and_(

                    KnowledgeBase.tenant_id == self.tenant_id,

                    KnowledgeBase.agent_id == (uuid.UUID(agent_id) if isinstance(agent_id, str) else agent_id),

                    KnowledgeBase.is_active == True,

                )

            )

            .group_by(KnowledgeBase.source)

            .order_by(func.min(KnowledgeBase.created_at).asc())

        )

        rows = result.all()

        

        # Filter and structure into dicts

        sources = []

        for r in rows:

            src = r.source

            if src and src.strip():

                sources.append({

                    "source": src.strip(),

                    "created_at": r.created_at.isoformat() if isinstance(r.created_at, datetime) else r.created_at

                })

        logger.info(f"Listed {len(sources)} unique sources with timestamps for agent {agent_id}")

        return sources 