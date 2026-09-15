from arq import create_pool
from arq.connections import RedisSettings
from app.core.config import get_settings
import logging

logger = logging.getLogger(__name__)

async def get_redis_pool():
    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    return await create_pool(redis_settings)

async def startup(ctx):
    logger.info("Starting ARQ Worker...")
    settings = get_settings()
    ctx['redis'] = await get_redis_pool()

async def shutdown(ctx):
    logger.info("Shutting down ARQ Worker...")

from .jobs.gmail_sync import gmail_sync_job
from .jobs.email_processing import email_processing_job
from .jobs.embedding import embedding_job
from .jobs.graph_update import graph_update_job
from .jobs.google_drive_sync import google_drive_sync_job
from app.modules.integrations.slack.worker import slack_event_job

class WorkerSettings:
    functions = [
        gmail_sync_job,
        email_processing_job,
        embedding_job,
        graph_update_job,
        google_drive_sync_job,
        slack_event_job,
    ]

    
    on_startup = startup
    on_shutdown = shutdown
    
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 10
    job_timeout = 3600  # 1 hour for long processing
