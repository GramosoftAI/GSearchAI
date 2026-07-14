from ..domain.pipeline_context import PipelineContext

class SheetClassifier:
    """Classifies raw data vs. dashboards."""
    def run(self, context: PipelineContext) -> PipelineContext:
        if not context.workbook:
            return context
            
        for sheet in context.workbook.sheets:
            # Release 1 Heuristic
            sheet.classification = "Raw Data"
            
        context.log("Sheet Classifier completed.")
        return context
