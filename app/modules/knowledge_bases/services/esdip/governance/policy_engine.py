from ..domain.pipeline_context import PipelineContext
from ..domain.business_object import ObjectState
from .state_machine import StateMachine

class AcceptancePolicy:
    def evaluate(self, context: PipelineContext):
        pass

class ValidationPolicy:
    def evaluate(self, context: PipelineContext):
        pass

class PersistencePolicy:
    def evaluate(self, context: PipelineContext):
        for obj in context.business_object_store.get_all():
            if obj.state == ObjectState.VALIDATED:
                obj.state = ObjectState.READY

class PolicyEngine:
    """Defines and evaluates business rules for governance."""
    def __init__(self):
        self.acceptance_policies = [AcceptancePolicy()]
        self.validation_policies = [ValidationPolicy()]
        self.persistence_policies = [PersistencePolicy()]
        
    def run(self, context: PipelineContext) -> PipelineContext:
        for p in self.acceptance_policies:
            p.evaluate(context)
            
        for p in self.validation_policies:
            p.evaluate(context)
            
        for p in self.persistence_policies:
            p.evaluate(context)
                
        context.log("Policy Engine completed.")
        return context
