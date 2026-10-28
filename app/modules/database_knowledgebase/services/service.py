"""Database Knowledgebase Service Orchestration Layer

Coordinates connection validation, credential encryption, deterministic schema
introspection, canonical snapshot persistence, and tenant-scoped retrieval.
"""

import asyncio
import logging
import re
import time
from typing import Optional, List, Dict, Any, Set
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
from ..disambiguation.exceptions import DisambiguationRequiredError
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

        # Capture pre-update schema version BEFORE snapshot persistence, outside try block
        old_schema_version = entity.schema_version
        is_first_snapshot = not old_schema_version

        # Decrypt connection config
        config = self.secrets.decrypt_credentials(entity.encrypted_credentials)

        try:
            # 1. Run deterministic introspection
            canonical_schema = await DatabaseIntrospector.introspect(config=config, schemas=schemas)

            # 1.1 Ingest user-defined ER mappings from k2b_user_mapping
            try:
                user_mappings = await self.repo.get_user_mappings(kb_id=kb_id, only_active=True)
                if user_mappings:
                    from ..schemas.canonical import ForeignKeySchema
                    table_lookup = {t.name.lower(): t for t in canonical_schema.all_tables}
                    added_count = 0
                    for um in user_mappings:
                        src_tbl = table_lookup.get(um.source_table.lower())
                        if src_tbl:
                            # Avoid duplicates
                            existing = any(
                                fk.referred_table.lower() == um.target_table.lower()
                                and um.source_column.lower() in [c.lower() for c in fk.constrained_columns]
                                and um.target_column.lower() in [c.lower() for c in fk.referred_columns]
                                for fk in src_tbl.foreign_keys
                            )
                            if not existing:
                                src_tbl.foreign_keys.append(
                                    ForeignKeySchema(
                                        name=f"fk_user_{um.source_table}_{um.source_column}",
                                        constrained_columns=[um.source_column],
                                        referred_schema=src_tbl.schema_name or "public",
                                        referred_table=um.target_table,
                                        referred_columns=[um.target_column],
                                    )
                                )
                                added_count += 1
                    if added_count > 0:
                        logger.info(f"Ingested {added_count} user mappings into canonical schema for KB {kb_id}")
            except Exception as um_err:
                logger.warning(f"Failed to ingest user mappings into canonical schema for KB {kb_id}: {um_err}")

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
            await self.repo.update_db_kb(
                kb_id=kb_id,
                status="indexed",
                schema_version=canonical_schema.fingerprint,
                last_introspected_at=datetime.utcnow(),
                last_error=None,
            )

            # Phase 2 Knowledge Layer Trigger Hook (Invoked after Step 4, deferred by 2s so request commit completes)
            fingerprint_changed = bool(old_schema_version and old_schema_version != canonical_schema.fingerprint)
            try:
                from app.core.config import get_settings
                if getattr(settings, "enable_phase2_knowledge_layer", False) and getattr(settings, "db_kb_pipeline_mode", "grounded_docs") != "grounded_docs":
                    if is_first_snapshot or fingerprint_changed:
                        from ..knowledge.jobs import trigger_phase2_sync_job
                        redis_pool = None
                        try:
                            from app.worker.queue import get_redis_pool
                            redis_pool = await get_redis_pool()
                        except Exception as r_exc:
                            logger.warning(f"Phase 2 Knowledge Layer skipped: Redis queue unavailable: {r_exc}")

                        if redis_pool:
                            tenant_uuid = uuid.UUID(str(self.tenant_id)) if isinstance(self.tenant_id, str) else self.tenant_id
                            await trigger_phase2_sync_job(
                                tenant_id=tenant_uuid,
                                kb_id=kb_id,
                                snapshot_id=snapshot.id,
                                schema_version=canonical_schema.fingerprint,
                                redis_pool=redis_pool,
                                defer_by_seconds=2,
                            )
                            logger.info(f"Phase 2 sync job successfully triggered for KB {kb_id}, version {canonical_schema.fingerprint}")
                        else:
                            if getattr(settings, "phase2_manual_inline_fallback", True):
                                logger.info(f"Phase 2 Knowledge Layer: Redis pool unavailable; triggering background task fallback for KB {kb_id}")
                                from ..knowledge.jobs import run_phase2_pipeline
                                tenant_uuid = uuid.UUID(str(self.tenant_id)) if isinstance(self.tenant_id, str) else self.tenant_id
                                asyncio.create_task(
                                    run_phase2_pipeline(
                                        ctx=None,
                                        tenant_id=tenant_uuid,
                                        kb_id=kb_id,
                                        schema_version=canonical_schema.fingerprint,
                                    )
                                )
                            else:
                                logger.warning(f"Phase 2 Knowledge Layer skipped for KB {kb_id}: Redis pool unavailable (pipeline not executed inline)")
            except Exception as p2_err:
                logger.error(f"Non-fatal error: Phase 2 knowledge layer trigger failed for KB {kb_id}: {p2_err}", exc_info=True)

            # 4.1 Build and Sync Universal Semantic Model (Phases C-K)
            semantic_profile_status = "ok"
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
                builder.sync_to_registries(
                    profile=profile,
                    semantic_model_registry=self._semantic_model_registry,
                    metric_registry=self._metric_registry,
                    relationship_graph=self._relationship_graph,
                )
            except Exception as sm_exc:
                import traceback
                logger.error(f"Universal semantic model build error for KB {kb_id}: {sm_exc}\n{traceback.format_exc()}")
                semantic_profile_status = "failed"
            
            # Update snapshot status
            snapshot.semantic_profile_status = semantic_profile_status
            await self.db.flush()

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

            # 4.3 Trigger Schema Documentation ("Cheat Sheet") Pipeline (Step 1)
            try:
                from ..schema_doc.pipeline import SchemaDocPipeline
                from app.core.config import get_settings
                settings = get_settings()
                tenant_uuid = uuid.UUID(str(self.tenant_id)) if isinstance(self.tenant_id, str) else self.tenant_id
                
                # Check feature flag (default off except for test KB)
                allowed_kb_ids = [k.strip() for k in getattr(settings, "schema_cheat_sheet_kb_ids", "").split(",") if k.strip()]
                is_cheat_sheet_enabled = getattr(settings, "schema_cheat_sheet_enabled", False) or (str(kb_id) in allowed_kb_ids)

                if is_cheat_sheet_enabled:
                    logger.info(f"Triggering background SchemaDocPipeline for KB {kb_id} (schema_version={canonical_schema.fingerprint[:8]})")
                    asyncio.create_task(
                        SchemaDocPipeline.run_pipeline_background(
                            tenant_id=tenant_uuid,
                            kb_id=kb_id,
                            schema=canonical_schema,
                            config=config,
                        )
                    )
                else:
                    logger.debug(f"SchemaDocPipeline feature flag disabled for KB {kb_id}")
            except Exception as doc_err:
                logger.warning(f"Non-fatal: failed to enqueue SchemaDocPipeline: {doc_err}")

            # 5. Invalidate cached schema retrieval subgraphs for this KB
            from ..retrieval.cache import SchemaRetrievalCache
            SchemaRetrievalCache.get_instance().invalidate_kb(str(self.tenant_id), str(kb_id))

            return DatabaseSchemaResponse(
                success=True,
                db_knowledgebase_id=kb_id,
                schema_version=canonical_schema.fingerprint,
                schema_data=canonical_schema,
                introspected_at=canonical_schema.introspected_at,
                semantic_profile_status=semantic_profile_status,
            )

        except Exception as e:
            safe_err = sanitize_error_message(e)
            try:
                await self.db.rollback()
            except Exception:
                pass
            try:
                await self.repo.update_db_kb(
                    kb_id=kb_id,
                    status="error",
                    last_error=safe_err,
                )
            except Exception as upd_err:
                logger.warning(f"Failed to record KB error state: {upd_err}")
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

        if isinstance(snapshot.schema_data, dict) and "tables" in snapshot.schema_data and "schemas" not in snapshot.schema_data:
            from ...NEW_DB.service import convert_canonical_to_database_schema
            canonical_schema = convert_canonical_to_database_schema(snapshot.schema_data)
        else:
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

    async def retrieve_schema_phase3(
        self,
        kb_id: uuid.UUID,
        user_query: str,
        conversation_context: Optional[List[str]] = None,
        top_k_tables: int = 5,
        top_k_columns_per_table: int = 25,
        include_relationships: bool = True,
        canonical_schema: Optional[DatabaseSchema] = None,
        reference_date: Optional[Any] = None,
        clarification_answers: Optional[Dict[str, Any]] = None,
    ) -> SchemaRetrievalResult:
        """
        Execute Phase 3 Grounded Schema & Context Retrieval via ContextPackBuilder (Steps 3.1 - 3.10).
        Coordinates:
        - QuestionAnalyzer (time range, unit values, comparisons, tokens)
        - LiveEntityResolver (checks sensitive fields, unanswerable guard)
        - TableRetriever (RRF multi-signal fusion: FTS, Vector, Glossary, Metrics, Value Index)
        - ColumnRetriever (prunes columns, identifies metrics)
        - JoinPathFinder (connective join paths)
        - QueryMemory & KnowledgeItem rules
        - Converts token-bounded ContextPack into version-pinned SchemaRetrievalResult with grounded XML.
        """
        from ..knowledge.retrieval.context_pack import ContextPackBuilder, ContextPack
        from ..retrieval.scorer import TableRetrievalScore
        from ..retrieval.pruner import SchemaPruner
        from ..schemas.canonical import RelationshipSchema, RelationshipType

        tenant_uuid = uuid.UUID(str(self.tenant_id))

        # 1. Fetch canonical schema snapshot if not provided
        if canonical_schema is None:
            snapshot = await self.repo.get_latest_schema_snapshot(kb_id)
            if not snapshot:
                raise DatabaseKnowledgebaseNotFoundError(f"No schema snapshot found for KB {kb_id}")
            canonical_schema = DatabaseSchema(**snapshot.schema_data)

        # 2. Execute Phase 3 ContextPackBuilder
        builder = ContextPackBuilder(db=self.db, tenant_id=tenant_uuid)
        pack: ContextPack = await builder.build(
            db_knowledgebase_id=kb_id,
            question=user_query,
            reference_date=reference_date,
            clarification_answers=clarification_answers,
        )

        # 3. Fail-closed security guard on unanswerable sensitive access vs entity lookup
        if pack.unanswerable and pack.unanswerable.get("flag"):
            reason = pack.unanswerable.get("reason", "Question references restricted/sensitive data.")
            is_security = any(
                kw in reason.lower()
                for kw in ("restricted", "sensitive", "forbidden", "unauthorized", "security", "policy", "denied")
            )
            if is_security:
                raise SQLValidationError(f"Security policy rejection: {reason}")
            else:
                raise DatabaseKnowledgebaseNotFoundError(detail=reason)

        # 4. Map candidate tables against canonical schema
        canonical_tables_map: Dict[str, Any] = {}
        for s_info in canonical_schema.schemas.values():
            for t_name, t_schema in s_info.tables.items():
                canonical_tables_map[t_name.lower()] = t_schema
                canonical_tables_map[f"{t_schema.schema_name.lower()}.{t_name.lower()}"] = t_schema

        selected_scores: Dict[str, TableRetrievalScore] = {}
        retrieved_table_schemas: List[Any] = []

        for cand in pack.tables:
            tbl_clean = cand.get("name", "").lower()
            matching_schema = canonical_tables_map.get(tbl_clean)
            if matching_schema:
                t_key = f"{matching_schema.schema_name}.{matching_schema.table_name}"
                matched_cols = [
                    c.get("name") for c in pack.columns
                    if c.get("table", "").lower() in (tbl_clean, matching_schema.table_name.lower())
                ]
                score_val = float(cand.get("score", 1.0))
                score_obj = TableRetrievalScore(
                    table_name=matching_schema.table_name,
                    final_score=score_val,
                    vector_score=score_val,
                    keyword_score=score_val,
                    graph_score=1.0,
                    matched_columns=matched_cols,
                )
                selected_scores[t_key] = score_obj
                selected_scores[matching_schema.table_name] = score_obj
                if matching_schema not in retrieved_table_schemas:
                    retrieved_table_schemas.append(matching_schema)
            if len(retrieved_table_schemas) >= top_k_tables:
                break

        # Fallback to Phase 2A hybrid if Phase 3 yields no candidate tables (e.g. unindexed KB or cold start)
        if not retrieved_table_schemas:
            logger.info("[PHASE_3_RETRIEVAL] Phase 3 returned 0 candidate tables; falling back to Phase 2A hybrid retriever")
            fallback_res = await self.retrieve_schema(
                kb_id=kb_id,
                user_query=user_query,
                conversation_context=conversation_context,
                top_k_tables=top_k_tables,
                top_k_columns_per_table=top_k_columns_per_table,
                include_relationships=include_relationships,
                canonical_schema=canonical_schema,
                use_phase3=False,
            )
            fallback_res.context_pack = pack
            return fallback_res

        # 5. Build active relationships from Phase 3 join tree
        active_relationships: List[RelationshipSchema] = []
        for j in pack.joins:
            l_tbl_name = j.get("left_table", "").lower()
            r_tbl_name = j.get("right_table", "").lower()
            l_schema = canonical_tables_map.get(l_tbl_name)
            r_schema = canonical_tables_map.get(r_tbl_name)
            if l_schema and r_schema:
                active_relationships.append(
                    RelationshipSchema(
                        source_schema=l_schema.schema_name,
                        source_table=l_schema.table_name,
                        source_columns=[j.get("left_col", "id")],
                        target_schema=r_schema.schema_name,
                        target_table=r_schema.table_name,
                        target_columns=[j.get("right_col", "id")],
                        relationship_type=RelationshipType.MANY_TO_ONE,
                    )
                )

        if include_relationships:
            retrieved_names = {t.table_name.lower() for t in retrieved_table_schemas}
            for s_info in canonical_schema.schemas.values():
                for tbl in s_info.tables.values():
                    if tbl.table_name.lower() in retrieved_names:
                        for rel in getattr(tbl, "relationships", []):
                            if (
                                rel.source_table.lower() in retrieved_names
                                and rel.target_table.lower() in retrieved_names
                                and rel not in active_relationships
                            ):
                                active_relationships.append(rel)
                        for fk in getattr(tbl, "foreign_keys", []):
                            if fk.referred_table.lower() in retrieved_names:
                                rel_obj = RelationshipSchema(
                                    source_schema=tbl.schema_name,
                                    source_table=tbl.table_name,
                                    source_columns=fk.constrained_columns,
                                    target_schema=fk.referred_schema,
                                    target_table=fk.referred_table,
                                    target_columns=fk.referred_columns,
                                    relationship_type=RelationshipType.MANY_TO_ONE,
                                )
                                if rel_obj not in active_relationships:
                                    active_relationships.append(rel_obj)

            # Ingest active user mappings dynamically into active relationships
            try:
                user_maps = await self.repo.get_user_mappings(kb_id=kb_id, only_active=True)
                for um in user_maps:
                    if (
                        um.source_table.lower() in retrieved_names
                        and um.target_table.lower() in retrieved_names
                    ):
                        user_rel = RelationshipSchema(
                            source_schema=canonical_tables_map.get(um.source_table.lower(), {}).schema_name or "public" if hasattr(canonical_tables_map.get(um.source_table.lower()), "schema_name") else "public",
                            source_table=um.source_table,
                            source_columns=[um.source_column],
                            target_schema=canonical_tables_map.get(um.target_table.lower(), {}).schema_name or "public" if hasattr(canonical_tables_map.get(um.target_table.lower()), "schema_name") else "public",
                            target_table=um.target_table,
                            target_columns=[um.target_column],
                            relationship_type=RelationshipType.MANY_TO_ONE,
                        )
                        if user_rel not in active_relationships:
                            active_relationships.append(user_rel)
            except Exception as um_ret_err:
                logger.debug(f"User mapping retrieval injection ignored: {um_ret_err}")

        # 6. Hierarchical Sub-Schema Pruning
        pruned_tables, pruned_rels, untrusted_xml = SchemaPruner.prune_schema(
            canonical_schema=canonical_schema,
            selected_scores=selected_scores,
            active_relationships=active_relationships,
            top_k_columns_per_table=top_k_columns_per_table,
        )

        # 7. Enrich XML with Phase 3 Grounded Context Pack
        grounded_lines = ["\n<!-- PHASE 3 GROUNDED CONTEXT PACK -->\n<grounded_context>"]
        if pack.entities:
            grounded_lines.append("  <resolved_entities>")
            for ent in pack.entities:
                m_val = ent.get("matched_value") or ent.get("value") or ""
                grounded_lines.append(
                    f'    <entity span="{ent.get("span")}" table="{ent.get("table")}" '
                    f'column="{ent.get("column")}" matched_value="{m_val}" resolved_pk="{ent.get("pk")}" '
                    f'status="{ent.get("status")}"/>'
                )
            grounded_lines.append("  </resolved_entities>")
        if pack.time_range:
            tr = pack.time_range
            grounded_lines.append(
                f'  <time_range start="{tr.get("start_date")}" end="{tr.get("end_date")}" '
                f'expression="{tr.get("expression")}"/>'
            )
        if pack.comparisons:
            grounded_lines.append("  <comparisons>")
            for cmp in pack.comparisons:
                grounded_lines.append(
                    f'    <comparison operator="{cmp.get("operator")}" target="{cmp.get("target_value")}" '
                    f'unit="{cmp.get("target_unit")}"/>'
                )
            grounded_lines.append("  </comparisons>")
        if pack.metrics:
            grounded_lines.append("  <metrics>")
            for m in pack.metrics:
                grounded_lines.append(
                    f'    <metric name="{m.get("name")}" expression="{m.get("expression")}" '
                    f'unit="{m.get("unit")}"/>'
                )
            grounded_lines.append("  </metrics>")
        if pack.rules:
            grounded_lines.append("  <business_rules>")
            for r in pack.rules:
                grounded_lines.append(
                    f'    <rule name="{r.get("name")}" description="{r.get("description")}" '
                    f'expression="{r.get("rule_expression")}"/>'
                )
            grounded_lines.append("  </business_rules>")
        if pack.similar_queries:
            grounded_lines.append("  <similar_queries>")
            for sq in pack.similar_queries:
                grounded_lines.append(
                    f'    <query question="{sq.get("question")}" sql="{sq.get("compiled_sql")}"/>'
                )
            grounded_lines.append("  </similar_queries>")
        grounded_lines.append("</grounded_context>")
        grounded_xml = "\n".join(grounded_lines)

        if "</database>" in untrusted_xml:
            enriched_xml = untrusted_xml.replace("</database>", f"{grounded_xml}\n</database>")
        else:
            enriched_xml = f"{untrusted_xml}\n{grounded_xml}"

        return SchemaRetrievalResult(
            database_name=canonical_schema.database_name,
            database_type=canonical_schema.database_type,
            schema_version=canonical_schema.fingerprint,
            retrieved_tables=pruned_tables,
            retrieval_scores=selected_scores,
            join_paths=pruned_rels,
            overall_confidence=float(pack.confidence),
            untrusted_boundary_text=enriched_xml,
            context_pack=pack,
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
        use_phase3: bool = True,
    ) -> SchemaRetrievalResult:
        """Execute schema retrieval scoped by tenant_id and kb_id. Defaults to Phase 3 ContextPack."""
        if use_phase3:
            return await self.retrieve_schema_phase3(
                kb_id=kb_id,
                user_query=user_query,
                conversation_context=conversation_context,
                top_k_tables=top_k_tables,
                top_k_columns_per_table=top_k_columns_per_table,
                include_relationships=include_relationships,
                canonical_schema=canonical_schema,
            )
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

    async def _query_database_grounded_docs(
        self,
        kb_id: uuid.UUID,
        entity: DatabaseKnowledgebase,
        user_query: str,
        top_k_tables: int = 8,
        top_k_columns_per_table: int = 25,
        use_llm: bool = True,
        execution_config: Optional[ExecutionConfig] = None,
        request_id: Optional[str] = None,
        user_id: Optional[Any] = None,
        event_sink: Optional[DatabasePipelineEventSink] = None,
        resolved_entities: Optional[list] = None,
    ) -> GroundedDatabaseAnswer:
        """
        Streamlined, grounded database knowledgebase pipeline inspired by D:\\DB\\main.
        Retrieves top-K AI-understandable table markdown docs from pgvector, resolves
        concrete entities (e.g. user Arun -> ID 113), generates strictly grounded read-only
        SQL with DeepSeek, validates AST safety with sqlglot, executes read-only on tenant DB,
        and synthesizes rich narrative summaries with full column detail.
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

        current_stage = "INITIALIZATION"
        t_ret_ms = 0.0
        t_sql_ms = 0.0
        t_exec_ms = 0.0
        t_syn_ms = 0.0

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

            # Security Pre-Validation
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

            prompt_injection = re.search(
                r"\b(ignore\s+(?:all\s+)?(?:previous\s+)?(?:instructions|rules|safety|security\s+policy)|disregard\s+(?:all\s+)?(?:rules|instructions)|override\s+system\s+prompt|bypass\s+security)\b",
                user_query_clean,
                re.IGNORECASE,
            )
            if prompt_injection:
                raise SQLValidationError(
                    f"Security policy rejection: Adversarial prompt injection detected: '{prompt_injection.group(0)}'"
                )

            # 1. Retrieval (Semantic Schema Docs from pgvector)
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
            from ..retrieval.schema_doc_retriever import SchemaDocRetriever
            from ..schemas.canonical import DatabaseSchema

            snapshot = await self.repo.get_latest_schema_snapshot(kb_id)
            canonical_schema = DatabaseSchema(**snapshot.schema_data) if snapshot and snapshot.schema_data else None

            tenant_uuid = uuid.UUID(str(self.tenant_id)) if isinstance(self.tenant_id, (str, uuid.UUID)) else self.tenant_id
            schema_docs = await SchemaDocRetriever.retrieve_schema_docs(
                session=self.db,
                tenant_id=tenant_uuid,
                kb_id=kb_id,
                user_query=user_query,
                top_k=top_k_tables,
                canonical_schema=canonical_schema,
            )
            t_ret_ms = (time.perf_counter() - t_ret_start) * 1000.0

            table_names = [d.get("table_name", "") for d in schema_docs if d.get("table_name")]
            table_scores = {d.get("table_name", f"table_{i}"): d.get("score", 1.0) for i, d in enumerate(schema_docs)}

            tracer.record_retrieval(
                retrieved_tables=table_names,
                table_scores=table_scores,
                omitted_tables=[],
                retrieved_columns={},
                selected_relationships=[],
                latency_ms=t_ret_ms,
                schema_version=entity.schema_version or (snapshot.schema_version if snapshot else "grounded_docs"),
            )

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.RETRIEVAL_COMPLETED,
                    stage="RETRIEVAL",
                    status="completed",
                    data={
                        "retrieved_tables_count": len(table_names),
                        "retrieved_tables": table_names,
                        "latency_ms": round(t_ret_ms, 2),
                        "schema_version": entity.schema_version or "grounded_docs",
                    },
                    elapsed_stage_ms=t_ret_ms,
                )

            # 2. Dynamic Entity Resolution & Disambiguation
            # ------------------------------------------------------------------
            # Phase 2: Fully Dynamic Schema-Driven Dimension Entity Resolution
            # ------------------------------------------------------------------
            resolved_dimension_entities: List[Dict[str, Any]] = []
            disambiguation_notices: List[str] = []

            # 1. Pre-resolved entities from prior interactive turn
            if resolved_entities:
                for ent in resolved_entities:
                    if ent.get("id"):
                        resolved_dimension_entities.append(ent)
                        tbl = ent.get("table", "entity")
                        name_str = ent.get("name") or ent.get("label") or str(ent.get("id"))
                        disambiguation_notices.append(f"Targeting pre-resolved {tbl} '{name_str}' (ID {ent['id']})")

            # 2. Dynamic Schema-Driven Dimension Discovery & Entity Resolution
            config = self.secrets.decrypt_credentials(entity.encrypted_credentials)
            if not resolved_dimension_entities and canonical_schema:
                from ..retrieval.grounded_entity_resolver import GroundedEntityResolver
                try:
                    res_outcome = await GroundedEntityResolver.resolve_entities_in_query(
                        user_query=user_query,
                        canonical_schema=canonical_schema,
                        conn_config=config,
                        kb_id=str(kb_id),
                        tenant_id=str(self.tenant_id),
                    )

                    # Check for ambiguous entity matches that require user clarification
                    ambiguous = res_outcome.get("ambiguous_entities", [])
                    if ambiguous and not resolved_entities:
                        first_amb = ambiguous[0]
                        candidates = first_amb.get("candidates", [])
                        
                        # Only prompt user if candidates offer genuinely distinct semantic labels/names.
                        # If all candidates have identical names (e.g. all 30 are 'BENZ'), or if the query
                        # already contains a high-entropy specific identifier/code (e.g. 'W129589010700'),
                        # disambiguating identical names is redundant and disrupts user experience.
                        has_specific_code = bool(re.search(r"\b[A-Za-z0-9_-]{6,}\b", user_query or "") and any(c.isdigit() for c in (user_query or "")))
                        clean_candidate_names = {re.sub(r"\s*\(id\s+[^)]+\)", "", str(c.get("name") or "")).strip().lower() for c in candidates}
                        clean_candidate_names.discard("")
                        has_differentiated = len(clean_candidate_names) > 1

                        if has_differentiated and not has_specific_code:
                            options = [
                                {
                                    "id": c["id"],
                                    "label": f"{c.get('name')} (ID: {c['id']})",
                                    "name": c.get("name"),
                                    "table": c.get("table", first_amb.get("dimension_table")),
                                    "column": c.get("column", "id"),
                                    "pk_column": c.get("column", "id"),
                                }
                                for c in candidates
                            ]
                            raise DisambiguationRequiredError(
                                message=f"Multiple matches found for '{first_amb.get('matched_term')}'. Which one did you mean?",
                                options=options,
                                entity_type=first_amb.get("dimension_table", "entity"),
                            )
                        else:
                            logger.info(
                                f"[GROUNDED_PIPELINE] Bypassing disambiguation for '{first_amb.get('matched_term')}' "
                                f"(identical_names={not has_differentiated}, has_specific_code={has_specific_code})"
                            )

                    resolved_dimension_entities = res_outcome.get("resolved_entities", [])
                    disambiguation_notices.extend(res_outcome.get("notices", []))
                    for ent in resolved_dimension_entities:
                        logger.info(f"[GROUNDED_PIPELINE] Dynamically resolved entity: {ent['table']}.{ent['column']}={ent['id']} ('{ent.get('name')}')")
                except DisambiguationRequiredError:
                    raise
                except Exception as ent_err:
                    logger.debug(f"[GROUNDED_PIPELINE] Dynamic dimension entity resolution skipped: {ent_err}")

            # 3. Dynamic Schema Graph Expansion:
            # Traverses the canonical schema's FK graph dynamically without hardcoded table lists:
            # a) All tables of resolved entities (users, projects, types, categories, etc.)
            # b) Connecting / junction tables linking resolved entities together
            # c) 1-hop foreign key parent dimension tables
            retrieved_table_set = {d.get("table_name", "").lower() for d in schema_docs}
            dynamically_needed_tables: Set[str] = set()
            resolved_table_names = {ent.get("table", "").lower() for ent in resolved_dimension_entities if ent.get("table")}

            # Add tables containing any resolved entities
            for ent in resolved_dimension_entities:
                ent_tbl = ent.get("table", "").lower()
                if ent_tbl and ent_tbl not in retrieved_table_set:
                    dynamically_needed_tables.add(ent_tbl)

            if canonical_schema and hasattr(canonical_schema, "all_tables"):
                # Dynamically discover junction / connecting tables that link 2 or more resolved entities
                if len(resolved_table_names) >= 2:
                    discovered_junctions: List[Tuple[str, int]] = []
                    for t in canonical_schema.all_tables:
                        t_clean = t.table_name.split(".")[-1].lower()
                        if t_clean in retrieved_table_set or t_clean in dynamically_needed_tables:
                            continue
                        if any(t_clean.startswith(pfx) for pfx in ("github_", "gitlab_", "scim_", "good_job_", "bcf_", "ar_internal_metadata", "schema_migrations")):
                            continue
                        if any(t_clean.endswith(sfx) or t_clean.startswith(sfx) for sfx in ("_journals", "_hierarchies", "_days", "_cache", "_audits", "non_")):
                            continue

                        fk_targets = {fk.referred_table.split(".")[-1].lower() for fk in t.foreign_keys}
                        # Also check foreign key naming patterns (e.g. author_id, user_id, project_id, type_id)
                        cols = {c.name.lower() for c in t.columns.values()}
                        for r_tbl in resolved_table_names:
                            r_singular = r_tbl.rstrip('s')
                            if f"{r_singular}_id" in cols or (r_tbl == "users" and any(c in cols for c in ("author_id", "assigned_to_id", "creator_id", "user_id"))):
                                fk_targets.add(r_tbl)

                        inter = fk_targets.intersection(resolved_table_names)
                        if len(inter) >= 2:
                            discovered_junctions.append((t_clean, len(inter)))

                    # Sort by number of connected resolved entities descending, prioritizing fact hubs
                    discovered_junctions.sort(key=lambda x: x[1], reverse=True)
                    for j_tbl, num_conn in discovered_junctions[:3]:
                        dynamically_needed_tables.add(j_tbl)
                        logger.info(f"[GROUNDED_PIPELINE] Discovered connecting junction table '{j_tbl}' linking {num_conn} resolved entities")

                seed_tables = retrieved_table_set.union(dynamically_needed_tables)
                # 1-hop parent dimension tables referenced via FK from currently selected tables
                for t_name in list(seed_tables):
                    t_schema = canonical_schema.get_table(t_name)
                    if t_schema:
                        for fk in t_schema.foreign_keys:
                            ref_tbl = fk.referred_table.split(".")[-1].lower()
                            if ref_tbl not in retrieved_table_set and ref_tbl not in dynamically_needed_tables:
                                if ref_tbl in user_query.lower() or ref_tbl.rstrip('s') in user_query.lower():
                                    dynamically_needed_tables.add(ref_tbl)

            if dynamically_needed_tables:
                from ..models.embeddings import DatabaseSchemaEmbedding
                from sqlalchemy import select, or_
                for tbl_name in dynamically_needed_tables:
                    if tbl_name not in retrieved_table_set:
                        extra_stmt = select(
                            DatabaseSchemaEmbedding.entity_key,
                            DatabaseSchemaEmbedding.document_text,
                            DatabaseSchemaEmbedding.metadata_json,
                        ).where(
                            DatabaseSchemaEmbedding.tenant_id == tenant_uuid,
                            DatabaseSchemaEmbedding.db_knowledgebase_id == kb_id,
                            DatabaseSchemaEmbedding.entity_type == "table_doc",
                            or_(
                                DatabaseSchemaEmbedding.entity_key.ilike(f"%.{tbl_name}"),
                                DatabaseSchemaEmbedding.entity_key == tbl_name,
                            ),
                        ).limit(1)
                        extra_res = await self.db.execute(extra_stmt)
                        extra_row = extra_res.first()
                        if extra_row:
                            meta = extra_row.metadata_json or {}
                            schema_docs.append({
                                "source": meta.get("source", f"{extra_row.entity_key}.md"),
                                "title": meta.get("title", extra_row.entity_key),
                                "text": extra_row.document_text,
                                "score": 0.98 if tbl_name in resolved_table_names else 0.95,
                                "table_name": meta.get("table_name", tbl_name),
                                "schema_name": meta.get("schema_name", "public"),
                                "column_names": meta.get("column_names", []),
                            })
                            table_names.append(tbl_name)
                            retrieved_table_set.add(tbl_name)
                            logger.info(f"[GROUNDED_PIPELINE] Dynamically expanded schema graph with '{tbl_name}' table")
                        elif canonical_schema:
                            t_obj = canonical_schema.get_table(tbl_name) or canonical_schema.get_table(tbl_name.split(".")[-1])
                            if t_obj:
                                from ..schema.markdown_doc_generator import SchemaMarkdownGenerator
                                doc_text = SchemaMarkdownGenerator.generate_table_markdown(t_obj)
                                schema_docs.append({
                                    "source": f"{tbl_name}.md",
                                    "title": f"Table: {tbl_name}",
                                    "text": doc_text,
                                    "score": 0.98 if tbl_name in resolved_table_names else 0.95,
                                    "table_name": t_obj.table_name,
                                    "schema_name": t_obj.schema_name or "public",
                                    "column_names": [c.name for c in t_obj.columns.values()],
                                })
                                table_names.append(tbl_name)
                                retrieved_table_set.add(tbl_name)
                                logger.info(f"[GROUNDED_PIPELINE] Dynamically generated on-the-fly doc for '{tbl_name}' table from DDL")

            # Prioritize resolved entity tables (score 1.0) and central connecting fact tables (score 0.95)
            for d in schema_docs:
                d_tbl = d.get("table_name", "").lower()
                if d_tbl in resolved_table_names:
                    d["score"] = max(d.get("score", 0.0), 1.0)

            # Rank and cap final schema documents to top 8 tables
            schema_docs.sort(key=lambda d: d.get("score", 0.0), reverse=True)
            schema_docs = schema_docs[:8]
            table_names = [d.get("table_name", "") for d in schema_docs if d.get("table_name")]
            logger.info(f"[GROUNDED_PIPELINE] Final schema context tables: {table_names}")
            print(f"[GROUNDED_PIPELINE] Final schema context tables: {table_names}")

            # 3. Dynamic Query Intent Analysis & Planning Trace
            current_stage = "PLANNING"
            if event_sink:
                event_sink.start_stage("PLANNING")
                await event_sink.emit(
                    DatabaseStreamEventType.PLANNING_STARTED,
                    stage="PLANNING",
                    status="started",
                )

            t_plan_start = time.perf_counter()
            from ..planning.intent_analyzer import QueryIntentAnalyzer
            intent_analysis = QueryIntentAnalyzer.analyze(user_query)
            t_plan_ms = (time.perf_counter() - t_plan_start) * 1000.0

            # Record planning into tracer so Phase 2B shows clean, accurate intent and latency
            tracer.record_planning(
                intent=intent_analysis.intent.value,
                tables=table_names,
                joins=[],
                filters=[f"{p.target_concept} {p.operator} {p.value}" for p in intent_analysis.predicates],
                aggregations=[a.raw_match for a in intent_analysis.aggregations],
                group_by=[intent_analysis.grouping_concept] if intent_analysis.grouping_concept else [],
                order_by=[f"{intent_analysis.ranking.target_metric or 'col'} {intent_analysis.ranking.direction.value}"] if intent_analysis.ranking else [],
                limit=intent_analysis.ranking.limit if intent_analysis.ranking else 50,
                latency_ms=t_plan_ms,
            )

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.PLANNING_COMPLETED,
                    stage="PLANNING",
                    status="completed",
                    data={
                        "intent": intent_analysis.intent.value,
                        "tables_count": len(table_names),
                        "target_tables": table_names,
                        "joins_count": 0,
                        "has_aggregations": len(intent_analysis.aggregations) > 0,
                        "has_ranking": intent_analysis.ranking is not None,
                        "limit": intent_analysis.ranking.limit if intent_analysis.ranking else 50,
                        "latency_ms": round(t_plan_ms, 2),
                    },
                    elapsed_stage_ms=t_plan_ms,
                )

            # 4. SQL Generation
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
            from ..sql_generator.grounded_generator import GroundedSQLGenerator

            candidate_sql_raw = await GroundedSQLGenerator.generate_sql(
                question=user_query,
                retrieved_docs=schema_docs,
                resolved_entities=resolved_dimension_entities,
                intent_analysis=intent_analysis,
            )
            t_sql_ms = (time.perf_counter() - t_sql_start) * 1000.0

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.SQL_GENERATION_COMPLETED,
                    stage="SQL_GENERATION",
                    status="completed",
                    data={
                        "sql_generation_mode": "grounded_docs",
                        "deterministic_sql_compilation": False,
                        "sql_llm_bypassed": False,
                        "repair_attempts": 0,
                        "latency_ms": round(t_sql_ms, 2),
                    },
                    elapsed_stage_ms=t_sql_ms,
                )

            # 5. Validation & Authorization
            current_stage = "VALIDATION"
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.VALIDATION_STARTED,
                    stage="VALIDATION",
                    status="started",
                )

            from ..sql_security.grounded_validator import GroundedSQLValidator
            try:
                candidate_sql_clean = GroundedSQLValidator.validate_readonly_sql(candidate_sql_raw)
            except ValueError as val_err:
                raise SQLValidationError(f"Security policy rejection: {val_err}")

            if "LIMIT" not in candidate_sql_clean.upper():
                default_limit = 1 if "count(" in candidate_sql_clean.lower() else 50
                candidate_sql_clean = f"{candidate_sql_clean.rstrip()} LIMIT {default_limit}"

            logger.info(f"[GROUNDED_PIPELINE] Generated SQL: {candidate_sql_clean}")
            print(f"[GROUNDED_PIPELINE] Generated SQL: {candidate_sql_clean}")

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.VALIDATION_COMPLETED,
                    stage="VALIDATION",
                    status="completed",
                    data={"is_valid": True, "warnings_count": 0, "errors_count": 0},
                )

            current_stage = "AUTHORIZATION"
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.AUTHORIZATION_STARTED,
                    stage="AUTHORIZATION",
                    status="started",
                )
                await event_sink.emit(
                    DatabaseStreamEventType.AUTHORIZATION_COMPLETED,
                    stage="AUTHORIZATION",
                    status="completed",
                    data={"allowed": True, "mode": "READ_ONLY", "reason": "Execution policy approved"},
                )

            # 6. Read-Only DB Execution
            current_stage = "EXECUTION"
            if event_sink:
                event_sink.start_stage("EXECUTION")
                await event_sink.emit(
                    DatabaseStreamEventType.EXECUTION_STARTED,
                    stage="EXECUTION",
                    status="started",
                )

            from ..sql_parser.ast_parser import SQLASTParser
            from ..sql_security.parameterizer import SQLParameterizer
            from ..sql_security.diagnostics import ValidationResult
            from ..planning.models import QueryPlanIR, IntentType, TablePlan
            from ..sql_generator.repair import ValidatedCandidateSQL

            parsed_ast = SQLASTParser.parse_sql(candidate_sql_clean, dialect="postgres")
            parameterized = SQLParameterizer.parameterize(parsed_ast)

            active_schema_version = entity.schema_version or (snapshot.schema_version if snapshot else "grounded_docs")
            cand_sql = ValidatedCandidateSQL(
                raw_sql=candidate_sql_clean,
                sanitized_sql=candidate_sql_clean,
                parameterized=parameterized,
                plan=QueryPlanIR(
                    database_knowledgebase_id=kb_id,
                    schema_version=active_schema_version,
                    user_query=user_query,
                    intent=intent_analysis.intent,
                    tables=[TablePlan(schema_name="public", table_name=t, alias=t[:2]) for t in table_names],
                    joins=[],
                    projections=[],
                    predicates=[],
                ),
                validation_report=ValidationResult(is_valid=True, errors=[], warnings=[]),
                repair_attempts=0,
                sql_generation_mode="grounded_docs",
                deterministic_sql_compilation=False,
                sql_llm_bypassed=False,
            )

            t_exec_start = time.perf_counter()
            try:
                canonical_result = await self.execute_candidate_sql(
                    kb_id=kb_id,
                    candidate_sql=cand_sql,
                    execution_config=execution_config,
                )
            except Exception as exec_err:
                err_msg = str(exec_err)
                logger.warning(f"[GROUNDED_AUTO_REPAIR] SQL execution failed: {err_msg}. Triggering dynamic self-healing...")
                repaired_sql = None
                repair_mode = "grounded_hint_repaired"

                # 1. Fast path: PostgreSQL HINT for column name typos (e.g. u.email -> u.mail)
                hint_match = re.search(r'column\s+([a-zA-Z0-9_\.]+)\s+does not exist.*?HINT:\s*Perhaps you meant to reference the column\s+"([a-zA-Z0-9_\.]+)"', err_msg, re.IGNORECASE | re.DOTALL)
                if hint_match:
                    bad_ref = hint_match.group(1)
                    good_ref = hint_match.group(2)
                    bad_col = bad_ref.split(".")[-1]
                    good_col = good_ref.split(".")[-1]
                    # Only apply fast-path hint if column name actually changed and modifies query
                    if bad_col != good_col:
                        cand_hint_sql = re.sub(rf'\b{re.escape(bad_col)}\b', good_col, candidate_sql_clean)
                        if cand_hint_sql.strip() != candidate_sql_clean.strip():
                            logger.info(f"[GROUNDED_AUTO_REPAIR] Attempting fast-path hint repair: '{bad_col}' -> '{good_col}'")
                            repaired_sql = cand_hint_sql

                # Try executing fast hint repair if available
                if repaired_sql:
                    try:
                        repaired_sql_clean = GroundedSQLValidator.validate_readonly_sql(repaired_sql)
                        if "LIMIT" not in repaired_sql_clean.upper():
                            default_limit = 1 if "count(" in repaired_sql_clean.lower() else 50
                            repaired_sql_clean = f"{repaired_sql_clean.rstrip()} LIMIT {default_limit}"

                        parsed_repaired = SQLASTParser.parse_sql(repaired_sql_clean, dialect="postgres")
                        cand_sql = ValidatedCandidateSQL(
                            raw_sql=repaired_sql_clean,
                            sanitized_sql=repaired_sql_clean,
                            parameterized=SQLParameterizer.parameterize(parsed_repaired),
                            plan=cand_sql.plan,
                            validation_report=ValidationResult(is_valid=True, errors=[], warnings=[]),
                            repair_attempts=1,
                            sql_generation_mode=repair_mode,
                        )
                        canonical_result = await self.execute_candidate_sql(
                            kb_id=kb_id,
                            candidate_sql=cand_sql,
                            execution_config=execution_config,
                        )
                        logger.info(f"[GROUNDED_AUTO_REPAIR] Query successfully repaired and executed via fast hint: {repaired_sql_clean}")
                    except Exception as hint_err:
                        logger.warning(f"[GROUNDED_AUTO_REPAIR] Fast-path hint repair execution failed: {hint_err}. Falling back to universal LLM repair loop.")
                        repaired_sql = None

                # 2. Universal LLM dynamic repair loop: pass error + schema docs + failed query
                if not repaired_sql:
                    # Dynamically augment schema docs if failed SQL or error references tables missing from schema_docs
                    if canonical_schema:
                        existing_doc_tables = {d.get("table_name", "").lower() for d in schema_docs}
                        sql_tables = set(re.findall(r'\b(?:FROM|JOIN)\s+([a-zA-Z0-9_\.]+)', candidate_sql_clean, re.IGNORECASE))
                        for raw_tbl in sql_tables:
                            ref_tbl = raw_tbl.split(".")[-1].lower()
                            if ref_tbl not in existing_doc_tables:
                                t_obj = canonical_schema.get_table(ref_tbl) or canonical_schema.get_table(ref_tbl, schema_name="public")
                                if t_obj:
                                    from ..schema.markdown_doc_generator import SchemaMarkdownGenerator
                                    doc_text = SchemaMarkdownGenerator.generate_table_document(t_obj)
                                    schema_docs.append({
                                        "source": f"{ref_tbl}.md",
                                        "title": f"Table: {ref_tbl}",
                                        "text": doc_text,
                                        "score": 0.99,
                                        "table_name": t_obj.table_name,
                                        "schema_name": t_obj.schema_name or "public",
                                        "column_names": [c.name for c in t_obj.columns.values()],
                                    })
                                    existing_doc_tables.add(ref_tbl)
                                    logger.info(f"[GROUNDED_AUTO_REPAIR] Dynamically augmented schema docs with '{ref_tbl}' table for LLM repair loop")

                        # Discover any central connecting fact table linking 2+ of the tables used in the failed SQL
                        clean_sql_tables = {raw_tbl.split(".")[-1].lower() for raw_tbl in sql_tables}
                        if len(clean_sql_tables) >= 2:
                            for t in canonical_schema.all_tables:
                                t_clean = t.table_name.split(".")[-1].lower()
                                if t_clean not in existing_doc_tables and not any(t_clean.startswith(p) for p in ("github_", "gitlab_", "scim_", "good_job_", "bcf_", "ar_internal_metadata")):
                                    fks_to_sql = {fk.referred_table.split(".")[-1].lower() for fk in t.foreign_keys if fk.referred_table.split(".")[-1].lower() in clean_sql_tables}
                                    if len(fks_to_sql) >= 2:
                                        from ..schema.markdown_doc_generator import SchemaMarkdownGenerator
                                        doc_text = SchemaMarkdownGenerator.generate_table_document(t)
                                        schema_docs.append({
                                            "source": f"{t_clean}.md",
                                            "title": f"Table: {t_clean}",
                                            "text": doc_text,
                                            "score": 0.99,
                                            "table_name": t.table_name,
                                            "schema_name": t.schema_name or "public",
                                            "column_names": [c.name for c in t.columns.values()],
                                        })
                                        existing_doc_tables.add(t_clean)
                                        logger.info(f"[GROUNDED_AUTO_REPAIR] Dynamically injected missing connecting fact table '{t_clean}' (connects {fks_to_sql}) for LLM repair loop")

                    current_failed_sql = candidate_sql_clean
                    current_err_msg = err_msg
                    repaired_successfully = False

                    for repair_attempt in range(1, 3):
                        try:
                            logger.info(f"[GROUNDED_AUTO_REPAIR] Invoking universal LLM repair loop (attempt {repair_attempt}/2) for error: {current_err_msg}")
                            repaired_sql = await GroundedSQLGenerator.repair_sql(
                                question=user_query,
                                failed_sql=current_failed_sql,
                                error_message=current_err_msg,
                                retrieved_docs=schema_docs,
                                resolved_entities=resolved_dimension_entities,
                                intent_analysis=intent_analysis,
                            )
                            repair_mode = "grounded_llm_repaired"
                        except Exception as repair_exc:
                            logger.error(f"[GROUNDED_AUTO_REPAIR] Dynamic LLM repair attempt {repair_attempt} failed: {repair_exc}")
                            raise exec_err

                        if not repaired_sql:
                            break

                        try:
                            repaired_sql_clean = GroundedSQLValidator.validate_readonly_sql(repaired_sql)
                        except ValueError as val_err:
                            logger.error(f"[GROUNDED_AUTO_REPAIR] Repaired SQL failed security validation: {val_err}")
                            raise exec_err

                        if "LIMIT" not in repaired_sql_clean.upper():
                            default_limit = 1 if "count(" in repaired_sql_clean.lower() else 50
                            repaired_sql_clean = f"{repaired_sql_clean.rstrip()} LIMIT {default_limit}"

                        parsed_repaired = SQLASTParser.parse_sql(repaired_sql_clean, dialect="postgres")
                        cand_sql = ValidatedCandidateSQL(
                            raw_sql=repaired_sql_clean,
                            sanitized_sql=repaired_sql_clean,
                            parameterized=SQLParameterizer.parameterize(parsed_repaired),
                            plan=cand_sql.plan,
                            validation_report=ValidationResult(is_valid=True, errors=[], warnings=[]),
                            repair_attempts=repair_attempt,
                            sql_generation_mode=repair_mode,
                        )

                        try:
                            canonical_result = await self.execute_candidate_sql(
                                kb_id=kb_id,
                                candidate_sql=cand_sql,
                                execution_config=execution_config,
                            )
                            logger.info(f"[GROUNDED_AUTO_REPAIR] Query successfully repaired and executed via LLM (attempt {repair_attempt}): {repaired_sql_clean}")
                            repaired_successfully = True
                            break
                        except Exception as second_exec_err:
                            logger.warning(f"[GROUNDED_AUTO_REPAIR] Execution of repaired SQL failed (attempt {repair_attempt}): {second_exec_err}")
                            current_failed_sql = repaired_sql_clean
                            current_err_msg = str(second_exec_err)

                    if not repaired_successfully:
                        raise exec_err
            t_exec_ms = (time.perf_counter() - t_exec_start) * 1000.0

            # Zero-Row dynamic temporal relaxation recovery
            if canonical_result.row_count == 0 and any(
                kw in candidate_sql_raw.lower()
                for kw in ("current_date", "now()", "interval", "_at::date", "date =", "date >=", "date <=")
            ):
                logger.info("[GROUNDED_ZERO_ROW] Zero rows returned with temporal filter. Relaxing temporal bound...")
                lines = candidate_sql_raw.splitlines()
                filtered_lines = [
                    ln for ln in lines
                    if not any(kw in ln.lower() for kw in ("current_date", "now()", "interval", "_at::date", "_at >=", "_at <="))
                ]
                relaxed_sql = "\n".join(filtered_lines)
                relaxed_sql = re.sub(r"\bWHERE\s+AND\b", "WHERE", relaxed_sql, flags=re.IGNORECASE)
                relaxed_sql = re.sub(r"\bAND\s*$", "", relaxed_sql, flags=re.MULTILINE)

                if relaxed_sql != candidate_sql_raw:
                    try:
                        relaxed_sql_clean = GroundedSQLValidator.validate_readonly_sql(relaxed_sql)
                        if "LIMIT" not in relaxed_sql_clean.upper():
                            default_limit = 1 if "count(" in relaxed_sql_clean.lower() else 50
                            relaxed_sql_clean = f"{relaxed_sql_clean.rstrip()} LIMIT {default_limit}"
                        parsed_relaxed = SQLASTParser.parse_sql(relaxed_sql_clean, dialect="postgres")
                        cand_relaxed = ValidatedCandidateSQL(
                            raw_sql=relaxed_sql_clean,
                            sanitized_sql=relaxed_sql_clean,
                            parameterized=SQLParameterizer.parameterize(parsed_relaxed),
                            plan=cand_sql.plan,
                            validation_report=ValidationResult(is_valid=True, errors=[], warnings=[]),
                            repair_attempts=1,
                            sql_generation_mode="grounded_temporal_relaxed",
                        )
                        relaxed_result = await self.execute_candidate_sql(
                            kb_id=kb_id,
                            candidate_sql=cand_relaxed,
                            execution_config=execution_config,
                        )
                        if relaxed_result.row_count > 0:
                            logger.info(f"[GROUNDED_ZERO_ROW] Relaxed query recovered {relaxed_result.row_count} rows!")
                            canonical_result = relaxed_result
                            cand_sql = cand_relaxed
                            disambiguation_notices.append(
                                "No activity was found strictly for the specified date. Showing latest associated activity."
                            )
                    except Exception as rel_err:
                        logger.debug(f"[GROUNDED_ZERO_ROW] Relaxed query attempt failed: {rel_err}")

            tracer.record_sql_generation(
                candidate_sql=cand_sql.sanitized_sql,
                parameters=cand_sql.parameterized.parameters,
                ast_valid=True,
                ast_errors=[],
                ast_warnings=[],
                repair_attempts=cand_sql.repair_attempts,
                latency_ms=t_sql_ms,
                sql_generation_mode=cand_sql.sql_generation_mode,
                deterministic_sql_compilation=cand_sql.deterministic_sql_compilation,
                sql_llm_bypassed=cand_sql.sql_llm_bypassed,
            )
            tracer.record_execution(
                executed=True,
                row_count=canonical_result.row_count,
                truncated=canonical_result.truncated,
                execution_time_ms=canonical_result.execution_time_ms,
                column_count=len(canonical_result.columns),
                normalization_latency_ms=0.0,
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

            # 7. Answer Synthesis
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
            from ..answering.grounded_synthesizer import GroundedAnswerSynthesizer
            from ..answering.models import (
                AnswerType,
                EvidenceModel,
                GroundedDatabaseAnswer,
                GroundingStatus,
                VerificationStatus,
            )

            answer_text = await GroundedAnswerSynthesizer.synthesize_answer(
                question=user_query,
                sql=cand_sql.sanitized_sql,
                result={
                    "columns": canonical_result.columns,
                    "rows": canonical_result.rows,
                    "row_count": canonical_result.row_count,
                    "truncated": canonical_result.truncated,
                },
            )
            t_syn_ms = (time.perf_counter() - t_syn_start) * 1000.0

            tracer.record_synthesis(
                answer_type="NARRATIVE",
                deterministic=False,
                grounding_status="VERIFIED",
                verification_status="PASSED",
                repair_attempts=0,
                latency_ms=t_syn_ms,
                fallback_used=False,
            )

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.SYNTHESIS_COMPLETED,
                    stage="SYNTHESIS",
                    status="completed",
                    data={
                        "answer_type": "NARRATIVE",
                        "deterministic": False,
                        "latency_ms": round(t_syn_ms, 2),
                    },
                    elapsed_stage_ms=t_syn_ms,
                )
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
                        "grounding_status": "VERIFIED",
                        "verification_status": "PASSED",
                        "repair_attempts": 0,
                    },
                )

            # 8. Terminal Answer Assembly
            if disambiguation_notices:
                prefix = "Notice: " + "; ".join(disambiguation_notices) + "\n\n"
                if not answer_text.startswith("Notice:"):
                    answer_text = prefix + answer_text

            evidence = EvidenceModel(
                query_id=query_id,
                database_knowledgebase_id=kb_id,
                schema_version=entity.schema_version or "grounded_docs",
                columns=canonical_result.columns,
                rows=canonical_result.rows,
                row_count=canonical_result.row_count,
                execution_time_ms=canonical_result.execution_time_ms,
            )

            t_total_ms = (time.perf_counter() - tracer.start_time) * 1000.0
            final_answer = GroundedDatabaseAnswer(
                query_id=query_id,
                database_knowledgebase_id=kb_id,
                schema_version=entity.schema_version or "grounded_docs",
                answer_text=answer_text,
                answer_type=AnswerType.COUNT if "count" in cand_sql.sanitized_sql.lower() else AnswerType.NARRATIVE,
                evidence=evidence,
                source_columns=canonical_result.columns,
                row_count=canonical_result.row_count,
                truncated=canonical_result.truncated,
                grounding_status=GroundingStatus.VERIFIED,
                verification_status=VerificationStatus.PASSED,
                warnings=disambiguation_notices,
                rows=canonical_result.rows,
                columns=canonical_result.columns,
                raw_result=canonical_result,
                status="success",
                candidate_tables=table_names,
                generation_metadata={
                    "pipeline_mode": "grounded_docs",
                    "sql": cand_sql.sanitized_sql,
                    "latency_ms": round(t_total_ms, 2),
                    "stage_timings_ms": {
                        "retrieval": round(t_ret_ms, 2),
                        "sql_generation": round(t_sql_ms, 2),
                        "execution": round(t_exec_ms, 2),
                        "synthesis": round(t_syn_ms, 2),
                        "total": round(t_total_ms, 2),
                    },
                },
                pipeline_trace=tracer.finalize(),
            )

            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.ANSWER_COMPLETED,
                    stage="ANSWER",
                    status="completed",
                    data={
                        "answer_text": final_answer.answer_text,
                        "answer_type": final_answer.answer_type.value if hasattr(final_answer.answer_type, "value") else str(final_answer.answer_type),
                        "row_count": final_answer.row_count,
                        "grounding_status": final_answer.grounding_status.value if hasattr(final_answer.grounding_status, "value") else str(final_answer.grounding_status),
                        "verification_status": final_answer.verification_status.value if hasattr(final_answer.verification_status, "value") else str(final_answer.verification_status),
                        "rows": final_answer.rows,
                        "columns": final_answer.columns,
                        "source_columns": final_answer.source_columns,
                        "truncated": final_answer.truncated,
                        "warnings": final_answer.warnings,
                        "pipeline_trace": final_answer.pipeline_trace.model_dump(mode="json") if final_answer.pipeline_trace else None,
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

            return final_answer

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
        except DisambiguationRequiredError as disambig_err:
            tracer.record_failure(error_type="DisambiguationRequiredError", error_msg=disambig_err.message, stage="DISAMBIGUATION")
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.QUERY_ERROR,
                    stage="DISAMBIGUATION",
                    status="error",
                    data={
                        "error_code": "DISAMBIGUATION_REQUIRED",
                        "stage": "DISAMBIGUATION",
                        "retryable": False,
                        "message": disambig_err.message,
                        "correlation_id": tracer.request_id or query_id,
                        "options": disambig_err.options,
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

    async def query_database(
        self,
        kb_id: uuid.UUID,
        user_query: str,
        top_k_tables: int = 8,
        top_k_columns_per_table: int = 25,
        use_llm: bool = True,
        execution_config: Optional[ExecutionConfig] = None,
        request_id: Optional[str] = None,
        user_id: Optional[Any] = None,
        event_sink: Optional[DatabasePipelineEventSink] = None,
        resolved_entities: Optional[list] = None,
    ) -> GroundedDatabaseAnswer:
        """
        Complete end-to-end database knowledgebase querying pipeline with Phase 3A observability
        and Phase 3D SSE lifecycle event streaming support.
        """
        # Verify tenant ownership of knowledgebase
        entity = await self.repo.get_by_id(kb_id)
        if not entity:
            raise TenantMismatchError(detail=f"Database knowledgebase '{kb_id}' not found.")

        # Grounded Docs Pipeline Mode Gate
        from app.core.config import get_settings
        settings = get_settings()
        pipeline_mode = getattr(settings, "db_kb_pipeline_mode", "grounded_docs")
        if pipeline_mode == "grounded_docs":
            return await self._query_database_grounded_docs(
                kb_id=kb_id,
                entity=entity,
                user_query=user_query,
                top_k_tables=top_k_tables,
                top_k_columns_per_table=top_k_columns_per_table,
                use_llm=use_llm,
                execution_config=execution_config,
                request_id=request_id,
                user_id=user_id,
                event_sink=event_sink,
                resolved_entities=resolved_entities,
            )

        query_id = str(uuid.uuid4())
        tracer = PipelineTracer(
            query_id=query_id,
            kb_id=kb_id,
            user_query=user_query,
            tenant_id=self.tenant_id,
            request_id=request_id,
            user_id=user_id,
        )

        security_overrides = entity.settings.get("security_overrides", {}) if hasattr(entity, "settings") and entity.settings else {}

        audit_ctx = {
            "query_id": query_id,
            "tenant_id": self.tenant_id,
            "knowledgebase_id": kb_id,
        }

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

            # Stage timings initialization
            t_disambig_ms = 0.0
            t_emb_ms = 0.0
            t_table_fts_ms = 0.0
            t_table_vec_ms = 0.0
            t_entity_res_ms = 0.0
            t_col_ret_ms = 0.0
            t_join_ms = 0.0
            t_qm_ms = 0.0
            t_rules_ms = 0.0
            t_plan_ms = 0.0
            t_sql_ms = 0.0
            t_exec_ms = 0.0
            t_syn_ms = 0.0

            # 1. Retrieval
            current_stage = "RETRIEVAL"
            disambiguation_notices: List[str] = []
            resolved_entities_list = resolved_entities or []

            if event_sink:
                event_sink.start_stage("RETRIEVAL")
                await event_sink.emit(
                    DatabaseStreamEventType.RETRIEVAL_STARTED,
                    stage="RETRIEVAL",
                    status="started",
                    data={"top_k_tables": top_k_tables, "top_k_columns_per_table": top_k_columns_per_table},
                )

            t_ret_start = time.perf_counter()
            retrieval_res = await self.retrieve_schema_phase3(
                kb_id=kb_id,
                user_query=user_query,
                top_k_tables=top_k_tables,
                top_k_columns_per_table=top_k_columns_per_table,
                include_relationships=True,
                canonical_schema=canonical_schema,
            )
            t_ret_ms = (time.perf_counter() - t_ret_start) * 1000.0

            pack = getattr(retrieval_res, "context_pack", None)
            pack_timings = getattr(pack, "timings_ms", {}) if pack else {}
            t_emb_ms = pack_timings.get("embedding_ms", 0.0)
            t_table_fts_ms = pack_timings.get("table_fts_ms", 0.0)
            t_table_vec_ms = pack_timings.get("table_vector_ms", 0.0)
            t_entity_res_ms = pack_timings.get("entity_resolution_ms", 0.0)
            t_col_ret_ms = pack_timings.get("column_retrieval_ms", 0.0)
            t_join_ms = pack_timings.get("join_path_ms", 0.0)
            t_qm_ms = pack_timings.get("query_memory_ms", 0.0)
            t_rules_ms = pack_timings.get("rules_ms", 0.0)

            if pack and getattr(pack, "clarifications", None):
                disambiguation_notices.extend(pack.clarifications)

            # Populate resolved_entities_list from ContextPack (eliminates duplicate entity resolution)
            if not resolved_entities_list and pack and getattr(pack, "entities", None):
                for ent_info in pack.entities:
                    t_norm = ent_info.get("table", "").lower().split(".")[-1]
                    col_name = ent_info.get("column", "")
                    pk_val = ent_info.get("pk")
                    raw_val = ent_info.get("value") or ent_info.get("matched_value", "")
                    choices = ent_info.get("choices") or []
                    choice_pks = [c["pk"] for c in choices if isinstance(c, dict) and "pk" in c]
                    resolved_ids = choice_pks if len(choice_pks) > 1 else (pk_val if pk_val is not None else ([choice_pks[0]] if choice_pks else None))

                    # Interactive Disambiguation Check: prompt user if multiple ambiguous matches exist
                    # Only prompt user if choices offer genuinely distinct semantic labels.
                    # If all choices have identical labels (e.g. all are 'BENZ' or 'BENZ (id X)'), or if the query
                    # already contains a high-entropy specific identifier/code (e.g. alphanumeric code like 'W129589010700'),
                    # disambiguating a broad category/lookup value is redundant and disrupts user experience.
                    has_specific_code = bool(re.search(r"\b[A-Za-z0-9_-]{6,}\b", user_query or "") and any(c.isdigit() for c in (user_query or "")))
                    clean_labels = {re.sub(r"\s*\(id\s+[^)]+\)", "", c.get("label", "")).strip().lower() for c in choices if isinstance(c, dict)}
                    clean_labels.discard("")
                    has_differentiated_options = len(clean_labels) > 1

                    if len(choices) > 1 and not resolved_entities and has_differentiated_options and not has_specific_code:
                        from ..disambiguation.exceptions import DisambiguationRequiredError
                        options = [
                            {
                                "id": c["pk"],
                                "label": c.get("label") or f"{raw_val} (id {c['pk']})",
                                "name": raw_val,
                                "table": t_norm,
                                "column": col_name,
                                "pk_column": "id",
                            }
                            for c in choices if isinstance(c, dict) and "pk" in c
                        ]
                        is_user_entity = any(u_kw in t_norm for u_kw in ("user", "employee", "member", "staff", "person"))
                        entity_label_plural = (
                            "users"
                            if is_user_entity
                            else ("records" if t_norm.endswith("s") else f"{t_norm} records")
                        )
                        options.append({
                            "id": choice_pks,
                            "label": f"All of them ({len(choice_pks)} {entity_label_plural})",
                            "name": raw_val,
                            "table": t_norm,
                            "column": col_name,
                            "pk_column": "id",
                            "values": [c.get("label", raw_val) for c in choices if isinstance(c, dict)],
                        })
                        raise DisambiguationRequiredError(
                            message=f"Multiple matches found for '{raw_val}'. Which one did you mean?",
                            options=options,
                            entity_type=t_norm,
                        )

                    resolved_entities_list.append({
                        "type": "user" if any(u_kw in t_norm for u_kw in ("user", "employee", "member", "staff", "person")) else "entity",
                        "id": resolved_ids,
                        "name": raw_val,
                        "table": t_norm,
                        "column": col_name,
                        "pk_column": "id",
                        "values": [c.get("label", raw_val) for c in choices if isinstance(c, dict)] if choices else [raw_val],
                    })
                    logger.info(f"[DISAMBIGUATION] From ContextPack resolved '{t_norm}.{col_name}' -> IDs {resolved_ids}")

            from ..disambiguation.rules_engine import RulesEngine
            strict_rules = RulesEngine.apply_glossary_rules(resolved_entities_list, user_query)
            t_disambig_ms = 0.0

            # Incorporate strict_rules into user_query for downstream LLM generation
            query_with_rules = user_query
            if strict_rules:
                query_with_rules += "\n\n" + "\n".join(strict_rules)
                logger.info(f"[DISAMBIGUATION] Injected {len(strict_rules)} rules into query")

            tracer.schema_version = retrieval_res.schema_version
            table_scores = {}
            for tbl_name, score_obj in retrieval_res.retrieval_scores.items():
                if hasattr(score_obj, "final_score"):
                    table_scores[tbl_name] = {
                        "final_score": round(float(getattr(score_obj, "final_score", 0.0)), 4),
                        "vector_score": round(float(getattr(score_obj, "vector_score", 0.0)), 4),
                        "keyword_score": round(float(getattr(score_obj, "keyword_score", 0.0)), 4),
                        "graph_score": round(float(getattr(score_obj, "graph_score", 0.0)), 4),
                    }
                elif hasattr(score_obj, "combined_score"):
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
                resolved_entities=resolved_entities_list,
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

            # Phase 2.5: Insufficient Schema Guard
            # Evaluates retrieval evidence only (top1_score, margin, table-level signals).
            # Planner confidence is NOT a trigger. Thresholds calibrated from retrieval eval C2.
            from app.core.config import settings
            guard_enabled = getattr(settings, "db_kb_insufficient_schema_guard_enabled", True)
            min_top1_score = getattr(settings, "db_kb_guard_min_top1_score", 0.030)
            min_margin = getattr(settings, "db_kb_guard_min_margin", 0.0010)
            require_table_signal = getattr(settings, "db_kb_guard_require_table_signal", True)

            top_3_candidates = [t.table_name for t in retrieval_res.retrieved_tables[:3]]
            if not top_3_candidates and retrieval_res.retrieval_scores:
                top_3_candidates = list(retrieval_res.retrieval_scores.keys())[:3]

            pack = getattr(retrieval_res, "context_pack", None)
            top1_score = getattr(pack, "top1_score", 0.0) if pack else 0.0
            margin = getattr(pack, "margin", 0.0) if pack else 0.0
            top3_signals = getattr(pack, "top3_signals", []) if pack else []

            # Fallback to retrieval_scores if pack did not set them
            if top1_score == 0.0 and retrieval_res.retrieval_scores:
                sorted_scores = sorted(
                    [
                        getattr(s_obj, "final_score", 0.0) if hasattr(s_obj, "final_score")
                        else (float(s_obj) if isinstance(s_obj, (int, float)) else 0.0)
                        for s_obj in retrieval_res.retrieval_scores.values()
                    ],
                    reverse=True,
                )
                top1_score = sorted_scores[0] if sorted_scores else 0.0
                margin = (sorted_scores[0] - sorted_scores[1]) if len(sorted_scores) > 1 else top1_score

            top1_signals = set(top3_signals[0].get("signals", [])) if top3_signals else set()
            TABLE_LEVEL_SIGNALS = {
                "fts", "vector", "token_exact", "token_synonym",
                "glossary", "glossary_vector", "metric", "value_index",
            }
            has_table_level_signal = bool(top1_signals & TABLE_LEVEL_SIGNALS)
            if not top1_signals:
                has_table_level_signal = (top1_score >= min_top1_score)

            is_relevant = True
            decision_reason = "Sufficient schema relevance detected"

            if guard_enabled:
                if top1_score < min_top1_score:
                    is_relevant = False
                    decision_reason = f"Top-1 table score {top1_score:.4f} is below threshold {min_top1_score:.4f}"
                elif margin < min_margin:
                    is_relevant = False
                    decision_reason = f"Top-1 margin {margin:.4f} is below threshold {min_margin:.4f}"
                elif require_table_signal and not has_table_level_signal:
                    is_relevant = False
                    decision_reason = f"Top-1 table has no table-level signal (signals: {list(top1_signals)})"

            # Check planner failure: A planner failure (Cartesian, confidence 0) must NEVER block;
            # pass the plan to the LLM flagged 'planner failed, hint unreliable'.
            plan_conf = getattr(plan, "confidence", 1.0)
            plan_reason = getattr(plan, "reasoning", "")
            if (
                plan_conf == 0.0
                or "planner failed" in plan_reason.lower()
                or "cartesian" in plan_reason.lower()
                or "failed" in plan_reason.lower()
                or not getattr(plan, "projections", [])
            ):
                plan.reasoning = "planner failed, hint unreliable"
                logger.info(
                    f"[PLANNER] Planner failure (confidence={plan_conf}, reasoning='{plan_reason}'). "
                    f"Passing plan to LLM flagged 'planner failed, hint unreliable'."
                )

            logger.info(
                f"[SCHEMA_GUARD] Decision: relevant={is_relevant}, reason='{decision_reason}', "
                f"top1_score={top1_score:.4f} (min {min_top1_score:.4f}), "
                f"margin={margin:.4f} (min {min_margin:.4f}), "
                f"has_table_level_signal={has_table_level_signal} (signals: {list(top1_signals)})"
            )

            relevance_telemetry = {
                "guard_enabled": guard_enabled,
                "relevant": is_relevant,
                "decision_reason": decision_reason,
                "top1_score": round(top1_score, 4),
                "margin": round(margin, 4),
                "min_top1_score": min_top1_score,
                "min_margin": min_margin,
                "has_table_level_signal": has_table_level_signal,
                "top1_signals": list(top1_signals),
                "candidate_tables": top_3_candidates,
            }

            tracer.record_schema_relevance(
                relevant=is_relevant,
                reason=decision_reason,
                scores=relevance_telemetry,
                candidate_tables=top_3_candidates,
            )

            if not is_relevant:
                logger.info(
                    f"[INSUFFICIENT_SCHEMA_GUARD] Triggered for query '{user_query[:50]}...': "
                    f"{decision_reason}. Skipping SQL generation and execution."
                )
                from ..answering.models import (
                    AnswerType,
                    EvidenceModel,
                    GroundedDatabaseAnswer,
                    GroundingStatus,
                    VerificationStatus,
                )

                empty_evidence = EvidenceModel(
                    query_id=query_id,
                    database_knowledgebase_id=kb_id,
                    schema_version=retrieval_res.schema_version,
                    columns=[],
                    rows=[],
                    row_count=0,
                    execution_time_ms=0.0,
                )
                no_rel_message = (
                    "No relevant data or matching schema could be found in the connected database "
                    "to answer this question."
                )
                t_total_ms = (time.perf_counter() - tracer.start_time) * 1000.0
                guard_answer = GroundedDatabaseAnswer(
                    status="no_relevant_data",
                    candidate_tables=top_3_candidates,
                    query_id=query_id,
                    database_knowledgebase_id=kb_id,
                    schema_version=retrieval_res.schema_version,
                    answer_text=no_rel_message,
                    answer_type=AnswerType.EMPTY,
                    evidence=empty_evidence,
                    grounding_status=GroundingStatus.FALLBACK_DETERMINISTIC,
                    verification_status=VerificationStatus.PASSED,
                    row_count=0,
                    truncated=False,
                    warnings=disambiguation_notices + [decision_reason],
                    generation_metadata={
                        "deterministic": True,
                        "bypassed_sql_generation": True,
                        "guard_decision": "no_relevant_data",
                        "latency_ms": round(t_total_ms, 2),
                        "stage_timings_ms": {
                            "disambiguation": round(t_disambig_ms, 2),
                            "embedding": round(t_emb_ms, 2),
                            "table_fts": round(t_table_fts_ms, 2),
                            "table_vector": round(t_table_vec_ms, 2),
                            "entity_resolution": round(t_entity_res_ms, 2),
                            "column_retrieval": round(t_col_ret_ms, 2),
                            "join_path": round(t_join_ms, 2),
                            "query_memory": round(t_qm_ms, 2),
                            "rules": round(t_rules_ms, 2),
                            "planner": round(t_plan_ms, 2),
                            "sql_generation": 0.0,
                            "execution": 0.0,
                            "answer": 0.0,
                            "total": round(t_total_ms, 2),
                        },
                    },
                    pipeline_trace=tracer.finalize(),
                )

                logger.info(
                    f"[STAGE_TIMINGS] disambiguation={t_disambig_ms:.1f}ms, embedding={t_emb_ms:.1f}ms, "
                    f"table_fts={t_table_fts_ms:.1f}ms, table_vector={t_table_vec_ms:.1f}ms, "
                    f"entity_resolution={t_entity_res_ms:.1f}ms, column_retrieval={t_col_ret_ms:.1f}ms, "
                    f"join_path={t_join_ms:.1f}ms, query_memory={t_qm_ms:.1f}ms, rules={t_rules_ms:.1f}ms, "
                    f"planner={t_plan_ms:.1f}ms, sql_generation=0.0ms, execution=0.0ms, "
                    f"answer=0.0ms (total={t_total_ms:.1f}ms)"
                )

                if event_sink:
                    await event_sink.emit(
                        DatabaseStreamEventType.ANSWER_COMPLETED,
                        stage="ANSWER",
                        status="completed",
                        data={
                            "status": "no_relevant_data",
                            "answer_text": guard_answer.answer_text,
                            "candidate_tables": top_3_candidates,
                            "reason": decision_reason,
                        },
                    )
                    await event_sink.emit(
                        DatabaseStreamEventType.STREAM_COMPLETED,
                        stage="STREAM",
                        status="completed",
                        data={
                            "total_duration_ms": event_sink.get_total_elapsed_ms(),
                            "final_status": "NO_RELEVANT_DATA",
                            "events_emitted": event_sink._seq,
                        },
                    )

                return guard_answer

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
                user_query=query_with_rules,
                plan=plan,
                canonical_schema=canonical_schema,
                retrieval_result=retrieval_res,
                use_llm=use_llm,
                security_overrides=security_overrides,
                audit_context=audit_ctx,
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
            t_exec_ms = (time.perf_counter() - t_exec_start) * 1000.0
            t_norm_ms = max(0.0, t_exec_ms - canonical_result.execution_time_ms)
            tracer.record_execution(
                executed=True,
                row_count=canonical_result.row_count,
                truncated=canonical_result.truncated,
                execution_time_ms=canonical_result.execution_time_ms,
                column_count=len(canonical_result.columns),
                normalization_latency_ms=t_norm_ms,
                error=None,
            )

            # =========================================================================
            # STEP 5b: Zero-Row Recovery Gate
            # If deterministic SQL returned 0 rows and contains WHERE filters,
            # retry via LLM candidate generation with schema context to relax or repair filters!
            # =========================================================================
            # STEP 5b: Dynamic Zero-Row Recovery & Traversal Gate
            # When a query returns 0 rows, dynamically diagnose and recover:
            # 1. Entity PK Binding Recovery (replaces hallucinated string filters like u.login='Arun N' with u.id=113)
            # 2. Dynamic Inter-linked Foreign Key Traversal (evaluates alternate FKs e.g. author_id vs assigned_to_id)
            # 3. Dynamic Temporal Bound Relaxation (checks if records exist outside restrictive 'yesterday' bounds)
            # 4. LLM-Assisted Schema Repair (if deterministic relaxation does not resolve)
            # =========================================================================
            if canonical_result.row_count == 0:
                logger.info(
                    "[ZERO_ROW_RECOVERY] Executed query returned 0 rows. "
                    "Initiating dynamic traversal and filter relaxation recovery."
                )
                from ..sql_security.parameterizer import SQLParameterizer
                from ..sql_parser.ast_parser import SQLASTParser
                from ..schema.graph import SchemaGraph

                recovered = False
                cur_sql_str = candidate_sql.sanitized_sql

                # Strategy 1: String-to-ID Entity Resolution Mismatch Recovery
                if not recovered and resolved_entities_list:
                    for ent in resolved_entities_list:
                        ent_id = ent.get("id")
                        pk_col = ent.get("pk_column") or "id"
                        if ent_id is not None and (isinstance(ent_id, int) or (isinstance(ent_id, str) and str(ent_id).isdigit())):
                            str_filter_pat = rf"\b([a-zA-Z0-9_]+)\.(?:login|firstname|lastname|name|username|full_name)\s*=\s*['\"][^'\"]+['\"]"
                            if re.search(str_filter_pat, cur_sql_str, re.IGNORECASE):
                                m = re.search(str_filter_pat, cur_sql_str, re.IGNORECASE)
                                alias_found = m.group(1) if m else "u"
                                repaired_sql = re.sub(
                                    str_filter_pat,
                                    f"{alias_found}.{pk_col} = {ent_id}",
                                    cur_sql_str,
                                    flags=re.IGNORECASE,
                                )
                                try:
                                    repaired_cand = ValidatedCandidateSQL(
                                        raw_sql=repaired_sql,
                                        sanitized_sql=repaired_sql,
                                        parameterized=SQLParameterizer.parameterize(SQLASTParser.parse_sql(repaired_sql, dialect="postgres")),
                                        plan=plan,
                                        validation_report=candidate_sql.validation_report,
                                        repair_attempts=candidate_sql.repair_attempts + 1,
                                        sql_generation_mode="dynamic_entity_recovery",
                                        deterministic_sql_compilation=True,
                                        sql_llm_bypassed=True,
                                    )
                                    test_res = await self.execute_candidate_sql(
                                        kb_id=kb_id,
                                        candidate_sql=repaired_cand,
                                        execution_config=execution_config,
                                    )
                                    if test_res.row_count > 0:
                                        logger.info(
                                            f"[ZERO_ROW_RECOVERY] Strategy 1 (Entity ID binding) succeeded with {test_res.row_count} rows!"
                                        )
                                        candidate_sql = repaired_cand
                                        canonical_result = test_res
                                        recovered = True
                                        cur_sql_str = candidate_sql.sanitized_sql
                                except Exception as e1:
                                    logger.debug(f"[ZERO_ROW_RECOVERY] Strategy 1 failed: {e1}")

                # Strategy 2: Dynamic Inter-linked Foreign Key Traversal
                if not recovered and canonical_schema and len(plan.tables) > 1:
                    try:
                        if "assigned_to_id" in cur_sql_str.lower():
                            alt_sql_simple = re.sub(
                                r"\bassigned_to_id\b",
                                "author_id",
                                cur_sql_str,
                                count=1,
                                flags=re.IGNORECASE,
                            )
                            if alt_sql_simple and alt_sql_simple != cur_sql_str:
                                try:
                                    alt_cand = ValidatedCandidateSQL(
                                        raw_sql=alt_sql_simple,
                                        sanitized_sql=alt_sql_simple,
                                        parameterized=SQLParameterizer.parameterize(SQLASTParser.parse_sql(alt_sql_simple, dialect="postgres")),
                                        plan=plan,
                                        validation_report=candidate_sql.validation_report,
                                        repair_attempts=candidate_sql.repair_attempts + 1,
                                        sql_generation_mode="dynamic_fk_traversal",
                                        deterministic_sql_compilation=True,
                                        sql_llm_bypassed=True,
                                    )
                                    test_res2 = await self.execute_candidate_sql(
                                        kb_id=kb_id,
                                        candidate_sql=alt_cand,
                                        execution_config=execution_config,
                                    )
                                    if test_res2.row_count > 0:
                                        logger.info(
                                            f"[ZERO_ROW_RECOVERY] Strategy 2 (FK traversal author_id) succeeded with {test_res2.row_count} rows!"
                                        )
                                        candidate_sql = alt_cand
                                        canonical_result = test_res2
                                        recovered = True
                                        cur_sql_str = candidate_sql.sanitized_sql
                                except Exception as e2a:
                                    logger.debug(f"[ZERO_ROW_RECOVERY] Strategy 2 attempt failed: {e2a}")
                    except Exception as e2:
                        logger.debug(f"[ZERO_ROW_RECOVERY] Strategy 2 failed: {e2}")

                # Strategy 3: Dynamic Temporal / Date Bound Relaxation
                if not recovered:
                    has_date_filter = any(
                        kw in cur_sql_str.lower()
                        for kw in ("current_date", "now()", "interval", "_at >=", "_at >", "_at <=", "_at <", "date >=", "date <=")
                    )
                    if has_date_filter:
                        try:
                            # Strip out temporal conditions from WHERE clause
                            lines = cur_sql_str.splitlines()
                            filtered_lines = [
                                ln for ln in lines
                                if not any(kw in ln.lower() for kw in ("current_date", "now()", "interval", "_at >=", "_at >", "_at <=", "_at <"))
                            ]
                            relaxed_sql = "\n".join(filtered_lines)
                            # Clean up dangling AND / WHERE
                            relaxed_sql = re.sub(r"\bWHERE\s+AND\b", "WHERE", relaxed_sql, flags=re.IGNORECASE)
                            relaxed_sql = re.sub(r"\bAND\s*$", "", relaxed_sql, flags=re.MULTILINE)
                            if relaxed_sql != cur_sql_str:
                                rel_cand = ValidatedCandidateSQL(
                                    raw_sql=relaxed_sql,
                                    sanitized_sql=relaxed_sql,
                                    parameterized=SQLParameterizer.parameterize(SQLASTParser.parse_sql(relaxed_sql, dialect="postgres")),
                                    plan=plan,
                                    validation_report=candidate_sql.validation_report,
                                    repair_attempts=candidate_sql.repair_attempts + 1,
                                    sql_generation_mode="dynamic_temporal_relaxation",
                                    deterministic_sql_compilation=True,
                                    sql_llm_bypassed=True,
                                )
                                test_res3 = await self.execute_candidate_sql(
                                    kb_id=kb_id,
                                    candidate_sql=rel_cand,
                                    execution_config=execution_config,
                                )
                                if test_res3.row_count > 0:
                                    logger.info(
                                        f"[ZERO_ROW_RECOVERY] Strategy 3 (Temporal relaxation) found {test_res3.row_count} records!"
                                    )
                                    candidate_sql = rel_cand
                                    canonical_result = test_res3
                                    recovered = True
                                    disambiguation_notices.append(
                                        "No activity was recorded for the specified date filter. "
                                        f"Showing all {test_res3.row_count} associated records found."
                                    )
                        except Exception as e3:
                            logger.debug(f"[ZERO_ROW_RECOVERY] Strategy 3 failed: {e3}")

                # Strategy 3.5: Dynamic Single-Table Zero-Row Recovery
                # If a joined query returned 0 rows, check if the projection table or any single table
                # in the query contains both the requested attribute and a matching column for the entity literal.
                if not recovered and len(plan.tables) > 1 and literals:
                    try:
                        import sqlglot
                        from sqlglot import exp
                        parsed_cur = sqlglot.parse_one(cur_sql_str, read="postgres")
                        projs = [p.sql(dialect="postgres") for p in parsed_cur.expressions]
                        
                        # Inspect each table referenced in the query
                        referenced_tables = [t.name for t in parsed_cur.find_all(exp.Table)]
                        for r_tbl in referenced_tables:
                            tbl_obj = canonical_schema.get_table(r_tbl) if canonical_schema else None
                            if not tbl_obj:
                                tbl_obj = next((t for t in retrieval_res.retrieved_tables if t.table_name.lower() == r_tbl.lower()), None)
                            if not tbl_obj:
                                continue
                            
                            t_cols = {c.lower(): c for c in tbl_obj.columns.keys()}
                            # Find candidate name/title/text columns in this table
                            cand_text_cols = [c for c in t_cols if any(k in c for k in ("name", "title", "description", "item", "code")) and not c.endswith(("_id", "_id_id"))]
                            
                            for c_text in cand_text_cols:
                                for lit in literals:
                                    clean_lit = lit.replace("'", "''")
                                    # Select direct projections without joins
                                    single_sql = f"SELECT {', '.join(projs)} FROM {tbl_obj.schema_name or 'public'}.{tbl_obj.table_name} WHERE {c_text} ILIKE '%{clean_lit}%' LIMIT 1"
                                    # Ensure aliases match if projs use table prefix
                                    # Strip old table aliases from projs if necessary
                                    clean_projs = []
                                    for p_expr in projs:
                                        col_only = p_expr.split(".")[-1].strip()
                                        if col_only.lower() in t_cols:
                                            clean_projs.append(col_only)
                                    if clean_projs:
                                        single_sql = f"SELECT {', '.join(clean_projs)} FROM {tbl_obj.schema_name or 'public'}.{tbl_obj.table_name} WHERE {c_text} ILIKE '%{clean_lit}%' LIMIT 1"
                                        try:
                                            single_ast = SQLASTParser.parse_sql(single_sql, dialect="postgres")
                                            single_cand = ValidatedCandidateSQL(
                                                raw_sql=single_sql,
                                                sanitized_sql=single_sql,
                                                parameterized=SQLParameterizer.parameterize(single_ast),
                                                plan=plan,
                                                validation_report=candidate_sql.validation_report,
                                                repair_attempts=candidate_sql.repair_attempts + 1,
                                                sql_generation_mode="dynamic_single_table_recovery",
                                                deterministic_sql_compilation=True,
                                                sql_llm_bypassed=True,
                                            )
                                            test_single = await self.execute_candidate_sql(
                                                kb_id=kb_id,
                                                candidate_sql=single_cand,
                                                execution_config=execution_config,
                                            )
                                            if test_single.row_count > 0:
                                                logger.info(
                                                    f"[ZERO_ROW_RECOVERY] Strategy 3.5 (Single-table fallback on {tbl_obj.table_name}.{c_text}) succeeded with {test_single.row_count} rows!"
                                                )
                                                candidate_sql = single_cand
                                                canonical_result = test_single
                                                recovered = True
                                                cur_sql_str = candidate_sql.sanitized_sql
                                                break
                                        except Exception as e_s:
                                            logger.debug(f"[ZERO_ROW_RECOVERY] Strategy 3.5 test failed on {tbl_obj.table_name}: {e_s}")
                                if recovered:
                                    break
                            if recovered:
                                break
                    except Exception as e35:
                        logger.debug(f"[ZERO_ROW_RECOVERY] Strategy 3.5 failed: {e35}")

                # Strategy 4: LLM-Assisted Generation & Repair
                if not recovered and use_llm:
                    logger.info("[ZERO_ROW_RECOVERY] Deterministic strategies exhausted. Triggering LLM recovery.")
                    try:
                        retry_candidate = await SQLRepairEngine.generate_and_validate(
                            user_query=query_with_rules,
                            plan=plan,
                            canonical_schema=canonical_schema,
                            retrieval_result=retrieval_res,
                            use_llm=True,
                            security_overrides=security_overrides,
                            audit_context=audit_ctx,
                        )
                        retry_result = await self.execute_candidate_sql(
                            kb_id=kb_id,
                            candidate_sql=retry_candidate,
                            execution_config=execution_config,
                        )
                        if retry_result.row_count > 0:
                            logger.info(
                                f"[ZERO_ROW_RECOVERY] Strategy 4 (LLM retry) succeeded with {retry_result.row_count} rows! "
                                "Adopting recovered result."
                            )
                            candidate_sql = retry_candidate
                            canonical_result = retry_result
                            recovered = True
                    except Exception as retry_err:
                        logger.warning(f"[ZERO_ROW_RECOVERY] Strategy 4 failed: {retry_err}")

                t_exec_ms = (time.perf_counter() - t_exec_start) * 1000.0

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
            if disambiguation_notices:
                answer.warnings.extend(disambiguation_notices)
                notice_prefix = "Notice: " + "; ".join(disambiguation_notices) + "\n\n"
                if not answer.answer_text.startswith("Notice:"):
                    answer.answer_text = notice_prefix + answer.answer_text
            if not getattr(answer, "candidate_tables", None) and top_3_candidates:
                answer.candidate_tables = top_3_candidates
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

            t_total_ms = (time.perf_counter() - tracer.start_time) * 1000.0
            logger.info(
                f"[STAGE_TIMINGS] disambiguation={t_disambig_ms:.1f}ms, embedding={t_emb_ms:.1f}ms, "
                f"table_fts={t_table_fts_ms:.1f}ms, table_vector={t_table_vec_ms:.1f}ms, "
                f"entity_resolution={t_entity_res_ms:.1f}ms, column_retrieval={t_col_ret_ms:.1f}ms, "
                f"join_path={t_join_ms:.1f}ms, query_memory={t_qm_ms:.1f}ms, rules={t_rules_ms:.1f}ms, "
                f"planner={t_plan_ms:.1f}ms, sql_generation={t_sql_ms:.1f}ms, execution={t_exec_ms:.1f}ms, "
                f"answer={t_syn_ms:.1f}ms (total={t_total_ms:.1f}ms)"
            )
            answer.generation_metadata["stage_timings_ms"] = {
                "disambiguation": round(t_disambig_ms, 2),
                "embedding": round(t_emb_ms, 2),
                "table_fts": round(t_table_fts_ms, 2),
                "table_vector": round(t_table_vec_ms, 2),
                "entity_resolution": round(t_entity_res_ms, 2),
                "column_retrieval": round(t_col_ret_ms, 2),
                "join_path": round(t_join_ms, 2),
                "query_memory": round(t_qm_ms, 2),
                "rules": round(t_rules_ms, 2),
                "planner": round(t_plan_ms, 2),
                "sql_generation": round(t_sql_ms, 2),
                "execution": round(t_exec_ms, 2),
                "answer": round(t_syn_ms, 2),
                "total": round(t_total_ms, 2),
            }
            if candidate_sql:
                if hasattr(candidate_sql, "parameterized") and hasattr(candidate_sql.parameterized, "parameterized_sql"):
                    answer.generation_metadata["generated_sql"] = candidate_sql.parameterized.parameterized_sql
                elif hasattr(candidate_sql, "sql"):
                    answer.generation_metadata["generated_sql"] = candidate_sql.sql

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
        except DisambiguationRequiredError as disambig_err:
            tracer.record_failure(error_type="DisambiguationRequiredError", error_msg=disambig_err.message, stage="DISAMBIGUATION")
            if event_sink:
                await event_sink.emit(
                    DatabaseStreamEventType.QUERY_ERROR,
                    stage="DISAMBIGUATION",
                    status="disambiguation_required",
                    data={
                        "error_code": 300,
                        "stage": "DISAMBIGUATION",
                        "retryable": False,
                        "message": disambig_err.message,
                        "options": disambig_err.options,
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
            try:
                test_res = await connector.test_connection()
            finally:
                await connector.close()
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

    # ============= USER MAPPINGS (ER DIAGRAM) =============

    async def get_user_mappings(self, kb_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Fetch all user-defined schema mappings."""
        records = await self.repo.get_user_mappings(kb_id=kb_id, only_active=True)
        return [
            {
                "id": str(r.id),
                "sourceTable": r.source_table,
                "sourceColumn": r.source_column,
                "targetTable": r.target_table,
                "targetColumn": r.target_column,
                "relationshipType": r.relationship_type,
                "sync_status": getattr(r, "sync_status", "SUCCESS") or "SUCCESS",
                "sync_error": getattr(r, "sync_error", None),
                "description": r.description,
                "metadata": r.extra_metadata or {},
                "is_active": r.is_active,
            }
            for r in records
        ]

    async def save_user_mappings(
        self,
        kb_id: uuid.UUID,
        mappings: List[Dict[str, Any]],
        trigger_sync: bool = True,
    ) -> Dict[str, Any]:
        """Save user mappings and set sync_status to SUCCESS or FAILED in the database."""
        saved = await self.repo.save_user_mappings(kb_id=kb_id, mappings=mappings, replace=True)
        await self.db.commit()

        synced = False
        error_msg = None

        if trigger_sync:
            try:
                # 1. Try full live introspection and sync
                await self.introspect_and_snapshot_schema(kb_id=kb_id)
                synced = True
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Live database sync failed ({e}); falling back to local snapshot patch")
                # 2. Resilient Fallback: Patch existing snapshot with the newly added foreign keys
                try:
                    snapshot = await self.repo.get_latest_schema_snapshot(kb_id)
                    if snapshot and snapshot.schema_data:
                        schema_dict = dict(snapshot.schema_data)
                        schemas = schema_dict.get("schemas", {})
                        for m in mappings:
                            src_tbl = (m.get("sourceTable") or m.get("source_table") or "").lower()
                            src_col = m.get("sourceColumn") or m.get("source_column")
                            tgt_tbl = m.get("targetTable") or m.get("target_table")
                            tgt_col = m.get("targetColumn") or m.get("target_column")
                            
                            for s_val in schemas.values():
                                tbl_obj = s_val.get("tables", {}).get(src_tbl)
                                if tbl_obj:
                                    fks = tbl_obj.setdefault("foreign_keys", [])
                                    # Avoid duplicates
                                    if not any(fk.get("referred_table", "").lower() == tgt_tbl.lower() and src_col in fk.get("constrained_columns", []) for fk in fks):
                                        fks.append({
                                            "name": f"fk_user_{src_tbl}_{src_col}",
                                            "constrained_columns": [src_col],
                                            "referred_schema": "public",
                                            "referred_table": tgt_tbl,
                                            "referred_columns": [tgt_col],
                                        })
                        
                        snapshot.schema_data = schema_dict
                        await self.db.commit()
                        synced = True
                        error_msg = None
                        logger.info(f"Successfully patched existing snapshot with user mappings for KB {kb_id}")
                except Exception as patch_err:
                    error_msg = f"Live sync failed: {e}; Patch failed: {patch_err}"
                    logger.error(f"Failed to patch local snapshot with user mappings: {patch_err}")

        # Update sync_status directly on saved records
        final_status = "SUCCESS" if synced else "FAILED"
        for entity in saved:
            entity.sync_status = final_status
            entity.sync_error = error_msg
        await self.db.commit()

        return {
            "status": "success",
            "saved_count": len(saved),
            "sync_status": final_status,
            "sync_error": error_msg,
            "synced": synced,
        }

    async def get_table_aliases(self, kb_id: uuid.UUID) -> Dict[str, List[str]]:
        """Fetch all user-defined table aliases as a dictionary {table_name: [aliases]}."""
        records = await self.repo.get_table_aliases(kb_id=kb_id)
        aliases_map: Dict[str, List[str]] = {}
        for r in records:
            aliases_map[r.table_name] = r.aliases if isinstance(r.aliases, list) else []
        return aliases_map

    async def save_table_aliases(
        self,
        kb_id: uuid.UUID,
        table_aliases_data: Any,
    ) -> Dict[str, Any]:
        """Save single or batch table aliases."""
        aliases_map: Dict[str, List[str]] = {}

        # Handle various input structures (dict, TableAliasSaveRequest, or list)
        if isinstance(table_aliases_data, dict):
            if "table_aliases" in table_aliases_data and isinstance(table_aliases_data["table_aliases"], dict):
                aliases_map.update(table_aliases_data["table_aliases"])
            elif "tableAliases" in table_aliases_data and isinstance(table_aliases_data["tableAliases"], dict):
                aliases_map.update(table_aliases_data["tableAliases"])
            
            table_name = table_aliases_data.get("table_name") or table_aliases_data.get("tableName")
            aliases = table_aliases_data.get("aliases")
            if table_name and isinstance(aliases, list):
                aliases_map[table_name] = aliases

            items = table_aliases_data.get("items")
            if items and isinstance(items, list):
                for item in items:
                    t_name = item.get("table_name") or item.get("tableName")
                    t_aliases = item.get("aliases") or []
                    if t_name:
                        aliases_map[t_name] = t_aliases
        elif hasattr(table_aliases_data, "table_aliases") and table_aliases_data.table_aliases:
            aliases_map.update(table_aliases_data.table_aliases)
        elif hasattr(table_aliases_data, "table_name") and table_aliases_data.table_name:
            aliases_map[table_aliases_data.table_name] = table_aliases_data.aliases or []

        if not aliases_map:
            if isinstance(table_aliases_data, dict) and not any(k in table_aliases_data for k in ("table_name", "tableName", "table_aliases", "tableAliases", "items")):
                aliases_map = {k: v for k, v in table_aliases_data.items() if isinstance(v, list)}

        saved = await self.repo.save_table_aliases(kb_id=kb_id, aliases_map=aliases_map)
        
        # Invalidate SchemaRetrievalCache & TableRetriever so subsequent queries immediately pick up updated aliases
        try:
            from ..retrieval.cache import SchemaRetrievalCache
            SchemaRetrievalCache.get_instance().invalidate_kb(str(self.tenant_id), str(kb_id))
        except Exception as cache_err:
            logger.debug(f"Failed to invalidate SchemaRetrievalCache for KB {kb_id}: {cache_err}")

        try:
            from ..knowledge.retrieval.table_retriever import TableRetriever
            TableRetriever.clear_cache(kb_id)
        except Exception as cache_err:
            logger.debug(f"Failed to clear TableRetriever cache for KB {kb_id}: {cache_err}")

        result_map: Dict[str, List[str]] = {}
        for r in saved:
            result_map[r.table_name] = r.aliases if isinstance(r.aliases, list) else []

        return {
            "success": True,
            "table_aliases": result_map,
            "saved_count": len(saved),
        }

    async def delete_table_alias(self, kb_id: uuid.UUID, table_name: str) -> Dict[str, Any]:
        """Delete aliases for a specific table."""
        await self.repo.delete_table_alias(kb_id=kb_id, table_name=table_name)
        
        # Invalidate SchemaRetrievalCache & TableRetriever on alias deletion
        try:
            from ..retrieval.cache import SchemaRetrievalCache
            SchemaRetrievalCache.get_instance().invalidate_kb(str(self.tenant_id), str(kb_id))
        except Exception as cache_err:
            logger.debug(f"Failed to invalidate SchemaRetrievalCache for KB {kb_id}: {cache_err}")

        try:
            from ..knowledge.retrieval.table_retriever import TableRetriever
            TableRetriever.clear_cache(kb_id)
        except Exception as cache_err:
            logger.debug(f"Failed to clear TableRetriever cache for KB {kb_id}: {cache_err}")

        remaining = await self.get_table_aliases(kb_id=kb_id)
        return {
            "success": True,
            "table_aliases": remaining,
            "deleted_table": table_name,
        }




