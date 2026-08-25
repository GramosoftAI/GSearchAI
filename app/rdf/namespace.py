"""
Layer 1 — RDF: Namespace Management & Triple Model

This is the foundation of the RDF stack. It defines:
  1. RDFTriple — The canonical data structure that flows through all layers.
  2. Namespace — Tenant-aware URI generation using RFC 3986 compliant IRIs.
  3. RDFLayer — Converts raw LLM ExtractedFact objects into RDFTriple instances.

Design rationale:
  - URIs become the PRIMARY KEY for entity deduplication in Neo4j (replacing text+type).
  - Every entity, predicate, and event gets a globally unique, deterministic URI.
  - The Namespace class is tenant-scoped so different tenants can have isolated URI spaces.
"""

import urllib.parse
import logging
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS — The canonical triple representation
# ============================================================================

class ParticipantNode(BaseModel):
    """A participant in an event-hub triple."""
    entity: str
    role: str
    entity_type: str = "CONCEPT"
    uri: str = ""


class AttributeNode(BaseModel):
    """An attribute attached to an event-hub triple."""
    attribute: str
    value: str
    entity_type: str = "CONCEPT"
    uri: str = ""


class RDFTriple(BaseModel):
    """
    The single canonical data structure that flows through all RDF stack layers.

    Every fact extracted by the LLM is converted to this model before any
    normalization, validation, or persistence occurs.
    """
    # Subject
    subject_uri: str = ""
    subject_text: str = ""
    subject_type: str = "CONCEPT"

    # Predicate
    predicate: str = ""

    # Object
    object_uri: str = ""
    object_text: str = ""
    object_type: str = "CONCEPT"

    # Provenance
    chunk_id: str = ""
    tenant_id: str = ""
    confidence: float = 1.0

    # Routing mode — set by LLM hint, verified by OWL layer
    mode: Literal["relationship", "event"] = "relationship"
    event_type: str = "EVENT"

    # Event-hub fields (populated only when mode == "event")
    event_name: str = ""
    participants: List[ParticipantNode] = Field(default_factory=list)
    attributes: List[AttributeNode] = Field(default_factory=list)

    # Evidence / source text span
    evidence: Optional[str] = None


# ============================================================================
# NAMESPACE — Tenant-aware URI generation
# ============================================================================

class Namespace:
    """
    Generates globally unique, deterministic RDF-compliant URIs.

    URI format:
        {base}/{entity_type}/{normalized_text}

    Examples:
        https://grag.ai/kg/person/albert_einstein
        https://grag.ai/kg/organization/google
        https://grag.ai/kg/predicate/works_for
    """

    DEFAULT_BASE = "https://grag.ai/kg"

    def __init__(self, tenant_id: str, base_uri: Optional[str] = None):
        self.tenant_id = tenant_id
        self.base_uri = (base_uri or self.DEFAULT_BASE).rstrip("/")

    def entity_uri(self, entity_type: str, text: str) -> str:
        """Generate a URI for an entity node."""
        clean_type = urllib.parse.quote(entity_type.lower().strip(), safe="")
        clean_text = urllib.parse.quote(
            text.lower().strip().replace(" ", "_"), safe=""
        )
        return f"{self.base_uri}/{clean_type}/{clean_text}"

    def predicate_uri(self, predicate: str) -> str:
        """Generate a URI for a predicate/relation."""
        clean_pred = urllib.parse.quote(
            predicate.lower().strip().replace(" ", "_"), safe=""
        )
        return f"{self.base_uri}/predicate/{clean_pred}"

    def event_uri(self, event_name: str) -> str:
        """Generate a URI for an event hub node."""
        clean_name = urllib.parse.quote(
            event_name.lower().strip().replace(" ", "_"), safe=""
        )
        return f"{self.base_uri}/event/{clean_name}"


# ============================================================================
# RDF LAYER — Converts ExtractedFact → RDFTriple
# ============================================================================

class RDFLayer:
    """
    Layer 1 processor: converts raw LLM-extracted facts into RDFTriple
    instances with proper URIs assigned.
    """

    def __init__(self, tenant_id: str, base_uri: Optional[str] = None):
        self.tenant_id = tenant_id
        self.ns = Namespace(tenant_id, base_uri)

    def to_triples(self, facts, chunk_id: str) -> List[RDFTriple]:
        """
        Convert a list of ExtractedFact dataclass objects into RDFTriple models.

        Args:
            facts: List of ExtractedFact (from app.modules.tripets.models)
            chunk_id: Source chunk UUID

        Returns:
            List of RDFTriple with URIs populated
        """
        triples = []
        for fact in facts:
            try:
                triple = self._convert_fact(fact, chunk_id)
                if triple:
                    triples.append(triple)
            except Exception as e:
                logger.warning(
                    f"RDF Layer: failed to convert fact '{getattr(fact, 'name', '?')}': {e}"
                )
        return triples

    def _convert_fact(self, fact, chunk_id: str) -> Optional[RDFTriple]:
        """Convert a single ExtractedFact to an RDFTriple."""
        name = getattr(fact, "name", "") or ""
        if not name.strip():
            return None

        mode = getattr(fact, "mode_hint", "relationship") or "relationship"

        # Build participants with URIs
        participants = []
        for p in getattr(fact, "participants", []) or []:
            entity = getattr(p, "entity", "") or ""
            etype = getattr(p, "entity_type", "CONCEPT") or "CONCEPT"
            participants.append(
                ParticipantNode(
                    entity=entity,
                    role=getattr(p, "role", "participant") or "participant",
                    entity_type=etype,
                    uri=self.ns.entity_uri(etype, entity) if entity else "",
                )
            )

        # Build attributes with URIs
        attributes = []
        for a in getattr(fact, "attributes", []) or []:
            value = getattr(a, "value", "") or ""
            etype = getattr(a, "entity_type", "CONCEPT") or "CONCEPT"
            attributes.append(
                AttributeNode(
                    attribute=getattr(a, "attribute", "has_attribute") or "has_attribute",
                    value=value,
                    entity_type=etype,
                    uri=self.ns.entity_uri(etype, value) if value else "",
                )
            )

        # Subject / Object URIs
        subject_text = getattr(fact, "subject", "") or ""
        subject_type = getattr(fact, "subject_type", "CONCEPT") or "CONCEPT"
        object_text = getattr(fact, "object", "") or ""
        object_type = getattr(fact, "object_type", "CONCEPT") or "CONCEPT"

        return RDFTriple(
            subject_uri=self.ns.entity_uri(subject_type, subject_text) if subject_text else "",
            subject_text=subject_text,
            subject_type=subject_type,
            predicate=name,
            object_uri=self.ns.entity_uri(object_type, object_text) if object_text else "",
            object_text=object_text,
            object_type=object_type,
            chunk_id=chunk_id,
            tenant_id=self.tenant_id,
            confidence=getattr(fact, "confidence", 1.0) or 1.0,
            mode=mode,
            event_type=getattr(fact, "event_type", "EVENT") or "EVENT",
            event_name=name if mode == "event" else "",
            participants=participants,
            attributes=attributes,
            evidence=getattr(fact, "evidence", None),
        )
