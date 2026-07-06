import json
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class StructuredRecord(BaseModel):
    document_type: str
    source_file: str
    group_name: str
    row_index: int
    columns: List[str]
    values: Dict[str, Any]

class StructuredChunk(BaseModel):
    text: str
    metadata: Dict[str, Any]

from .structured_chunker_helpers import detect_label_column, normalize_numeric

class StructuredChunker:
    """
    Chunks structured records (like spreadsheet rows or JSON array elements)
    using a dual-representation strategy:
    1. Atomic Cell-Statements: High precision for exact point-lookups.
    2. Consolidated Table Chunks: High recall for aggregation and table-scan queries.
    """
    
    @staticmethod
    def chunk(records: List[StructuredRecord], chunk_size: int = 2500, overlap_rows: int = 2) -> List[StructuredChunk]:
        if not records:
            return []
            
        chunks = []
        
        # ---------------------------------------------------------
        # 1. Generate Atomic Cell-Level Chunks
        # ---------------------------------------------------------
        for rec in records:
            label_col = detect_label_column(rec)
            row_label = str(rec.values.get(label_col, "")).strip() or f"Row {rec.row_index}"
            parent_prefix = f"{getattr(rec, 'parent_label', '')} > " if getattr(rec, "parent_label", None) else ""
            table_id = rec.group_name
            
            for col_name, raw_value in rec.values.items():
                if col_name == label_col:
                    continue
                    
                cell_value = str(raw_value).strip()
                if cell_value and cell_value.lower() not in ("none", "null", ""):
                    # The highly explicit, domain-agnostic statement
                    statement = f"- [{table_id}] {parent_prefix}{row_label}, {col_name}: {cell_value}"
                    
                    metadata = {
                        "document_type": rec.document_type,
                        "source_file": rec.source_file,
                        "table_id": table_id,
                        "row_label": row_label,
                        "parent_label": getattr(rec, "parent_label", None),
                        "column_label": col_name,
                        "raw_value": cell_value,
                        "parsed_value": normalize_numeric(cell_value),
                        "chunk_type": "atomic" # Distinguishes from consolidated chunks
                    }
                    
                    chunks.append(StructuredChunk(text=statement, metadata=metadata))

        # ---------------------------------------------------------
        # 2. Generate Consolidated Table Chunks (Batched)
        # ---------------------------------------------------------
        current_chunk_records = []
        sorted_records = sorted(records, key=lambda x: x.row_index)
        
        def format_consolidated_chunk(rec_list: List[StructuredRecord]) -> Optional[StructuredChunk]:
            if not rec_list:
                return None
                
            first_rec = rec_list[0]
            header = f"Source: {first_rec.source_file} -> {first_rec.group_name}\n"
            header += f"Columns: {', '.join(first_rec.columns)}\n\n"
            
            row_texts = []
            for rec in rec_list:
                label_col = detect_label_column(rec)
                row_label = str(rec.values.get(label_col, "")).strip() or f"Row {rec.row_index}"
                parent_prefix = f"{getattr(rec, 'parent_label', '')} > " if getattr(rec, "parent_label", None) else ""
                
                # Use the same semantic statements inside the consolidated chunk
                row_statements = []
                for col_name, raw_value in rec.values.items():
                    if col_name == label_col:
                        continue
                    cell_value = str(raw_value).strip()
                    if cell_value and cell_value.lower() not in ("none", "null", ""):
                        row_statements.append(f"{col_name}: {cell_value}")
                
                if row_statements:
                    row_texts.append(f"- {parent_prefix}{row_label} -> " + ", ".join(row_statements))
                
            text = header + "\n".join(row_texts)
            
            metadata = {
                "document_type": first_rec.document_type,
                "source_file": first_rec.source_file,
                "sheet": first_rec.group_name,
                "start_row": rec_list[0].row_index,
                "end_row": rec_list[-1].row_index,
                "row_count": len(rec_list),
                "columns": first_rec.columns,
                "chunk_type": "consolidated"
            }
            
            return StructuredChunk(text=text, metadata=metadata)
            
        def estimate_len(rec: StructuredRecord) -> int:
            return sum(len(str(v)) + len(str(k)) for k, v in rec.values.items()) + 100
            
        current_len = 0
        header_len = 200
        
        for rec in sorted_records:
            rec_len = estimate_len(rec)
            
            if current_len + rec_len + header_len > chunk_size and current_chunk_records:
                chunk_obj = format_consolidated_chunk(current_chunk_records)
                if chunk_obj:
                    chunks.append(chunk_obj)
                
                overlap_candidates = current_chunk_records[-overlap_rows:] if overlap_rows > 0 else []
                while overlap_candidates and sum(estimate_len(r) for r in overlap_candidates) + rec_len + header_len > chunk_size:
                    overlap_candidates.pop(0)
                    
                current_chunk_records = overlap_candidates + [rec]
                current_len = sum(estimate_len(r) for r in current_chunk_records)
            else:
                current_chunk_records.append(rec)
                current_len += rec_len
                
        if current_chunk_records:
            chunk_obj = format_consolidated_chunk(current_chunk_records)
            if chunk_obj:
                chunks.append(chunk_obj)
                
        logger.info(f"StructuredChunker successfully generated {len(chunks)} dual-representation chunks.")
        return chunks
