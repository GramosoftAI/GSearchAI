"""
Layer 5 — Neo4j Writer: URI-Aware MERGE

Responsibilities:
  1. Entity node creation — MERGE on URI (instead of text+type) for true dedup.
  2. Relationship creation — standard (S)-[:PREDICATE]->(O) edges.
  3. Event hub creation — hub node + typed participant/attribute edges.
  4. Triplet node creation — searchable Triplet nodes with embeddings.
  5. Coreference resolution — embedding-based entity merging via OntologyResolver.

Absorbs:
  - EntityMerger from app/modules/tripets/entity_merger.py
  - StandardTripletWriter from app/modules/tripets/standard_writer.py
  - EventHubWriter from app/modules/tripets/event_hub_writer.py
"""

import uuid
import logging
from typing import Dict, List, Optional

from .namespace import RDFTriple

logger = logging.getLogger(__name__)


class RDFNeo4jWriter:
    """
    Layer 5: writes validated RDFTriples to Neo4j using URI-based MERGE
    for entity deduplication.

    Handles both:
      - Simple relationship triples (Subject → Predicate → Object)
      - Event hub triples (Hub node + participant/attribute edges)
    """

    def __init__(self, tenant_id: str):
        from app.core.neo4j_repository import Neo4jRepository
        from app.core.neo4j_retry import retry_neo4j_operation

        self.tenant_id = tenant_id
        self.neo4j_repo = Neo4jRepository(tenant_id)
        self._retry = retry_neo4j_operation

    async def write(self, triples: List[RDFTriple]) -> Dict:
        """
        Write all validated triples to Neo4j.

        Routes each triple to the appropriate write pattern based on its mode.
        """
        relationships = [t for t in triples if t.mode == "relationship"]
        events = [t for t in triples if t.mode == "event"]

        # Step 1: Coreference resolution (embedding-based entity merging)
        all_triples = relationships + events
        canonical_map = await self._resolve_coreferences(all_triples)

        # Apply canonical mappings
        for t in all_triples:
            self._apply_canonical(t, canonical_map)

        # Step 2: Collect and MERGE all unique entities
        entities_to_merge = self._collect_entities(all_triples)
        entities_created = await self._merge_entities(entities_to_merge)

        # Step 3: Write relationships
        relationships_created = 0
        triplets_created = 0
        if relationships:
            relationships_created = await self._create_relationships(relationships)
            triplets_created = await self._create_triplet_nodes(relationships)

        # Step 4: Write event hubs
        events_created = 0
        if events:
            events_created = await self._create_event_hubs(events)

        logger.info(
            f"RDF Neo4j Writer: {entities_created} entities, "
            f"{relationships_created} relationships, "
            f"{triplets_created} triplet nodes, "
            f"{events_created} event hubs"
        )

        return {
            "entities_created": entities_created,
            "relationships_created": relationships_created,
            "triplets_created": triplets_created,
            "events_created": events_created,
        }

    # ----------------------------------------------------------------
    # Coreference resolution
    # ----------------------------------------------------------------

    async def _resolve_coreferences(
        self, triples: List[RDFTriple]
    ) -> Dict[str, Dict]:
        """Use OntologyResolver for embedding-based entity merging."""
        unique_entities = []
        seen = set()

        for t in triples:
            for text, etype in [
                (t.subject_text, t.subject_type),
                (t.object_text, t.object_type),
            ]:
                key = f"{text}|{etype}"
                if key not in seen and text:
                    seen.add(key)
                    unique_entities.append({"text": text, "type": etype})

            for p in t.participants:
                key = f"{p.entity}|{p.entity_type}"
                if key not in seen and p.entity:
                    seen.add(key)
                    unique_entities.append({"text": p.entity, "type": p.entity_type})

            for a in t.attributes:
                key = f"{a.value}|{a.entity_type}"
                if key not in seen and a.value:
                    seen.add(key)
                    unique_entities.append({"text": a.value, "type": a.entity_type})

        if not unique_entities:
            return {}

        try:
            from app.core.ontology_resolver import OntologyResolver
            resolver = OntologyResolver(self.tenant_id)
            return await resolver.resolve_entities(unique_entities)
        except Exception as e:
            logger.warning(f"RDF Writer: coreference resolution failed: {e}")
            return {e_item["text"]: {"text": e_item["text"], "embedding": []} for e_item in unique_entities}

    def _apply_canonical(self, triple: RDFTriple, canonical_map: Dict) -> None:
        """Apply canonical entity mappings from coreference resolution."""
        if triple.subject_text and triple.subject_text in canonical_map:
            mapped = canonical_map[triple.subject_text]
            triple.subject_text = mapped["text"]
            # Regenerate URI for the canonical text
            from .namespace import Namespace
            ns = Namespace(self.tenant_id)
            triple.subject_uri = ns.entity_uri(triple.subject_type, mapped["text"])

        if triple.object_text and triple.object_text in canonical_map:
            mapped = canonical_map[triple.object_text]
            triple.object_text = mapped["text"]
            from .namespace import Namespace
            ns = Namespace(self.tenant_id)
            triple.object_uri = ns.entity_uri(triple.object_type, mapped["text"])

        for p in triple.participants:
            if p.entity and p.entity in canonical_map:
                mapped = canonical_map[p.entity]
                p.entity = mapped["text"]
                from .namespace import Namespace
                ns = Namespace(self.tenant_id)
                p.uri = ns.entity_uri(p.entity_type, mapped["text"])

        for a in triple.attributes:
            if a.value and a.value in canonical_map:
                mapped = canonical_map[a.value]
                a.value = mapped["text"]
                from .namespace import Namespace
                ns = Namespace(self.tenant_id)
                a.uri = ns.entity_uri(a.entity_type, mapped["text"])

    # ----------------------------------------------------------------
    # Entity collection and MERGE
    # ----------------------------------------------------------------

    def _collect_entities(self, triples: List[RDFTriple]) -> List[Dict]:
        """Collect all unique entities from triples for MERGE."""
        entities: Dict[str, Dict] = {}

        for t in triples:
            # Subject
            if t.subject_text and t.subject_uri:
                key = t.subject_uri
                if key not in entities:
                    entities[key] = {
                        "text": t.subject_text,
                        "type": t.subject_type,
                        "uri": t.subject_uri,
                        "embedding": [],
                    }

            # Object
            if t.object_text and t.object_uri:
                key = t.object_uri
                if key not in entities:
                    entities[key] = {
                        "text": t.object_text,
                        "type": t.object_type,
                        "uri": t.object_uri,
                        "embedding": [],
                    }

            # Participants
            for p in t.participants:
                if p.entity and p.uri:
                    key = p.uri
                    if key not in entities:
                        entities[key] = {
                            "text": p.entity,
                            "type": p.entity_type,
                            "uri": p.uri,
                            "embedding": [],
                        }

            # Attributes
            for a in t.attributes:
                if a.value and a.uri:
                    key = a.uri
                    if key not in entities:
                        entities[key] = {
                            "text": a.value,
                            "type": a.entity_type,
                            "uri": a.uri,
                            "embedding": [],
                        }

        return list(entities.values())

    async def _merge_entities(self, entity_list: List[Dict]) -> int:
        """MERGE unique entity nodes using URI as the primary dedup key."""
        if not entity_list:
            return 0

        # Generate embeddings for new entities
        try:
            from app.core.embeddings import EmbeddingGenerator
            texts = [e["text"] for e in entity_list]
            embeddings = await EmbeddingGenerator.generate_embeddings_batch(texts)
            for i, e in enumerate(entity_list):
                if embeddings[i]:
                    e["embedding"] = embeddings[i]
        except Exception as e:
            logger.warning(f"RDF Writer: entity embedding generation failed: {e}")

        query = """
        WITH $entities AS entity_list
        UNWIND entity_list AS e
        MERGE (ent:Entity {
            tenant_id: $tenant_id,
            uri: e.uri
        })
        ON CREATE SET
            ent.id = randomUUID(),
            ent.text = e.text,
            ent.type = e.type,
            ent.created_at = timestamp()
        SET ent.text = e.text,
            ent.type = e.type,
            ent.embedding = CASE
                WHEN e.embedding IS NOT NULL AND size(e.embedding) > 0
                THEN e.embedding
                ELSE ent.embedding
            END
        RETURN count(ent) as count
        """

        try:
            await self._retry(
                lambda: self.neo4j_repo.execute_write(
                    query,
                    {"entities": entity_list, "tenant_id": self.tenant_id},
                )
            )
            return len(entity_list)
        except Exception as e:
            logger.warning(f"RDF Writer: entity MERGE failed: {e}")
            return 0

    # ----------------------------------------------------------------
    # Relationship writes
    # ----------------------------------------------------------------

    async def _create_relationships(self, triples: List[RDFTriple]) -> int:
        """CREATE typed relationship edges between entities."""
        rel_data = []
        for t in triples:
            rel_data.append({
                "subject_uri": t.subject_uri,
                "subject_text": t.subject_text,
                "subject_type": t.subject_type,
                "predicate": t.predicate,
                "object_uri": t.object_uri,
                "object_text": t.object_text,
                "object_type": t.object_type,
                "chunk_id": t.chunk_id,
                "confidence": t.confidence,
            })

        if not rel_data:
            return 0

        query = """
        WITH $relationships AS rel_list
        UNWIND rel_list AS r
        MATCH (s:Entity {tenant_id: $tenant_id, uri: r.subject_uri})
        MATCH (o:Entity {tenant_id: $tenant_id, uri: r.object_uri})
        OPTIONAL MATCH (c:Chunk {id: r.chunk_id, tenant_id: $tenant_id})
        CREATE (s)-[:RELATES_TO {
            predicate: r.predicate,
            chunk_id: r.chunk_id,
            confidence: r.confidence,
            tenant_id: $tenant_id,
            source_document: CASE WHEN c.source IS NOT NULL THEN c.source ELSE 'unknown' END,
            extraction_model: 'deepinfra-llm',
            created_at: timestamp()
        }]->(o)
        RETURN count(*) as count
        """

        try:
            await self._retry(
                lambda: self.neo4j_repo.execute_write(
                    query,
                    {"relationships": rel_data, "tenant_id": self.tenant_id},
                )
            )
            return len(rel_data)
        except Exception as e:
            logger.warning(f"RDF Writer: relationship creation failed: {e}")
            return 0

    async def _create_triplet_nodes(self, triples: List[RDFTriple]) -> int:
        """CREATE searchable Triplet nodes with embeddings."""
        triplet_texts = []
        for t in triples:
            text = f"{t.subject_text}  {t.predicate}  {t.object_text}"
            triplet_texts.append(text)

        try:
            from app.core.embeddings import EmbeddingGenerator
            embeddings = await EmbeddingGenerator.generate_embeddings_batch(
                triplet_texts
            )
        except Exception as e:
            logger.warning(f"RDF Writer: triplet embedding generation failed: {e}")
            embeddings = [None] * len(triplet_texts)

        node_data = []
        for i, t in enumerate(triples):
            node_data.append({
                "triplet_id": str(uuid.uuid4()),
                "text": triplet_texts[i],
                "subject": t.subject_text,
                "predicate": t.predicate,
                "object": t.object_text,
                "chunk_id": t.chunk_id,
                "embedding": embeddings[i] if embeddings[i] else [],
            })

        if not node_data:
            return 0

        query = """
        WITH $triplets AS triplet_list
        UNWIND triplet_list AS td
        CREATE (t:Triplet {
            id: td.triplet_id,
            tenant_id: $tenant_id,
            text: td.text,
            subject: td.subject,
            predicate: td.predicate,
            object: td.object,
            chunk_id: td.chunk_id,
            embedding: td.embedding,
            created_at: timestamp()
        })
        WITH t, td
        MATCH (c:Chunk {id: td.chunk_id, tenant_id: $tenant_id})
        CREATE (c)-[:HAS_TRIPLET]->(t)
        RETURN count(t) as count
        """

        try:
            await self._retry(
                lambda: self.neo4j_repo.execute_write(
                    query,
                    {"triplets": node_data, "tenant_id": self.tenant_id},
                )
            )
            return len(node_data)
        except Exception as e:
            logger.warning(f"RDF Writer: triplet node creation failed: {e}")
            return 0

    # ----------------------------------------------------------------
    # Event hub writes
    # ----------------------------------------------------------------

    async def _create_event_hubs(self, triples: List[RDFTriple]) -> int:
        """Create EventHub nodes and their participant/attribute edges."""
        hubs: Dict[str, Dict] = {}
        chunk_links = []
        participant_links = []
        occurred_on_links = []
        attribute_of_links = []

        date_attributes = {"DATE", "TIME", "OCCURRED_ON", "WHEN", "YEAR"}

        for t in triples:
            hub_key = t.event_name
            hubs[hub_key] = {
                "name": t.event_name,
                "event_type": t.event_type,
            }

            chunk_links.append({
                "chunk_id": t.chunk_id,
                "event_name": t.event_name,
            })

            for p in t.participants:
                participant_links.append({
                    "event_name": t.event_name,
                    "entity_uri": p.uri,
                    "entity_text": p.entity,
                    "entity_type": p.entity_type,
                    "role": p.role,
                })

            for a in t.attributes:
                link = {
                    "event_name": t.event_name,
                    "entity_uri": a.uri,
                    "entity_text": a.value,
                    "entity_type": a.entity_type,
                    "attribute": a.attribute,
                }
                if a.attribute.upper() in date_attributes:
                    occurred_on_links.append(link)
                else:
                    attribute_of_links.append(link)

        # Batch MERGE EventHub nodes
        hub_query = """
        WITH $hubs AS hub_list
        UNWIND hub_list AS h
        MERGE (hub:EventHub {tenant_id: $tenant_id, name: h.name})
        ON CREATE SET
            hub.id = randomUUID(),
            hub.type = h.event_type,
            hub.created_at = timestamp()
        RETURN count(hub) as count
        """

        # Batch MERGE Chunk connections
        chunk_query = """
        WITH $links AS link_list
        UNWIND link_list AS l
        MATCH (c:Chunk {id: l.chunk_id, tenant_id: $tenant_id})
        MATCH (hub:EventHub {tenant_id: $tenant_id, name: l.event_name})
        MERGE (c)-[:HAS_EVENT_HUB {tenant_id: $tenant_id}]->(hub)
        RETURN count(*) as count
        """

        # Batch MERGE Participant connections (using URI for entity match)
        participant_query = """
        WITH $links AS link_list
        UNWIND link_list AS l
        MATCH (e:Entity {tenant_id: $tenant_id, uri: l.entity_uri})
        MATCH (hub:EventHub {tenant_id: $tenant_id, name: l.event_name})
        MERGE (e)-[:PARTICIPANT_IN {role: l.role, tenant_id: $tenant_id}]->(hub)
        RETURN count(*) as count
        """

        # Batch MERGE Occurred On (Dates) connections
        occurred_on_query = """
        WITH $links AS link_list
        UNWIND link_list AS l
        MATCH (e:Entity {tenant_id: $tenant_id, uri: l.entity_uri})
        MATCH (hub:EventHub {tenant_id: $tenant_id, name: l.event_name})
        MERGE (e)-[:OCCURRED_ON {tenant_id: $tenant_id}]->(hub)
        RETURN count(*) as count
        """

        # Batch MERGE Attribute Of connections
        attribute_of_query = """
        WITH $links AS link_list
        UNWIND link_list AS l
        MATCH (e:Entity {tenant_id: $tenant_id, uri: l.entity_uri})
        MATCH (hub:EventHub {tenant_id: $tenant_id, name: l.event_name})
        MERGE (e)-[:ATTRIBUTE_OF {attribute: l.attribute, tenant_id: $tenant_id}]->(hub)
        RETURN count(*) as count
        """

        try:
            # 1. Merge Hubs
            await self._retry(
                lambda: self.neo4j_repo.execute_write(
                    hub_query,
                    {"hubs": list(hubs.values()), "tenant_id": self.tenant_id},
                )
            )

            # 2. Chunk connections
            if chunk_links:
                await self._retry(
                    lambda: self.neo4j_repo.execute_write(
                        chunk_query,
                        {"links": chunk_links, "tenant_id": self.tenant_id},
                    )
                )

            # 3. Participant connections
            if participant_links:
                await self._retry(
                    lambda: self.neo4j_repo.execute_write(
                        participant_query,
                        {"links": participant_links, "tenant_id": self.tenant_id},
                    )
                )

            # 4. Occurred On connections
            if occurred_on_links:
                await self._retry(
                    lambda: self.neo4j_repo.execute_write(
                        occurred_on_query,
                        {"links": occurred_on_links, "tenant_id": self.tenant_id},
                    )
                )

            # 5. Attribute Of connections
            if attribute_of_links:
                await self._retry(
                    lambda: self.neo4j_repo.execute_write(
                        attribute_of_query,
                        {"links": attribute_of_links, "tenant_id": self.tenant_id},
                    )
                )

            return len(hubs)
        except Exception as e:
            logger.warning(f"RDF Writer: event hub creation failed: {e}")
            return 0
