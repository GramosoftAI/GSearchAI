"""Tests for Layer 1 — RDF Namespace & Triple Model."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.rdf.namespace import Namespace, RDFTriple, RDFLayer, ParticipantNode, AttributeNode


def test_namespace_entity_uri():
    ns = Namespace("tenant-1")
    uri = ns.entity_uri("PERSON", "Albert Einstein")
    assert uri == "https://grag.ai/kg/person/albert_einstein"
    print(f"  ✓ entity_uri: {uri}")


def test_namespace_predicate_uri():
    ns = Namespace("tenant-1")
    uri = ns.predicate_uri("WORKS_FOR")
    assert uri == "https://grag.ai/kg/predicate/works_for"
    print(f"  ✓ predicate_uri: {uri}")


def test_namespace_event_uri():
    ns = Namespace("tenant-1")
    uri = ns.event_uri("Google acquisition of DeepMind")
    assert uri == "https://grag.ai/kg/event/google_acquisition_of_deepmind"
    print(f"  ✓ event_uri: {uri}")


def test_namespace_custom_base():
    ns = Namespace("tenant-1", base_uri="https://custom.org/graph")
    uri = ns.entity_uri("ORGANIZATION", "Google")
    assert uri == "https://custom.org/graph/organization/google"
    print(f"  ✓ custom_base: {uri}")


def test_rdf_triple_model():
    triple = RDFTriple(
        subject_uri="https://grag.ai/kg/person/alice",
        subject_text="alice",
        subject_type="PERSON",
        predicate="WORKS_FOR",
        object_uri="https://grag.ai/kg/organization/google",
        object_text="google",
        object_type="ORGANIZATION",
        chunk_id="chunk-001",
        tenant_id="tenant-1",
        mode="relationship",
    )
    assert triple.subject_text == "alice"
    assert triple.mode == "relationship"
    print(f"  ✓ RDFTriple model created successfully")


def test_rdf_layer_convert():
    """Test RDFLayer conversion from a mock ExtractedFact-like object."""
    from dataclasses import dataclass, field
    from typing import List, Optional

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

    layer = RDFLayer("tenant-1")

    # Test relationship conversion
    fact = MockFact(
        name="CEO_OF",
        subject="Demis Hassabis",
        object="DeepMind",
        subject_type="PERSON",
        object_type="ORGANIZATION",
    )
    triples = layer.to_triples([fact], "chunk-001")
    assert len(triples) == 1
    t = triples[0]
    assert t.predicate == "CEO_OF"
    assert t.subject_text == "Demis Hassabis"
    assert t.subject_uri != ""
    assert "person" in t.subject_uri
    print(f"  ✓ RDFLayer relationship conversion: {t.subject_uri} → {t.predicate} → {t.object_uri}")

    # Test event conversion
    event_fact = MockFact(
        name="Google acquisition of DeepMind",
        mode_hint="event",
        event_type="ACQUISITION",
        participants=[
            MockParticipant(entity="Google", role="buyer", entity_type="ORGANIZATION"),
            MockParticipant(entity="DeepMind", role="acquired", entity_type="ORGANIZATION"),
        ],
        attributes=[
            MockAttribute(attribute="date", value="2014", entity_type="DATE"),
        ],
    )
    triples = layer.to_triples([event_fact], "chunk-002")
    assert len(triples) == 1
    t = triples[0]
    assert t.mode == "event"
    assert len(t.participants) == 2
    assert len(t.attributes) == 1
    assert t.participants[0].uri != ""
    print(f"  ✓ RDFLayer event conversion: {t.event_name} with {len(t.participants)} participants")


def test_rdf_layer_empty_fact():
    """Ensure facts with no name are skipped."""
    from dataclasses import dataclass

    @dataclass
    class EmptyFact:
        name: str = ""
        subject: str = ""
        object: str = ""
        subject_type: str = "CONCEPT"
        object_type: str = "CONCEPT"
        mode_hint: str = "relationship"
        event_type: str = "EVENT"
        participants: list = None
        attributes: list = None
        confidence: float = 1.0
        evidence: str = None

        def __post_init__(self):
            if self.participants is None:
                self.participants = []
            if self.attributes is None:
                self.attributes = []

    layer = RDFLayer("tenant-1")
    triples = layer.to_triples([EmptyFact()], "chunk-003")
    assert len(triples) == 0
    print(f"  ✓ Empty fact correctly skipped")


if __name__ == "__main__":
    print("\nRunning Layer 1 — RDF Namespace Tests\n")
    test_namespace_entity_uri()
    test_namespace_predicate_uri()
    test_namespace_event_uri()
    test_namespace_custom_base()
    test_rdf_triple_model()
    test_rdf_layer_convert()
    test_rdf_layer_empty_fact()
    print("\n✅ All Layer 1 tests passed!\n")
