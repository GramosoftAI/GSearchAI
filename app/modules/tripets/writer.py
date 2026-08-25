"""
TripletGraphWriter — Thin wrapper around the RDF Pipeline.

This module preserves the existing public API:
    writer = TripletGraphWriter(tenant_id)
    result = await writer.persist_triplets(extraction_results)

Internally it delegates all work to app.rdf.RDFPipeline which chains
the full RDF → RDFS → OWL → SHACL → Neo4j stack.
"""

import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class TripletGraphWriter:
    """
    Orchestrator for persisting extracted triplets to Neo4j graph.
    Delegates to the RDF Pipeline (app.rdf.pipeline.RDFPipeline).
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._pipeline = None  # Lazy-initialized async

    async def _get_pipeline(self):
        """Lazy-initialize the RDF pipeline (requires async factory)."""
        if self._pipeline is None:
            from app.rdf.pipeline import RDFPipeline
            self._pipeline = await RDFPipeline.create(self.tenant_id)
        return self._pipeline

    async def persist_triplets(
        self,
        extraction_results: List,
    ) -> Dict:
        """
        Persist all extracted triplets and events to Neo4j.

        This method sanitizes text, then delegates to the RDF Pipeline
        which handles URI generation, normalization, OWL enforcement,
        SHACL validation, and Neo4j writes.
        """
        # Pre-sanitize text (remove newlines from entity names)
        for result in extraction_results:
            if not getattr(result, "success", False):
                continue
            for fact in getattr(result, "facts", []):
                mode = getattr(fact, "mode_hint", "relationship")
                if mode == "relationship":
                    if getattr(fact, "subject", None):
                        fact.subject = self._sanitize(fact.subject)
                    if getattr(fact, "object", None):
                        fact.object = self._sanitize(fact.object)
                for p in getattr(fact, "participants", []):
                    if hasattr(p, "entity") and p.entity:
                        p.entity = self._sanitize(p.entity)

        # Delegate to the RDF Pipeline
        pipeline = await self._get_pipeline()
        pipeline_result = await pipeline.process_batch(extraction_results)

        logger.info(
            f"[TripletGraphWriter] Pipeline complete: "
            f"{pipeline_result.entities_created} entities, "
            f"{pipeline_result.relationships_created} relationships, "
            f"{pipeline_result.triplets_created} triplet nodes, "
            f"{pipeline_result.events_created} event hubs, "
            f"{pipeline_result.owl_rejected} OWL-rejected, "
            f"{pipeline_result.shacl_rejected} SHACL-rejected, "
            f"in {pipeline_result.elapsed_seconds:.2f}s"
        )

        return {
            "entities_created": pipeline_result.entities_created,
            "relationships_created": pipeline_result.relationships_created,
            "triplets_created": pipeline_result.triplets_created,
            "events_created": pipeline_result.events_created,
        }

    @staticmethod
    def _sanitize(text: str) -> str:
        """Remove newlines and extra whitespace from entity text."""
        if not text:
            return text
        return re.sub(r'[\r\n]+', ' ', text).strip()
