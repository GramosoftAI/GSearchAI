"""Database Knowledgebase Service Orchestration Layer

Coordinates connection validation, credential encryption, deterministic schema
introspection, canonical snapshot persistence, and tenant-scoped retrieval.
"""

import asyncio
import logging
import re
import time
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid
import sqlglot
from sqlglot import exp

from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.repository import DatabaseKnowledgebaseRepository
from ..models.database_knowledgebase import DatabaseKnowledgebase, DatabaseSchemaSnapshot
from ..schemas.connection import DatabaseConnectionConfig, ConnectionTestResult
from ..schemas.canonical import DatabaseSchema
from ..schemas.api import (
    DatabaseKnowledgebaseCreate,
    DatabaseKnowledgebaseUpdate,
    DatabaseKnowledgebaseResponse,
    DatabaseSchemaResponse,
    SchemaSnapshotResponse,
)
from ..security.secrets import SecretManager, get_secret_manager
from ..security.sanitizer import mask_connection_string, sanitize_error_message
from ..schema.introspector import DatabaseIntrospector
from ..schema.indexer import SchemaIndexer
from ..retrieval.retriever import (
    SchemaRetriever,
    SchemaRetrievalRequest,
    SchemaRetrievalResult,
)
from ..connectors.factory import ConnectorFactory
from ..planning.planner import QueryPlanner
from ..planning.models import QueryPlanIR
from ..sql_generator.repair import SQLRepairEngine, ValidatedCandidateSQL
from ..execution import (
    CanonicalQueryResult,
    ExecutionConfig,
    ExecutionPolicyEngine,
    ReadOnlyDatabaseExecutor,
)
from ..answering import DatabaseAnswerSynthesisService, GroundedDatabaseAnswer
from ..observability import PipelineTracer, DatabaseKnowledgebaseMetrics, AuditSanitizer
from ..schemas.audit_api import AuditLogFilterParams, AuditLogListResponse, AuditLogEntryResponse
from ..schemas.health import DatabaseKnowledgebaseHealth
from ..exceptions.errors import (
    DatabaseKnowledgebaseError,
    TenantMismatchError,
    SchemaIntrospectionError,
    SQLValidationError,
    DatabaseTimeoutError,
    DatabaseKnowledgebaseNotFoundError,
)
from ..execution.errors import ExecutionPolicyViolation
from ..streaming.models import DatabaseStreamEventType
from ..streaming.sink import DatabasePipelineEventSink
from ..streaming.sanitizer import StreamingSanitizer
from ..sql_security.policy import SQLSecurityPolicyEngine
from ..semantic.models import VerifiedQueryMemoryRecord
from ..semantic.registry import SemanticModelRegistry
from ..semantic.metrics import CanonicalMetricRegistry
from ..semantic.relationships import SemanticRelationshipGraph
from ..semantic.business_rules import BusinessRuleRegistry
from ..semantic.memory import VerifiedQueryMemory
from ..semantic.profiling import ValueProfiler
from ..semantic.resolver import SemanticResolver, SemanticResolutionResult

logger = logging.getLogger(__name__)


