"""
Layer 3 — OWL: Ontology Rule Engine

Responsibilities:
  1. Ontology rule enforcement — validates that a (subject_type, predicate, object_type)
     combination is allowed by the schema before it reaches Neo4j.
  2. Event hub routing — deterministic decision on whether a fact should be modeled as
     a simple relationship or an event-hub node (absorbs condition_checker.py).
  3. Inverse relation support — declares which predicates have inverses (OWL inverseOf).
  4. Tenant-aware rule loading — loads ALLOWED_RELATION edges from OntologyService
     and falls back to a built-in default matrix.

Absorbs:
  - ALLOWED_SCHEMA_MATRIX from app/core/schema_config.py
  - needs_event_hub() from app/modules/tripets/condition_checker.py
"""

import logging
from typing import Dict, List, Optional, Set, Tuple

from .namespace import RDFTriple

logger = logging.getLogger(__name__)


# ============================================================================
# DEFAULT SCHEMA MATRIX (owl:AllowedRelation equivalent)
# ============================================================================

# Tuple format: (SUBJECT_TYPE, PREDICATE, OBJECT_TYPE)
# Absorbed from app/core/schema_config.py with additions.
DEFAULT_SCHEMA_MATRIX: Set[Tuple[str, str, str]] = {
    # Organization relations
    ("ORGANIZATION", "LOCATED_IN", "LOCATION"),
    ("ORGANIZATION", "WORKS_AT", "ORGANIZATION"),
    ("ORGANIZATION", "ACQUIRED", "ORGANIZATION"),
    ("ORGANIZATION", "MERGED_WITH", "ORGANIZATION"),
    ("ORGANIZATION", "PRODUCES", "CONCEPT"),
    ("ORGANIZATION", "PRODUCES", "PRODUCT"),
    ("ORGANIZATION", "FOUNDED", "ORGANIZATION"),

    # Person relations
    ("PERSON", "WORKS_FOR", "ORGANIZATION"),
    ("PERSON", "EMPLOYEE_OF", "ORGANIZATION"),
    ("PERSON", "CEO_OF", "ORGANIZATION"),
    ("PERSON", "LEADS", "ORGANIZATION"),
    ("PERSON", "FOUNDED", "ORGANIZATION"),
    ("PERSON", "LOCATED_IN", "LOCATION"),
    ("PERSON", "LIVES_IN", "LOCATION"),
    ("PERSON", "SPOUSE", "PERSON"),
    ("PERSON", "RELATES_TO", "PERSON"),
    ("PERSON", "DEVELOPED", "CONCEPT"),
    ("PERSON", "DEVELOPED", "PRODUCT"),
    ("PERSON", "DEVELOPED", "TECHNOLOGY"),
    ("PERSON", "DEFINED", "CONCEPT"),
    ("PERSON", "HAS_EXPERIENCE", "CONCEPT"),

    # Concept relations
    ("CONCEPT", "RELATES_TO", "CONCEPT"),
    ("CONCEPT", "DEFINED_AS", "CONCEPT"),
    ("CONCEPT", "REFERRED_TO", "CONCEPT"),
    ("CONCEPT", "AIMS_FOR", "CONCEPT"),
    ("CONCEPT", "DETERMINES", "CONCEPT"),
    ("CONCEPT", "IN", "CONCEPT"),
    ("CONCEPT", "HAS_URL", "URL"),

    # Cross-type generic
    ("ORGANIZATION", "RELATES_TO", "CONCEPT"),
    ("PERSON", "RELATES_TO", "CONCEPT"),
    ("ORGANIZATION", "HAS_EXPERIENCE", "CONCEPT"),

    # Document relations
    ("DOCUMENT", "MENTIONS", "ORGANIZATION"),
    ("DOCUMENT", "MENTIONS", "PERSON"),
    ("DOCUMENT", "MENTIONS", "LOCATION"),
    ("DOCUMENT", "MENTIONS", "CONCEPT"),
    ("DOCUMENT", "HAS_SECTION", "SECTION"),

    # Structural Document Edges
    ("SECTION", "HAS_SUBSECTION", "SECTION"),
    ("SECTION", "HAS_TABLE", "TABLE"),
    ("SECTION", "HAS_TEXT", "TEXT"),
    ("SECTION", "HAS_LIST", "LIST"),
    ("SECTION", "HAS_CODE", "CODE"),
    ("SECTION", "HAS_IDENTIFIER", "STRUCTURED_IDENTIFIER"),
    ("TABLE", "HAS_ROW", "ROW"),
    ("DOCUMENT", "PART_OF", "DOCUMENT"),

    # Web Extraction Edges
    ("ORGANIZATION", "HAS_WEBSITE", "URL"),
    ("ORGANIZATION", "HAS_WEBSITE", "CONCEPT"),
    ("PERSON", "HAS_WEBSITE", "URL"),

    # Invoice / Financial
    ("ORGANIZATION", "ISSUED_BY", "ORGANIZATION"),
    ("ORGANIZATION", "ISSUED_TO", "ORGANIZATION"),
    ("PERSON", "ISSUED_BY", "ORGANIZATION"),
    ("PERSON", "PURCHASED", "PRODUCT"),
    ("ORGANIZATION", "PURCHASED", "PRODUCT"),
    ("ORGANIZATION", "SUPPLIED_BY", "ORGANIZATION"),
    ("PRODUCT", "CONTAINS_PRODUCT", "PRODUCT"),
    ("CONCEPT", "BELONGS_TO", "CONCEPT"),

    # Named entity identifiers
    ("NAME", "ORIGINATOR_OF", "CONCEPT"),
}


