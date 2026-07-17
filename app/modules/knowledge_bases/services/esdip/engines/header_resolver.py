from ..domain.pipeline_context import PipelineContext

class HeaderResolver:
    """Normalizes column names."""
    def run(self, context: PipelineContext) -> PipelineContext:
        if not context.workbook:
            return context
            
        for sheet in context.workbook.sheets:
            for table in sheet.tables:
                for col in table.columns:
                    col.name = str(col.name).lower().strip().replace(" ", "_")
                    
        context.log("Header Resolver completed.")
        return context
