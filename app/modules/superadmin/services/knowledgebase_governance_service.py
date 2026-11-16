"""SuperAdmin Global Knowledgebase Governance Service.

Provides platform-wide administration for customer knowledgebases:
- Global cross-tenant knowledgebase directory (Document KBs & Database KBs)
- Ownership tracking and associated agent relationships
- Document counts, ingestion metrics, and failure monitoring
- Processing jobs lifecycle management (listing, retry failed jobs, cancel stuck jobs)
- Ingestion audit history and telemetry inspection
- Storage consumption analytics and tenant capacity attribution
- Authorized maintenance and cleanup operations
- Strictly permission-controlled and audited raw content access (chunks, tables, entities)
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, and_, or_, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status, Request
import logging

from app.modules.knowledge_bases.models import (
    KnowledgeBase,
    DocumentChunk,
    DocumentTableRow,
    DocumentEntity,
    DocumentSection,
    DocumentIngestionRun,
    DatabaseConnection,
)
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseKnowledgebase
from app.modules.jobs.models import ProcessingJob
from app.modules.agents.models import Agent
from app.modules.auth.models import Tenant, User
from ..models import SuperAdminUser
from ..schemas import (
    SuperAdminKBListItem,
    SuperAdminKBListResponse,
    SuperAdminKBDetailResponse,
    KBContentItem,
    KBContentResponse,
    KBIngestionRunItem,
    KBProcessingJobItem,
    KBStorageAnalyticsResponse,
)
from ..dependencies import log_admin_activity

logger = logging.getLogger(__name__)


class KnowledgebaseGovernanceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_knowledgebases(
        self,
        search: Optional[str] = None,
        tenant_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        kb_type: Optional[str] = None,  # "document", "database", or None
        source: Optional[str] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SuperAdminKBListResponse:
        """List all customer knowledgebases across tenants with comprehensive metadata."""
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        kb_items: List[SuperAdminKBListItem] = []
        total_count = 0

        # 1. Document KnowledgeBases (if kb_type is not "database")
        if kb_type in [None, "document"]:
            doc_q = select(
                KnowledgeBase,
                Tenant.name.label("tenant_name"),
                User.email.label("user_email"),
                Agent.name.label("agent_name"),
            ).join(
                Tenant, KnowledgeBase.tenant_id == Tenant.id
            ).join(
                User, KnowledgeBase.user_id == User.id
            ).outerjoin(
                Agent, KnowledgeBase.agent_id == Agent.id
            )

            if tenant_id:
                doc_q = doc_q.where(KnowledgeBase.tenant_id == tenant_id)
            if agent_id:
                doc_q = doc_q.where(KnowledgeBase.agent_id == agent_id)
            if source:
                doc_q = doc_q.where(KnowledgeBase.source == source)
            if is_active is not None:
                doc_q = doc_q.where(KnowledgeBase.is_active == is_active)
            if search:
                s = f"%{search.strip().lower()}%"
                doc_q = doc_q.where(
                    or_(
                        func.lower(KnowledgeBase.name).like(s),
                        func.lower(KnowledgeBase.description).like(s),
                        func.lower(KnowledgeBase.canonical_name).like(s),
                    )
                )

            # Count total doc KBs
            count_q = select(func.count()).select_from(doc_q.subquery())
            doc_total = (await self.db.execute(count_q)).scalar_one() or 0
            total_count += doc_total

            doc_q = doc_q.order_by(desc(KnowledgeBase.created_at)).offset(offset).limit(page_size)
            doc_rows = (await self.db.execute(doc_q)).all()

            for row in doc_rows:
                kb_rec: KnowledgeBase = row[0]
                t_name = row[1] or "Unknown Organization"
                u_email = row[2] or "unknown"
                a_name = row[3] or "None"

                # Check last ingestion run status
                last_run_q = select(
                    DocumentIngestionRun.status,
                    DocumentIngestionRun.started_at,
                ).where(
                    DocumentIngestionRun.document_id == kb_rec.id
                ).order_by(desc(DocumentIngestionRun.started_at)).limit(1)
                last_run = (await self.db.execute(last_run_q)).first()
                ingest_status = last_run[0] if last_run else "NONE"
                ingest_at = last_run[1] if last_run else None

                kb_items.append(
                    SuperAdminKBListItem(
                        id=kb_rec.id,
                        name=kb_rec.name,
                        description=kb_rec.description,
                        canonical_name=kb_rec.canonical_name,
                        kb_type="document",
                        source=kb_rec.source,
                        total_chunks=kb_rec.total_chunks or 0,
                        is_active=kb_rec.is_active,
                        tenant_id=kb_rec.tenant_id,
                        tenant_name=t_name,
                        user_id=kb_rec.user_id,
                        user_email=u_email,
                        agent_id=kb_rec.agent_id,
                        agent_name=a_name,
                        last_ingestion_status=ingest_status,
                        last_ingestion_at=ingest_at,
                        created_at=kb_rec.created_at,
                        updated_at=kb_rec.updated_at,
                    )
                )

        # 2. Database Knowledgebases (if kb_type is not "document")
        if kb_type in [None, "database"]:
            db_kb_q = select(
                DatabaseKnowledgebase,
                Tenant.name.label("tenant_name"),
                User.email.label("user_email"),
                Agent.name.label("agent_name"),
            ).join(
                Tenant, DatabaseKnowledgebase.tenant_id == Tenant.id
            ).join(
                User, DatabaseKnowledgebase.user_id == User.id
            ).outerjoin(
                Agent, DatabaseKnowledgebase.agent_id == Agent.id
            )

            if tenant_id:
                db_kb_q = db_kb_q.where(DatabaseKnowledgebase.tenant_id == tenant_id)
            if agent_id:
                db_kb_q = db_kb_q.where(DatabaseKnowledgebase.agent_id == agent_id)
            if is_active is not None:
                db_kb_q = db_kb_q.where(DatabaseKnowledgebase.is_active == is_active)
            if search:
                s = f"%{search.strip().lower()}%"
                db_kb_q = db_kb_q.where(
                    or_(
                        func.lower(DatabaseKnowledgebase.name).like(s),
                        func.lower(DatabaseKnowledgebase.description).like(s),
                    )
                )

            count_db_q = select(func.count()).select_from(db_kb_q.subquery())
            db_total = (await self.db.execute(count_db_q)).scalar_one() or 0
            total_count += db_total

            # If filtering only database or if there is room on page
            if kb_type == "database" or len(kb_items) < page_size:
                db_kb_q = db_kb_q.order_by(desc(DatabaseKnowledgebase.created_at)).limit(page_size - len(kb_items))
                db_rows = (await self.db.execute(db_kb_q)).all()

                for row in db_rows:
                    dkb: DatabaseKnowledgebase = row[0]
                    t_name = row[1] or "Unknown Organization"
                    u_email = row[2] or "unknown"
                    a_name = row[3] or "None"

                    kb_items.append(
                        SuperAdminKBListItem(
                            id=dkb.id,
                            name=dkb.name,
                            description=dkb.description,
                            canonical_name=None,
                            kb_type="database",
                            source=dkb.database_type,
                            total_chunks=0,
                            is_active=dkb.is_active,
                            tenant_id=dkb.tenant_id,
                            tenant_name=t_name,
                            user_id=dkb.user_id,
                            user_email=u_email,
                            agent_id=dkb.agent_id,
                            agent_name=a_name,
                            last_ingestion_status=dkb.status.upper(),
                            last_ingestion_at=dkb.last_introspected_at or dkb.last_tested_at,
                            created_at=dkb.created_at,
                            updated_at=dkb.updated_at,
                        )
                    )

        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 1
        return SuperAdminKBListResponse(
            knowledgebases=kb_items,
            total=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def get_knowledgebase_detail(self, kb_id: UUID) -> SuperAdminKBDetailResponse:
        """Fetch detailed configuration, storage metrics, and ingestion history for a KB."""
        # 1. Try Document KB
        kb = await self.db.get(KnowledgeBase, kb_id)
        if kb:
            tenant = await self.db.get(Tenant, kb.tenant_id)
            user = await self.db.get(User, kb.user_id)
            agent = await self.db.get(Agent, kb.agent_id) if kb.agent_id else None

            # Storage metrics
            chunk_cnt = (await self.db.execute(
                select(func.count(DocumentChunk.id)).where(DocumentChunk.kb_id == kb.id)
            )).scalar_one() or 0

            table_cnt = (await self.db.execute(
                select(func.count(DocumentTableRow.id)).where(DocumentTableRow.kb_id == kb.id)
            )).scalar_one() or 0

            entity_cnt = (await self.db.execute(
                select(func.count(DocumentEntity.id)).where(DocumentEntity.document_id == kb.id)
            )).scalar_one() or 0

            section_cnt = (await self.db.execute(
                select(func.count(DocumentSection.id)).where(DocumentSection.document_id == kb.id)
            )).scalar_one() or 0

            # Database Connection if source is database
            db_conn_rec = await self.db.execute(
                select(DatabaseConnection).where(DatabaseConnection.kb_id == kb.id)
            )
            db_conn = db_conn_rec.scalar_one_or_none()
            db_conn_info = None
            if db_conn:
                db_conn_info = {
                    "db_type": db_conn.db_type,
                    "last_synced_at": db_conn.last_synced_at.isoformat() if db_conn.last_synced_at else None,
                    "created_at": db_conn.created_at.isoformat() if db_conn.created_at else None,
                }

            # Ingestion Runs
            runs_q = select(DocumentIngestionRun).where(
                DocumentIngestionRun.document_id == kb.id
            ).order_by(desc(DocumentIngestionRun.started_at)).limit(5)
            runs = (await self.db.execute(runs_q)).scalars().all()
            runs_data = [
                {
                    "id": str(r.id),
                    "status": r.status,
                    "chunk_count": r.chunk_count,
                    "entity_count": r.entity_count,
                    "triplet_count": r.triplet_count,
                    "duration_ms": r.total_duration_ms,
                    "error_message": r.error_message,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                }
                for r in runs
            ]

            return SuperAdminKBDetailResponse(
                id=kb.id,
                name=kb.name,
                description=kb.description,
                canonical_name=kb.canonical_name,
                kb_type="document",
                source=kb.source,
                total_chunks=kb.total_chunks or 0,
                is_active=kb.is_active,
                tenant_id=kb.tenant_id,
                tenant_name=tenant.name if tenant else "Unknown",
                user_id=kb.user_id,
                user_email=user.email if user else "unknown",
                agent_id=kb.agent_id,
                agent_name=agent.name if agent else None,
                s3_path=kb.s3_path,
                parsed_path=kb.parsed_path,
                file_hash=kb.file_hash,
                aliases=kb.aliases if isinstance(kb.aliases, list) else None,
                dataset_schema=kb.dataset_schema if isinstance(kb.dataset_schema, dict) else None,
                storage_stats={
                    "chunks": chunk_cnt,
                    "table_rows": table_cnt,
                    "entities": entity_cnt,
                    "sections": section_cnt,
                },
                db_connection=db_conn_info,
                recent_ingestion_runs=runs_data,
                created_at=kb.created_at,
                updated_at=kb.updated_at,
            )

        # 2. Try Database KB
        dkb = await self.db.get(DatabaseKnowledgebase, kb_id)
        if dkb:
            tenant = await self.db.get(Tenant, dkb.tenant_id)
            user = await self.db.get(User, dkb.user_id)
            agent = await self.db.get(Agent, dkb.agent_id) if dkb.agent_id else None

            return SuperAdminKBDetailResponse(
                id=dkb.id,
                name=dkb.name,
                description=dkb.description,
                canonical_name=None,
                kb_type="database",
                source=dkb.database_type,
                total_chunks=0,
                is_active=dkb.is_active,
                tenant_id=dkb.tenant_id,
                tenant_name=tenant.name if tenant else "Unknown",
                user_id=dkb.user_id,
                user_email=user.email if user else "unknown",
                agent_id=dkb.agent_id,
                agent_name=agent.name if agent else None,
                dataset_schema=dkb.settings if isinstance(dkb.settings, dict) else None,
                storage_stats={"database_type": dkb.database_type, "status": dkb.status},
                db_connection={
                    "db_type": dkb.database_type,
                    "status": dkb.status,
                    "schema_version": dkb.schema_version,
                    "last_tested_at": dkb.last_tested_at.isoformat() if dkb.last_tested_at else None,
                    "last_introspected_at": dkb.last_introspected_at.isoformat() if dkb.last_introspected_at else None,
                },
                recent_ingestion_runs=[],
                created_at=dkb.created_at,
                updated_at=dkb.updated_at,
            )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledgebase with ID {kb_id} not found."
        )

    async def get_knowledgebase_content(
        self,
        kb_id: UUID,
        content_type: str = "chunks",  # "chunks", "tables", "entities", "sections"
        page: int = 1,
        page_size: int = 20,
        admin: Optional[SuperAdminUser] = None,
        request: Optional[Request] = None,
    ) -> KBContentResponse:
        """
        PERMISSION-CONTROLLED AND AUDITED raw content inspection.
        Requires 'kb:read_content' permission scope.
        Logs every content inspection to the immutable platform audit trail.
        """
        kb = await self.db.get(KnowledgeBase, kb_id)
        if not kb:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document KnowledgeBase with ID {kb_id} not found."
            )

        tenant = await self.db.get(Tenant, kb.tenant_id)
        tenant_name = tenant.name if tenant else "Unknown"

        page = max(1, page)
        page_size = max(1, min(50, page_size))
        offset = (page - 1) * page_size

        items: List[KBContentItem] = []
        total_items = 0

        if content_type == "chunks":
            total_items = (await self.db.execute(
                select(func.count(DocumentChunk.id)).where(DocumentChunk.kb_id == kb.id)
            )).scalar_one() or 0

            q = select(DocumentChunk).where(
                DocumentChunk.kb_id == kb.id
            ).order_by(DocumentChunk.chunk_index).offset(offset).limit(page_size)
            chunks = (await self.db.execute(q)).scalars().all()

            for c in chunks:
                items.append(
                    KBContentItem(
                        id=c.id,
                        content_type="chunk",
                        index_or_page=c.chunk_index,
                        section=c.section,
                        preview_text=c.text[:500] if c.text else "",
                        metadata=c.metadata_json if isinstance(c.metadata_json, dict) else None,
                        created_at=c.created_at,
                    )
                )

        elif content_type == "tables":
            total_items = (await self.db.execute(
                select(func.count(DocumentTableRow.id)).where(DocumentTableRow.kb_id == kb.id)
            )).scalar_one() or 0

            q = select(DocumentTableRow).where(
                DocumentTableRow.kb_id == kb.id
            ).order_by(DocumentTableRow.table_index, DocumentTableRow.row_index).offset(offset).limit(page_size)
            rows = (await self.db.execute(q)).scalars().all()

            for r in rows:
                items.append(
                    KBContentItem(
                        id=r.id,
                        content_type="table_row",
                        index_or_page=r.page_number,
                        section=f"Table {r.table_index}, Row {r.row_index}",
                        preview_text=f"Part: {r.part_number or 'N/A'} | Product: {r.product_name or 'N/A'} | MRP: {r.mrp or 'N/A'}",
                        metadata=r.row_data if isinstance(r.row_data, dict) else None,
                        created_at=r.created_at,
                    )
                )

        elif content_type == "entities":
            total_items = (await self.db.execute(
                select(func.count(DocumentEntity.id)).where(DocumentEntity.document_id == kb.id)
            )).scalar_one() or 0

            q = select(DocumentEntity).where(
                DocumentEntity.document_id == kb.id
            ).order_by(desc(DocumentEntity.created_at)).offset(offset).limit(page_size)
            entities = (await self.db.execute(q)).scalars().all()

            for e in entities:
                items.append(
                    KBContentItem(
                        id=e.id,
                        content_type="entity",
                        index_or_page=e.page_number,
                        section=e.section_name,
                        preview_text=f"[{e.entity_type}] {e.entity_value} (confidence: {e.confidence})",
                        metadata={"source_text": e.source_text[:200] if e.source_text else ""},
                        created_at=e.created_at,
                    )
                )

        elif content_type == "sections":
            total_items = (await self.db.execute(
                select(func.count(DocumentSection.id)).where(DocumentSection.document_id == kb.id)
            )).scalar_one() or 0

            q = select(DocumentSection).where(
                DocumentSection.document_id == kb.id
            ).order_by(desc(DocumentSection.created_at)).offset(offset).limit(page_size)
            sections = (await self.db.execute(q)).scalars().all()

            for s in sections:
                items.append(
                    KBContentItem(
                        id=s.id,
                        content_type="section",
                        index_or_page=s.page_number,
                        section=s.section_name,
                        preview_text=str(s.section_json)[:400] if s.section_json else "",
                        metadata=s.section_json if isinstance(s.section_json, dict) else None,
                        created_at=s.created_at,
                    )
                )

        # STRICT AUDIT LOGGING FOR CONTENT ACCESS
        if admin:
            await log_admin_activity(
                db=self.db,
                admin=admin,
                action="VIEW_KB_CONTENT",
                resource_type="knowledgebase",
                resource_id=str(kb_id),
                target_tenant_id=kb.tenant_id,
                details={
                    "kb_name": kb.name,
                    "content_type": content_type,
                    "page": page,
                    "page_size": page_size,
                    "items_returned": len(items),
                },
                status_val="SUCCESS",
                request=request,
            )

        return KBContentResponse(
            kb_id=kb.id,
            kb_name=kb.name,
            tenant_id=kb.tenant_id,
            tenant_name=tenant_name,
            content_type=content_type,
            total_items=total_items,
            page=page,
            page_size=page_size,
            items=items,
        )

    async def list_ingestion_runs(
        self,
        kb_id: Optional[UUID] = None,
        tenant_id: Optional[UUID] = None,
        status_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[KBIngestionRunItem]:
        """View synchronization and ingestion history across knowledgebases."""
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        q = select(
            DocumentIngestionRun,
            KnowledgeBase.name.label("kb_name"),
            Tenant.name.label("tenant_name"),
        ).join(
            KnowledgeBase, DocumentIngestionRun.document_id == KnowledgeBase.id
        ).join(
            Tenant, DocumentIngestionRun.tenant_id == Tenant.id
        )

        if kb_id:
            q = q.where(DocumentIngestionRun.document_id == kb_id)
        if tenant_id:
            q = q.where(DocumentIngestionRun.tenant_id == tenant_id)
        if status_filter:
            q = q.where(DocumentIngestionRun.status == status_filter.upper())

        q = q.order_by(desc(DocumentIngestionRun.started_at)).offset(offset).limit(page_size)
        rows = (await self.db.execute(q)).all()

        return [
            KBIngestionRunItem(
                id=r[0].id,
                document_id=r[0].document_id,
                kb_name=r[1],
                tenant_id=r[0].tenant_id,
                tenant_name=r[2],
                status=r[0].status,
                chunk_count=r[0].chunk_count,
                entity_count=r[0].entity_count,
                triplet_count=r[0].triplet_count,
                repair_count=r[0].repair_count,
                retry_count=r[0].retry_count,
                llm_calls=r[0].llm_calls,
                llm_input_tokens=r[0].llm_input_tokens,
                llm_output_tokens=r[0].llm_output_tokens,
                embedding_tokens=r[0].embedding_tokens,
                embedding_cost_usd=r[0].embedding_cost_usd,
                total_duration_ms=r[0].total_duration_ms,
                error_message=r[0].error_message,
                started_at=r[0].started_at,
                completed_at=r[0].completed_at,
            )
            for r in rows
        ]

    async def list_processing_jobs(
        self,
        tenant_id: Optional[UUID] = None,
        kb_id: Optional[UUID] = None,
        status_filter: Optional[str] = None,
        job_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[KBProcessingJobItem]:
        """Inspect asynchronous processing jobs across all tenants."""
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        q = select(
            ProcessingJob,
            Tenant.name.label("tenant_name"),
            KnowledgeBase.name.label("kb_name"),
        ).join(
            Tenant, ProcessingJob.tenant_id == Tenant.id
        ).outerjoin(
            KnowledgeBase, ProcessingJob.kb_id == KnowledgeBase.id
        )

        if tenant_id:
            q = q.where(ProcessingJob.tenant_id == tenant_id)
        if kb_id:
            q = q.where(ProcessingJob.kb_id == kb_id)
        if status_filter:
            q = q.where(ProcessingJob.status == status_filter.lower())
        if job_type:
            q = q.where(ProcessingJob.job_type == job_type)

        q = q.order_by(desc(ProcessingJob.created_at)).offset(offset).limit(page_size)
        rows = (await self.db.execute(q)).all()

        return [
            KBProcessingJobItem(
                id=r[0].id,
                tenant_id=r[0].tenant_id,
                tenant_name=r[1],
                user_id=r[0].user_id,
                kb_id=r[0].kb_id,
                kb_name=r[2],
                job_type=r[0].job_type,
                status=r[0].status,
                progress=r[0].progress or 0,
                current_step=r[0].current_step,
                error_message=r[0].error_message,
                file_name=r[0].file_name,
                created_at=r[0].created_at,
                started_at=r[0].started_at,
                completed_at=r[0].completed_at,
            )
            for r in rows
        ]

    async def retry_failed_job(
        self,
        job_id: UUID,
        reason: str,
        admin: SuperAdminUser,
        request: Optional[Request] = None,
    ) -> Dict[str, Any]:
        """Retry a failed ingestion or processing job."""
        job = await self.db.get(ProcessingJob, job_id)
        if not job:
            # Check if it is a DocumentIngestionRun ID
            run = await self.db.get(DocumentIngestionRun, job_id)
            if run:
                run.status = "QUEUED"
                run.retry_count = (run.retry_count or 0) + 1
                run.error_message = None
                self.db.add(run)
                await self.db.commit()

                await log_admin_activity(
                    db=self.db,
                    admin=admin,
                    action="RETRY_INGESTION_RUN",
                    resource_type="ingestion_run",
                    resource_id=str(job_id),
                    target_tenant_id=run.tenant_id,
                    details={"reason": reason, "document_id": str(run.document_id)},
                    status_val="SUCCESS",
                    request=request,
                )
                return {"job_id": str(job_id), "status": "QUEUED", "message": "Document ingestion run queued for retry."}

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job with ID {job_id} not found."
            )

        job.status = "queued"
        job.progress = 0
        job.current_step = "Retrying from SuperAdmin"
        job.error_message = None
        job.updated_at = datetime.utcnow()
        self.db.add(job)
        await self.db.commit()

        # Try to re-enqueue into ARQ Redis if available
        try:
            from app.worker.queue import get_redis_pool
            redis_pool = await get_redis_pool()
            await redis_pool.enqueue_job("process_document_job", str(job.id), job.file_name, str(job.kb_id))
        except Exception as e:
            logger.warning(f"Could not re-enqueue job to Redis ARQ worker: {e}")

        await log_admin_activity(
            db=self.db,
            admin=admin,
            action="RETRY_PROCESSING_JOB",
            resource_type="processing_job",
            resource_id=str(job_id),
            target_tenant_id=job.tenant_id,
            details={"job_type": job.job_type, "reason": reason, "kb_id": str(job.kb_id) if job.kb_id else None},
            status_val="SUCCESS",
            request=request,
        )

        return {
            "job_id": str(job_id),
            "status": "queued",
            "message": f"Processing job {job_id} re-queued successfully."
        }

    async def cancel_job(
        self,
        job_id: UUID,
        reason: str,
        admin: SuperAdminUser,
        request: Optional[Request] = None,
    ) -> Dict[str, Any]:
        """Cancel a stuck or unwanted processing job."""
        job = await self.db.get(ProcessingJob, job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Processing job with ID {job_id} not found."
            )

        # Abort ARQ task if running
        try:
            from arq.jobs import Job as ArqJob, JobStatus
            from app.worker.queue import get_redis_pool
            redis_pool = await get_redis_pool()
            arq_job = ArqJob(str(job_id), redis_pool)
            status_val = await arq_job.status()
            if status_val in [JobStatus.queued, JobStatus.in_progress]:
                await arq_job.abort()
                logger.info(f"Aborted ARQ job {job_id}")
        except Exception as e:
            logger.warning(f"ARQ abort check failed: {e}")

        job.status = "cancelled"
        job.error_message = f"Cancelled by SuperAdmin: {reason}"
        job.completed_at = datetime.utcnow()
        self.db.add(job)
        await self.db.commit()

        await log_admin_activity(
            db=self.db,
            admin=admin,
            action="CANCEL_PROCESSING_JOB",
            resource_type="processing_job",
            resource_id=str(job_id),
            target_tenant_id=job.tenant_id,
            details={"reason": reason, "job_type": job.job_type},
            status_val="SUCCESS",
            request=request,
        )

        return {
            "job_id": str(job_id),
            "status": "cancelled",
            "message": f"Processing job {job_id} successfully cancelled."
        }

    async def get_storage_analytics(self) -> KBStorageAnalyticsResponse:
        """Monitor platform-wide storage consumption across customer knowledgebases."""
        doc_kb_cnt = (await self.db.execute(select(func.count(KnowledgeBase.id)))).scalar_one() or 0
        db_kb_cnt = (await self.db.execute(select(func.count(DatabaseKnowledgebase.id)))).scalar_one() or 0
        total_kbs = doc_kb_cnt + db_kb_cnt

        total_chunks = (await self.db.execute(select(func.count(DocumentChunk.id)))).scalar_one() or 0
        total_tables = (await self.db.execute(select(func.count(DocumentTableRow.id)))).scalar_one() or 0
        total_entities = (await self.db.execute(select(func.count(DocumentEntity.id)))).scalar_one() or 0
        total_sections = (await self.db.execute(select(func.count(DocumentSection.id)))).scalar_one() or 0

        # Top tenants by chunk count
        top_q = select(
            KnowledgeBase.tenant_id,
            Tenant.name.label("tenant_name"),
            func.count(KnowledgeBase.id).label("kb_count"),
            func.coalesce(func.sum(KnowledgeBase.total_chunks), 0).label("chunks_sum"),
        ).join(
            Tenant, KnowledgeBase.tenant_id == Tenant.id
        ).group_by(
            KnowledgeBase.tenant_id, Tenant.name
        ).order_by(
            desc("chunks_sum")
        ).limit(10)

        top_rows = (await self.db.execute(top_q)).all()
        top_tenants = [
            {
                "tenant_id": str(r[0]),
                "tenant_name": r[1],
                "kb_count": int(r[2]),
                "total_chunks": int(r[3]),
            }
            for r in top_rows
        ]

        return KBStorageAnalyticsResponse(
            total_knowledgebases=total_kbs,
            total_document_kbs=doc_kb_cnt,
            total_database_kbs=db_kb_cnt,
            total_chunks=total_chunks,
            total_table_rows=total_tables,
            total_entities=total_entities,
            total_sections=total_sections,
            top_tenants_by_storage=top_tenants,
        )

    async def execute_maintenance(
        self,
        kb_id: UUID,
        operation: str,
        reason: str,
        admin: SuperAdminUser,
        request: Optional[Request] = None,
    ) -> Dict[str, Any]:
        """Trigger authorized maintenance or cleanup operations on a knowledgebase."""
        kb = await self.db.get(KnowledgeBase, kb_id)
        if not kb:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document KnowledgeBase with ID {kb_id} not found."
            )

        details_out: Dict[str, Any] = {"operation": operation, "reason": reason}

        if operation == "generate_noisy_words":
            from app.modules.knowledge_bases.tasks import generate_kb_noisy_words
            try:
                await generate_kb_noisy_words(str(kb.id), str(kb.tenant_id))
                details_out["result"] = "Dynamic noisy words generated and cache invalidated."
            except Exception as e:
                logger.error(f"Maintenance generate_noisy_words failed: {e}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

        elif operation == "cleanup_orphaned_chunks":
            # Delete chunks without text or invalid
            del_q = delete(DocumentChunk).where(
                DocumentChunk.kb_id == kb.id,
                or_(DocumentChunk.text == None, DocumentChunk.text == "")
            )
            del_res = await self.db.execute(del_q)
            details_out["deleted_chunks"] = del_res.rowcount
            await self.db.commit()

        elif operation == "purge_failed_runs":
            del_runs_q = delete(DocumentIngestionRun).where(
                DocumentIngestionRun.document_id == kb.id,
                DocumentIngestionRun.status == "FAILED"
            )
            del_res = await self.db.execute(del_runs_q)
            details_out["purged_failed_runs"] = del_res.rowcount
            await self.db.commit()

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported maintenance operation '{operation}'. Supported: generate_noisy_words, cleanup_orphaned_chunks, purge_failed_runs."
            )

        await log_admin_activity(
            db=self.db,
            admin=admin,
            action="KB_MAINTENANCE_OP",
            resource_type="knowledgebase",
            resource_id=str(kb_id),
            target_tenant_id=kb.tenant_id,
            details=details_out,
            status_val="SUCCESS",
            request=request,
        )

        return {
            "kb_id": str(kb_id),
            "operation": operation,
            "details": details_out,
            "message": f"Maintenance operation '{operation}' completed successfully."
        }

    async def delete_knowledgebase(
        self,
        kb_id: UUID,
        reason: str,
        hard_delete: bool,
        admin: SuperAdminUser,
        request: Optional[Request] = None,
    ) -> Dict[str, Any]:
        """Soft-delete or permanently purge a knowledgebase under authorized policies."""
        kb = await self.db.get(KnowledgeBase, kb_id)
        if not kb:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Knowledgebase with ID {kb_id} not found."
            )

        tenant_id = kb.tenant_id
        kb_name = kb.name

        if hard_delete:
            # Delete children chunks, table rows, entities, sections, runs
            await self.db.execute(delete(DocumentChunk).where(DocumentChunk.kb_id == kb.id))
            await self.db.execute(delete(DocumentTableRow).where(DocumentTableRow.kb_id == kb.id))
            await self.db.execute(delete(DocumentEntity).where(DocumentEntity.document_id == kb.id))
            await self.db.execute(delete(DocumentSection).where(DocumentSection.document_id == kb.id))
            await self.db.execute(delete(DocumentIngestionRun).where(DocumentIngestionRun.document_id == kb.id))
            await self.db.delete(kb)
        else:
            kb.is_active = False
            kb.deleted_at = datetime.now(timezone.utc)
            self.db.add(kb)

        await self.db.commit()

        await log_admin_activity(
            db=self.db,
            admin=admin,
            action="HARD_DELETE_KB" if hard_delete else "SOFT_DELETE_KB",
            resource_type="knowledgebase",
            resource_id=str(kb_id),
            target_tenant_id=tenant_id,
            details={"kb_name": kb_name, "hard_delete": hard_delete, "reason": reason},
            status_val="SUCCESS",
            request=request,
        )

        return {
            "kb_id": str(kb_id),
            "name": kb_name,
            "hard_delete": hard_delete,
            "message": f"Knowledgebase '{kb_name}' {'purged permanently' if hard_delete else 'deactivated'}."
        }

    async def reassign_knowledgebase(
        self,
        kb_id: UUID,
        new_agent_id: Optional[UUID],
        new_user_id: Optional[UUID],
        reason: str,
        authorization_reference: str,
        admin: SuperAdminUser,
        request: Optional[Request] = None,
    ) -> Dict[str, Any]:
        """Reassign knowledgebase ownership or associated AI agent."""
        kb = await self.db.get(KnowledgeBase, kb_id)
        if not kb:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Knowledgebase with ID {kb_id} not found."
            )

        old_agent_id = kb.agent_id
        old_user_id = kb.user_id

        if new_agent_id:
            new_agent = await self.db.get(Agent, new_agent_id)
            if not new_agent:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent with ID {new_agent_id} not found."
                )
            if new_agent.tenant_id != kb.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Target agent belongs to a different tenant. Migrate tenant first."
                )
            kb.agent_id = new_agent_id

        if new_user_id:
            new_user = await self.db.get(User, new_user_id)
            if not new_user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User with ID {new_user_id} not found."
                )
            if new_user.tenant_id != kb.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Target user belongs to a different tenant."
                )
            kb.user_id = new_user_id

        self.db.add(kb)
        await self.db.commit()

        await log_admin_activity(
            db=self.db,
            admin=admin,
            action="REASSIGN_KB",
            resource_type="knowledgebase",
            resource_id=str(kb_id),
            target_tenant_id=kb.tenant_id,
            details={
                "kb_name": kb.name,
                "previous_agent_id": str(old_agent_id) if old_agent_id else None,
                "new_agent_id": str(new_agent_id) if new_agent_id else None,
                "previous_user_id": str(old_user_id) if old_user_id else None,
                "new_user_id": str(new_user_id) if new_user_id else None,
                "authorization_reference": authorization_reference,
                "reason": reason,
            },
            status_val="SUCCESS",
            request=request,
        )

        return {
            "kb_id": str(kb_id),
            "name": kb.name,
            "agent_id": str(kb.agent_id) if kb.agent_id else None,
            "user_id": str(kb.user_id) if kb.user_id else None,
            "message": f"Knowledgebase '{kb.name}' reassigned successfully."
        }