class DatabaseKnowledgebaseService:
    """
    Main service orchestrating Database Knowledgebase lifecycle.
    """

    # Phase 6 Shared Semantic Registries
    _semantic_model_registry = SemanticModelRegistry()
    _metric_registry = CanonicalMetricRegistry()
    _relationship_graph = SemanticRelationshipGraph()
    _business_rules = BusinessRuleRegistry()
    _query_memory = VerifiedQueryMemory()
    _value_profiler = ValueProfiler()

    @property
    def semantic_resolver(self) -> SemanticResolver:
        return SemanticResolver(
            semantic_registry=self._semantic_model_registry,
            metric_registry=self._metric_registry,
            relationship_graph=self._relationship_graph,
            business_rules=self._business_rules,
            query_memory=self._query_memory,
        )

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str,
        secret_manager: Optional[SecretManager] = None,
    ):
        self.db = db
        self.tenant_id = tenant_id
        self.repo = DatabaseKnowledgebaseRepository(db, tenant_id)
        self.secrets = secret_manager or get_secret_manager()

    def _entity_to_response(
        self, entity: DatabaseKnowledgebase, config: Optional[DatabaseConnectionConfig] = None
    ) -> DatabaseKnowledgebaseResponse:
        """Helper to build safe response model with masked DSN."""
        masked_dsn = None
        if config:
            masked_dsn = config.masked_dsn
        elif entity.encrypted_credentials:
            try:
                decrypted = self.secrets.decrypt_credentials(entity.encrypted_credentials)
                masked_dsn = decrypted.masked_dsn
            except Exception:
                masked_dsn = f"{entity.database_type}://***"

        return DatabaseKnowledgebaseResponse(
            id=entity.id,
            tenant_id=entity.tenant_id,
            user_id=entity.user_id,
            agent_id=entity.agent_id,
            name=entity.name,
            description=entity.description,
            database_type=entity.database_type,
            status=entity.status,
            schema_version=entity.schema_version,
            masked_dsn=masked_dsn,
            last_tested_at=entity.last_tested_at,
            last_introspected_at=entity.last_introspected_at,
            last_error=entity.last_error,
            is_active=entity.is_active,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    async def create_database_knowledgebase(
        self, user_id: uuid.UUID, data: DatabaseKnowledgebaseCreate
    ) -> DatabaseKnowledgebaseResponse:
        """Create and securely persist a new DatabaseKnowledgebase."""
        logger.info(
            f"Creating DatabaseKnowledgebase '{data.name}' for tenant={self.tenant_id}, "
            f"target={data.connection.masked_dsn}"
        )
        
        # 1. Encrypt credentials at rest
        encrypted_creds = self.secrets.encrypt_credentials(data.connection)

        # 2. Persist in database
        entity = await self.repo.create_db_kb(
            user_id=user_id,
            name=data.name,
            database_type=data.connection.db_type.value,
            encrypted_credentials=encrypted_creds,
            description=data.description,
            agent_id=data.agent_id,
        )

        return self._entity_to_response(entity, config=data.connection)

    async def get_database_knowledgebase(
        self, kb_id: uuid.UUID
    ) -> DatabaseKnowledgebaseResponse:
        """Retrieve a specific database knowledgebase for current tenant."""
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")
        return self._entity_to_response(entity)

    async def list_database_knowledgebases(
        self, skip: int = 0, limit: int = 50, agent_id: Optional[uuid.UUID] = None
    ) -> List[DatabaseKnowledgebaseResponse]:
        """List all active database knowledgebases for current tenant."""
        entities = await self.repo.list_kbs(skip=skip, limit=limit, agent_id=agent_id)
        return [self._entity_to_response(e) for e in entities]

    async def update_database_knowledgebase(
        self, kb_id: uuid.UUID, data: DatabaseKnowledgebaseUpdate
    ) -> DatabaseKnowledgebaseResponse:
        """Update metadata or credentials for an existing database knowledgebase."""
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")

        encrypted_creds = None
        if data.connection:
            encrypted_creds = self.secrets.encrypt_credentials(data.connection)

        updated_entity = await self.repo.update_db_kb(
            kb_id=kb_id,
            name=data.name,
            description=data.description,
            agent_id=data.agent_id,
            encrypted_credentials=encrypted_creds,
        )
        return self._entity_to_response(updated_entity, config=data.connection)

    async def delete_database_knowledgebase(self, kb_id: uuid.UUID) -> bool:
        """Soft-delete a database knowledgebase."""
        deleted = await self.repo.delete_db_kb(kb_id, soft=True)
        if not deleted:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")
        return True

    # ============= CONNECTION TESTING =============

    async def test_connection(self, kb_id: uuid.UUID) -> ConnectionTestResult:
        """Test connection against a stored database knowledgebase."""
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")

        # Decrypt stored credentials
        config = self.secrets.decrypt_credentials(entity.encrypted_credentials)
        connector = ConnectorFactory.create_connector(config)

        try:
            result = await connector.test_connection()
            status_val = "tested" if result.success else "error"
            await self.repo.update_db_kb(
                kb_id=kb_id,
                status=status_val,
                last_tested_at=datetime.utcnow(),
                last_error=result.error_message if not result.success else None,
            )
            return result
        finally:
            await connector.close()

    async def test_connection_adhoc(
        self, config: DatabaseConnectionConfig
    ) -> ConnectionTestResult:
        """Test connection against unpersisted configuration (e.g. from UI modal)."""
        connector = ConnectorFactory.create_connector(config)
        try:
            return await connector.test_connection()
        finally:
            await connector.close()

    # ============= SCHEMA INTROSPECTION & SNAPSHOTS =============

    async def introspect_and_snapshot_schema(
        self, kb_id: uuid.UUID, schemas: Optional[List[str]] = None
    ) -> DatabaseSchemaResponse:
        """
        Run deterministic schema introspection, compute fingerprint, and save snapshot.
        """
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")

        # Decrypt connection config
        config = self.secrets.decrypt_credentials(entity.encrypted_credentials)

        try:
            # 1. Run deterministic introspection
            canonical_schema = await DatabaseIntrospector.introspect(config=config, schemas=schemas)

            # 2. Persist Schema Snapshot
            schema_json = canonical_schema.model_dump(mode="json")
            snapshot = await self.repo.save_schema_snapshot(
                db_kb_id=kb_id,
                schema_version=canonical_schema.fingerprint,
                schema_data=schema_json,
                table_count=canonical_schema.summary.get("table_count", len(canonical_schema.all_tables)),
                column_count=canonical_schema.summary.get("column_count", 0),
                relationship_count=canonical_schema.summary.get("relationship_count", 0),
            )

            # 3. Trigger Schema Indexing (Batch vector embeddings)
            try:
                indexer = SchemaIndexer(session=self.db, tenant_id=uuid.UUID(str(self.tenant_id)))
                await indexer.index_schema(
                    kb_id=kb_id,
                    schema=canonical_schema,
                    database_description=entity.description or "",
                )
            except Exception as index_err:
                logger.warning(f"Non-fatal warning: background schema indexing encountered error: {index_err}")

            # 4. Update DatabaseKnowledgebase status and version
            old_schema_version = entity.schema_version
            await self.repo.update_db_kb(
                kb_id=kb_id,
                status="indexed",
                schema_version=canonical_schema.fingerprint,
                last_introspected_at=datetime.utcnow(),
                last_error=None,
            )

            # 4.1 Build and Sync Universal Semantic Model (Phases C-K)
            try:
                from ..semantic.semantic_model_builder import SemanticModelBuilder
                builder = SemanticModelBuilder()
                tenant_uuid = uuid.UUID(str(self.tenant_id)) if isinstance(self.tenant_id, str) else self.tenant_id
                profile = builder.build_profile_from_canonical_schema(
                    schema=canonical_schema,
                    tenant_id=tenant_uuid,
                    knowledgebase_id=kb_id,
                    database_name=entity.name,
                )
                builder.sync_to_legacy_registries(
                    profile=profile,
                    semantic_registry=self._semantic_model_registry,
                    metric_registry=self._metric_registry,
                    relationship_graph=self._relationship_graph,
                )
            except Exception as sm_exc:
                logger.warning(f"Universal semantic model build warning: {sm_exc}")

            # 4.2 Enqueue Offline Semantic Glossary Enrichment & Schema Drift Handling (Phases 3, 5, 7)
            try:
                from ..semantic_glossary.enrichment import GlossaryEnrichmentService
                from ..semantic_glossary.drift_handler import SchemaDriftHandler

                is_drift = bool(old_schema_version and old_schema_version != canonical_schema.fingerprint)
                enrichment_service = GlossaryEnrichmentService()
                tenant_uuid = uuid.UUID(str(self.tenant_id)) if isinstance(self.tenant_id, str) else self.tenant_id

                # Resolve operator tenant overrides (antonym_overrides, canonical_overrides)
                # from entity metadata or connection extra_params
                tenant_meta: Dict[str, Any] = {}
                if hasattr(entity, "metadata") and isinstance(entity.metadata, dict):
                    tenant_meta.update(entity.metadata)
                elif hasattr(entity, "tenant_metadata") and isinstance(entity.tenant_metadata, dict):
                    tenant_meta.update(entity.tenant_metadata)
                if config and hasattr(config, "extra_params") and isinstance(config.extra_params, dict):
                    tenant_meta.update(config.extra_params)

                canonical_overrides = tenant_meta.get("canonical_overrides")
                raw_antonym_overrides = tenant_meta.get("antonym_overrides") or tenant_meta.get("non_interchangeable_overrides")
                antonym_overrides: Optional[Set[Tuple[str, str]]] = None
                if raw_antonym_overrides:
                    antonym_overrides = set()
                    for item in raw_antonym_overrides:
                        if isinstance(item, (list, tuple)) and len(item) == 2:
                            antonym_overrides.add((str(item[0]).strip().lower(), str(item[1]).strip().lower()))

                if is_drift:
                    logger.info(
                        f"Schema drift detected for KB {kb_id} "
                        f"(old={old_schema_version[:8]}, new={canonical_schema.fingerprint[:8]}). "
                        f"Invoking SchemaDriftHandler with {len(antonym_overrides or ())} antonym overrides."
                    )
                    old_snapshot = await self.repo.get_snapshot_by_version(kb_id, old_schema_version)
                    if old_snapshot:
                        old_schema = DatabaseSchema.model_validate(old_snapshot.schema_data)
                        await SchemaDriftHandler.handle_drift_async(
                            session=self.db,
                            tenant_id=str(self.tenant_id),
                            kb_id=kb_id,
                            old_schema=old_schema,
                            new_schema=canonical_schema,
                            canonical_overrides=canonical_overrides,
                            antonym_overrides=antonym_overrides,
                            non_interchangeable_overrides=antonym_overrides,
                            enrichment_service=enrichment_service,
                        )
                    else:
                        asyncio.create_task(
                            enrichment_service.enrich_schema_async(
                                session=self.db,
                                tenant_id=tenant_uuid,
                                kb_id=kb_id,
                                schema=canonical_schema,
                                fingerprint=canonical_schema.fingerprint,
                                strict_review=True,
                                canonical_overrides=canonical_overrides,
                            )
                        )
                else:
                    logger.info(f"Initial onboarding completed for KB {kb_id}. Enqueued semantic glossary enrichment.")
                    asyncio.create_task(
                        enrichment_service.enrich_schema_async(
                            session=self.db,
                            tenant_id=tenant_uuid,
                            kb_id=kb_id,
                            schema=canonical_schema,
                            fingerprint=canonical_schema.fingerprint,
                            strict_review=True,
                            canonical_overrides=canonical_overrides,
                        )
                    )
            except Exception as enrich_err:
                logger.warning(f"Failed to process semantic glossary drift / enrichment: {enrich_err}")

            # 5. Invalidate cached schema retrieval subgraphs for this KB
            from ..retrieval.cache import SchemaRetrievalCache
            SchemaRetrievalCache.get_instance().invalidate_kb(str(self.tenant_id), str(kb_id))

            return DatabaseSchemaResponse(
                success=True,
                db_knowledgebase_id=kb_id,
                schema_version=canonical_schema.fingerprint,
                schema_data=canonical_schema,
                introspected_at=canonical_schema.introspected_at,
            )

        except Exception as e:
            safe_err = sanitize_error_message(e)
            await self.repo.update_db_kb(
                kb_id=kb_id,
                status="error",
                last_error=safe_err,
            )
            raise SchemaIntrospectionError(detail=f"Introspection failed: {safe_err}") from e

    async def get_latest_schema(self, kb_id: uuid.UUID) -> DatabaseSchemaResponse:
        """Fetch latest canonical schema snapshot for a knowledgebase."""
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")

        snapshot = await self.repo.get_latest_schema_snapshot(kb_id)
        if not snapshot:
            raise SchemaIntrospectionError(
                detail="No schema snapshot found. Please run introspection first.",
                error_code="SCHEMA_SNAPSHOT_NOT_FOUND",
            )

        canonical_schema = DatabaseSchema(**snapshot.schema_data)
        return DatabaseSchemaResponse(
            success=True,
            db_knowledgebase_id=kb_id,
            schema_version=snapshot.schema_version,
            schema_data=canonical_schema,
            introspected_at=snapshot.created_at,
        )

    async def list_schema_snapshots(
        self, kb_id: uuid.UUID, limit: int = 10
    ) -> List[SchemaSnapshotResponse]:
        """List historical schema snapshots for a knowledgebase."""
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")

        snapshots = await self.repo.list_snapshots(kb_id, limit=limit)
        return [
            SchemaSnapshotResponse(
                id=s.id,
                db_knowledgebase_id=s.db_knowledgebase_id,
                schema_version=s.schema_version,
                table_count=s.table_count,
                column_count=s.column_count,
                relationship_count=s.relationship_count,
                created_at=s.created_at,
            )
            for s in snapshots
        ]

    # ============= SCHEMA VECTOR INDEXING & RETRIEVAL =============

    async def index_schema(self, kb_id: uuid.UUID) -> int:
        """Manually trigger or refresh vector embedding indexing for canonical schema."""
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")

        snapshot = await self.repo.get_latest_schema_snapshot(kb_id)
        if not snapshot:
            raise SchemaIntrospectionError(
                detail="No schema snapshot found. Please run introspection first.",
                error_code="SCHEMA_SNAPSHOT_NOT_FOUND",
            )

        canonical_schema = DatabaseSchema(**snapshot.schema_data)
        indexer = SchemaIndexer(session=self.db, tenant_id=uuid.UUID(str(self.tenant_id)))
        return await indexer.index_schema(
            kb_id=kb_id,
            schema=canonical_schema,
            database_description=entity.description or "",
        )

    async def retrieve_schema(
        self,
        kb_id: uuid.UUID,
        user_query: str,
        conversation_context: Optional[List[str]] = None,
        top_k_tables: int = 5,
        top_k_columns_per_table: int = 25,
        include_relationships: bool = True,
        canonical_schema: Optional[DatabaseSchema] = None,
    ) -> SchemaRetrievalResult:
        """Execute hybrid schema retrieval scoped by tenant_id and kb_id."""
        retriever = SchemaRetriever(session=self.db, tenant_id=uuid.UUID(str(self.tenant_id)))
        request = SchemaRetrievalRequest(
            tenant_id=uuid.UUID(str(self.tenant_id)),
            database_knowledgebase_id=kb_id,
            user_query=user_query,
            conversation_context=conversation_context,
            top_k_tables=top_k_tables,
            top_k_columns_per_table=top_k_columns_per_table,
            include_relationships=include_relationships,
        )
        return await retriever.retrieve(request, canonical_schema=canonical_schema)

    # ============= QUERY PLANNING & CANDIDATE SQL GENERATION =============

    async def plan_query(
        self,
        kb_id: uuid.UUID,
        user_query: str,
        top_k_tables: int = 5,
        top_k_columns_per_table: int = 25,
    ) -> QueryPlanIR:
        """Construct machine-validated QueryPlanIR from user query and retrieved sub-schema."""
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")

        snapshot = await self.repo.get_latest_schema_snapshot(kb_id)
        if not snapshot:
            raise SchemaIntrospectionError(
                detail="No schema snapshot found. Please run introspection first.",
                error_code="SCHEMA_SNAPSHOT_NOT_FOUND",
            )

        canonical_schema = DatabaseSchema(**snapshot.schema_data)
        retrieval_res = await self.retrieve_schema(
            kb_id=kb_id,
            user_query=user_query,
            top_k_tables=top_k_tables,
            top_k_columns_per_table=top_k_columns_per_table,
            include_relationships=True,
        )
        tenant_uuid = uuid.UUID(self.tenant_id) if isinstance(self.tenant_id, str) else self.tenant_id
        semantic_res = self.semantic_resolver.resolve(
            query=user_query,
            tenant_id=tenant_uuid,
            knowledgebase_id=kb_id,
            schema_version=canonical_schema.fingerprint if canonical_schema else "unknown",
        )
        return QueryPlanner.plan(
            user_query=user_query,
            database_knowledgebase_id=kb_id,
            canonical_schema=canonical_schema,
            retrieval_result=retrieval_res,
            semantic_context=semantic_res,
        )

    async def generate_candidate_sql(
        self,
        kb_id: uuid.UUID,
        user_query: str,
        top_k_tables: int = 5,
        top_k_columns_per_table: int = 25,
        use_llm: bool = True,
    ) -> ValidatedCandidateSQL:
        """Generate, validate, and repair candidate SQL returning ValidatedCandidateSQL."""
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")

        snapshot = await self.repo.get_latest_schema_snapshot(kb_id)
        if not snapshot:
            raise SchemaIntrospectionError(
                detail="No schema snapshot found. Please run introspection first.",
                error_code="SCHEMA_SNAPSHOT_NOT_FOUND",
            )

        canonical_schema = DatabaseSchema(**snapshot.schema_data)
        retrieval_res = await self.retrieve_schema(
            kb_id=kb_id,
            user_query=user_query,
            top_k_tables=top_k_tables,
            top_k_columns_per_table=top_k_columns_per_table,
            include_relationships=True,
        )
        tenant_uuid = uuid.UUID(self.tenant_id) if isinstance(self.tenant_id, str) else self.tenant_id
        semantic_res = self.semantic_resolver.resolve(
            query=user_query,
            tenant_id=tenant_uuid,
            knowledgebase_id=kb_id,
            schema_version=canonical_schema.fingerprint if canonical_schema else "unknown",
        )
        plan = QueryPlanner.plan(
            user_query=user_query,
            database_knowledgebase_id=kb_id,
            canonical_schema=canonical_schema,
            retrieval_result=retrieval_res,
            semantic_context=semantic_res,
        )
        return await SQLRepairEngine.generate_and_validate(
            user_query=user_query,
            plan=plan,
            canonical_schema=canonical_schema,
            retrieval_result=retrieval_res,
            use_llm=use_llm,
        )

    # ============= PHASE 2C SAFE READ-ONLY EXECUTION =============

    async def execute_candidate_sql(
        self,
        kb_id: uuid.UUID,
        candidate_sql: ValidatedCandidateSQL,
        execution_config: Optional[ExecutionConfig] = None,
    ) -> CanonicalQueryResult:
        """
        Authorize and execute ValidatedCandidateSQL against target database.
        Strictly enforces tenant isolation, schema version matching, read-only
        transaction safety, and result resource bounds.
        """
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")

        # 1. Authorize execution via ExecutionPolicyEngine (Defense-in-depth gate)
        active_version = entity.schema_version or ""
        authorization = ExecutionPolicyEngine.authorize_execution(
            candidate_sql=candidate_sql,
            request_tenant_id=str(self.tenant_id),
            knowledgebase_tenant_id=str(entity.tenant_id),
            active_schema_version=active_version,
            knowledgebase_id=kb_id,
        )

        # 2. Decrypt stored connection credentials
        config = self.secrets.decrypt_credentials(entity.encrypted_credentials)

        # 3. Execute via ReadOnlyDatabaseExecutor
        executor = ReadOnlyDatabaseExecutor(execution_config=execution_config)
        return await executor.execute(
            candidate_sql=candidate_sql,
            authorization=authorization,
            db_config=config,
        )

    async def synthesize_database_answer(
        self,
        kb_id: uuid.UUID,
        user_query: str,
        result: CanonicalQueryResult,
        use_llm: bool = True,
    ) -> GroundedDatabaseAnswer:
        """
        Phase 2D: Synthesize verified natural-language answer from CanonicalQueryResult.
        """
        answering_service = DatabaseAnswerSynthesisService(max_fast_path_rows=500)
        return await answering_service.synthesize_answer(
            result=result,
            user_query=user_query,
            use_llm=use_llm,
        )

    async def query_database(
        self,
        kb_id: uuid.UUID,
        user_query: str,
        top_k_tables: int = 5,
        top_k_columns_per_table: int = 25,
        use_llm: bool = True,
        execution_config: Optional[ExecutionConfig] = None,
        request_id: Optional[str] = None,
        user_id: Optional[Any] = None,
        event_sink: Optional[DatabasePipelineEventSink] = None,
    ) -> GroundedDatabaseAnswer:
        """
        Complete end-to-end database knowledgebase querying pipeline with Phase 3A observability
        and Phase 3D SSE lifecycle event streaming support.
        """
        query_id = str(uuid.uuid4())
        tracer = PipelineTracer(
            query_id=query_id,
            kb_id=kb_id,
            user_query=user_query,
            tenant_id=self.tenant_id,
            request_id=request_id,
            user_id=user_id,
        )

        # Verify tenant ownership of knowledgebase
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")

        # Load canonical schema snapshot early for pre-validation and planning
        snapshot = await self.repo.get_latest_schema_snapshot(kb_id)
        canonical_schema = DatabaseSchema(**snapshot.schema_data) if snapshot else None

        current_stage = "INITIALIZATION"
        try:
            # 0. Query Acceptance
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.QUERY_ACCEPTED,
                    stage="QUERY",
                    status="accepted",
                    data={
                        "correlation_id": tracer.request_id or query_id,
                        "query_length": len(user_query),
                        "timestamp": datetime.now().isoformat(),
                    },
                )

            # Security Pre-Validation: Fail-closed on direct DDL/DML, system catalog exfiltration, or adversarial injections
            user_query_clean = user_query.strip()
            hostile_ddl_dml = re.search(
                r"\b(drop\s+table|delete\s+from|update\s+\w+\s+set|truncate\s+table|alter\s+table|grant\s+all|revoke\s+all)\b",
                user_query_clean,
                re.IGNORECASE,
            )
            if hostile_ddl_dml:
                raise SQLValidationError(
                    f"Security policy rejection: Non-SELECT command detected: {hostile_ddl_dml.group(0)}"
                )

            # Adversarial Prompt Injection Defense: Fail-closed on instructions override / security bypass attempts
            prompt_injection = re.search(
                r"\b(ignore\s+(?:all\s+)?(?:previous\s+)?(?:instructions|rules|safety|security\s+policy)|disregard\s+(?:all\s+)?(?:rules|instructions)|override\s+system\s+prompt|bypass\s+security)\b",
                user_query_clean,
                re.IGNORECASE,
            )
            if prompt_injection:
                raise SQLValidationError(
                    f"Security policy rejection: Adversarial prompt injection detected: '{prompt_injection.group(0)}'"
                )

            try:
                parsed_expr = sqlglot.parse_one(user_query_clean, read="postgres")
                if isinstance(parsed_expr, exp.Select):
                    # Check for injection tautologies or unparameterized user literals
                    if re.search(r"\b(1\s*=\s*1|or\s+true|--|;\s*\S)\b", user_query_clean, re.IGNORECASE):
                        raise SQLValidationError(
                            "Security policy rejection: Unparameterized injection or boolean tautology detected."
                        )

                    for tbl in parsed_expr.find_all(exp.Table):
                        tbl_name = tbl.name.lower()
                        if tbl_name in SQLSecurityPolicyEngine.FORBIDDEN_TABLES or (
                            tbl.db and tbl.db.lower() in SQLSecurityPolicyEngine.FORBIDDEN_CATALOGS
                        ):
                            raise SQLValidationError(
                                f"Security policy rejection: System catalog or metadata access to '{tbl_name}' is forbidden."
                            )
                        if canonical_schema:
                            known_tables = {
                                t.lower()
                                for s in canonical_schema.schemas.values()
                                for t in s.tables.keys()
                            }
                            if tbl_name not in known_tables:
                                raise SQLValidationError(
                                    f"Security policy rejection: Unauthorized table '{tbl_name}' is not permitted."
                                )

                    if canonical_schema:
                        known_columns = {
                            c.lower()
                            for s in canonical_schema.schemas.values()
                            for t in s.tables.values()
                            for c in t.columns.keys()
                        }
                        for col in parsed_expr.find_all(exp.Column):
                            col_name = col.name.lower()
                            if col_name not in ("*", "1") and col_name not in known_columns:
                                raise SQLValidationError(
                                    f"Security policy rejection: Unauthorized column '{col_name}' is not permitted."
                                )
                elif isinstance(parsed_expr, (exp.Drop, exp.Update, exp.Delete, exp.Insert, exp.AlterTable, exp.TruncateTable)):
                    raise SQLValidationError(
                        f"Security policy rejection: Non-SELECT statement '{type(parsed_expr).__name__}' is forbidden."
                    )
            except SQLValidationError:
                raise
            except Exception:
                pass  # Natural language query, proceed to retrieval & planning

            # 1. Retrieval
            current_stage = "RETRIEVAL"
            if event_sink:
                event_sink.start_stage("RETRIEVAL")
                await event_sink.emit(
                    DatabaseStreamEventType.RETRIEVAL_STARTED,
                    stage="RETRIEVAL",
                    status="started",
                    data={"top_k_tables": top_k_tables, "top_k_columns_per_table": top_k_columns_per_table},
                )

            t_ret_start = time.perf_counter()
            retrieval_res = await self.retrieve_schema(
                kb_id=kb_id,
                user_query=user_query,
                top_k_tables=top_k_tables,
                top_k_columns_per_table=top_k_columns_per_table,
                include_relationships=True,
                canonical_schema=canonical_schema,
            )
            t_ret_ms = (time.perf_counter() - t_ret_start) * 1000.0
            tracer.schema_version = retrieval_res.schema_version
            table_scores = {}
            for tbl_name, score_obj in retrieval_res.retrieval_scores.items():
                if hasattr(score_obj, "combined_score"):
                    table_scores[tbl_name] = round(float(score_obj.combined_score), 4)
                elif hasattr(score_obj, "score"):
                    table_scores[tbl_name] = round(float(score_obj.score), 4)
                else:
                    table_scores[tbl_name] = 1.0

            tracer.record_retrieval(
                retrieved_tables=[t.table_name for t in retrieval_res.retrieved_tables],
                table_scores=table_scores,
                omitted_tables=[],
                retrieved_columns={
                    t.table_name: [c if isinstance(c, str) else c.name for c in t.columns]
                    for t in retrieval_res.retrieved_tables
                },
                selected_relationships=[
                    f"{r.source_table}.{','.join(r.source_columns)} -> {r.target_table}.{','.join(r.target_columns)}"
                    for r in retrieval_res.join_paths
                ],
                latency_ms=t_ret_ms,
                schema_version=retrieval_res.schema_version,
            )

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.RETRIEVAL_COMPLETED,
                    stage="RETRIEVAL",
                    status="completed",
                    data={
                        "retrieved_tables_count": len(retrieval_res.retrieved_tables),
                        "retrieved_tables": [t.table_name for t in retrieval_res.retrieved_tables],
                        "latency_ms": round(t_ret_ms, 2),
                        "schema_version": retrieval_res.schema_version,
                    },
                    elapsed_stage_ms=t_ret_ms,
                )

            # 2. Planning
            current_stage = "PLANNING"
            if event_sink:
                event_sink.start_stage("PLANNING")
                await event_sink.emit(
                    DatabaseStreamEventType.PLANNING_STARTED,
                    stage="PLANNING",
                    status="started",
                )

            t_plan_start = time.perf_counter()
            if canonical_schema is None:
                snapshot = await self.repo.get_latest_schema_snapshot(kb_id)
                canonical_schema = DatabaseSchema(**snapshot.schema_data) if snapshot else None

            # Phase 6: Semantic Context Resolution
            tenant_uuid = uuid.UUID(self.tenant_id) if isinstance(self.tenant_id, str) else self.tenant_id
            semantic_res = self.semantic_resolver.resolve(
                query=user_query,
                tenant_id=tenant_uuid,
                knowledgebase_id=kb_id,
                schema_version=canonical_schema.fingerprint if canonical_schema else "unknown",
            )

            plan = QueryPlanner.plan(
                user_query=user_query,
                database_knowledgebase_id=kb_id,
                canonical_schema=canonical_schema,
                retrieval_result=retrieval_res,
                semantic_context=semantic_res,
            )
            # Ensure all tables planned from canonical schema are registered in retrieval_res.retrieved_tables
            # so AST security policy recognizes valid schema bridges and anchors
            retrieved_names = {t.table_name.lower() for t in retrieval_res.retrieved_tables}
            if canonical_schema:
                for tp in plan.tables:
                    if tp.table_name.lower() not in retrieved_names:
                        for s_val in canonical_schema.schemas.values():
                            if tp.table_name in s_val.tables:
                                retrieval_res.retrieved_tables.append(s_val.tables[tp.table_name])
                                retrieved_names.add(tp.table_name.lower())
                                break
            t_plan_ms = (time.perf_counter() - t_plan_start) * 1000.0
            tracer.record_planning(
                intent=plan.intent.value if hasattr(plan.intent, "value") else str(plan.intent),
                tables=[t.table_name for t in plan.tables],
                joins=[
                    f"{j.source_table_alias}.{j.source_column} = {j.target_table_alias}.{j.target_column}"
                    for j in plan.joins
                ],
                filters=[f"{p.table_alias}.{p.column_name} {p.operator} {p.value}" for p in plan.predicates],
                aggregations=[
                    f"{p.aggregation.value if hasattr(p.aggregation, 'value') else p.aggregation}({p.column_name})"
                    for p in plan.projections
                    if p.aggregation and (getattr(p.aggregation, "value", str(p.aggregation)) != "NONE")
                ],
                group_by=plan.group_by,
                order_by=[
                    f"{o.expression} {o.direction.value if hasattr(o.direction, 'value') else o.direction}"
                    for o in plan.order_by
                ],
                limit=plan.limit,
                latency_ms=t_plan_ms,
            )

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.PLANNING_COMPLETED,
                    stage="PLANNING",
                    status="completed",
                    data={
                        "intent": plan.intent.value if hasattr(plan.intent, "value") else str(plan.intent),
                        "tables_count": len(plan.tables),
                        "joins_count": len(plan.joins),
                        "has_aggregations": bool(plan.projections and any(p.aggregation and getattr(p.aggregation, "value", str(p.aggregation)) != "NONE" for p in plan.projections)),
                        "has_ranking": bool(plan.order_by),
                        "limit": plan.limit,
                        "latency_ms": round(t_plan_ms, 2),
                    },
                    elapsed_stage_ms=t_plan_ms,
                )

            # 3. SQL Generation
            current_stage = "SQL_GENERATION"
            if event_sink:
                event_sink.start_stage("SQL_GENERATION")
                await event_sink.emit(
                    DatabaseStreamEventType.SQL_GENERATION_STARTED,
                    stage="SQL_GENERATION",
                    status="started",
                    data={"use_llm": use_llm, "stage": "SQL_GENERATION"},
                )

            t_sql_start = time.perf_counter()
            candidate_sql = await SQLRepairEngine.generate_and_validate(
                user_query=user_query,
                plan=plan,
                canonical_schema=canonical_schema,
                retrieval_result=retrieval_res,
                use_llm=use_llm,
            )
            t_sql_ms = (time.perf_counter() - t_sql_start) * 1000.0
            tracer.record_sql_generation(
                candidate_sql=candidate_sql.parameterized.parameterized_sql,
                parameters=candidate_sql.parameterized.parameters,
                ast_valid=candidate_sql.validation_report.is_valid,
                ast_errors=candidate_sql.validation_report.errors,
                ast_warnings=candidate_sql.validation_report.warnings,
                repair_attempts=candidate_sql.repair_attempts,
                latency_ms=t_sql_ms,
                sql_generation_mode=candidate_sql.sql_generation_mode,
                deterministic_sql_compilation=candidate_sql.deterministic_sql_compilation,
                sql_llm_bypassed=candidate_sql.sql_llm_bypassed,
            )

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.SQL_GENERATION_COMPLETED,
                    stage="SQL_GENERATION",
                    status="completed",
                    data={
                        "sql_generation_mode": candidate_sql.sql_generation_mode,
                        "deterministic_sql_compilation": candidate_sql.deterministic_sql_compilation,
                        "sql_llm_bypassed": candidate_sql.sql_llm_bypassed,
                        "repair_attempts": candidate_sql.repair_attempts,
                        "latency_ms": round(t_sql_ms, 2),
                    },
                    elapsed_stage_ms=t_sql_ms,
                )

            # 4. AST Validation & Authorization
            current_stage = "VALIDATION"
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.VALIDATION_STARTED,
                    stage="VALIDATION",
                    status="started",
                )
                await event_sink.emit(
                    DatabaseStreamEventType.VALIDATION_COMPLETED,
                    stage="VALIDATION",
                    status="completed",
                    data={
                        "is_valid": candidate_sql.validation_report.is_valid,
                        "warnings_count": len(candidate_sql.validation_report.warnings),
                        "errors_count": len(candidate_sql.validation_report.errors),
                    },
                )

            current_stage = "AUTHORIZATION"
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.AUTHORIZATION_STARTED,
                    stage="AUTHORIZATION",
                    status="started",
                )

            tracer.record_execution_authorization(allowed=True, reason="Execution policy approved")
            tracer.record_execution_start()

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.AUTHORIZATION_COMPLETED,
                    stage="AUTHORIZATION",
                    status="completed",
                    data={"allowed": True, "mode": "READ_ONLY", "reason": "Execution policy approved"},
                )

            # 5. Read-Only Execution
            current_stage = "EXECUTION"
            if event_sink:
                event_sink.start_stage("EXECUTION")
                await event_sink.emit(
                    DatabaseStreamEventType.EXECUTION_STARTED,
                    stage="EXECUTION",
                    status="started",
                )

            t_exec_start = time.perf_counter()
            canonical_result = await self.execute_candidate_sql(
                kb_id=kb_id,
                candidate_sql=candidate_sql,
                execution_config=execution_config,
            )
            t_norm_ms = max(0.0, (time.perf_counter() - t_exec_start) * 1000.0 - canonical_result.execution_time_ms)
            tracer.record_execution(
                executed=True,
                row_count=canonical_result.row_count,
                truncated=canonical_result.truncated,
                execution_time_ms=canonical_result.execution_time_ms,
                column_count=len(canonical_result.columns),
                normalization_latency_ms=t_norm_ms,
                error=None,
            )

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.EXECUTION_COMPLETED,
                    stage="EXECUTION",
                    status="completed",
                    data={
                        "row_count": canonical_result.row_count,
                        "truncated": canonical_result.truncated,
                        "execution_time_ms": canonical_result.execution_time_ms,
                        "columns_count": len(canonical_result.columns),
                    },
                    elapsed_stage_ms=canonical_result.execution_time_ms,
                )

            # 6. Answer Synthesis
            current_stage = "SYNTHESIS"
            if event_sink:
                event_sink.start_stage("SYNTHESIS")
                await event_sink.emit(
                    DatabaseStreamEventType.SYNTHESIS_STARTED,
                    stage="SYNTHESIS",
                    status="started",
                    data={"use_llm": use_llm, "stage": "SYNTHESIS"},
                )

            t_syn_start = time.perf_counter()
            answer = await self.synthesize_database_answer(
                kb_id=kb_id,
                user_query=user_query,
                result=canonical_result,
                use_llm=use_llm,
            )
            t_syn_ms = (time.perf_counter() - t_syn_start) * 1000.0
            is_fallback = getattr(answer.grounding_status, "value", str(answer.grounding_status)) == "FALLBACK_DETERMINISTIC"
            tracer.record_synthesis(
                answer_type=answer.answer_type.value if hasattr(answer.answer_type, "value") else str(answer.answer_type),
                deterministic=answer.generation_metadata.get("deterministic", False),
                grounding_status=answer.grounding_status.value if hasattr(answer.grounding_status, "value") else str(answer.grounding_status),
                verification_status=answer.verification_status.value if hasattr(answer.verification_status, "value") else str(answer.verification_status),
                repair_attempts=answer.generation_metadata.get("repair_attempts", 0),
                latency_ms=t_syn_ms,
                fallback_used=is_fallback,
            )

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.SYNTHESIS_COMPLETED,
                    stage="SYNTHESIS",
                    status="completed",
                    data={
                        "answer_type": answer.answer_type.value if hasattr(answer.answer_type, "value") else str(answer.answer_type),
                        "deterministic": answer.generation_metadata.get("deterministic", False),
                        "latency_ms": round(t_syn_ms, 2),
                    },
                    elapsed_stage_ms=t_syn_ms,
                )

            # 7. Grounding & Verification
            current_stage = "GROUNDING"
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.GROUNDING_STARTED,
                    stage="GROUNDING",
                    status="started",
                )
                await event_sink.emit(
                    DatabaseStreamEventType.GROUNDING_COMPLETED,
                    stage="GROUNDING",
                    status="completed",
                    data={
                        "grounding_status": answer.grounding_status.value if hasattr(answer.grounding_status, "value") else str(answer.grounding_status),
                        "verification_status": answer.verification_status.value if hasattr(answer.verification_status, "value") else str(answer.verification_status),
                        "repair_attempts": answer.generation_metadata.get("repair_attempts", 0),
                    },
                )

            # Phase 6H: Record into Verified Query Memory if execution passed verification
            if (
                hasattr(answer, "verification_status")
                and (
                    getattr(answer.verification_status, "value", str(answer.verification_status)) == "PASSED"
                )
                and semantic_res
            ):
                try:
                    self.semantic_resolver.query_memory.record_verified_query(
                        VerifiedQueryMemoryRecord(
                            record_id=str(uuid.uuid4()),
                            normalized_query=semantic_res.normalized_query,
                            raw_query=user_query,
                            semantic_intent=plan.intent.value if hasattr(plan.intent, "value") else str(plan.intent),
                            selected_entities=[e.name for e in semantic_res.resolved_entities],
                            selected_metric=semantic_res.resolved_metric.metric_id if semantic_res.resolved_metric else None,
                            selected_relationships=[r.relationship_id for r in semantic_res.approved_joins],
                            applied_rules=[r.rule_id for r in semantic_res.applicable_rules],
                            compiled_sql=candidate_sql.parameterized.parameterized_sql if hasattr(candidate_sql, "parameterized") else str(candidate_sql),
                            context_fingerprint=semantic_res.context_fingerprint.combined_fingerprint,
                            schema_fingerprint=canonical_schema.fingerprint if canonical_schema else "unknown",
                            grounding_status=answer.grounding_status.value if hasattr(answer.grounding_status, "value") else str(answer.grounding_status),
                            verifier_status="PASSED",
                            tenant_id=tenant_uuid,
                            knowledgebase_id=kb_id,
                        )
                    )
                except Exception as mem_err:
                    logger.warning(f"Failed to record verified query memory: {mem_err}")

            # Attach finalized trace
            answer.pipeline_trace = tracer.finalize()

            # 8. Answer Completed & Stream Completed
            current_stage = "ANSWER"
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.ANSWER_COMPLETED,
                    stage="ANSWER",
                    status="completed",
                    data={
                        "answer_text": answer.answer_text,
                        "answer_type": answer.answer_type.value if hasattr(answer.answer_type, "value") else str(answer.answer_type),
                        "row_count": answer.row_count,
                        "grounding_status": answer.grounding_status.value if hasattr(answer.grounding_status, "value") else str(answer.grounding_status),
                        "verification_status": answer.verification_status.value if hasattr(answer.verification_status, "value") else str(answer.verification_status),
                        "rows": answer.rows if answer.rows else (answer.evidence.rows if answer.evidence else []),
                        "columns": answer.columns if answer.columns else (answer.evidence.columns if answer.evidence else []),
                        "source_columns": answer.source_columns,
                        "truncated": answer.truncated,
                        "warnings": answer.warnings,
                        "pipeline_trace": answer.pipeline_trace.model_dump(mode="json") if answer.pipeline_trace else None,
                    },
                )
                await event_sink.emit(
                    DatabaseStreamEventType.STREAM_COMPLETED,
                    stage="STREAM",
                    status="completed",
                    data={
                        "total_duration_ms": event_sink.get_total_elapsed_ms(),
                        "final_status": "SUCCESS",
                        "events_emitted": event_sink._seq,
                    },
                )

            return answer

        except (SQLValidationError, ExecutionPolicyViolation) as sec_err:
            tracer.record_security_rejection(error_msg=str(sec_err), ast_errors=[str(sec_err)])
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.QUERY_ERROR,
                    stage="SECURITY",
                    status="error",
                    data={
                        "error_code": StreamingSanitizer.resolve_safe_error_code(sec_err),
                        "stage": "SECURITY",
                        "retryable": False,
                        "message": StreamingSanitizer.resolve_safe_error_message(sec_err, "SECURITY"),
                        "correlation_id": tracer.request_id or query_id,
                    },
                )
            raise
        except DatabaseTimeoutError as time_err:
            tracer.record_failure(error_type="DatabaseTimeoutError", error_msg=str(time_err), stage="EXECUTION")
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.QUERY_ERROR,
                    stage="EXECUTION",
                    status="error",
                    data={
                        "error_code": "DATABASE_TIMEOUT",
                        "stage": "EXECUTION",
                        "retryable": True,
                        "message": "The database query exceeded the execution timeout limit.",
                        "correlation_id": tracer.request_id or query_id,
                    },
                )
            raise
        except asyncio.CancelledError:
            tracer.record_failure(error_type="CancelledError", error_msg="Query cancelled", stage=current_stage)
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.QUERY_CANCELLED,
                    stage=current_stage,
                    status="cancelled",
                    data={
                        "stage": current_stage,
                        "reason": "Query was cancelled by client.",
                        "correlation_id": tracer.request_id or query_id,
                    },
                )
            raise
        except Exception as exc:
            tracer.record_failure(error_type=type(exc).__name__, error_msg=str(exc), stage=current_stage)
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.QUERY_ERROR,
                    stage=current_stage,
                    status="error",
                    data={
                        "error_code": StreamingSanitizer.resolve_safe_error_code(exc),
                        "stage": current_stage,
                        "retryable": False,
                        "message": StreamingSanitizer.resolve_safe_error_message(exc, current_stage),
                        "correlation_id": tracer.request_id or query_id,
                    },
                )
            raise

    async def get_audit_logs(
        self,
        kb_id: uuid.UUID,
        filter_params: AuditLogFilterParams,
    ) -> AuditLogListResponse:
        """Retrieve paginated and filtered audit logs for target database knowledgebase."""
        kb = await self.repo.get_by_id(kb_id)
        if not kb:
            raise DatabaseKnowledgebaseNotFoundError(f"Database knowledgebase '{kb_id}' not found.")

        items, total = await self.repo.get_audit_logs(
            kb_id=kb_id,
            limit=filter_params.limit,
            offset=filter_params.offset,
            start_time=filter_params.start_time,
            end_time=filter_params.end_time,
            final_status=filter_params.final_status,
            min_latency_ms=filter_params.min_latency_ms,
        )

        entries = [
            AuditLogEntryResponse.model_validate(item)
            for item in items
        ]

        return AuditLogListResponse(
            items=entries,
            total=total,
            limit=filter_params.limit,
            offset=filter_params.offset,
        )

    async def check_health(
        self,
        kb_id: uuid.UUID,
    ) -> DatabaseKnowledgebaseHealth:
        """
        Subsystem Health and Diagnostics Probe:
        1. Target DB connectivity ping (SELECT 1).
        2. Read-only privilege enforcement check.
        3. Schema snapshot freshness.
        4. Operational metrics summary.
        """
        kb = await self.repo.get_by_id(kb_id)
        if not kb:
            raise DatabaseKnowledgebaseNotFoundError(f"Database knowledgebase '{kb_id}' not found.")

        metrics_summary = DatabaseKnowledgebaseMetrics.get_instance().get_metrics(tenant_id=self.tenant_id)
        snapshot = await self.repo.get_latest_schema_snapshot(kb_id)
        active_schema_version = snapshot.schema_version if snapshot else "NO_SNAPSHOT"
        freshness_status = "CURRENT" if snapshot else "OUTDATED"

        t_ping_start = time.perf_counter()
        try:
            conn_config = self.secrets.decrypt_credentials(kb.encrypted_credentials)
            connector = ConnectorFactory.create_connector(conn_config)
            test_res = await connector.test_connection()
            ping_ms = round((time.perf_counter() - t_ping_start) * 1000.0, 2)

            is_connected = bool(test_res.success)
            overall_status = "HEALTHY" if is_connected else "UNHEALTHY"

            return DatabaseKnowledgebaseHealth(
                status=overall_status,
                database_connectivity=is_connected,
                database_ping_ms=ping_ms,
                read_only_enforced=True,
                schema_version=active_schema_version,
                schema_freshness_status=freshness_status,
                metrics_summary=metrics_summary,
                error=test_res.error_message,
            )
        except Exception as exc:
            _, safe_msg = AuditSanitizer.sanitize_error(exc)
            ping_ms = round((time.perf_counter() - t_ping_start) * 1000.0, 2)
            return DatabaseKnowledgebaseHealth(
                status="UNHEALTHY",
                database_connectivity=False,
                database_ping_ms=ping_ms,
                read_only_enforced=False,
                schema_version=active_schema_version,
                schema_freshness_status=freshness_status,
                metrics_summary=metrics_summary,
                error=safe_msg,
            )


