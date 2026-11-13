"""
Integration test for the full RDF Pipeline (L1 → L2 → L3 → L4).

Tests the pipeline end-to-end using mock ExtractedFact objects,
WITHOUT requiring a live Neo4j connection (Layer 5 is not tested here).
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dataclasses import dataclass, field
from typing import List, Optional

from app.rdf.namespace import RDFLayer, RDFTriple
from app.rdf.rdfs_layer import RDFSLayer
from app.rdf.owl_layer import OWLLayer
from app.rdf.shacl_layer import SHACLLayer


# ============================================================================
# Mock data classes (simulating LLM output)
# ============================================================================

@dataclass
class MockParticipant:
    entity: str
    role: str
    entity_type: str = "CONCEPT"

@dataclass
class MockAttribute:
    attribute: str
    value: str
    entity_type: str = "CONCEPT"

@dataclass
class MockFact:
    name: str
    subject: Optional[str] = None
    object: Optional[str] = None
    subject_type: str = "CONCEPT"
    object_type: str = "CONCEPT"
    mode_hint: str = "relationship"
    event_type: str = "EVENT"
    participants: List[MockParticipant] = field(default_factory=list)
    attributes: List[MockAttribute] = field(default_factory=list)
    confidence: float = 1.0
    evidence: Optional[str] = None


# ============================================================================
# Tests
# ============================================================================

def test_pipeline_simple_relationship():
    """Test a simple 2-entity relationship flowing through L1→L2→L3→L4."""
    fact = MockFact(
        name="works_for",
        subject="Alice Johnson",
        object="Google LLC",
        subject_type="PERSON",
        object_type="ORGANIZATION",
    )

    # L1: RDF
    rdf = RDFLayer("test-tenant")
    triples = rdf.to_triples([fact], "chunk-001")
    assert len(triples) == 1
    t = triples[0]
    assert t.subject_uri != ""
    assert t.object_uri != ""
    print(f"  ✓ L1 RDF: created triple with URIs")

    # L2: RDFS
    rdfs = RDFSLayer("test-tenant")
    t = rdfs.normalize(t)
    assert t.predicate == "WORKS_FOR"  # Canonical
    assert t.subject_text == "alice johnson"  # Lowered
    print(f"  ✓ L2 RDFS: normalized predicate and text")

    # L3: OWL
    owl = OWLLayer("test-tenant", strict_mode=True)
    t = owl.route(t)
    assert t.mode == "relationship"  # No attributes, stays flat
    allowed, reason = owl.enforce(t)
    assert allowed is True
    print(f"  ✓ L3 OWL: rule enforced, route = {t.mode}")

    # L4: SHACL
    shacl = SHACLLayer("test-tenant")
    result = shacl.validate(t)
    assert result.valid is True
    print(f"  ✓ L4 SHACL: shape validated")

    print(f"\n  Pipeline output: ({t.subject_text} [{t.predicate}] {t.object_text})")


def test_pipeline_event_hub():
    """Test an event fact with participants and attributes."""
    fact = MockFact(
        name="Google acquisition of DeepMind",
        mode_hint="event",
        event_type="ACQUISITION",
        participants=[
            MockParticipant(entity="Google", role="buyer", entity_type="ORGANIZATION"),
            MockParticipant(entity="DeepMind", role="acquired", entity_type="ORGANIZATION"),
        ],
        attributes=[
            MockAttribute(attribute="date", value="2014", entity_type="DATE"),
            MockAttribute(attribute="amount", value="500 million", entity_type="NUMERIC"),
        ],
    )

    # L1: RDF
    rdf = RDFLayer("test-tenant")
    triples = rdf.to_triples([fact], "chunk-002")
    assert len(triples) == 1
    t = triples[0]
    assert t.mode == "event"
    assert len(t.participants) == 2
    assert len(t.attributes) == 2
    print(f"  ✓ L1 RDF: event triple created")

    # L2: RDFS
    rdfs = RDFSLayer("test-tenant")
    t = rdfs.normalize(t)
    assert t.participants[0].entity == "google"  # Lowered
    assert t.attributes[0].attribute == "DATE"  # Uppercased
    print(f"  ✓ L2 RDFS: event normalized")

    # L3: OWL
    owl = OWLLayer("test-tenant")
    t = owl.route(t)
    assert t.mode == "event"
    allowed, reason = owl.enforce(t)
    assert allowed is True
    print(f"  ✓ L3 OWL: event allowed")

    # L4: SHACL
    shacl = SHACLLayer("test-tenant")
    result = shacl.validate(t)
    assert result.valid is True
    print(f"  ✓ L4 SHACL: event shape valid")

    print(f"\n  Pipeline output: Event '{t.event_name}' with "
          f"{len(t.participants)} participants, {len(t.attributes)} attributes")


def test_pipeline_rejected_by_owl():
    """Test that strict OWL mode rejects unknown type combos."""
    fact = MockFact(
        name="eats",
        subject="Cat",
        object="Fish",
        subject_type="ANIMAL",
        object_type="FOOD",
    )

    rdf = RDFLayer("test-tenant")
    triples = rdf.to_triples([fact], "chunk-003")
    rdfs = RDFSLayer("test-tenant")
    triples = rdfs.normalize_batch(triples)

    owl = OWLLayer("test-tenant", strict_mode=True)
    allowed, rejected = owl.enforce_batch(triples)
    assert len(allowed) == 0
    assert len(rejected) == 1
    print(f"  ✓ OWL strict rejection: {rejected[0][1]}")


def test_pipeline_rejected_by_shacl():
    """Test that SHACL rejects structurally invalid triples."""
    # A triple with empty subject
    triple = RDFTriple(
        predicate="WORKS_FOR",
        subject_text="",
        subject_type="PERSON",
        object_text="google",
        object_type="ORGANIZATION",
        mode="relationship",
    )

    shacl = SHACLLayer("test-tenant")
    result = shacl.validate(triple)
    assert result.valid is False
    print(f"  ✓ SHACL rejection: {result.reason[:60]}...")


def test_pipeline_auto_route_to_event():
    """Test that a relationship with attributes auto-routes to event hub."""
    fact = MockFact(
        name="purchased",
        subject="Alice",
        object="Laptop",
        subject_type="PERSON",
        object_type="PRODUCT",
        mode_hint="relationship",
        attributes=[
            MockAttribute(attribute="price", value="999", entity_type="NUMERIC"),
        ],
    )

    rdf = RDFLayer("test-tenant")
    triples = rdf.to_triples([fact], "chunk-004")
    rdfs = RDFSLayer("test-tenant")
    triples = rdfs.normalize_batch(triples)

    owl = OWLLayer("test-tenant")
    triples = owl.route_batch(triples)
    assert triples[0].mode == "event"  # Auto-routed due to attribute
    print(f"  ✓ Auto-routed to event hub due to attribute")


def test_pipeline_batch_mixed():
    """Test a batch with valid and invalid facts mixed together."""
    facts = [
        MockFact(name="works_for", subject="Alice", object="Google",
                 subject_type="PERSON", object_type="ORGANIZATION"),
        MockFact(name="", subject="", object=""),  # Invalid: empty name
        MockFact(name="MEETING", mode_hint="event", event_type="EVENT",
                 participants=[
                     MockParticipant(entity="Alice", role="attendee"),
                     MockParticipant(entity="Bob", role="attendee"),
                     MockParticipant(entity="Charlie", role="attendee"),
                 ]),
    ]

    rdf = RDFLayer("test-tenant")
    triples = rdf.to_triples(facts, "chunk-005")
    assert len(triples) == 2  # Empty name fact skipped in L1
    print(f"  ✓ L1: {len(triples)} of {len(facts)} facts converted (empty skipped)")

    rdfs = RDFSLayer("test-tenant")
    triples = rdfs.normalize_batch(triples)

    owl = OWLLayer("test-tenant")
    triples = owl.route_batch(triples)
    allowed, rejected = owl.enforce_batch(triples)

    shacl = SHACLLayer("test-tenant")
    validated, shacl_rejected = shacl.validate_batch(allowed)

    print(f"  ✓ Final: {len(validated)} validated, "
          f"{len(rejected)} OWL-rejected, {len(shacl_rejected)} SHACL-rejected")


if __name__ == "__main__":
    print("\nRunning RDF Pipeline Integration Tests (L1→L4, no Neo4j)\n")
    test_pipeline_simple_relationship()
    print()
    test_pipeline_event_hub()
    print()
    test_pipeline_rejected_by_owl()
    test_pipeline_rejected_by_shacl()
    test_pipeline_auto_route_to_event()
    test_pipeline_batch_mixed()
    print("\n✅ All Pipeline integration tests passed!\n")
