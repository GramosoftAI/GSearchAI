import logging
from ..domain.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

class EventEmitter:
    @staticmethod
    def emit(event_name: str, context: PipelineContext, metadata: dict = None):
        """Emits standard lifecycle events for telemetry."""
        meta_str = f" | {metadata}" if metadata else ""
        logger.info(f"[ESDIP_EVENT] {event_name} (Tenant: {context.tenant_id}){meta_str}")
        
    @staticmethod
    def emit_detailed(event_name: str, tenant_id: str, metadata: dict = None):
        """Emits events when context is not available."""
        meta_str = f" | {metadata}" if metadata else ""
        logger.info(f"[ESDIP_EVENT] {event_name} (Tenant: {tenant_id}){meta_str}")
