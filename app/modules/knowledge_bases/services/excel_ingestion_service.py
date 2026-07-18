"""
Excel/CSV Ingestion Service - High-Intelligence Ontological Graph Builder
(Upgraded to ESDIP Architecture - Blueprint v3)
"""

import io
import logging
from typing import Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.ontology.service import OntologyService
from app.core.neo4j_repository import Neo4jRepository

from .esdip.domain.pipeline_context import PipelineContext
from .esdip.orchestration.pipeline_manager import EngineRegistry, PipelineManager

from .esdip.engines.workbook_discovery_engine import WorkbookDiscoveryEngine
from .esdip.engines.table_detection_engine import TableDetectionEngine
from .esdip.engines.sheet_classifier import SheetClassifier
from .esdip.engines.header_resolver import HeaderResolver
from .esdip.engines.schema_engine import SchemaEngine
from .esdip.engines.business_object_engine import BusinessObjectEngine
from .esdip.engines.relationship_engine import RelationshipEngine

from .esdip.governance.validation_engine import ValidationEngine
from .esdip.governance.confidence_evaluator import ConfidenceEvaluator
from .esdip.governance.policy_engine import PolicyEngine
from .esdip.governance.quarantine_manager import QuarantineManager

from .esdip.persistence.postgres_writer import PostgresWriter
from .esdip.persistence.neo4j_writer import Neo4jWriter
from .esdip.persistence.persistence_coordinator import PersistenceCoordinator

from .esdip.telemetry.events import EventEmitter

logger = logging.getLogger(__name__)

class ExcelIngestionService:
    """
    Adapter bridging the HTTP request to the ESDIP Engine Framework.
    """
    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = str(tenant_id)
        self.neo4j_repo = Neo4jRepository(self.tenant_id)
        
    async def ingest_file(
        self,
        kb_id: str,
        file_bytes: bytes,
        filename: str,
        mime_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Main entry point for ESDIP Excel/CSV ingestion."""
        logger.info(f" Ingesting structured file '{filename}' for KB {kb_id} under tenant {self.tenant_id} via ESDIP v3")
        
        context = PipelineContext(
            tenant_id=self.tenant_id,
            kb_id=kb_id,
            file_bytes=file_bytes,
            filename=filename
        )
        
        EventEmitter.emit("PipelineStarted", context)
        
        registry = EngineRegistry()
        # Discovery Layer
        registry.register(WorkbookDiscoveryEngine())
        registry.register(TableDetectionEngine())
        
        # Normalization Layer
        registry.register(SheetClassifier())
        registry.register(HeaderResolver())
        
        # Inference Layer
        registry.register(SchemaEngine())
        registry.register(BusinessObjectEngine())
        registry.register(RelationshipEngine())
        
        # Governance Layer
        registry.register(ValidationEngine())
        registry.register(ConfidenceEvaluator())
        registry.register(PolicyEngine())
        registry.register(QuarantineManager())
        
        manager = PipelineManager(registry)
        
        try:
            context = manager.execute(context)
        except Exception as e:
            logger.error(f"ESDIP Pipeline failed: {e}")
            EventEmitter.emit("PipelineFailed", context, {"error": str(e)})
            return {"success": False, "error": f"Failed to parse file: {str(e)}"}
            
        EventEmitter.emit("PipelineProcessingCompleted", context, {"objects_extracted": len(context.business_object_store.get_all())})
        
        # Persistence Layer
        try:
            pg_writer = PostgresWriter(self.db)
            neo4j_writer = Neo4jWriter(self.neo4j_repo)
            coordinator = PersistenceCoordinator(pg_writer, neo4j_writer)
            
            context = await coordinator.run_async(context)
            
            EventEmitter.emit("PersistenceCompleted", context)
        except Exception as e:
            logger.error(f"ESDIP Persistence failed: {e}")
            EventEmitter.emit("PipelineFailed", context, {"error": f"Persistence Error: {e}"})
            return {"success": False, "error": f"Persistence failed: {str(e)}"}
            
        EventEmitter.emit("PipelineCompleted", context)
        
        return {
            "success": True,
            "data": {
                "kb_id": kb_id,
                "chunks_created": len([o for o in context.business_object_store.get_all() if o.state.value == "PERSISTED"]),
                "logs": context.logs,
                "warnings": context.warnings
            }
        }
