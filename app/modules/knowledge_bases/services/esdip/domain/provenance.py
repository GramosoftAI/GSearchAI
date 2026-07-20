from dataclasses import dataclass, field
from typing import Dict, Any, Optional

@dataclass
class Provenance:
    """Reusable entity tracking origin and lineage of facts."""
    source_file: str
    sheet_name: Optional[str] = None
    table_id: Optional[str] = None
    row_index: Optional[int] = None
    col_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
