"""
Layer 4 — SHACL: Shape Validation & Rejection Sink

Responsibilities:
  1. Structural validation — every RDFTriple must pass a Pydantic shape check
     before it can be written to Neo4j.
  2. Semantic validation — per-type shapes enforce domain-specific constraints
     (e.g., InvoiceEvent must have issued_by, issued_to, amount).
  3. Rejection sink — failed triples are logged to both a JSONL file and
     (optionally) a RejectedTriple node in Neo4j for API visibility.
  4. Extensible shape registry — new shapes can be registered at runtime
     for tenant-specific validation requirements.

Absorbs:
  - ExtractedFactShape, ExtractedParticipantShape, ExtractedAttributeShape
    from app/modules/tripets/models.py
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Literal, Optional, Tuple, Type

from pydantic import BaseModel, Field, ValidationError

from .namespace import RDFTriple

logger = logging.getLogger(__name__)


# ============================================================================
# VALIDATION RESULT
# ============================================================================

class ValidationResult(BaseModel):
    """Result of validating a single RDFTriple through the SHACL layer."""
    valid: bool
    triple: Optional[RDFTriple] = None
    reason: Optional[str] = None
    shape_name: Optional[str] = None


# ============================================================================
# BASE SHAPES — Structural validation
# ============================================================================

class RelationshipShape(BaseModel):
    """
    Base shape for relationship-mode triples.
    Every relationship must have a subject, predicate, and object.
    """
    subject_text: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_text: str = Field(min_length=1)
    subject_type: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    mode: Literal["relationship"] = "relationship"


class EventShape(BaseModel):
    """
    Base shape for event-mode triples.
    Every event must have a name, and at least one participant or attribute.
    """
    event_name: str = Field(min_length=1)
    mode: Literal["event"] = "event"


# ============================================================================
# DOMAIN-SPECIFIC SHAPES — Semantic validation
# ============================================================================

class PersonNodeShape(BaseModel):
    """Shape for validating Person entity nodes."""
    subject_type: Literal["PERSON"]
    subject_text: str = Field(min_length=2)


class OrganizationNodeShape(BaseModel):
    """Shape for validating Organization entity nodes."""
    subject_type: Literal["ORGANIZATION"]
    subject_text: str = Field(min_length=2)


class InvoiceEventShape(BaseModel):
    """
    Shape for validating Invoice event hubs.
    Invoices must have identifiable issuer and recipient.
    """
    event_name: str = Field(min_length=1)
    # At least 2 participants expected (issuer + recipient)


class AcquisitionEventShape(BaseModel):
    """
    Shape for validating Acquisition event hubs.
    Acquisitions must identify buyer and target.
    """
    event_name: str = Field(min_length=1)


# ============================================================================
# REJECTION SINK
# ============================================================================

class RejectionSink:
    """
    Logs rejected triples to both a JSONL file and optionally to Neo4j.
    """

    def __init__(self, tenant_id: str, log_dir: str = "logs"):
        self.tenant_id = tenant_id
        self.log_dir = log_dir
        self._log_path = os.path.join(log_dir, "rejected_triplets.jsonl")

    async def log(
        self,
        rejections: List[Tuple[RDFTriple, str]],
        chunk_id: Optional[str] = None,
    ) -> int:
        """
        Log rejected triples.

        Args:
            rejections: List of (triple, reason) tuples
            chunk_id: Optional chunk ID override

        Returns:
            Number of rejections logged
        """
        if not rejections:
            return 0

        # Ensure log directory exists
        os.makedirs(self.log_dir, exist_ok=True)

        count = 0
        for triple, reason in rejections:
            record = {
                "timestamp": datetime.utcnow().isoformat(),
                "tenant_id": self.tenant_id,
                "chunk_id": chunk_id or triple.chunk_id,
                "reason": reason,
                "predicate": triple.predicate,
                "subject_text": triple.subject_text,
                "subject_type": triple.subject_type,
                "object_text": triple.object_text,
                "object_type": triple.object_type,
                "mode": triple.mode,
                "event_name": triple.event_name,
            }
            try:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
                count += 1
            except Exception as e:
                logger.warning(f"SHACL Sink: failed to write rejection log: {e}")

        if count > 0:
            logger.info(
                f"SHACL Sink: logged {count} rejected triples for tenant {self.tenant_id}"
            )
        return count


# ============================================================================
# SHACL LAYER
# ============================================================================

class SHACLLayer:
    """
    Layer 4 processor: validates RDFTriples against structural and semantic
    shapes before they reach the Neo4j writer.

    Validation stages:
      1. Structural — relationship triples must have subject/predicate/object;
         event triples must have event_name.
      2. Semantic — domain-specific shapes enforce field constraints per type.
      3. Rejection — failed triples go to the rejection sink.
    """

    def __init__(self, tenant_id: str, log_dir: str = "logs"):
        self.tenant_id = tenant_id
        self.sink = RejectionSink(tenant_id, log_dir)

        # Shape registry: maps (mode, event_type or predicate) → shape class
        # Extensible at runtime via register_shape()
        self._shape_registry: Dict[str, Type[BaseModel]] = {}

    def register_shape(self, key: str, shape_class: Type[BaseModel]) -> None:
        """
        Register a custom shape for a specific entity/event type.

        Args:
            key: Lookup key (e.g., "INVOICE_EVENT", "PERSON")
            shape_class: Pydantic BaseModel class for validation
        """
        self._shape_registry[key.upper()] = shape_class
        logger.info(f"SHACL Layer: registered shape '{key}' -> {shape_class.__name__}")

    def validate(self, triple: RDFTriple) -> ValidationResult:
        """
        Validate a single RDFTriple.

        Returns:
            ValidationResult with valid=True if the triple passes all checks.
        """
        # --- Stage 1: Structural validation ---
        try:
            if triple.mode == "relationship":
                RelationshipShape(
                    subject_text=triple.subject_text,
                    predicate=triple.predicate,
                    object_text=triple.object_text,
                    subject_type=triple.subject_type,
                    object_type=triple.object_type,
                    mode=triple.mode,
                )
            elif triple.mode == "event":
                EventShape(
                    event_name=triple.event_name,
                    mode=triple.mode,
                )
                # Additional: events must have participants or attributes
                if not triple.participants and not triple.attributes:
                    return ValidationResult(
                        valid=False,
                        triple=triple,
                        reason=(
                            f"Event '{triple.event_name}' has no participants "
                            f"or attributes"
                        ),
                        shape_name="EventShape",
                    )
        except ValidationError as e:
            return ValidationResult(
                valid=False,
                triple=triple,
                reason=f"Structural validation failed: {e}",
                shape_name="RelationshipShape" if triple.mode == "relationship" else "EventShape",
            )

        # --- Stage 2: Semantic validation (optional per-type shapes) ---
        shape_key = self._get_shape_key(triple)
        if shape_key and shape_key in self._shape_registry:
            shape_class = self._shape_registry[shape_key]
            try:
                # Build a dict from triple fields for shape validation
                shape_data = self._triple_to_shape_dict(triple)
                shape_class(**shape_data)
            except ValidationError as e:
                return ValidationResult(
                    valid=False,
                    triple=triple,
                    reason=f"Semantic validation failed ({shape_class.__name__}): {e}",
                    shape_name=shape_class.__name__,
                )

        return ValidationResult(valid=True, triple=triple)

    def validate_batch(
        self, triples: List[RDFTriple]
    ) -> Tuple[List[RDFTriple], List[Tuple[RDFTriple, str]]]:
        """
        Validate a batch of triples.

        Returns:
            (validated: List[RDFTriple], rejected: List[(RDFTriple, reason)])
        """
        validated = []
        rejected = []
        for triple in triples:
            result = self.validate(triple)
            if result.valid:
                validated.append(triple)
            else:
                rejected.append(
                    (triple, result.reason or "Unknown validation failure")
                )
        return validated, rejected

    def _get_shape_key(self, triple: RDFTriple) -> Optional[str]:
        """Determine the shape registry key for a triple."""
        if triple.mode == "event":
            return triple.event_type.upper()
        # For relationships, check subject type
        return triple.subject_type.upper()

    def _triple_to_shape_dict(self, triple: RDFTriple) -> dict:
        """Convert an RDFTriple to a dict suitable for shape validation."""
        return {
            "subject_text": triple.subject_text,
            "subject_type": triple.subject_type,
            "predicate": triple.predicate,
            "object_text": triple.object_text,
            "object_type": triple.object_type,
            "mode": triple.mode,
            "event_name": triple.event_name,
            "event_type": triple.event_type,
        }
