"""
RDF Pipeline Orchestrator

Chains all 5 layers in sequence:
    Layer 1: RDF (namespace.py)   — Convert ExtractedFact → RDFTriple with URIs
    Layer 2: RDFS (rdfs_layer.py) — Normalize types, predicates, aliases
    Layer 3: OWL (owl_layer.py)   — Enforce ontology rules, route event hubs
    Layer 4: SHACL (shacl_layer.py) — Validate shapes, reject bad triples
    Layer 5: Neo4j (neo4j_writer.py) — Write validated triples to graph

Usage:
    pipeline = await RDFPipeline.create(tenant_id="abc-123")
    result = await pipeline.process(facts, chunk_id="chunk-001")
"""

import time
import logging
from typing import Dict, List, Optional

from pydantic import BaseModel

from .namespace import RDFLayer, RDFTriple
from .rdfs_layer import RDFSLayer
from .owl_layer import OWLLayer
from .shacl_layer import SHACLLayer
from .neo4j_writer import RDFNeo4jWriter

logger = logging.getLogger(__name__)


class PipelineResult(BaseModel):
    """Result of the full RDF pipeline execution."""
    entities_created: int = 0
    relationships_created: int = 0
    triplets_created: int = 0
    events_created: int = 0
    total_input_facts: int = 0
    owl_rejected: int = 0
    shacl_rejected: int = 0
    elapsed_seconds: float = 0.0


