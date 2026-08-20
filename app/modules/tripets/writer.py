import time
import json
import logging
from typing import List, Dict

from pydantic import ValidationError
from app.modules.tripets.condition_checker import needs_event_hub
from app.modules.tripets.models import ExtractedFactShape, TripletExtractionResult, create_uri
from app.modules.tripets.standard_writer import StandardTripletWriter
from app.modules.tripets.event_hub_writer import EventHubWriter

logger = logging.getLogger(__name__)

class TripletGraphWriter:
    """
    Orchestrator for persisting extracted triplets to Neo4j graph.
    Delegates to StandardTripletWriter and EventHubWriter.
    """
    def __init__(self, tenant_id: str):
        from app.core.neo4j_repository import Neo4jRepository
        from app.core.neo4j_retry import retry_neo4j_operation

        self.tenant_id = tenant_id
        self.neo4j_repo = Neo4jRepository(tenant_id)
        self._retry = retry_neo4j_operation
        
        self.standard_writer = StandardTripletWriter(tenant_id, self.neo4j_repo, self._retry)
        self.event_hub_writer = EventHubWriter(tenant_id, self.neo4j_repo, self._retry)

    async def persist_triplets(
        self,
        extraction_results: List[TripletExtractionResult],
    ) -> Dict:
        """
        Persist all extracted triplets and events to Neo4j.
        """
        all_triplets = []
        all_events = []
        
        start_time = time.perf_counter()

        def sanitize_text(text: str) -> str:
            if not text:
                return text
            import re
            return re.sub(r'[\r\n]+', ' ', text).strip()

        # Validation & Routing
        for result in extraction_results:
            if not result.success: continue
            
            chunk_entities = set()
            for fact in result.facts:
                if fact.mode_hint == "relationship":
                    if fact.subject: fact.subject = sanitize_text(fact.subject)
                    if fact.object: fact.object = sanitize_text(fact.object)
                    if fact.subject: chunk_entities.add(fact.subject)
                    if fact.object: chunk_entities.add(fact.object)
                else:
                    for p in fact.participants:
                        if hasattr(p, "entity"):
                            p.entity = sanitize_text(p.entity)
                            ent = p.entity
                        else:
                            p["entity"] = sanitize_text(p.get("entity", ""))
                            ent = p["entity"]
                        if ent: chunk_entities.add(ent)
            
            logger.info(f" Chunk {result.chunk_id[:8]} has {len(chunk_entities)} unique extracted entities: {list(chunk_entities)}")

            for fact in result.facts:
                try:
                    # Validate and convert the dataclass object
                    validated_fact = ExtractedFactShape.model_validate(fact)
                except ValidationError as e:
                    logger.warning(f"Fact validation failed: {e}")
                    # Write to rejection sink
                    with open("logs/rejected_triplets.jsonl", "a", encoding="utf-8") as f:
                        # Fallback to string serialization if needed
                        f.write(json.dumps({"chunk_id": result.chunk_id, "tenant_id": self.tenant_id, "reason": str(e), "fact": str(fact)}) + "\n")
                    continue
                    
                if needs_event_hub(fact):
                    logger.info(f" Routed fact to EVENT-HUB: [Name: {fact.name}, Participants: {[p.entity for p in fact.participants]}, Attributes: {[a.attribute for a in fact.attributes]}]")
                    all_events.append({
                        "chunk_id": result.chunk_id,
                        "event": fact,
                    })
                else:
                    logger.info(f" Routed fact to STANDARD TRIPLET: ({fact.subject} -> {fact.name} -> {fact.object})")
                    all_triplets.append({
                        "chunk_id": result.chunk_id,
                        "triplet": fact,
                    })

        if not all_triplets and not all_events:
            logger.info(" No facts to persist after validation")
            return {
                "entities_created": 0,
                "relationships_created": 0,
                "triplets_created": 0,
                "events_created": 0,
            }

        logger.info(f" Persisting {len(all_triplets)} relations and {len(all_events)} events to Neo4j...")

        # Step 1: ONTOLOGY GROUNDING (Coreference Resolution)
        from app.core.ontology_resolver import OntologyResolver
        resolver = OntologyResolver(self.tenant_id)
        
        unique_entities_list = []
        seen = set()
        
        # Collect from triplets
        for item in all_triplets:
            t = item["triplet"]
            for text, type_ in [(t.subject, t.subject_type), (t.object, t.object_type)]:
                k = f"{text}|{type_}"
                if k not in seen and text:
                    seen.add(k)
                    unique_entities_list.append({"text": text, "type": type_})
                    
        # Collect from events
        for item in all_events:
            ev = item["event"]
            for p in ev.participants:
                k = f"{p.entity}|{p.entity_type}"
                if k not in seen:
                    seen.add(k)
                    unique_entities_list.append({"text": p.entity, "type": p.entity_type})
            for a in ev.attributes:
                k = f"{a.value}|{a.entity_type}"
                if k not in seen:
                    seen.add(k)
                    unique_entities_list.append({"text": a.value, "type": a.entity_type})
                    
        canonical_map = await resolver.resolve_entities(unique_entities_list)
        
        canonical_entities_to_merge = {}
        
        def add_entity_to_merge(text: str, type_: str):
            if not text: return text
            mapped = canonical_map.get(text)
            if mapped:
                resolved_text = mapped["text"]
                emb = mapped["embedding"]
            else:
                resolved_text = text
                emb = []
            
            key = f"{resolved_text}|{type_}"
            canonical_entities_to_merge[key] = {
                "text": resolved_text,
                "type": type_,
                "embedding": emb,
                "uri": create_uri(type_, resolved_text)
            }
            return resolved_text

        # Update triplets and collect entities
        for item in all_triplets:
            t = item["triplet"]
            t.subject = add_entity_to_merge(t.subject, t.subject_type)
            t.object = add_entity_to_merge(t.object, t.object_type)
            
        # Update events and collect entities
        for item in all_events:
            ev = item["event"]
            for p in ev.participants:
                p.entity = add_entity_to_merge(p.entity, p.entity_type)
            for a in ev.attributes:
                a.value = add_entity_to_merge(a.value, a.entity_type)

        # Delegate writes
        std_results = await self.standard_writer.write(all_triplets, canonical_entities_to_merge)
        events_created = await self.event_hub_writer.write(all_events)

        elapsed = time.perf_counter() - start_time
        logger.info(
            f" Triplet & Event persistence complete in {elapsed:.2f}s: "
            f"{std_results['entities_created']} entities, "
            f"{std_results['relationships_created']} relationships, "
            f"{std_results['triplets_created']} triplet nodes, "
            f"{events_created} event hubs"
        )
        return {
            "entities_created": std_results["entities_created"],
            "relationships_created": std_results["relationships_created"],
            "triplets_created": std_results["triplets_created"],
            "events_created": events_created,
        }
