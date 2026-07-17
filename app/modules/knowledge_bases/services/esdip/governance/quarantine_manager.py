from ..domain.pipeline_context import PipelineContext
from ..domain.business_object import ObjectState

class QuarantineManager:
    """Handles objects routed to QUARANTINED state."""
    def run(self, context: PipelineContext) -> PipelineContext:
        quarantined = [obj for obj in context.business_object_store.get_all() if obj.state == ObjectState.QUARANTINED]
        if quarantined:
            context.log(f"Quarantine Manager: {len(quarantined)} objects are currently in quarantine.")
            # Future: send to dead-letter queue or alert system
        return context
