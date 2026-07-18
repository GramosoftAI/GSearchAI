from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class BusinessObjectVersion:
    """Tracks changes to a Business Object over time. Stored in its own package for future evolution."""
    version_id: str
    timestamp: str
    changes: Dict[str, Any]
