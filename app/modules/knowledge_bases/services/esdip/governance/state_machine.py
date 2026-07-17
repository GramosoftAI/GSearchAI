from ..domain.pipeline_context import PipelineContext
from ..domain.business_object import ObjectState

class StateMachine:
    """Enforces BusinessObject lifecycle transitions."""
    @staticmethod
    def transition(context: PipelineContext, from_state: ObjectState, to_state: ObjectState):
        """Transitions all objects currently in `from_state` to `to_state`."""
        for obj in context.business_object_store.get_all():
            if obj.state == from_state:
                obj.state = to_state
                context.log(f"Transitioned {obj.id} from {from_state.value} to {to_state.value}")
