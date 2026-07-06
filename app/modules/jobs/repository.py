from typing import Optional
from sqlalchemy.future import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from datetime import datetime

from app.core.base_repository import BaseRepository
from .models import ProcessingJob
from .schemas import JobCreate

class JobRepository(BaseRepository):

    async def create_job(self, user_id: str, job_in: JobCreate) -> ProcessingJob:
        job = ProcessingJob(
            tenant_id=self.tenant_id,
            user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
            job_type=job_in.job_type,
            file_name=job_in.file_name,
            kb_id=job_in.kb_id,
            status="queued"
        )
        self.db.add(job)
        await self.db.flush()
        return job

    async def get_job(self, job_id: str) -> Optional[ProcessingJob]:
        stmt = select(ProcessingJob).where(
            ProcessingJob.id == (uuid.UUID(job_id) if isinstance(job_id, str) else job_id),
            ProcessingJob.tenant_id == self.tenant_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_job_status(
        self, 
        job_id: str, 
        status: str, 
        progress: int = None, 
        current_step: str = None, 
        error_message: str = None,
        kb_id: str = None
    ) -> Optional[ProcessingJob]:
        
        job = await self.get_job(job_id)
        if not job:
            return None
            
        update_data = {"status": status, "updated_at": datetime.utcnow()}
        
        if progress is not None:
            update_data["progress"] = progress
        if current_step is not None:
            update_data["current_step"] = current_step
        if error_message is not None:
            update_data["error_message"] = error_message
        if kb_id is not None:
            update_data["kb_id"] = uuid.UUID(kb_id) if isinstance(kb_id, str) else kb_id
            
        if status == "processing" and job.started_at is None:
            update_data["started_at"] = datetime.utcnow()
        elif status in ["completed", "failed"]:
            update_data["completed_at"] = datetime.utcnow()
            
        stmt = update(ProcessingJob).where(
            ProcessingJob.id == (uuid.UUID(job_id) if isinstance(job_id, str) else job_id),
            ProcessingJob.tenant_id == self.tenant_id
        ).values(**update_data)
        
        await self.db.execute(stmt)
        await self.db.flush()
        
        return await self.get_job(job_id)
