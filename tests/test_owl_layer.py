"""Tests for Layer 3 — OWL Ontology Rule Engine."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.rdf.owl_layer import OWLLayer, DEFAULT_SCHEMA_MATRIX, INVERSE_RELATIONS
from app.rdf.namespace import RDFTriple, ParticipantNode, AttributeNode


def test_default_schema_matrix():
    assert ("PERSON", "WORKS_FOR", "ORGANIZATION") in DEFAULT_SCHEMA_MATRIX
    assert ("ORGANIZATION", "LOCATED_IN", "LOCATION") in DEFAULT_SCHEMA_MATRIX
    print(f"  ✓ DEFAULT_SCHEMA_MATRIX loaded: {len(DEFAULT_SCHEMA_MATRIX)} rules")


def test_inverse_relations():
    assert INVERSE_RELATIONS["WORKS_FOR"] == "EMPLOYS"
    assert INVERSE_RELATIONS["PURCHASED"] == "SOLD_TO"
    print(f"  ✓ INVERSE_RELATIONS loaded: {len(INVERSE_RELATIONS)} entries")


def test_enforce_allowed_relationship():
    owl = OWLLayer("test-tenant", strict_mode=True)
    triple = RDFTriple(
        predicate="WORKS_FOR",
        subject_text="alice",
        subject_type="PERSON",
        object_text="google",
        object_type="ORGANIZATION",
        mode="relationship",
    )
    allowed, reason = owl.enforce(triple)
    assert allowed is True
    assert reason is None
    print(f"  ✓ Allowed relationship passed: PERSON -[WORKS_FOR]-> ORGANIZATION")


def test_enforce_rejected_relationship_strict():
    owl = OWLLayer("test-tenant", strict_mode=True)
    triple = RDFTriple(
        predicate="EATS",
        subject_text="cat",
        subject_type="ANIMAL",
        object_text="fish",
        object_type="FOOD",
        mode="relationship",
    )
    allowed, reason = owl.enforce(triple)
    assert allowed is False
    assert "OWL rule violation" in reason
    print(f"  ✓ Rejected in strict mode: {reason}")


def test_enforce_allowed_non_strict():
    owl = OWLLayer("test-tenant", strict_mode=False)
    triple = RDFTriple(
        predicate="EATS",
        subject_text="cat",
        subject_type="ANIMAL",
        object_text="fish",
        object_type="FOOD",
        mode="relationship",
    )
    allowed, reason = owl.enforce(triple)
    assert allowed is True  # Non-strict mode allows unknown rules
    print(f"  ✓ Allowed in non-strict mode")


def test_enforce_event_valid():
    owl = OWLLayer("test-tenant")
    triple = RDFTriple(
        mode="event",
        event_name="Google Acquisition",
        participants=[
            ParticipantNode(entity="google", role="buyer", entity_type="ORGANIZATION"),
        ],
    )
    allowed, reason = owl.enforce(triple)
    assert allowed is True
    print(f"  ✓ Valid event passed")


def test_enforce_event_empty():
    owl = OWLLayer("test-tenant")
    triple = RDFTriple(
        mode="event",
        event_name="Empty Event",
        participants=[],
        attributes=[],
    )
    allowed, reason = owl.enforce(triple)
    assert allowed is False
    assert "no participants or attributes" in reason
    print(f"  ✓ Empty event rejected: {reason}")


def test_enforce_event_no_name():
    owl = OWLLayer("test-tenant")
    triple = RDFTriple(
        mode="event",
        event_name="",
        participants=[
            ParticipantNode(entity="alice", role="participant"),
        ],
    )
    allowed, reason = owl.enforce(triple)
    assert allowed is False
    print(f"  ✓ Event with no name rejected")


def test_enforce_batch():
    owl = OWLLayer("test-tenant", strict_mode=True)
    triples = [
        RDFTriple(predicate="WORKS_FOR", subject_type="PERSON", object_type="ORGANIZATION",
                  subject_text="a", object_text="b", mode="relationship"),
        RDFTriple(predicate="EATS", subject_type="ANIMAL", object_type="FOOD",
                  subject_text="c", object_text="d", mode="relationship"),
        RDFTriple(mode="event", event_name="Test Event",
                  participants=[ParticipantNode(entity="x", role="r")]),
    ]
    allowed, rejected = owl.enforce_batch(triples)
    assert len(allowed) == 2  # WORKS_FOR + valid event
    assert len(rejected) == 1  # EATS
    print(f"  ✓ Batch: {len(allowed)} allowed, {len(rejected)} rejected")


def test_needs_event_hub_simple():
    """2-party fact with no attributes → False."""
    triple = RDFTriple(
        mode="relationship",
        predicate="CEO_OF",
        subject_text="demis",
        object_text="deepmind",
    )
    assert OWLLayer.needs_event_hub(triple) is False
    print(f"  ✓ Simple relationship → not event hub")


def test_needs_event_hub_with_attributes():
    """2-party fact with attribute → True."""
    triple = RDFTriple(
        mode="relationship",
        predicate="CEO_OF",
        subject_text="demis",
        object_text="deepmind",
        attributes=[AttributeNode(attribute="since", value="2010")],
    )
    assert OWLLayer.needs_event_hub(triple) is True
    print(f"  ✓ Fact with attribute → event hub")


def test_needs_event_hub_3_participants():
    """3+ participant fact → True."""
    triple = RDFTriple(
        mode="relationship",
        predicate="MEETING",
        participants=[
            ParticipantNode(entity="alice", role="attendee"),
            ParticipantNode(entity="bob", role="attendee"),
            ParticipantNode(entity="charlie", role="attendee"),
        ],
    )
    assert OWLLayer.needs_event_hub(triple) is True
    print(f"  ✓ 3+ participants → event hub")


def test_needs_event_hub_event_mode():
    """Explicit event mode → True."""
    triple = RDFTriple(mode="event", event_name="Test")
    assert OWLLayer.needs_event_hub(triple) is True
    print(f"  ✓ Explicit event mode → event hub")


def test_route():
    owl = OWLLayer("test-tenant")
    triple = RDFTriple(
        mode="relationship",
        predicate="ACQUISITION",
        attributes=[AttributeNode(attribute="amount", value="500M")],
    )
    routed = owl.route(triple)
    assert routed.mode == "event"
    assert routed.event_name == "ACQUISITION"
    print(f"  ✓ Route upgraded relationship → event")


def test_get_inverse():
    owl = OWLLayer("test-tenant")
    assert owl.get_inverse("WORKS_FOR") == "EMPLOYS"
    assert owl.get_inverse("UNKNOWN") is None
    print(f"  ✓ Inverse relation lookup works")


def test_wildcard_concept_fallback():
    """CONCEPT wildcard rules should allow unknown type combos."""
    owl = OWLLayer("test-tenant", strict_mode=True)
    triple = RDFTriple(
        predicate="RELATES_TO",
        subject_type="CONCEPT",
        object_type="CONCEPT",
        subject_text="a", object_text="b",
        mode="relationship",
    )
    allowed, reason = owl.enforce(triple)
    assert allowed is True
    print(f"  ✓ CONCEPT wildcard fallback works")


if __name__ == "__main__":
    print("\nRunning Layer 3 — OWL Tests\n")
    test_default_schema_matrix()
    test_inverse_relations()
    test_enforce_allowed_relationship()
    test_enforce_rejected_relationship_strict()
    test_enforce_allowed_non_strict()
    test_enforce_event_valid()
    test_enforce_event_empty()
    test_enforce_event_no_name()
    test_enforce_batch()
    test_needs_event_hub_simple()
    test_needs_event_hub_with_attributes()
    test_needs_event_hub_3_participants()
    test_needs_event_hub_event_mode()
    test_route()
    test_get_inverse()
    test_wildcard_concept_fallback()
    print("\n✅ All Layer 3 tests passed!\n")
