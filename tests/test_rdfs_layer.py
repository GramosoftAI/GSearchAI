"""Tests for Layer 2 — RDFS Canonical Mapping & Type Hierarchy."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.rdf.rdfs_layer import RDFSLayer, CANONICAL_RELATIONS, ENTITY_TYPE_ALIASES, TYPE_HIERARCHY
from app.rdf.namespace import RDFTriple


def test_canonical_relations_exist():
    assert "bought" in CANONICAL_RELATIONS
    assert CANONICAL_RELATIONS["bought"] == "PURCHASED"
    assert CANONICAL_RELATIONS["issued"] == "ISSUED_BY"
    print(f"  ✓ CANONICAL_RELATIONS loaded: {len(CANONICAL_RELATIONS)} entries")


def test_entity_type_aliases_exist():
    assert "GSTIN" in ENTITY_TYPE_ALIASES
    assert "PAN" in ENTITY_TYPE_ALIASES
    print(f"  ✓ ENTITY_TYPE_ALIASES loaded: {len(ENTITY_TYPE_ALIASES)} types")


def test_type_hierarchy():
    assert TYPE_HIERARCHY["EMPLOYEE"] == "PERSON"
    assert TYPE_HIERARCHY["CITY"] == "LOCATION"
    assert TYPE_HIERARCHY["STARTUP"] == "ORGANIZATION"
    print(f"  ✓ TYPE_HIERARCHY loaded: {len(TYPE_HIERARCHY)} entries")


def test_normalize_predicate():
    rdfs = RDFSLayer("test-tenant")
    triple = RDFTriple(
        predicate="bought",
        subject_text="Alice",
        subject_type="PERSON",
        object_text="Laptop",
        object_type="PRODUCT",
        mode="relationship",
    )
    result = rdfs.normalize(triple)
    assert result.predicate == "PURCHASED"
    print(f"  ✓ Predicate normalized: 'bought' → '{result.predicate}'")


def test_normalize_unknown_predicate():
    rdfs = RDFSLayer("test-tenant")
    triple = RDFTriple(
        predicate="invented",
        subject_text="Tesla",
        subject_type="PERSON",
        object_text="AC Motor",
        object_type="CONCEPT",
        mode="relationship",
    )
    result = rdfs.normalize(triple)
    assert result.predicate == "INVENTED"  # Unknown → uppercased
    print(f"  ✓ Unknown predicate uppercased: 'invented' → '{result.predicate}'")


def test_resolve_entity_type_alias():
    rdfs = RDFSLayer("test-tenant")
    assert rdfs.resolve_entity_type("GST Reg. Number") == "GSTIN"
    assert rdfs.resolve_entity_type("PAN Number") == "PAN"
    assert rdfs.resolve_entity_type("Vehicle Identification Number") == "VIN"
    assert rdfs.resolve_entity_type("UNKNOWN_TYPE") == "UNKNOWN_TYPE"
    print(f"  ✓ Entity type alias resolution works")


def test_get_parent_type():
    rdfs = RDFSLayer("test-tenant")
    assert rdfs.get_parent_type("EMPLOYEE") == "PERSON"
    assert rdfs.get_parent_type("CITY") == "LOCATION"
    assert rdfs.get_parent_type("PERSON") is None  # Root type
    print(f"  ✓ Parent type lookup works")


def test_get_all_supertypes():
    rdfs = RDFSLayer("test-tenant")
    supertypes = rdfs.get_all_supertypes("CITY")
    assert "LOCATION" in supertypes
    print(f"  ✓ Supertype chain: CITY → {supertypes}")


def test_normalize_text_lowered():
    rdfs = RDFSLayer("test-tenant")
    triple = RDFTriple(
        predicate="CEO_OF",
        subject_text="  Demis Hassabis  ",
        subject_type="PERSON",
        object_text="  DeepMind  ",
        object_type="ORGANIZATION",
        mode="relationship",
    )
    result = rdfs.normalize(triple)
    assert result.subject_text == "demis hassabis"
    assert result.object_text == "deepmind"
    print(f"  ✓ Text normalized and lowered")


def test_normalize_batch():
    rdfs = RDFSLayer("test-tenant")
    triples = [
        RDFTriple(predicate="bought", subject_text="Alice", subject_type="PERSON",
                  object_text="Book", object_type="PRODUCT", mode="relationship"),
        RDFTriple(predicate="ordered", subject_text="Bob", subject_type="PERSON",
                  object_text="Phone", object_type="PRODUCT", mode="relationship"),
    ]
    results = rdfs.normalize_batch(triples)
    assert results[0].predicate == "PURCHASED"
    assert results[1].predicate == "PURCHASED"
    print(f"  ✓ Batch normalization: {len(results)} triples processed")


def test_custom_relations():
    custom = {"custom_rel": "CUSTOM_CANONICAL"}
    rdfs = RDFSLayer("test-tenant", custom_relations=custom)
    triple = RDFTriple(
        predicate="custom_rel",
        subject_text="A", subject_type="CONCEPT",
        object_text="B", object_type="CONCEPT",
        mode="relationship",
    )
    result = rdfs.normalize(triple)
    assert result.predicate == "CUSTOM_CANONICAL"
    print(f"  ✓ Custom relation mapping works")


def test_get_all_aliases():
    rdfs = RDFSLayer("test-tenant")
    aliases = rdfs.get_all_aliases()
    assert "GSTIN" in aliases
    assert "GST Number" in aliases
    print(f"  ✓ get_all_aliases returns {len(aliases)} aliases")


if __name__ == "__main__":
    print("\nRunning Layer 2 — RDFS Tests\n")
    test_canonical_relations_exist()
    test_entity_type_aliases_exist()
    test_type_hierarchy()
    test_normalize_predicate()
    test_normalize_unknown_predicate()
    test_resolve_entity_type_alias()
    test_get_parent_type()
    test_get_all_supertypes()
    test_normalize_text_lowered()
    test_normalize_batch()
    test_custom_relations()
    test_get_all_aliases()
    print("\n✅ All Layer 2 tests passed!\n")
