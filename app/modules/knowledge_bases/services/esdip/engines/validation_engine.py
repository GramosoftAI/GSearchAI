from ..domain.pipeline_context import PipelineContext

class ValidationEngine:
    """Validates Data Quality, quarantines bad records."""
    def run(self, context: PipelineContext) -> PipelineContext:
        for obj in context.business_objects:
            # Example: Missing critical properties or corrupted state
            if not obj.attributes:
                obj.is_quarantined = True
                obj.quarantine_reason = "Empty attributes"
                context.add_warning(f"Quarantined {obj.id}: Empty attributes")
                
        # Filter out quarantined objects from main flow if desired,
        # or leave them marked for the persistence layer to handle.
        return context
