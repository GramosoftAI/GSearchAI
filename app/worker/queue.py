from arq import create_pool
from arq.connections import RedisSettings
from app.core.config import get_settings
import logging

import asyncio

logger = logging.getLogger(__name__)

_redis_pool = None
_redis_pool_lock = asyncio.Lock()

async def get_redis_pool():
    global _redis_pool
    if _redis_pool is None:
        async with _redis_pool_lock:
            if _redis_pool is None:
                settings = get_settings()
                redis_settings = RedisSettings.from_dsn(settings.redis_url)
                _redis_pool = await create_pool(redis_settings)
    return _redis_pool

async def startup(ctx):
    logger.info("Starting ARQ Worker...")
    ctx['redis'] = await get_redis_pool()

async def shutdown(ctx):
    global _redis_pool
    logger.info("Shutting down ARQ Worker...")
    if _redis_pool is not None:
        try:
            await _redis_pool.close()
        except Exception as e:
            logger.debug(f"Error closing redis pool: {e}")
        _redis_pool = None

from .jobs.gmail_sync import gmail_sync_job
from .jobs.email_processing import email_processing_job
from .jobs.embedding import embedding_job
from .jobs.graph_update import graph_update_job
from .jobs.google_drive_sync import google_drive_sync_job
from app.modules.integrations.slack.worker import slack_event_job
from app.modules.database_knowledgebase.knowledge.jobs import run_phase2_pipeline

class WorkerSettings:
    functions = [
        gmail_sync_job,
        email_processing_job,
        embedding_job,
        graph_update_job,
        google_drive_sync_job,
        slack_event_job,
        run_phase2_pipeline,
    ]

    max_tries = 5
    
    on_startup = startup
    on_shutdown = shutdown
    
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 10
    job_timeout = 3600  # 1 hour for long processing