# ============================================================================
# INVERSE RELATIONS (owl:inverseOf)
# ============================================================================

INVERSE_RELATIONS: Dict[str, str] = {
    "ISSUED_BY": "ISSUED_TO",
    "ISSUED_TO": "ISSUED_BY",
    "WORKS_FOR": "EMPLOYS",
    "EMPLOYS": "WORKS_FOR",
    "PURCHASED": "SOLD_TO",
    "SOLD_TO": "PURCHASED",
    "ACQUIRED": "ACQUIRED_BY",
    "ACQUIRED_BY": "ACQUIRED",
    "SUPPLIED_BY": "SUPPLIES",
    "SUPPLIES": "SUPPLIED_BY",
    "BELONGS_TO": "HAS_MEMBER",
    "HAS_MEMBER": "BELONGS_TO",
}


# ============================================================================
# OWL LAYER
# ============================================================================

class OWLLayer:
    """
    Layer 3 processor: enforces ontology rules and routes facts to the
    correct write pattern (simple relationship vs event hub).

    Rule sources (in priority order):
      1. Tenant-specific ALLOWED_RELATION edges loaded from Neo4j
      2. Built-in DEFAULT_SCHEMA_MATRIX

    Unknown (subject_type, predicate, object_type) combinations are rejected
    unless strict_mode is False, in which case they are allowed with a warning.
    """

    def __init__(
        self,
        tenant_id: str,
        schema_matrix: Optional[Set[Tuple[str, str, str]]] = None,
        strict_mode: bool = False,
    ):
        self.tenant_id = tenant_id
        self.strict_mode = strict_mode

        # Merge tenant rules with defaults
        self.allowed_rules = set(DEFAULT_SCHEMA_MATRIX)
        if schema_matrix:
            self.allowed_rules.update(schema_matrix)

    @classmethod
    async def create(cls, tenant_id: str, strict_mode: bool = False) -> "OWLLayer":
        """
        Factory method that loads tenant-specific ALLOWED_RELATION edges
        from the OntologyService before constructing the layer.
        """
        tenant_rules: Set[Tuple[str, str, str]] = set()
        try:
            from app.modules.ontology.service import OntologyService
            ont_svc = OntologyService(tenant_id)
            ont_data = await ont_svc.get_ontology()

            for rule in ont_data.get("rules", []):
                src = rule.get("source_class", "")
                rel = rule.get("relation", "")
                tgt = rule.get("target_class", "")
                if src and rel and tgt:
                    tenant_rules.add((src.upper(), rel.upper(), tgt.upper()))

            if tenant_rules:
                logger.info(
                    f"OWL Layer: loaded {len(tenant_rules)} tenant-specific rules "
                    f"for tenant {tenant_id}"
                )
        except Exception as e:
            logger.warning(f"OWL Layer: could not load tenant ontology rules: {e}")

        return cls(tenant_id, schema_matrix=tenant_rules, strict_mode=strict_mode)

    # ----------------------------------------------------------------
    # Rule enforcement
    # ----------------------------------------------------------------

    def enforce(self, triple: RDFTriple) -> Tuple[bool, Optional[str]]:
        """
        Check whether a triple is allowed by the ontology rules.

        For event-mode triples, structural validation is applied instead
        of (subject_type, predicate, object_type) checks.

        Returns:
            (allowed: bool, rejection_reason: Optional[str])
        """
        # Event hub triples are validated differently
        if triple.mode == "event":
            return self._enforce_event(triple)

        return self._enforce_relationship(triple)

    def _enforce_relationship(self, triple: RDFTriple) -> Tuple[bool, Optional[str]]:
        """Validate a simple relationship triple against the schema matrix."""
        s_type = triple.subject_type.upper()
        pred = triple.predicate.upper()
        o_type = triple.object_type.upper()

        # Check if this exact combination is allowed
        rule = (s_type, pred, o_type)
        if rule in self.allowed_rules:
            return True, None

        # Check with CONCEPT as a wildcard fallback
        # e.g., (CONCEPT, RELATES_TO, CONCEPT) allows any unknown types
        wildcard_rules = [
            (s_type, pred, "CONCEPT"),
            ("CONCEPT", pred, o_type),
            ("CONCEPT", pred, "CONCEPT"),
        ]
        for wr in wildcard_rules:
            if wr in self.allowed_rules:
                return True, None

        if self.strict_mode:
            reason = (
                f"OWL rule violation: ({s_type} -[{pred}]-> {o_type}) "
                f"not in allowed schema matrix"
            )
            return False, reason

        # Non-strict mode: allow but log warning
        logger.debug(
            f"OWL Layer: unmatched rule ({s_type}, {pred}, {o_type}) — "
            f"allowed in non-strict mode"
        )
        return True, None

    def _enforce_event(self, triple: RDFTriple) -> Tuple[bool, Optional[str]]:
        """Validate an event hub triple (structural checks only)."""
        if not triple.event_name:
            return False, "Event triple has no event_name"

        # Events must have at least one participant or attribute
        if not triple.participants and not triple.attributes:
            return False, (
                f"Event '{triple.event_name}' has no participants or attributes"
            )

        return True, None

    def enforce_batch(
        self, triples: List[RDFTriple]
    ) -> Tuple[List[RDFTriple], List[Tuple[RDFTriple, str]]]:
        """
        Enforce rules on a batch of triples.

        Returns:
            (allowed: List[RDFTriple], rejected: List[(RDFTriple, reason)])
        """
        allowed = []
        rejected = []
        for triple in triples:
            ok, reason = self.enforce(triple)
            if ok:
                allowed.append(triple)
            else:
                rejected.append((triple, reason or "Unknown OWL rule violation"))
        return allowed, rejected

    # ----------------------------------------------------------------
    # Event hub routing (absorbed from condition_checker.py)
    # ----------------------------------------------------------------

    @staticmethod
    def needs_event_hub(triple: RDFTriple) -> bool:
        """
        Deterministic decision: should this triple be modeled as an
        event-hub node or a simple relationship?

        Criteria (any one triggers True):
          - 3+ distinct participant entities
          - 1+ non-participant attributes (date, amount, status, etc.)
          - The LLM flagged it as mode_hint == "event"
        """
        # Already marked as event
        if triple.mode == "event":
            return True

        # 3+ distinct participants
        unique_participants = set(p.entity for p in triple.participants if p.entity)
        if len(unique_participants) >= 3:
            return True

        # Has attributes
        if len(triple.attributes) >= 1:
            return True

        return False

    def route(self, triple: RDFTriple) -> RDFTriple:
        """
        Apply event hub routing: sets triple.mode based on deterministic
        analysis, overriding the LLM hint when needed.
        """
        if self.needs_event_hub(triple):
            triple.mode = "event"
            if not triple.event_name:
                triple.event_name = triple.predicate
        return triple

    def route_batch(self, triples: List[RDFTriple]) -> List[RDFTriple]:
        """Apply routing to a batch of triples."""
        return [self.route(t) for t in triples]

    # ----------------------------------------------------------------
    # Inverse relations
    # ----------------------------------------------------------------

    def get_inverse(self, predicate: str) -> Optional[str]:
        """Return the inverse predicate, or None."""
        return INVERSE_RELATIONS.get(predicate.upper())