class RDFPipeline:
    """
    Orchestrator that chains all 5 RDF stack layers in sequence.

    Each layer is independently testable and configurable, but the
    pipeline ensures they execute in the correct order with proper
    error handling and timing instrumentation.
    """

    def __init__(
        self,
        tenant_id: str,
        rdf_layer: RDFLayer,
        rdfs_layer: RDFSLayer,
        owl_layer: OWLLayer,
        shacl_layer: SHACLLayer,
        neo4j_writer: RDFNeo4jWriter,
    ):
        self.tenant_id = tenant_id
        self.rdf_layer = rdf_layer
        self.rdfs_layer = rdfs_layer
        self.owl_layer = owl_layer
        self.shacl_layer = shacl_layer
        self.neo4j_writer = neo4j_writer

    @classmethod
    async def create(
        cls,
        tenant_id: str,
        strict_mode: bool = False,
        base_uri: Optional[str] = None,
    ) -> "RDFPipeline":
        """
        Factory method that initializes all layers with tenant-specific
        configuration loaded from the OntologyService.
        """
        rdf_layer = RDFLayer(tenant_id, base_uri)
        rdfs_layer = await RDFSLayer.create(tenant_id)
        owl_layer = await OWLLayer.create(tenant_id, strict_mode=strict_mode)
        shacl_layer = SHACLLayer(tenant_id)
        neo4j_writer = RDFNeo4jWriter(tenant_id)

        return cls(
            tenant_id=tenant_id,
            rdf_layer=rdf_layer,
            rdfs_layer=rdfs_layer,
            owl_layer=owl_layer,
            shacl_layer=shacl_layer,
            neo4j_writer=neo4j_writer,
        )

    async def process(
        self,
        facts: list,
        chunk_id: str,
    ) -> PipelineResult:
        """
        Execute the full RDF pipeline on a list of ExtractedFact objects.

        Args:
            facts: List of ExtractedFact (from app.modules.tripets.models)
            chunk_id: Source chunk UUID

        Returns:
            PipelineResult with counts and timing
        """
        start_time = time.perf_counter()
        total_input = len(facts)

        # --- Layer 1: RDF — Convert to RDFTriple with URIs ---
        triples = self.rdf_layer.to_triples(facts, chunk_id)
        logger.info(
            f"[RDF Pipeline] L1 RDF: {total_input} facts → {len(triples)} triples"
        )

        if not triples:
            return PipelineResult(
                total_input_facts=total_input,
                elapsed_seconds=time.perf_counter() - start_time,
            )

        # --- Layer 2: RDFS — Normalize types, predicates, aliases ---
        triples = self.rdfs_layer.normalize_batch(triples)
        logger.info(
            f"[RDF Pipeline] L2 RDFS: normalized {len(triples)} triples"
        )

        # --- Layer 3a: OWL — Route event hubs ---
        triples = self.owl_layer.route_batch(triples)

        # --- Layer 3b: OWL — Enforce ontology rules ---
        owl_allowed, owl_rejected = self.owl_layer.enforce_batch(triples)
        logger.info(
            f"[RDF Pipeline] L3 OWL: {len(owl_allowed)} allowed, "
            f"{len(owl_rejected)} rejected"
        )

        # --- Layer 4: SHACL — Validate shapes ---
        shacl_validated, shacl_rejected = self.shacl_layer.validate_batch(owl_allowed)
        logger.info(
            f"[RDF Pipeline] L4 SHACL: {len(shacl_validated)} validated, "
            f"{len(shacl_rejected)} rejected"
        )

        # Log all rejections
        all_rejections = owl_rejected + shacl_rejected
        if all_rejections:
            await self.shacl_layer.sink.log(all_rejections)

        if not shacl_validated:
            return PipelineResult(
                total_input_facts=total_input,
                owl_rejected=len(owl_rejected),
                shacl_rejected=len(shacl_rejected),
                elapsed_seconds=time.perf_counter() - start_time,
            )

        # --- Layer 5: Neo4j — Write validated triples ---
        write_result = await self.neo4j_writer.write(shacl_validated)

        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[RDF Pipeline] L5 Neo4j: complete in {elapsed:.2f}s — "
            f"{write_result}"
        )

        return PipelineResult(
            entities_created=write_result.get("entities_created", 0),
            relationships_created=write_result.get("relationships_created", 0),
            triplets_created=write_result.get("triplets_created", 0),
            events_created=write_result.get("events_created", 0),
            total_input_facts=total_input,
            owl_rejected=len(owl_rejected),
            shacl_rejected=len(shacl_rejected),
            elapsed_seconds=elapsed,
        )

    async def process_batch(
        self,
        extraction_results: list,
    ) -> PipelineResult:
        """
        Process a batch of TripletExtractionResult objects through the pipeline.

        This is the primary entry point called by TripletGraphWriter.persist_triplets().

        Args:
            extraction_results: List of TripletExtractionResult objects

        Returns:
            Aggregated PipelineResult
        """
        all_facts = []
        chunk_ids = []

        for result in extraction_results:
            if not getattr(result, "success", False):
                continue
            facts = getattr(result, "facts", [])
            chunk_id = getattr(result, "chunk_id", "")
            for fact in facts:
                all_facts.append((fact, chunk_id))

        if not all_facts:
            return PipelineResult()

        start_time = time.perf_counter()
        total_input = len(all_facts)

        # --- Layer 1: RDF ---
        all_triples: List[RDFTriple] = []
        for fact, chunk_id in all_facts:
            triples = self.rdf_layer.to_triples([fact], chunk_id)
            all_triples.extend(triples)

        logger.info(
            f"[RDF Pipeline] L1 RDF: {total_input} facts → {len(all_triples)} triples"
        )

        if not all_triples:
            return PipelineResult(
                total_input_facts=total_input,
                elapsed_seconds=time.perf_counter() - start_time,
            )

        # --- Layer 2: RDFS ---
        all_triples = self.rdfs_layer.normalize_batch(all_triples)

        # --- Layer 3: OWL ---
        all_triples = self.owl_layer.route_batch(all_triples)
        owl_allowed, owl_rejected = self.owl_layer.enforce_batch(all_triples)

        # --- Layer 4: SHACL ---
        shacl_validated, shacl_rejected = self.shacl_layer.validate_batch(owl_allowed)

        # Log rejections
        all_rejections = owl_rejected + shacl_rejected
        if all_rejections:
            await self.shacl_layer.sink.log(all_rejections)

        logger.info(
            f"[RDF Pipeline] Batch: {len(shacl_validated)} validated, "
            f"{len(owl_rejected)} OWL-rejected, {len(shacl_rejected)} SHACL-rejected"
        )

        if not shacl_validated:
            return PipelineResult(
                total_input_facts=total_input,
                owl_rejected=len(owl_rejected),
                shacl_rejected=len(shacl_rejected),
                elapsed_seconds=time.perf_counter() - start_time,
            )

        # --- Layer 5: Neo4j ---
        write_result = await self.neo4j_writer.write(shacl_validated)

        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[RDF Pipeline] Batch complete in {elapsed:.2f}s — {write_result}"
        )

        return PipelineResult(
            entities_created=write_result.get("entities_created", 0),
            relationships_created=write_result.get("relationships_created", 0),
            triplets_created=write_result.get("triplets_created", 0),
            events_created=write_result.get("events_created", 0),
            total_input_facts=total_input,
            owl_rejected=len(owl_rejected),
            shacl_rejected=len(shacl_rejected),
            elapsed_seconds=elapsed,
        )
