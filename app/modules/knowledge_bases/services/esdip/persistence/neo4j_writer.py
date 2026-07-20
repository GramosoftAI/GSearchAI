import re
import logging
from app.core.neo4j_repository import Neo4jRepository
from app.core.neo4j_retry import retry_neo4j_operation
from ..domain.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

class Neo4jWriter:
    def __init__(self, neo4j_repo: Neo4jRepository):
        self.neo4j_repo = neo4j_repo
        
    async def write(self, context: PipelineContext) -> PipelineContext:
        objects = [obj for obj in context.business_object_store.get_all() if not obj.state.value == "QUARANTINED"]
        total_chunks = len(objects)
        
        if total_chunks == 0 or total_chunks > 100000:
            if total_chunks > 100000:
                logger.warning(f"Skipping Neo4j graph generation ({total_chunks} rows > 100k limit).")
            return context
            
        logger.info(f"Generating Neo4j Graph Entities for {total_chunks} objects...")
        entities_created_set = set()
        total_relationships = 0
        
        for obj in objects:
            clean_primary_label = re.sub(r"[^a-zA-Z0-9_]", "", obj.entity_type.upper())
            
            # Merge Primary Entity
            primary_merge_query = f"""
            MERGE (e:Entity {clean_primary_label.join([':', ''])} {{tenant_id: $tenant_id, text: $id_val, type: $type}})
            ON CREATE SET e.id = randomUUID(), e.created_at = timestamp()
            SET e.properties = $properties
            RETURN e.id as id
            """
            await retry_neo4j_operation(lambda: self.neo4j_repo.execute_write(
                primary_merge_query,
                {
                    "tenant_id": context.tenant_id,
                    "id_val": obj.id,
                    "type": obj.entity_type,
                    "properties": {str(k): str(v) for k, v in obj.attributes.items()}
                }
            ))
            entities_created_set.add(f"{obj.id}|{obj.entity_type}")
            
            # Merge Targets and Relationships
            for rel in obj.relationships:
                clean_tgt_label = re.sub(r"[^a-zA-Z0-9_]", "", rel.target_type.upper())
                clean_rel_type = re.sub(r"[^a-zA-Z0-9_]", "", rel.predicate.upper())
                
                target_merge_query = f"""
                MERGE (tgt:Entity {clean_tgt_label.join([':', ''])} {{tenant_id: $tenant_id, text: $tgt_val, type: $type}})
                ON CREATE SET tgt.id = randomUUID(), tgt.created_at = timestamp()
                RETURN tgt.id as id
                """
                await retry_neo4j_operation(lambda: self.neo4j_repo.execute_write(
                    target_merge_query,
                    {
                        "tenant_id": context.tenant_id,
                        "tgt_val": rel.target_id,
                        "type": rel.target_type
                    }
                ))
                entities_created_set.add(f"{rel.target_id}|{rel.target_type}")
                
                edge_create_query = f"""
                MATCH (src:Entity {{tenant_id: $tenant_id, text: $src_val, type: $src_type}})
                MATCH (tgt:Entity {{tenant_id: $tenant_id, text: $tgt_val, type: $tgt_type}})
                MERGE (src)-[r:{clean_rel_type} {{tenant_id: $tenant_id}}]->(tgt)
                """
                await retry_neo4j_operation(lambda: self.neo4j_repo.execute_write(
                    edge_create_query,
                    {
                        "tenant_id": context.tenant_id,
                        "src_val": obj.id,
                        "src_type": obj.entity_type,
                        "tgt_val": rel.target_id,
                        "tgt_type": rel.target_type
                    }
                ))
                total_relationships += 1
                
        context.log(f"Graph generation complete: {len(entities_created_set)} entities, {total_relationships} relationships.")
        return context
