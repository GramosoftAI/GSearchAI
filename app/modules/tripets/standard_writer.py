import uuid
import logging
from typing import List, Dict

from app.core.embeddings import EmbeddingGenerator
from .entity_merger import EntityMerger

logger = logging.getLogger(__name__)

class StandardTripletWriter:
    """Handles Neo4j writes for Standard Triplets (2-party facts)."""
    
    def __init__(self, tenant_id: str, neo4j_repo, retry_func):
        self.tenant_id = tenant_id
        self.neo4j_repo = neo4j_repo
        self._retry = retry_func
        self.entity_merger = EntityMerger(tenant_id, neo4j_repo, retry_func)

    async def write(self, all_triplets: List[Dict], canonical_entities_to_merge: Dict) -> Dict:
        """
        Writes standard triplets to the database.
        Includes merging entities, creating relationships, and creating triplet nodes.
        """
        if not all_triplets:
            return {"relationships_created": 0, "triplets_created": 0, "entities_created": 0}

        entities_created = await self.entity_merger.merge_entities(list(canonical_entities_to_merge.values()))
        relationships_created = await self._create_relationships(all_triplets)
        triplets_created = await self._create_triplet_nodes(all_triplets)
        
        return {
            "entities_created": entities_created,
            "relationships_created": relationships_created,
            "triplets_created": triplets_created
        }

    async def _create_relationships(self, all_triplets: List[Dict]) -> int:
        """CREATE typed relationship edges between entities."""
        rel_data = []
        for item in all_triplets:
            t = item["triplet"]
            rel_data.append({
                "subject_text": t.subject,
                "subject_type": t.subject_type,
                "predicate": t.name,
                "object_text": t.object,
                "object_type": t.object_type,
                "chunk_id": item["chunk_id"],
                "confidence": t.confidence,
            })

        if not rel_data:
            return 0

        query = """
        WITH $relationships AS rel_list
        UNWIND rel_list AS r
        MATCH (s:Entity {tenant_id: $tenant_id, text: r.subject_text, type: r.subject_type})
        MATCH (o:Entity {tenant_id: $tenant_id, text: r.object_text, type: r.object_type})
        MATCH (c:Chunk {id: r.chunk_id, tenant_id: $tenant_id})
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
            logger.warning(f" Relationship creation failed: {e}")
            return 0

    async def _create_triplet_nodes(self, all_triplets: List[Dict]) -> int:
        """CREATE Triplet nodes with embeddings and link to source chunks."""
        # Generate embeddings for triplet text strings
        triplet_texts = [item["triplet"].text for item in all_triplets]

        try:
            embeddings = await EmbeddingGenerator.generate_embeddings_batch(
                triplet_texts
            )
        except Exception as e:
            logger.warning(f" Triplet embedding generation failed: {e}")
            embeddings = [None] * len(triplet_texts)

        node_data = []
        for i, item in enumerate(all_triplets):
            t = item["triplet"]
            node_data.append({
                "triplet_id": str(uuid.uuid4()),
                "text": t.text,
                "subject": t.subject,
                "predicate": t.name,
                "object": t.object,
                "chunk_id": item["chunk_id"],
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
            logger.warning(f" Triplet node creation failed: {e}")
            return 0
