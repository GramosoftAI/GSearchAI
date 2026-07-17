import logging
from ..domain.pipeline_context import PipelineContext
from ..domain.business_object import ObjectState
from .postgres_writer import PostgresWriter
from .neo4j_writer import Neo4jWriter

logger = logging.getLogger(__name__)

class PersistenceCoordinator:
    """Coordinates staged persistence across backends."""
    def __init__(self, pg_writer: PostgresWriter, neo4j_writer: Neo4jWriter):
        self.pg_writer = pg_writer
        self.neo4j_writer = neo4j_writer
        
    async def run_async(self, context: PipelineContext) -> PipelineContext:
        # Only persist objects that are in the READY state
        objects_to_persist = [obj for obj in context.business_object_store.get_all() if obj.state == ObjectState.READY]
        
        if not objects_to_persist:
            context.log("Persistence Coordinator: No objects in READY state to persist.")
            return context
            
        try:
            # First write to Postgres (Authoritative)
            await self.pg_writer.write(context)
            
            # Then write to Neo4j (Graph Index)
            await self.neo4j_writer.write(context)
            
            # Update state
            for obj in objects_to_persist:
                obj.state = ObjectState.PERSISTED
                
            context.log(f"Successfully persisted {len(objects_to_persist)} BusinessObjects.")
        except Exception as e:
            logger.error(f"Persistence Coordinator failed: {e}")
            context.add_error(f"Persistence Error: {e}")
            
        return context
