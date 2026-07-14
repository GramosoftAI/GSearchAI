from ..domain.pipeline_context import PipelineContext

class ConfidenceEngine:
    """Calibrates and aggregates confidence scores across all inferences."""
    def run(self, context: PipelineContext) -> PipelineContext:
        # For Release 1, simply logs the distribution of relationship confidences
        high_conf = 0
        low_conf = 0
        
        for obj in context.business_objects:
            for rel in obj.relationships:
                if rel.confidence.score >= 0.8:
                    high_conf += 1
                else:
                    low_conf += 1
                    
        context.log(f"Confidence calibration: {high_conf} high-confidence edges, {low_conf} low-confidence edges.")
        return context
