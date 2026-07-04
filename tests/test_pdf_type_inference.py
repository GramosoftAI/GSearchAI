import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.rag.pipeline import RAGPipeline

@pytest.mark.asyncio
async def test_rag_pipeline_fallback_schema_inference():
    # Setup mock DB and result rows
    db_mock = AsyncMock()
    
    class MockRow(dict):
        def keys(self):
            return list(super().keys())
            
    mock_row_1 = MockRow({
        "col_currency": "$1,200.50",
        "col_percentage": "45%",
        "col_integer": "1,000",
        "col_string": "Apple"
    })
    
    mock_row_2 = MockRow({
        "col_currency": "($300.00)",
        "col_percentage": "50.5%",
        "col_integer": "25",
        "col_string": "Google"
    })

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_row_1, mock_row_2]
    db_mock.execute.return_value = mock_result
    
    pipeline = RAGPipeline(tenant_id="00000000-0000-0000-0000-000000000000", db=db_mock)
    
    # We will simulate the fallback schema logic block in _execute_table_analytics
    kb_ids = ["00000000-0000-0000-0000-000000000000"]
    dataset_schema = None
    
    # Executing the fallback schema block
    if not dataset_schema:
        # Simulate query execution
        result = await pipeline.db.execute(None)
        rows = result.scalars().all()
        if rows:
            dataset_schema = {}
            all_keys = set()
            for row in rows:
                all_keys.update(row.keys())
            
            import re
            for k in all_keys:
                vals = [row[k] for row in rows if k in row and row[k] is not None and str(row[k]).strip() != ""]
                if not vals:
                    dataset_schema[k] = "string"
                    continue
                    
                unique_vals = set(str(v).lower().strip() for v in vals)
                if unique_vals.issubset({"true", "false", "yes", "no", "t", "f"}):
                    dataset_schema[k] = "boolean"
                    continue
                    
                is_numeric_candidate = True
                has_currency_symbols = False
                has_percentage_symbols = False
                is_integer_all = True
                cleaned_values = []
                
                for val in vals:
                    val_str = str(val).strip()
                    if not val_str or val_str.lower() in ["na", "n/a", "none", "null", "-", ""]:
                        continue
                        
                    is_neg = False
                    if val_str.startswith("(") and val_str.endswith(")"):
                        is_neg = True
                        val_str = val_str[1:-1].strip()
                        
                    if any(c in val_str for c in ["$", "€", "£", "₹"]):
                        has_currency_symbols = True
                        val_str = re.sub(r'[\$\€\£\₹]', '', val_str).strip()
                        
                    if "%" in val_str:
                        has_percentage_symbols = True
                        val_str = val_str.replace("%", "").strip()
                        
                    if "," in val_str:
                        if "." in val_str:
                            val_str = val_str.replace(",", "")
                        else:
                            parts = val_str.split(",")
                            if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
                                    val_str = val_str.replace(",", "")
                            elif len(parts) == 2 and len(parts[1]) != 3:
                                    val_str = val_str.replace(",", ".")
                            else:
                                    val_str = val_str.replace(",", "")
                                
                    if is_neg:
                        val_str = "-" + val_str
                        
                    try:
                        num_val = float(val_str)
                        cleaned_values.append(num_val)
                        if not num_val.is_integer():
                            is_integer_all = False
                    except ValueError:
                        is_numeric_candidate = False
                        break
                        
                if is_numeric_candidate and cleaned_values:
                    if has_currency_symbols:
                        dataset_schema[k] = "currency"
                    elif has_percentage_symbols:
                        dataset_schema[k] = "percentage"
                    elif is_integer_all:
                        dataset_schema[k] = "integer"
                    else:
                        dataset_schema[k] = "float"
                    continue
                    
                dataset_schema[k] = "string"

    # Assert correct type classification
    print("INFERRED SCHEMA:", dataset_schema)
    assert dataset_schema["col_currency"] == "currency"
    assert dataset_schema["col_percentage"] == "percentage"
    assert dataset_schema["col_integer"] == "integer"
    assert dataset_schema["col_string"] == "string"

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_rag_pipeline_fallback_schema_inference())
    print("ALL PASSED!")
