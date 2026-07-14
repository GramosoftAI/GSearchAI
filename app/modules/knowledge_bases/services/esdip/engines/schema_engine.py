from ..domain.pipeline_context import PipelineContext
from ..domain.workbook import Column

class SchemaEngine:
    """Infers datatypes and primary keys from raw table data."""
    def run(self, context: PipelineContext) -> PipelineContext:
        if not context.workbook:
            return context
            
        for sheet in context.workbook.sheets:
            for table in sheet.tables:
                if not table.raw_data:
                    continue
                    
                # Collect keys from first row
                keys = table.raw_data[0].keys()
                
                for key in keys:
                    # Simple heuristic for Release 1
                    col = Column(name=key, inferred_type="string", is_nullable=True)
                    if key.lower().endswith("id") or key.lower() == "uuid":
                        col.is_primary_key_candidate = True
                        col.is_unique = True
                        col.is_nullable = False
                    table.columns.append(col)
                    
        return context
