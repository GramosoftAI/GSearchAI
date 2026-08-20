import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class EntityMerger:
    """Helper class to merge unique entity nodes in Neo4j (prevents duplicates)."""
    
    def __init__(self, tenant_id: str, neo4j_repo, retry_func):
        self.tenant_id = tenant_id
        self.neo4j_repo = neo4j_repo
        self._retry = retry_func

    async def merge_entities(self, entity_list: List[Dict]) -> int:
        """MERGE unique entity nodes (prevents duplicates)."""
        if not entity_list:
            return 0

        query = """
        WITH $entities AS entity_list
        UNWIND entity_list AS e
        MERGE (ent:Entity {
            tenant_id: $tenant_id,
            text: e.text,
            type: e.type
        })
        ON CREATE SET 
            ent.id = randomUUID(), 
            ent.created_at = timestamp(),
            ent.uri = e.uri
        SET ent.embedding = CASE WHEN e.embedding IS NOT NULL AND size(e.embedding) > 0 THEN e.embedding ELSE ent.embedding END,
            ent.uri = CASE WHEN ent.uri IS NULL THEN e.uri ELSE ent.uri END
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
            logger.warning(f" Entity MERGE failed: {e}")
            return 0
