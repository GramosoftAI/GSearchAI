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
            if job:
                return format_success({"job": JobResponse.model_validate(job)})
            
            # Check ARQ Redis pool for background task status
            try:
                from arq.jobs import Job, JobStatus
                from app.worker.queue import get_redis_pool
                redis_pool = await get_redis_pool()
                arq_job = Job(job_id, redis_pool)
                status = await arq_job.status()
                info = await arq_job.info()
                
                if status != JobStatus.not_found:
                    result = None
                    if status == JobStatus.complete:
                        result = await arq_job.result()
                    return format_success({
                        "job_id": job_id,
                        "status": status.value,
                        "function": info.function if info else None,
                        "enqueue_time": info.enqueue_time.isoformat() if info and info.enqueue_time else None,
                        "result": result
                    })
            except Exception as arq_err:
                logger.warning(f"Failed to check ARQ Redis job status: {arq_err}")

            return format_error("Job not found", meta={"status_code": 404})
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

    async def cancel_and_delete_job(self, job_id: str) -> Dict[str, Any]:
        try:
            job = await self.repo.get_job(job_id)
            if not job:
                return format_error("Job not found", meta={"status_code": 404})
            
            # Cancel running task in Redis ARQ
            try:
                from arq.jobs import Job as ArqJob, JobStatus
                from app.worker.queue import get_redis_pool
                redis_pool = await get_redis_pool()
                arq_job = ArqJob(job_id, redis_pool)
                status = await arq_job.status()
                
                if status in [JobStatus.queued, JobStatus.in_progress]:
                    await arq_job.abort()
                    logger.info(f"Aborted ARQ job {job_id}")
            except Exception as arq_err:
                logger.warning(f"Failed to abort ARQ job: {arq_err}")
                
            # Delete from DB
            deleted = await self.repo.delete_job(job_id)
            if deleted:
                await self.db.commit()
                return format_success({"message": "Job cancelled and deleted successfully"})
            else:
                return format_error("Failed to delete job from database")
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to cancel/delete job {job_id}: {e}")
            return format_error(f"Failed to process request: {str(e)}")
