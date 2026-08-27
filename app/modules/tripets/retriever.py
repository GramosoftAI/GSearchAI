import logging
from typing import List, Dict

from app.core.embeddings import EmbeddingGenerator

logger = logging.getLogger(__name__)

class TripletRetriever:
    """
    Retrieve relevant triplets for a query using semantic search.

    INTEGRATION: Called as an optional enrichment step in RAG pipeline.
    Does NOT replace existing retrieval  ADDS triplet context alongside chunks.

    FLOW:
        Query  Embed  Search Triplet embeddings  Get relevant (S,P,O)
               Expand to neighboring entities  Format as context
    """

    def __init__(self, tenant_id: str):
        from app.core.neo4j_repository import Neo4jRepository
        self.tenant_id = tenant_id
        self.neo4j_repo = Neo4jRepository(tenant_id)

    async def search_triplets(
        self,
        query_embedding: List[float],
        kb_ids: List[str],
        top_k: int = 20,
        target_sections: List[str] = None,
    ) -> List[Dict]:
        """
        Search triplets by embedding similarity.

        Args:
            query_embedding: Query embedding vector
            kb_id: Knowledge Base UUID (scope search)
            top_k: Max triplets to return

        Returns:
            List of triplet dicts with text, subject, predicate, object, score
        """
        import time
        trace_start = time.time()
        logger.info(f"[TRACE_E2E] [ENTRY] TripletRetriever.search_triplets - Input: KB {kb_ids}")
        # Get triplets linked to chunks in this KB OR memory-based triplets (not linked to KB)
        query = """
        // Part 1: KB-linked triplets
        MATCH (kb:KnowledgeBase)
        WHERE kb.id IN $kb_ids AND kb.tenant_id = $tenant_id
        MATCH (kb)-[:HAS_CHUNK]->(c:Chunk)-[:HAS_TRIPLET]->(t:Triplet {tenant_id: $tenant_id})
        WHERE t.embedding IS NOT NULL AND size(t.embedding) = $dimension
        """

        if target_sections:
            query += " AND c.section IN $target_sections "

        query += """
        RETURN t.id as id, t.text as text, t.subject as subject,
               t.predicate as predicate, t.object as object,
               t.embedding as embedding, t.chunk_id as chunk_id
        
        UNION
        
        // Part 2: Floating memory-based triplets (e.g., from chat consolidation)
        MATCH (t:Triplet {tenant_id: $tenant_id})
        WHERE t.embedding IS NOT NULL AND size(t.embedding) = $dimension
        AND NOT (t)<-[:HAS_TRIPLET]-(:Chunk)-[:HAS_CHUNK]-(:KnowledgeBase)
        RETURN t.id as id, t.text as text, t.subject as subject,
               t.predicate as predicate, t.object as object,
               t.embedding as embedding, t.chunk_id as chunk_id
        
        LIMIT 500
        """ 

        try:
            results = await self.neo4j_repo.execute_read(
                query,
                {
                    "kb_ids": kb_ids,
                    "tenant_id": self.tenant_id,
                    "dimension": EmbeddingGenerator.get_dimension(),
                    "target_sections": target_sections if target_sections else []
                },
            )

            if not results:
                return []

            # Score by cosine similarity
            scored_triplets = []
            for r in results:
                similarity = EmbeddingGenerator.cosine_similarity(
                    query_embedding, r["embedding"]
                )
                scored_triplets.append({
                    "id": r["id"],
                    "text": r["text"],
                    "subject": r["subject"],
                    "predicate": r["predicate"],
                    "object": r["object"],
                    "chunk_id": r["chunk_id"],
                    "similarity": similarity,
                })

            # Sort by similarity, return top-k
            scored_triplets.sort(key=lambda x: x["similarity"], reverse=True)
            final_triplets = scored_triplets[:top_k]
            latency = time.time() - trace_start
            logger.info(f"[TRACE_E2E] [EXIT] TripletRetriever.search_triplets - Output: {len(final_triplets)} triplets - Latency: {latency:.2f}s")
            return final_triplets

        except Exception as e:
            latency = time.time() - trace_start
            logger.error(f"[TRACE_E2E] [EXIT] TripletRetriever.search_triplets - Output: ERROR - Latency: {latency:.2f}s - {e}")
            logger.warning(f" Triplet search failed: {e}")
            return []

    async def get_entity_neighborhood(
        self,
        entity_texts: List[str],
        max_hops: int = 1,
    ) -> List[Dict]:
        """
        Get triplet relationships around specific entities.

        Args:
            entity_texts: Entity names to expand
            max_hops: Relationship hops (1 = direct connections)

        Returns:
            List of relationship dicts
        """
        query = """
        WITH $entities AS entity_list
        UNWIND entity_list AS ent_text
        MATCH (e:Entity {tenant_id: $tenant_id, text: ent_text})
        MATCH (e)-[r:RELATES_TO]->(target:Entity {tenant_id: $tenant_id})
        RETURN e.text as source, r.predicate as predicate,
               target.text as target, r.confidence as confidence
        UNION
        MATCH (source:Entity {tenant_id: $tenant_id})-[r:RELATES_TO]->(e:Entity {tenant_id: $tenant_id})
        WHERE e.text IN $entities
        RETURN source.text as source, r.predicate as predicate,
               e.text as target, r.confidence as confidence
        """

        try:
            results = await self.neo4j_repo.execute_read(
                query,
                {"entities": entity_texts, "tenant_id": self.tenant_id},
            )
            return [dict(r) for r in results] if results else []
        except Exception as e:
            logger.warning(f" Entity neighborhood search failed: {e}")
            return []

    def format_triplets_as_context(self, triplets: List[Dict]) -> str:
        """Format triplets as readable context for LLM injection, grouping by event hubs."""
        if not triplets:
            return ""

        hubs = {}
        simple_relations = []

        for t in triplets:
            pred = t["predicate"].upper()
            subj = t["subject"]
            obj = t["object"]
            score = t.get("similarity", 0)

            # Check if this is a participant link to a hub
            if "PARTICIPATED_IN_ROLE_" in pred:
                role = pred.replace("PARTICIPATED_IN_ROLE_", "")
                hub_name = obj
                if hub_name not in hubs:
                    hubs[hub_name] = {"participants": [], "attributes": [], "max_score": score}
                hubs[hub_name]["participants"].append((subj, role))
                hubs[hub_name]["max_score"] = max(hubs[hub_name]["max_score"], score)
            
            # Check if this is an attribute link from a hub
            elif any(indicator in pred for indicator in ["DATE", "AMOUNT", "HAS_DATE", "HAS_AMOUNT", "LOCATION", "STATUS", "VALUE"]):
                hub_name = subj
                if hub_name not in hubs:
                    hubs[hub_name] = {"participants": [], "attributes": [], "max_score": score}
                hubs[hub_name]["attributes"].append((pred.lower(), obj))
                hubs[hub_name]["max_score"] = max(hubs[hub_name]["max_score"], score)
            
            else:
                simple_relations.append(t)

        lines = ["KNOWLEDGE GRAPH RELATIONSHIPS:"]

        # 1. Output Grouped Event Hubs
        if hubs:
            lines.append("   Grouped Events:")
            for hub_name, info in hubs.items():
                lines.append(f"     * Event: {hub_name} (relevance: {info['max_score']:.2f})")
                if info["participants"]:
                    parts_str = ", ".join([f"{entity} ({role.lower()})" for entity, role in info["participants"]])
                    lines.append(f"       - Participants: {parts_str}")
                if info["attributes"]:
                    attrs_str = ", ".join([f"{attr}: {val}" for attr, val in info["attributes"]])
                    lines.append(f"       - Details: {attrs_str}")

        # 2. Output Simple Binary Relationships
        if simple_relations:
            if hubs:
                lines.append("   Direct Relationships:")
            for t in simple_relations:
                lines.append(
                    f"     - {t['subject']} [{t['predicate']}] {t['object']} "
                    f"(relevance: {t.get('similarity', 0):.2f})"
                )

        return "\n".join(lines)
