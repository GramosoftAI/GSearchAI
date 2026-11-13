"""Tests for Layer 4 — SHACL Shape Validation."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.rdf.shacl_layer import SHACLLayer, ValidationResult
from app.rdf.namespace import RDFTriple, ParticipantNode, AttributeNode


def test_valid_relationship():
    shacl = SHACLLayer("test-tenant")
    triple = RDFTriple(
        predicate="WORKS_FOR",
        subject_text="alice",
        subject_type="PERSON",
        object_text="google",
        object_type="ORGANIZATION",
        mode="relationship",
    )
    result = shacl.validate(triple)
    assert result.valid is True
    print(f"  ✓ Valid relationship passed validation")


def test_invalid_relationship_no_subject():
    shacl = SHACLLayer("test-tenant")
    triple = RDFTriple(
        predicate="WORKS_FOR",
        subject_text="",  # Missing!
        subject_type="PERSON",
        object_text="google",
        object_type="ORGANIZATION",
        mode="relationship",
    )
    result = shacl.validate(triple)
    assert result.valid is False
    assert "Structural validation failed" in result.reason
    print(f"  ✓ Missing subject rejected: {result.reason[:60]}...")


def test_invalid_relationship_no_predicate():
    shacl = SHACLLayer("test-tenant")
    triple = RDFTriple(
        predicate="",  # Missing!
        subject_text="alice",
        subject_type="PERSON",
        object_text="google",
        object_type="ORGANIZATION",
        mode="relationship",
    )
    result = shacl.validate(triple)
    assert result.valid is False
    print(f"  ✓ Missing predicate rejected")


def test_valid_event():
    shacl = SHACLLayer("test-tenant")
    triple = RDFTriple(
        mode="event",
        event_name="Google Acquisition",
        participants=[
            ParticipantNode(entity="google", role="buyer"),
        ],
    )
    result = shacl.validate(triple)
    assert result.valid is True
    print(f"  ✓ Valid event passed validation")


def test_invalid_event_no_name():
    shacl = SHACLLayer("test-tenant")
    triple = RDFTriple(
        mode="event",
        event_name="",  # Missing!
        participants=[
            ParticipantNode(entity="google", role="buyer"),
        ],
    )
    result = shacl.validate(triple)
    assert result.valid is False
    print(f"  ✓ Event with no name rejected")


def test_invalid_event_no_participants():
    shacl = SHACLLayer("test-tenant")
    triple = RDFTriple(
        mode="event",
        event_name="Empty Event",
        participants=[],
        attributes=[],
    )
    result = shacl.validate(triple)
    assert result.valid is False
    assert "no participants" in result.reason
    print(f"  ✓ Event with no participants rejected")


def test_validate_batch():
    shacl = SHACLLayer("test-tenant")
    triples = [
        RDFTriple(predicate="WORKS_FOR", subject_text="a", subject_type="PERSON",
                  object_text="b", object_type="ORG", mode="relationship"),
        RDFTriple(predicate="", subject_text="c", subject_type="PERSON",
                  object_text="d", object_type="ORG", mode="relationship"),  # Invalid
        RDFTriple(mode="event", event_name="Test",
                  participants=[ParticipantNode(entity="x", role="r")]),
    ]
    validated, rejected = shacl.validate_batch(triples)
    assert len(validated) == 2
    assert len(rejected) == 1
    print(f"  ✓ Batch: {len(validated)} validated, {len(rejected)} rejected")


def test_register_custom_shape():
    """Test custom shape registration and enforcement."""
    from pydantic import BaseModel, Field
    from typing import Literal

    class StrictPersonShape(BaseModel):
        subject_type: Literal["PERSON"]
        subject_text: str = Field(min_length=3)  # Stricter than default

    shacl = SHACLLayer("test-tenant")
    shacl.register_shape("PERSON", StrictPersonShape)

    # Valid (name >= 3 chars)
    triple = RDFTriple(
        predicate="WORKS_FOR",
        subject_text="alice",
        subject_type="PERSON",
        object_text="google",
        object_type="ORGANIZATION",
        mode="relationship",
    )
    result = shacl.validate(triple)
    assert result.valid is True
    print(f"  ✓ Custom shape: valid person passed")

    # Invalid (name < 3 chars)
    triple2 = RDFTriple(
        predicate="WORKS_FOR",
        subject_text="ab",
        subject_type="PERSON",
        object_text="google",
        object_type="ORGANIZATION",
        mode="relationship",
    )
    result2 = shacl.validate(triple2)
    assert result2.valid is False
    assert "Semantic validation failed" in result2.reason
    print(f"  ✓ Custom shape: short name rejected")


if __name__ == "__main__":
    print("\nRunning Layer 4 — SHACL Tests\n")
    test_valid_relationship()
    test_invalid_relationship_no_subject()
    test_invalid_relationship_no_predicate()
    test_valid_event()
    test_invalid_event_no_name()
    test_invalid_event_no_participants()
    test_validate_batch()
    test_register_custom_shape()
    print("\n✅ All Layer 4 tests passed!\n")
