import urllib.parse
from typing import List, Optional, Literal
from dataclasses import dataclass, field
from pydantic import BaseModel, ConfigDict

# ============================================================================
# RDF SEMANTIC ONTOLOGY MAPPER
# ============================================================================
CANONICAL_RELATIONS = {
    "issued": "ISSUED_BY",
    "created_bill": "ISSUED_BY",
    "generated_invoice": "ISSUED_BY",
    "purchased": "PURCHASED",
    "bought": "PURCHASED",
    "ordered": "PURCHASED",
    "supplied_by": "SUPPLIED_BY",
    "provided_by": "SUPPLIED_BY",
    "contains": "CONTAINS_PRODUCT",
    "includes": "CONTAINS_PRODUCT",
    "belongs_to": "BELONGS_TO",
    "located_in": "LOCATED_IN",
    "has_amount": "HAS_AMOUNT",
    "has_date": "HAS_DATE",
    "references": "REFERENCES",
    "derived_from": "DERIVED_FROM"
}

def create_uri(entity_type: str, text: str) -> str:
    """Generate globally unique RDF-compliant URI for an entity."""
    clean_type = urllib.parse.quote(entity_type.lower().strip())
    clean_text = urllib.parse.quote(text.lower().strip().replace(' ', '_'))
    return f"https://grag.ai/kg/{clean_type}/{clean_text}"

# ============================================================================
# DATA MODELS & SHACL-LITE VALIDATION
# ============================================================================

@dataclass
class ExtractedParticipant:
    entity: str
    role: str
    entity_type: str = "CONCEPT"

@dataclass
class ExtractedAttribute:
    attribute: str
    value: str
    entity_type: str = "CONCEPT"

@dataclass
class ExtractedFact:
    """Unified representation of a fact that can be a simple relation or an event hub."""
    name: str  # The event name or the predicate
    subject: Optional[str] = None
    object: Optional[str] = None
    subject_type: str = "CONCEPT"
    object_type: str = "CONCEPT"
    mode_hint: str = "relationship" # 'relationship' or 'event'
    event_type: str = "EVENT"
    participants: List[ExtractedParticipant] = field(default_factory=list)
    attributes: List[ExtractedAttribute] = field(default_factory=list)
    confidence: float = 1.0
    evidence: str = None
    
    @property
    def text(self) -> str:
        if self.mode_hint == "relationship" and self.subject and self.object:
            return f"{self.subject}  {self.name}  {self.object}"
        return f"{self.name} (Event)"

    def normalize(self) -> "ExtractedFact":
        """Normalize fields for consistency."""
        raw_name = self.name.strip().lower().replace(" ", "_")
        canonical_name = CANONICAL_RELATIONS.get(raw_name, raw_name.upper())
        self.name = canonical_name
        
        if self.subject:
            self.subject = self.subject.strip().lower()
            self.subject_type = self.subject_type.upper().strip()
        if self.object:
            self.object = self.object.strip().lower()
            self.object_type = self.object_type.upper().strip()
            
        return self


class TripletExtractionResult:
    """Result of triplet extraction for a single chunk."""
    def __init__(
        self,
        chunk_id: str,
        facts: List[ExtractedFact] = None,
        triplets: List[ExtractedFact] = None,
        events: List[ExtractedFact] = None,
        error: Optional[str] = None
    ):
        self.chunk_id = chunk_id
        self.error = error
        
        if facts is not None:
            self.facts = facts
        else:
            self.facts = []
            
        if triplets is not None:
            for t in triplets:
                t.mode_hint = "relationship"
                self.facts.append(t)
                
        if events is not None:
            for ev in events:
                ev.mode_hint = "event"
                self.facts.append(ev)

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def triplets(self) -> List["ExtractedTriplet"]:
        return [
            ExtractedTriplet(
                subject=f.subject,
                predicate=f.name,
                object=f.object,
                subject_type=f.subject_type,
                object_type=f.object_type,
                confidence=f.confidence,
                evidence=f.evidence
            )
            for f in self.facts if f.mode_hint == "relationship"
        ]

    @property
    def events(self) -> List["ExtractedEvent"]:
        return [
            ExtractedEvent(
                name=f.name,
                event_type=f.event_type,
                participants=f.participants,
                attributes=f.attributes
            )
            for f in self.facts if f.mode_hint == "event"
        ]


class ExtractedTriplet(ExtractedFact):
    def __init__(
        self,
        subject: str,
        predicate: str,
        object: str,
        subject_type: str = "CONCEPT",
        object_type: str = "CONCEPT",
        confidence: float = 1.0,
        evidence: str = None
    ):
        self.subject = subject
        self.name = predicate
        self.object = object
        self.subject_type = subject_type
        self.object_type = object_type
        self.mode_hint = "relationship"
        self.confidence = confidence
        self.evidence = evidence
        self.participants = []
        self.attributes = []

    @property
    def predicate(self) -> str:
        return self.name

    @predicate.setter
    def predicate(self, value: str):
        self.name = value


class ExtractedEvent(ExtractedFact):
    def __init__(
        self,
        name: str,
        event_type: str = "EVENT",
        participants: List[ExtractedParticipant] = None,
        attributes: List[ExtractedAttribute] = None
    ):
        self.name = name
        self.event_type = event_type
        self.participants = participants or []
        self.attributes = attributes or []
        self.mode_hint = "event"
        self.subject = None
        self.object = None
        self.subject_type = "CONCEPT"
        self.object_type = "CONCEPT"

# --- SHACL-LITE PYDANTIC SHAPES ---
class ExtractedParticipantShape(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    entity: str
    role: str
    entity_type: str

class ExtractedAttributeShape(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    attribute: str
    value: str
    entity_type: str

class ExtractedFactShape(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    mode_hint: Literal["relationship", "event"]
    subject: Optional[str] = None
    object: Optional[str] = None
    participants: List[ExtractedParticipantShape] = []
    attributes: List[ExtractedAttributeShape] = []

