from sqlalchemy.ext.asyncio import AsyncSession
import logging
from typing import Dict, Any

from app.utils.formatters import format_success, format_error
from .repository import JobRepository
from .schemas import JobCreate, JobResponse

logger = logging.getLogger(__name__)

class JobService:
    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.repo = JobRepository(db, tenant_id)

    async def create_job(self, user_id: str, job_in: JobCreate) -> Dict[str, Any]:
        try:
            job = await self.repo.create_job(user_id, job_in)
            await self.db.commit()
            return format_success({"job": JobResponse.model_validate(job)})
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to create job: {e}")
            return format_error(f"Failed to create job: {str(e)}")

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        try:
            job = await self.repo.get_job(job_id)
            if not job:
                return format_error("Job not found", meta={"status_code": 404})
            return format_success({"job": JobResponse.model_validate(job)})
        except Exception as e:
            logger.error(f"Failed to fetch job {job_id}: {e}")
            return format_error(f"Failed to fetch job: {str(e)}")

    async def update_job_progress(self, job_id: str, status: str, progress: int = None, current_step: str = None, error_message: str = None, kb_id: str = None) -> Dict[str, Any]:
        try:
            job = await self.repo.update_job_status(job_id, status, progress, current_step, error_message, kb_id)
            await self.db.commit()
            return format_success({"job": JobResponse.model_validate(job)})
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to update job {job_id}: {e}")
            return format_error(f"Failed to update job: {str(e)}")
