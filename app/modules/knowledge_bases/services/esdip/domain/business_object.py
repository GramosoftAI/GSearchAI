from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from .relationship import Relationship
from .provenance import Provenance
from .business_object_version import BusinessObjectVersion

class ObjectState(Enum):
    DISCOVERED = "DISCOVERED"
    NORMALIZED = "NORMALIZED"
    VALIDATED = "VALIDATED"
    RELATED = "RELATED"
    READY = "READY"
    PERSISTED = "PERSISTED"
    INDEXED = "INDEXED"
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"

@dataclass
class BusinessObject:
    """The central domain entity representing a unified business concept."""
    id: str
    entity_type: str
    attributes: Dict[str, Any]
    provenance: Provenance
    relationships: List[Relationship] = field(default_factory=list)
    versions: List[BusinessObjectVersion] = field(default_factory=list)
    state: ObjectState = ObjectState.DISCOVERED
    quarantine_reason: Optional[str] = None
