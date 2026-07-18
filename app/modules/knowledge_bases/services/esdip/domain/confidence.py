from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class ConfidenceResult:
    """Represents the confidence of a specific inference or detection."""
    score: float  # 0.0 to 1.0
    reason: str
    evidence_metadata: Dict[str, Any] = field(default_factory=dict)
    
@dataclass
class Confidence:
    """Aggregated confidence for a complex object."""
    overall_score: float
    results: List[ConfidenceResult] = field(default_factory=list)
