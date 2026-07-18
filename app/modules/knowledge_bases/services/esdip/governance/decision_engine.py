from ..domain.pipeline_context import PipelineContext
from ..domain.business_object import ObjectState
from .state_machine import StateMachine

class DecisionEngine:
    """Decides routing (Accept, Reject, Retry, Escalate, Quarantine) based on policies and confidence."""
    def run(self, context: PipelineContext) -> PipelineContext:
        for obj in context.business_object_store.get_all():
            if obj.state == ObjectState.QUARANTINED:
                continue
            
            # Simulated decision logic
            # In production, this consults PolicyEngine rules
            if not obj.attributes:
                obj.state = ObjectState.QUARANTINED
                obj.quarantine_reason = "DecisionEngine: Rejected due to missing attributes"
                
        context.log("Decision Engine evaluation complete.")
        return context
