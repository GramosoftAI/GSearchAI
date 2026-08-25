import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class EventHubWriter:
    """Handles Neo4j writes for Event-Hub Triplets (complex facts with 3+ participants or attributes)."""
    
    def __init__(self, tenant_id: str, neo4j_repo, retry_func):
        self.tenant_id = tenant_id
        self.neo4j_repo = neo4j_repo
        self._retry = retry_func

    async def write(self, all_events: List[Dict]) -> int:
        """Create EventHub nodes and their relations to Entities and Chunks."""
        if not all_events:
            return 0

        hubs = {}
        chunk_links = []
        participant_links = []
        occurred_on_links = []
        attribute_of_links = []
        
        date_attributes = {'DATE', 'TIME', 'OCCURRED_ON', 'WHEN', 'YEAR'}

        for item in all_events:
            chunk_id = item["chunk_id"]
            ev = item["event"]
            
            # Deduplicate/collect hubs
            hub_key = ev.name
            hubs[hub_key] = {
                "name": ev.name,
                "event_type": ev.event_type,
            }
            
            chunk_links.append({
                "chunk_id": chunk_id,
                "event_name": ev.name,
            })
            
            for p in ev.participants:
                participant_links.append({
                    "event_name": ev.name,
                    "entity_text": p.entity,
                    "entity_type": p.entity_type,
                    "role": p.role,
                })
                
            for a in ev.attributes:
                link = {
                    "event_name": ev.name,
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
        
        # Batch MERGE Participant connections
        participant_query = """
        WITH $links AS link_list
        UNWIND link_list AS l
        MATCH (e:Entity {tenant_id: $tenant_id, text: l.entity_text, type: l.entity_type})
        MATCH (hub:EventHub {tenant_id: $tenant_id, name: l.event_name})
        MERGE (e)-[:PARTICIPANT_IN {role: l.role, tenant_id: $tenant_id}]->(hub)
        RETURN count(*) as count
        """

        # Batch MERGE Occurred On (Dates) connections
        occurred_on_query = """
        WITH $links AS link_list
        UNWIND link_list AS l
        MATCH (e:Entity {tenant_id: $tenant_id, text: l.entity_text, type: l.entity_type})
        MATCH (hub:EventHub {tenant_id: $tenant_id, name: l.event_name})
        MERGE (e)-[:OCCURRED_ON {tenant_id: $tenant_id}]->(hub)
        RETURN count(*) as count
        """

        # Batch MERGE Attribute Of connections
        attribute_of_query = """
        WITH $links AS link_list
        UNWIND link_list AS l
        MATCH (e:Entity {tenant_id: $tenant_id, text: l.entity_text, type: l.entity_type})
        MATCH (hub:EventHub {tenant_id: $tenant_id, name: l.event_name})
        MERGE (e)-[:ATTRIBUTE_OF {attribute: l.attribute, tenant_id: $tenant_id}]->(hub)
        RETURN count(*) as count
        """

        try:
            # 1. Merge Hubs
            await self._retry(lambda: self.neo4j_repo.execute_write(hub_query, {"hubs": list(hubs.values()), "tenant_id": self.tenant_id}))
            
            # 2. Chunk connections
            if chunk_links:
                await self._retry(lambda: self.neo4j_repo.execute_write(chunk_query, {"links": chunk_links, "tenant_id": self.tenant_id}))
            
            # 3. Participant connections
            if participant_links:
                await self._retry(lambda: self.neo4j_repo.execute_write(participant_query, {"links": participant_links, "tenant_id": self.tenant_id}))
                
            # 4. Occurred On connections
            if occurred_on_links:
                await self._retry(lambda: self.neo4j_repo.execute_write(occurred_on_query, {"links": occurred_on_links, "tenant_id": self.tenant_id}))
                
            # 5. Attribute Of connections
            if attribute_of_links:
                await self._retry(lambda: self.neo4j_repo.execute_write(attribute_of_query, {"links": attribute_of_links, "tenant_id": self.tenant_id}))
                
            return len(hubs)
        except Exception as e:
            logger.warning(f" Event creation failed: {e}")
            return 0
