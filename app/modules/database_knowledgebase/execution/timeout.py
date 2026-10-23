"""Phase 2C Timeout Protection and Configuration

Provides helpers to compute and format PostgreSQL statement and lock timeouts,
guaranteeing safe query execution bounded by explicit latency budgets.
"""

from typing import Dict, Optional
from .models import ExecutionConfig


class TimeoutManager:
    """Manages PostgreSQL session timeout configurations."""

    @classmethod
    def get_statement_timeout_str(cls, config: ExecutionConfig) -> str:
        """Return formatted statement timeout (e.g. '5000ms')."""
        return f"{config.statement_timeout_ms}ms"

    @classmethod
    def get_lock_timeout_str(cls, config: ExecutionConfig) -> str:
        """Return formatted lock timeout (e.g. '2000ms')."""
        return f"{config.lock_timeout_ms}ms"

    @classmethod
    def get_session_settings(cls, config: ExecutionConfig, tenant_id: Optional[str] = None) -> Dict[str, str]:
        """Return dictionary of server settings for asyncpg connection initialization."""
        settings = {
            "statement_timeout": cls.get_statement_timeout_str(config),
            "lock_timeout": cls.get_lock_timeout_str(config),
            "default_transaction_read_only": "on",
            "application_name": "GSearchAI_ReadOnly_Executor",
            "app.current_tenant": str(tenant_id or "00000000-0000-0000-0000-000000000000"),
        }
        return settings

