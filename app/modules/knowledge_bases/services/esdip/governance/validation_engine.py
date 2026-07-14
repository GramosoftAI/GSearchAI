from ..domain.pipeline_context import PipelineContext
from ..domain.business_object import ObjectState
from .state_machine import StateMachine

class ValidationEngine:
    """Ensures data quality and structural integrity."""
    def run(self, context: PipelineContext) -> PipelineContext:
        for obj in context.business_object_store.get_all():
            if not obj.attributes:
                obj.state = ObjectState.QUARANTINED
                obj.quarantine_reason = "Empty attributes"
                context.add_warning(f"Quarantined {obj.id}: Empty attributes")
                
        # Transition non-quarantined objects to VALIDATED
        StateMachine.transition(context, ObjectState.NORMALIZED, ObjectState.VALIDATED)
        return context
