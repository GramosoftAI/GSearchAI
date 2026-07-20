from ..domain.pipeline_context import PipelineContext
from ..domain.business_object import ObjectState

class ConfidenceEvaluator:
    """Evaluates confidence for inferred structures and relationships using deterministic heuristics."""
    def run(self, context: PipelineContext) -> PipelineContext:
        high_conf = 0
        low_conf = 0
        
        for obj in context.business_object_store.get_all():
            if obj.state == ObjectState.QUARANTINED:
                continue
                
            for rel in obj.relationships:
                if rel.confidence.score >= 0.8:
                    high_conf += 1
                else:
                    low_conf += 1
                    
        context.log(f"Confidence Evaluator: {high_conf} high-confidence, {low_conf} low-confidence relationships.")
        return context
