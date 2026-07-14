import logging
from typing import Optional, Dict, Any, List
from app.core.neo4j_repository import Neo4jRepository
from app.core.entity_extraction import EntityExtractor

logger = logging.getLogger(__name__)

class IdentifierResolver:
    """
    Dynamically resolves structured identifiers by querying the graph and applying normalizations.
    """
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.repo = Neo4jRepository(tenant_id)
        
    async def resolve_identifier(self, query: str) -> Optional[str]:
        """
        Extracts potential identifiers from the query and attempts to resolve them against the graph.
        """
        # Step 1: Extract potential identifiers using entity extraction
        # Since we just want to parse the query quickly, we use the regex engine.
        entities = EntityExtractor._extract_entities_regex(query, entity_types=["STRUCTURED_IDENTIFIER"])
        
        if not entities:
            return None
            
        # Get the highest confidence structured identifier
        best_entity = entities[0]
        normalized_id = best_entity.text
        
        # Step 2: Query Graph for exact match or alias
        # We look for a TripletEntity or Structured Identifier node
        cypher = """
        MATCH (n:Entity {tenant_id: $tenant_id})
        WHERE n.type = 'STRUCTURED_IDENTIFIER' AND toLower(n.text) = $identifier
        RETURN n.text AS resolved_id
        """
        
        try:
            results = await self.repo.execute_read(cypher, {"identifier": normalized_id.lower()})
            if results:
                logger.info(f"Resolved identifier '{normalized_id}' in graph.")
                return results[0]["resolved_id"]
            
            # If not in graph, we still return the normalized ID so RAG can attempt a fallback
            logger.info(f"Extracted identifier '{normalized_id}' (not verified in graph).")
            return normalized_id
            
        except Exception as e:
            logger.error(f"Failed to resolve identifier in graph: {e}")
            return normalized_id
