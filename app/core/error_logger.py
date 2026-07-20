import logging
from typing import Optional, Union
from uuid import UUID

from app.core.database import AsyncSessionLocal
from app.modules.analytics.models import AppErrorLog
from app.modules.chats.repository import safe_uuid

logger = logging.getLogger("app.core.error_logger")

async def log_error_to_db(
    module: str,
    message: str,
    error_type: str,
    stack_trace: Optional[str] = None,
    tenant_id: Optional[Union[str, UUID]] = None,
    user_id: Optional[Union[str, UUID]] = None,
    endpoint: Optional[str] = None,
    request_metadata: Optional[dict] = None,
) -> None:
    """
    Log an application or pipeline error to the app_error_logs database table asynchronously.
    Does not raise exceptions if the database write fails to prevent secondary crashes.
    """
    try:
        async with AsyncSessionLocal() as db:
            error_log = AppErrorLog(
                tenant_id=safe_uuid(tenant_id) if tenant_id else None,
                user_id=safe_uuid(user_id) if user_id else None,
                module=module,
                endpoint=endpoint,
                error_type=error_type,
                message=message,
                stack_trace=stack_trace,
                request_metadata=request_metadata,
            )
            db.add(error_log)
            await db.commit()
    except Exception as db_err:
        logger.error(
            f"Failed to write error log to database: {db_err}. "
            f"Original Error in {module}: [{error_type}] {message}"
        )
