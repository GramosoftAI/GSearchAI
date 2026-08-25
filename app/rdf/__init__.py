"""
RDF Stack Layer — Clean, layered RDF-to-Neo4j pipeline.

Architecture:
    Layer 1: namespace.py   — RDF triple model + URI generation
    Layer 2: rdfs_layer.py  — Canonical type/relation mapping + type hierarchy
    Layer 3: owl_layer.py   — Ontology rule enforcement + event hub routing
    Layer 4: shacl_layer.py — Pydantic shape validation + rejection sink
    Layer 5: neo4j_writer.py — URI-aware MERGE writer
    
    pipeline.py — Orchestrator chaining L1 → L2 → L3 → L4 → L5

Usage:
    from app.rdf import RDFPipeline

    pipeline = await RDFPipeline.create(tenant_id="abc-123")
    result = await pipeline.process(facts, chunk_id="chunk-001")
"""

from .namespace import (
    RDFTriple,
    ParticipantNode,
    AttributeNode,
    Namespace,
    RDFLayer,
)
from .rdfs_layer import RDFSLayer
from .owl_layer import OWLLayer
from .shacl_layer import SHACLLayer, ValidationResult
from .neo4j_writer import RDFNeo4jWriter
from .pipeline import RDFPipeline, PipelineResult

__all__ = [
    # Layer 1 — RDF
    "RDFTriple",
    "ParticipantNode",
    "AttributeNode",
    "Namespace",
    "RDFLayer",
    # Layer 2 — RDFS
    "RDFSLayer",
    # Layer 3 — OWL
    "OWLLayer",
    # Layer 4 — SHACL
    "SHACLLayer",
    "ValidationResult",
    # Layer 5 — Neo4j
    "RDFNeo4jWriter",
    # Pipeline
    "RDFPipeline",
    "PipelineResult",
]
