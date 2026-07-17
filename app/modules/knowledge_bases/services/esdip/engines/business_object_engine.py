from ..domain.pipeline_context import PipelineContext
from ..domain.business_object import BusinessObject
from ..domain.provenance import Provenance

class BusinessObjectEngine:
    """Translates LogicalTables into autonomous BusinessObjects."""
    def run(self, context: PipelineContext) -> PipelineContext:
        if not context.workbook:
            return context
            
        for sheet in context.workbook.sheets:
            entity_type = "".join([c for c in sheet.name if c.isalnum()]).upper() or "RECORD"
            
            for table in sheet.tables:
                pk_col = next((c.name for c in table.columns if c.is_primary_key_candidate), None)
                
                for idx, row in enumerate(table.raw_data):
                    pk_val = str(row.get(pk_col)) if pk_col and row.get(pk_col) else f"row_{idx}"
                    obj_id = f"{entity_type}_{pk_val}"
                    
                    prov = Provenance(
                        source_file=context.filename,
                        sheet_name=sheet.name,
                        table_id=table.table_id,
                        row_index=idx + table.start_row
                    )
                    
                    obj = BusinessObject(
                        id=obj_id,
                        entity_type=entity_type,
                        attributes=row,
                        provenance=prov
                    )
                    context.business_object_store.add(obj)
                    
        from ..governance.state_machine import StateMachine
        from ..domain.business_object import ObjectState
        StateMachine.transition(context, ObjectState.DISCOVERED, ObjectState.NORMALIZED)
                    
        return context
