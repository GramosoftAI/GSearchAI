from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime

@dataclass
class IngestionRun:
    """Core domain object tracking the full lifecycle of an ingestion event."""
    run_id: str
    workbook_id: str
    version: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "STARTED"
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    schema_version: Optional[str] = None
    pipeline_version: str = "1.0"
