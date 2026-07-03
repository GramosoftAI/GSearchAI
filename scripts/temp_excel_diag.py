import pandas as pd
import sys

try:
    file_path = r'v:\graphmind\sample_enterprise_ontology.xlsx'
    print(f"Reading {file_path}...")
    
    # Read all sheets
    xls = pd.ExcelFile(file_path)
    found = False
    
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet_name)
        
        # Convert all columns to string and search
        for col in df.columns:
            matches = df[df[col].astype(str).str.contains('Rajat|Mithunn|Gramosoft', case=False, na=False)]
            if not matches.empty:
                print(f"\nFound match in sheet: {sheet_name}, column: {col}")
                print(matches[col].values)
                found = True
                
    if not found:
        print("No matches found in the Excel file.")
except Exception as e:
    print(f"Error: {e}")
