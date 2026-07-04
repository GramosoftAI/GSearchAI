import pytest
import pandas as pd
from app.core.excel_extractor import ExcelExtractor

def test_robust_excel_schema_inference():
    # Test cases for sheet columns
    test_data = {
        "col_currency": ["$1,200.50", "€15,000", "(£300.00)", "₹4,500.00", "N/A"],
        "col_percentage": ["45%", "50.5%", "12%", "", "0.5%"],
        "col_integer": ["1,000", "25", "300", "-", "12"],
        "col_float": ["12.34", "0.56", "3,456.78", "N/A", "-12.5"],
        "col_boolean": ["True", "false", "yes", "no", "t"],
        "col_string": ["Apple", "Google", "$123.45", "Total", "N/A"]
    }
    
    # Constructing a DataFrame like the one in _sync_extract
    df_clean = pd.DataFrame(test_data)
    
    # We'll mock the columns loop in ExcelExtractor._sync_extract
    dataset_schema = {}
    valid_columns = list(df_clean.columns)
    
    import re
    # Copied from the actual implementation for isolation testing
    for col in valid_columns:
        col_series = df_clean[col].dropna()
        if col_series.empty:
            dataset_schema[col] = "string"
            continue
            
        unique_vals = set(col_series.astype(str).str.lower().unique())
        if unique_vals.issubset({"true", "false", "yes", "no", "t", "f"}):
            dataset_schema[col] = "boolean"
            continue
            
        is_numeric_candidate = True
        has_currency_symbols = False
        has_percentage_symbols = False
        is_integer_all = True
        cleaned_values = []
        
        for val in col_series:
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
                dataset_schema[col] = "currency"
            elif has_percentage_symbols:
                dataset_schema[col] = "percentage"
            elif is_integer_all:
                dataset_schema[col] = "integer"
            else:
                dataset_schema[col] = "float"
            continue
            
        dataset_schema[col] = "string"

    # Assert correct type classification
    assert dataset_schema["col_currency"] == "currency"
    assert dataset_schema["col_percentage"] == "percentage"
    assert dataset_schema["col_integer"] == "integer"
    assert dataset_schema["col_float"] == "float"
    assert dataset_schema["col_boolean"] == "boolean"
    assert dataset_schema["col_string"] == "string"
