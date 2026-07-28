"""
Ontology Resolver - Embedding-based coreference resolution
Resolves variations of entity names (e.g., 'A. Einstein' -> 'Albert Einstein')
using vector similarity.
"""
import logging
from typing import List, Dict
from .neo4j_repository import Neo4jRepository
from .embeddings import EmbeddingGenerator

logger = logging.getLogger(__name__)

class OntologyResolver:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.neo4j_repo = Neo4jRepository(tenant_id)
        
    async def resolve_entities(self, unique_entities: List[Dict]) -> Dict[str, Dict]:
        """
        Takes a list of dicts: [{"text": "A. Einstein", "type": "PERSON"}, ...]
        Returns a mapping from original text to canonical entity info (text and embedding).
        """
        if not unique_entities:
            return {}
            
        # 1. Generate embeddings for the incoming entities
        texts_to_embed = [e["text"] for e in unique_entities]
        try:
            embeddings = await EmbeddingGenerator.generate_embeddings_batch(texts_to_embed)
        except Exception as e:
            logger.error(f"Failed to generate embeddings for ontology resolution: {e}")
            # Fallback to exact match (no embedding)
            return {e["text"]: {"text": e["text"], "embedding": []} for e in unique_entities}
            
        mapping = {}
        for i, ent in enumerate(unique_entities):
            emb = embeddings[i] if embeddings[i] else []
            mapping[ent["text"]] = {"text": ent["text"], "embedding": emb}

        # Enterprise Performance Optimization: Limit Neo4j vector similarity scan
        # to top 60 relevant entity types (PERSON, ORGANIZATION, CONCEPT) to prevent
        # O(N*M) Cartesian similarity scans in Cypher when ingesting large documents.
        entities_for_neo4j = []
        for i, ent in enumerate(unique_entities):
            emb = embeddings[i] if embeddings[i] else []
            if emb and ent.get("type", "").upper() in ("PERSON", "ORGANIZATION", "CONCEPT"):
                entities_for_neo4j.append({
                    "text": ent["text"],
                    "type": ent["type"],
                    "embedding": emb
                })
        entities_for_neo4j = entities_for_neo4j[:60]
        if not entities_for_neo4j:
            return mapping

        # 2. Query Neo4j for matches using cosine similarity > 0.92
        # We find existing TripletEntities of the same type in the same tenant
        query = """
        UNWIND $entities AS ent
        MATCH (e:TripletEntity {tenant_id: $tenant_id, type: ent.type})
        WHERE e.embedding IS NOT NULL AND size(e.embedding) > 0 AND size(ent.embedding) > 0
        WITH ent, e, vector.similarity.cosine(ent.embedding, e.embedding) AS sim
        WHERE sim > 0.92
        // Sort by similarity to get the best match
        WITH ent.text AS original, e.text AS canonical, e.embedding AS canonical_emb, sim
        ORDER BY sim DESC
        WITH original, collect({text: canonical, embedding: canonical_emb})[0] AS best_match
        RETURN original, best_match.text AS canonical_text, best_match.embedding AS canonical_emb
        """
        
        try:
            import asyncio
            results = await asyncio.wait_for(
                self.neo4j_repo.execute_read(
                    query,
                    {"entities": entities_for_neo4j, "tenant_id": self.tenant_id}
                ),
                timeout=15.0
            )
            
            resolved_count = 0
            for r in results:
                original = r["original"]
                canonical_text = r["canonical_text"]
                if original != canonical_text:
                    mapping[original] = {
                        "text": canonical_text,
                        "embedding": r["canonical_emb"]
                    }
                    resolved_count += 1
                    
            if resolved_count > 0:
                logger.info(f" Ontology Grounding resolved {resolved_count} coreferences.")
                
            return mapping
            
        except Exception as e:
            logger.warning(f"Ontology resolution query skipped/timed out: {e}")
            return mapping
