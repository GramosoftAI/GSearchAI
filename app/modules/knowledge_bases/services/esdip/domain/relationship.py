from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from .confidence import ConfidenceResult

@dataclass
class Evidence:
    """Proof of why a relationship exists."""
    source_column: str
    target_column: str
    match_type: str
    description: str

@dataclass
class Relationship:
    """A directed edge between two Business Objects."""
    source_id: str
    source_type: str
    target_id: str
    target_type: str
    predicate: str
    evidence: List[Evidence] = field(default_factory=list)
    confidence: Optional[ConfidenceResult] = None
