import logging
import io
import asyncio
import hashlib
import re
import csv
import json
from typing import Optional, List, Dict
import pandas as pd

from app.core.pdf_extractor import ExtractedText

logger = logging.getLogger(__name__)

class ExcelExtractor:
    """
    Enterprise Spreadsheet Parser (Phase B).
    Extracts tabular data from Excel/CSV files and converts it into a row-aware
    natural language markdown string with foundational intelligence.
    """

    @staticmethod
    async def extract(
        file_bytes: bytes,
        filename: str = "document.xlsx",
        tenant_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> tuple:
        logger.info(f" Excel Extraction starting: {filename} ({len(file_bytes)} bytes)")
        
        loop = asyncio.get_event_loop()
        extracted_markdown, table_rows, dataset_schema = await loop.run_in_executor(
            None, ExcelExtractor._sync_extract, file_bytes, filename
        )
        
        if not extracted_markdown.strip():
            logger.warning(f" ExcelExtractor returned empty result for {filename}.")
            
        logger.info(f" Excel Extraction success: {filename} ({len(extracted_markdown)} chars)")
        return ExtractedText(extracted_markdown, extracted_markdown, is_html=False), table_rows, dataset_schema

    @staticmethod
    def _normalize_header(header: str) -> str:
        """Normalize header"""
        if not header or pd.isna(header) or str(header).strip() == "":
            return ""
        header = str(header).strip().lower()
        header = re.sub(r'[^a-z0-9]+', '_', header)
        return header.strip('_')

    @staticmethod
    def _detect_header_row(df: pd.DataFrame, max_rows: int = 30) -> int:
        """Intelligent Header Detection with Look-Ahead Validation"""
        best_score = -1
        best_idx = 0
        
        for idx in range(min(max_rows, len(df))):
            row = df.iloc[idx]
            valid_cells = [str(x).strip() for x in row if pd.notna(x) and str(x).strip() != ""]
            
            # Feature: Mostly text
            text_cells = [x for x in valid_cells if not x.replace('.', '', 1).isdigit()]
            unique_text_cells = len(set(text_cells))
            
            score = unique_text_cells
            if len(valid_cells) > 0 and len(valid_cells) == len(row):
                score += 2  # Feature: Fully populated
                
            # Penalize single-cell rows from being headers
            if len(valid_cells) <= 1:
                score -= 10
                
            # Look-ahead validation (next 3 rows)
            lookahead_valid = 0
            if len(valid_cells) > 1:
                for look_idx in range(idx + 1, min(idx + 4, len(df))):
                    look_row = df.iloc[look_idx]
                    look_valid = [str(x).strip() for x in look_row if pd.notna(x) and str(x).strip() != ""]
                    # Feature: Next rows resemble tabular data (>1 column, similar count)
                    if len(look_valid) > 1 and abs(len(look_valid) - len(valid_cells)) <= 1:
                        lookahead_valid += 1
                        
            # Heavily weight look-ahead validation to prevent false positives on standalone text
            if lookahead_valid > 0:
                score += (lookahead_valid * 5)
                
            if score > best_score:
                best_score = score
                best_idx = idx
                
        return best_idx

    @staticmethod
    def _detect_boundaries(df: pd.DataFrame, offset_idx: int) -> List[Dict]:
        """Lightweight Table Boundary Detection (Phase B3)"""
        boundaries = []
        current_table_start = 0
        prev_cols = len([x for x in df.iloc[0] if pd.notna(x) and str(x).strip() != ""]) if len(df) > 0 else 0
        
        for idx in range(1, len(df)):
            row = df.iloc[idx]
            valid_cells = [str(x).strip() for x in row if pd.notna(x) and str(x).strip() != ""]
            current_cols = len(valid_cells)
            
            score = 0
            if current_cols == 0:
                score += 20 # Signal: Blank Row
            elif prev_cols > 0 and current_cols != prev_cols:
                score += 15 # Signal: Column count shift
                
            if score >= 20:
                if idx - current_table_start > 1:
                    boundaries.append({
                        "start_row": offset_idx + current_table_start,
                        "end_row": offset_idx + idx - 1,
                        "confidence": min(100, score * 3)
                    })
                current_table_start = idx + 1
                
            if current_cols > 0:
                prev_cols = current_cols
                
        if current_table_start < len(df) and (len(df) - current_table_start) > 0:
            boundaries.append({
                "start_row": offset_idx + current_table_start,
                "end_row": offset_idx + len(df) - 1,
                "confidence": 99
            })
            
        return boundaries

    @staticmethod
    def _sync_extract(file_bytes: bytes, filename: str) -> tuple:
        fname_lower = filename.lower()
        extracted_text_blocks = []
        table_rows_extracted = []
        dataset_schema = {}
        
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        file_size = len(file_bytes)
        extension = fname_lower.split('.')[-1] if '.' in fname_lower else 'unknown'
        
        try:
            if fname_lower.endswith('.csv'):
                content_str = file_bytes.decode('utf-8', errors='replace')
                reader = csv.reader(io.StringIO(content_str))
                data = list(reader)
                df_dict = {"Sheet1": pd.DataFrame(data).astype(str).replace('None', '')}
            elif fname_lower.endswith(('.xls', '.xlsx')):
                df_dict = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None, dtype=str, keep_default_na=False)
            else:
                raise ValueError(f"Unsupported file format for ExcelExtractor: {filename}")
                
            for sheet_name, df in df_dict.items():
                if df.empty:
                    continue
                    
                df_clean = df.replace('', pd.NA).dropna(how='all', axis=1).fillna("")
                if df_clean.empty:
                    continue
                
                df_clean = df_clean.reset_index(drop=True)
                header_idx = ExcelExtractor._detect_header_row(df_clean)
                
                raw_headers = df_clean.iloc[header_idx].tolist()
                body_df = df_clean.iloc[header_idx + 1:].reset_index(drop=True)
                
                normalized_headers = []
                seen_headers = set()
                dropped_columns = 0
                duplicate_resolutions = 0
                
                for idx, h in enumerate(raw_headers):
                    norm_h = ExcelExtractor._normalize_header(h)
                    if not norm_h:
                        norm_h = f"unnamed_col_{idx}"
                        dropped_columns += 1
                        
                    if norm_h in seen_headers:
                        duplicate_resolutions += 1
                        suffix = 1
                        while f"{norm_h}_{suffix}" in seen_headers:
                            suffix += 1
                        norm_h = f"{norm_h}_{suffix}"
                        
                    seen_headers.add(norm_h)
                    normalized_headers.append(norm_h)
                    
                body_df.columns = normalized_headers
                body_df = body_df.replace('', pd.NA).dropna(how='all', axis=1)
                valid_columns = list(body_df.columns)
                
                import re
                # Infer schema before converting to strings
                for col in valid_columns:
                    col_series = body_df[col].dropna()
                    if col_series.empty:
                        dataset_schema[col] = "string"
                        continue
                        
                    # 1. Check boolean
                    unique_vals = set(col_series.astype(str).str.lower().unique())
                    if unique_vals.issubset({"true", "false", "yes", "no", "t", "f"}):
                        dataset_schema[col] = "boolean"
                        continue
                        
                    # 2. Check numeric
                    try:
                        num_series = pd.to_numeric(col_series)
                        if pd.api.types.is_integer_dtype(num_series) or (pd.api.types.is_float_dtype(num_series) and num_series.apply(lambda x: x.is_integer()).all()):
                            dataset_schema[col] = "integer"
                        else:
                            dataset_schema[col] = "float"
                        continue
                    except Exception:
                        pass
                        
                    # 3. Check datetime
                    try:
                        # Only try datetime if string contains delimiters commonly used in dates
                        if col_series.astype(str).str.contains(r'[-/:]').all():
                            pd.to_datetime(col_series, format="mixed")
                            dataset_schema[col] = "datetime"
                            continue
                    except Exception:
                        pass
                        
                    # 4. Currency and Percentage
                    sample_str = col_series.astype(str).str.strip().iloc[0]
                    if re.match(r'^[\$\€\£\₹]\s*\d+([,\.]\d+)?$', sample_str):
                        dataset_schema[col] = "currency"
                        continue
                    if re.match(r'^\d+([,\.]\d+)?\s*%$', sample_str):
                        dataset_schema[col] = "percentage"
                        continue

                    # Fallback
                    str_series = col_series.astype(str).str.strip()
                    non_empty_series = str_series[str_series != ""]
                    if not non_empty_series.empty:
                        avg_len = non_empty_series.str.len().mean()
                        has_sentences = non_empty_series.apply(lambda x: len(str(x).split()) > 8).mean() > 0.2
                        if avg_len > 80 or has_sentences:
                            dataset_schema[col] = "unstructured_text"
                        else:
                            dataset_schema[col] = "string"
                    else:
                        dataset_schema[col] = "string"

                body_df = body_df.fillna("")
                
                # Boundary Detection (Observability)
                boundaries = ExcelExtractor._detect_boundaries(body_df, offset_idx=header_idx + 1)
                
                # Observability Logging (Decoupled from LLM Prompt)
                logger.info(f"[{filename} - {sheet_name}] Data Quality Validation: {dropped_columns} unnamed columns dropped. {duplicate_resolutions} duplicate headers resolved.")
                if len(boundaries) > 1:
                    logger.info(f"[{filename} - {sheet_name}] Possible Multi-Table Boundaries Detected: {json.dumps(boundaries)}")
                
                # Output Generation
                sheet_text = f"## Spreadsheet Metadata (Phase B)\n"
                sheet_text += f"- Filename: {filename}\n"
                sheet_text += f"- Extension: {extension}\n"
                sheet_text += f"- File Size: {file_size} bytes\n"
                sheet_text += f"- SHA-256 Hash: {file_hash}\n"
                sheet_text += f"- Sheet Name: {sheet_name}\n"
                sheet_text += f"- Valid Rows Extracted: {len(body_df)}\n\n"
                
                for index, row in body_df.iterrows():
                    row_details = []
                    row_data_dict = {}
                    for col in valid_columns:
                        val = str(row[col]).strip()
                        if val:
                            row_details.append(f"[{col}]: {val}")
                            row_data_dict[col] = val
                            
                    if row_data_dict:
                        table_rows_extracted.append({
                            "page_number": 1,
                            "table_index": 0,
                            "row_index": index + header_idx + 2,
                            "row_data": row_data_dict
                        })
                    
                    if row_details:
                        row_str = f"- Row {index + header_idx + 2}: " + ", ".join(row_details)
                        sheet_text += row_str + "\n\n"
                        
                extracted_text_blocks.append(sheet_text)
                
            return "\n\n".join(extracted_text_blocks), table_rows_extracted, dataset_schema
            
        except Exception as e:
            logger.error(f"Excel extraction failed for {filename}: {e}")
            raise ValueError(f"Failed to process tabular data: {str(e)}")

    @staticmethod
    async def extract_tables_to_json(pdf_bytes: bytes) -> list:
        return []
