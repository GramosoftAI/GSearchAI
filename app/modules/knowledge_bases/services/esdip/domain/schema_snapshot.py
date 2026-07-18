from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class SchemaSnapshot:
    """Tracks schema evolution over time."""
    version: str
    timestamp: str
    hash: str
    schema_definition: Dict[str, Any]
