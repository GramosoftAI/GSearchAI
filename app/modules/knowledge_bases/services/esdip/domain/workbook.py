from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class Column:
    """Represents a column's inferred metadata and constraints."""
    name: str
    inferred_type: str = "string"
    is_nullable: bool = True
    is_unique: bool = False
    is_primary_key_candidate: bool = False

@dataclass
class LogicalTable:
    """A bounded tabular region within a sheet."""
    table_id: str
    start_row: int
    end_row: int
    columns: List[Column] = field(default_factory=list)
    raw_data: List[Dict[str, Any]] = field(default_factory=list)
    
@dataclass
class Sheet:
    """A worksheet within a workbook."""
    name: str
    classification: str = "Unknown"  # e.g., 'Raw Data', 'Dashboard'
    tables: List[LogicalTable] = field(default_factory=list)

@dataclass
class Workbook:
    """The root domain object representing the entire uploaded file."""
    filename: str
    file_size_bytes: int
    sheets: List[Sheet] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
