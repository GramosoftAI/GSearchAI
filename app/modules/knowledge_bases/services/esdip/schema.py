import logging
import re
import pandas as pd
from typing import List, Dict, Any
from .discovery import LogicalTable

logger = logging.getLogger(__name__)

class HeaderResolution:
    """
    Stage 4: Header Resolution
    Normalizes headers, handles duplicates and blanks.
    """
    @staticmethod
    def resolve(table: LogicalTable) -> LogicalTable:
        logger.info(f"Stage 4: Header Resolution for table in '{table.sheet_name}'")
        df = table.dataframe
        
        # Assume first row is header
        raw_headers = df.iloc[0].fillna("").astype(str).tolist()
        
        normalized_headers = []
        seen = set()
        
        for i, header in enumerate(raw_headers):
            # Normalize: lowercase, replace spaces with underscores, remove special chars
            clean_h = re.sub(r'[^a-z0-9]+', '_', header.lower()).strip('_')
            
            if not clean_h:
                clean_h = f"unnamed_column_{i}"
                
            if clean_h in seen:
                suffix = 1
                while f"{clean_h}_{suffix}" in seen:
                    suffix += 1
                clean_h = f"{clean_h}_{suffix}"
                
            seen.add(clean_h)
            normalized_headers.append(clean_h)
            
        table.headers = normalized_headers
        
        # Drop the header row and apply columns
        df_body = df.iloc[1:].reset_index(drop=True)
        df_body.columns = normalized_headers
        table.dataframe = df_body
        
        return table


class SchemaDiscovery:
    """
    Stage 5: Schema Discovery
    Analyzes columns to determine datatypes and constraints deterministically.
    """
    @staticmethod
    def discover(table: LogicalTable) -> LogicalTable:
        logger.info(f"Stage 5: Schema Discovery for table in '{table.sheet_name}'")
        df = table.dataframe
        schema: Dict[str, Any] = {}
        
        for col in df.columns:
            col_series = df[col].dropna()
            
            stats = {
                "nullable": len(col_series) < len(df),
                "unique": len(col_series.unique()) == len(col_series) if not col_series.empty else False,
                "type": "string"
            }
            
            if col_series.empty:
                schema[col] = stats
                continue
                
            str_series = col_series.astype(str).str.strip().str.lower()
            
            # Boolean check
            if set(str_series.unique()).issubset({"true", "false", "yes", "no", "1", "0", "t", "f"}):
                stats["type"] = "boolean"
            else:
                # Numeric check
                try:
                    num_series = pd.to_numeric(col_series)
                    if pd.api.types.is_integer_dtype(num_series) or (pd.api.types.is_float_dtype(num_series) and num_series.apply(lambda x: x.is_integer()).all()):
                        stats["type"] = "integer"
                    else:
                        stats["type"] = "float"
                except Exception:
                    # Date check
                    try:
                        if str_series.str.contains(r'[-/:]').all():
                            pd.to_datetime(col_series, format="mixed")
                            stats["type"] = "datetime"
                    except Exception:
                        # Check text length
                        avg_len = str_series.str.len().mean()
                        if avg_len > 100:
                            stats["type"] = "text"
                            
            schema[col] = stats
            
        table.schema = schema
        
        # Identify candidate primary key (first column that is unique and not nullable)
        table.schema["_primary_key_candidate"] = None
        for col, stats in schema.items():
            if stats["unique"] and not stats["nullable"]:
                table.schema["_primary_key_candidate"] = col
                break
                
        # Fallback to first column if no perfect candidate
        if not table.schema["_primary_key_candidate"] and len(df.columns) > 0:
            table.schema["_primary_key_candidate"] = df.columns[0]
            
        return table
