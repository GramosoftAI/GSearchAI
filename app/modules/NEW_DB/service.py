"""NewDBService Orchestration Layer

Coordinates connection management, fast deterministic introspection,
Markdown cheat sheet generation, pgvector indexing, and grounded execution.
Zero heavy 7-stage background jobs - pure, fast, grounded architecture.
"""

import time
import uuid
import logging
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.modules.database_knowledgebase.models.database_knowledgebase import (
    DatabaseKnowledgebase,
    DatabaseSchemaSnapshot,
)
from app.modules.database_knowledgebase.models.embeddings import DatabaseSchemaEmbedding
from .schemas import (
    DBConnectionConfig,
    ConnectionTestResult,
    CanonicalSchema,
    SyncResult,
    QueryResponse,
)
from .connection import DatabaseConnector, CredentialVault
from .introspector import SchemaIntrospector
from .doc_generator import MarkdownDocGenerator
from .indexer import TableDocIndexer
from .retriever import TableDocRetriever
from .entity_resolver import EntityResolver
from .sql_generator import SQLGenerator
from .validator import SQLValidator
from .executor import QueryExecutor
from .synthesizer import AnswerSynthesizer

def convert_canonical_to_database_schema(schema: Any) -> Any:
    """
    Converts NEW_DB CanonicalSchema or dictionary into standard DatabaseSchema
    so that frontend 'Explore Schema' and existing endpoints work seamlessly.
    """
    from app.modules.database_knowledgebase.schemas.canonical import (
        DatabaseSchema,
        SchemaInfo,
        TableSchema,
        ColumnSchema,
        ColumnDataType,
        PrimaryKeySchema,
        ForeignKeySchema,
        RelationshipSchema,
        RelationshipType,
    )
    from app.modules.database_knowledgebase.schema.normalizer import PG_TYPE_MAP

    if isinstance(schema, DatabaseSchema):
        return schema

    if isinstance(schema, dict):
        if "schemas" in schema and "tables" not in schema:
            return DatabaseSchema(**schema)
        from .schemas import CanonicalSchema
        schema = CanonicalSchema(**schema)

    schemas_dict: Dict[str, SchemaInfo] = {}

    for tbl in schema.tables:
        s_name = tbl.schema_name or "public"
        if s_name not in schemas_dict:
            schemas_dict[s_name] = SchemaInfo(schema_name=s_name, tables={})

        columns_dict: Dict[str, ColumnSchema] = {}
        for idx, col in enumerate(tbl.columns, start=1):
            raw_t = (col.data_type or "text").lower().strip()
            dt = PG_TYPE_MAP.get(raw_t)
            if not dt:
                for k, v in PG_TYPE_MAP.items():
                    if k in raw_t:
                        dt = v
                        break
            if not dt:
                dt = ColumnDataType.OTHER

            extra_meta = {}
            if col.sample_values:
                extra_meta["sample_values"] = col.sample_values

            columns_dict[col.name] = ColumnSchema(
                name=col.name,
                data_type=dt,
                raw_data_type=col.data_type or "text",
                is_nullable=col.is_nullable,
                default_value=col.default_value,
                is_primary_key=col.is_primary_key,
                is_foreign_key=col.is_foreign_key,
                comment=col.description,
                ordinal_position=idx,
                classification="GENERAL",
                default_projection=True,
                extra_metadata=extra_meta,
            )

        pk_schema = None
        if tbl.primary_keys:
            pk_schema = PrimaryKeySchema(
                name=f"pk_{tbl.table_name}",
                constrained_columns=tbl.primary_keys,
            )

        fk_list = []
        rel_list = []
        for fk in tbl.foreign_keys:
            fk_name = f"fk_{tbl.table_name}_{fk.column_name}"
            fk_list.append(
                ForeignKeySchema(
                    name=fk_name,
                    constrained_columns=[fk.column_name],
                    referred_schema=fk.target_schema or "public",
                    referred_table=fk.target_table,
                    referred_columns=[fk.target_column],
                )
            )
            rel_list.append(
                RelationshipSchema(
                    source_schema=s_name,
                    source_table=tbl.table_name,
                    source_columns=[fk.column_name],
                    target_schema=fk.target_schema or "public",
                    target_table=fk.target_table,
                    target_columns=[fk.target_column],
                    relationship_type=RelationshipType.MANY_TO_ONE,
                    foreign_key_name=fk_name,
                )
            )

        table_schema = TableSchema(
            schema_name=s_name,
            table_name=tbl.table_name,
            table_type="VIEW" if tbl.is_view else "TABLE",
            comment=f"Markdown cheat sheet generated: {len(tbl.markdown_doc)} chars" if tbl.markdown_doc else None,
            columns=columns_dict,
            primary_key=pk_schema,
            foreign_keys=fk_list,
            relationships=rel_list,
            indexes=[],
            row_count_estimate=tbl.row_count,
        )
        schemas_dict[s_name].tables[tbl.table_name] = table_schema

    db_schema = DatabaseSchema(
        database_name=schema.database_name,
        database_type=schema.database_type or "postgresql",
        schemas=schemas_dict,
        fingerprint=schema.fingerprint,
        introspected_at=schema.introspected_at,
        metadata={"source": "NEW_DB", "table_count": len(schema.tables)},
    )
    db_schema.compute_summary()
    return db_schema


class NewDBService:
    """Service implementing the streamlined Grounded Docs architecture for NEW_DB."""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))

    async def test_adhoc_connection(self, config: DBConnectionConfig) -> ConnectionTestResult:
        """Test a database connection before saving."""
        return await DatabaseConnector.test_connection(config)

    async def register_database(
        self, user_id: uuid.UUID, name: str, config: DBConnectionConfig, description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Save encrypted credentials and register database knowledgebase."""
        encrypted = CredentialVault.encrypt_config(config)
        kb_id = uuid.uuid4()

        kb = DatabaseKnowledgebase(
            id=kb_id,
            tenant_id=self.tenant_id,
            user_id=user_id,
            name=name,
            description=description,
            database_type=config.db_type.value,
            encrypted_credentials=encrypted,
            status="connected",
        )
        self.db.add(kb)
        await self.db.commit()

        return {
            "id": str(kb.id),
            "name": kb.name,
            "database_type": kb.database_type,
            "masked_dsn": config.masked_dsn,
            "status": kb.status,
        }

    async def get_connection_config(self, kb_id: uuid.UUID) -> Tuple[DatabaseKnowledgebase, DBConnectionConfig]:
        """Retrieve and decrypt credentials for a registered knowledgebase."""
        stmt = select(DatabaseKnowledgebase).where(
            DatabaseKnowledgebase.id == kb_id,
            DatabaseKnowledgebase.tenant_id == self.tenant_id,
        )
        res = await self.db.execute(stmt)
        kb = res.scalar_one_or_none()
        if not kb:
            raise ValueError(f"Database knowledgebase '{kb_id}' not found.")

        config = CredentialVault.decrypt_config(kb.encrypted_credentials)
        return kb, config

    async def sync_database(self, kb_id: uuid.UUID) -> SyncResult:
        """
        FAST SYNC PIPELINE:
        1. Deterministic Schema Introspection (tables, columns, PK, FK).
        2. Generate Markdown Cheat Sheets for each table.
        3. Vector Embed & Store Cheat Sheets in PostgreSQL pgvector.
        Completed in seconds without any heavy 7-stage profiling queue!
        """
        start_time = time.perf_counter()
        kb, config = await self.get_connection_config(kb_id)

        # 1. Deterministic Introspection
        canonical_schema = await SchemaIntrospector.introspect(config)

        # 2. Generate Markdown Cheat Sheets for each table
        for table in canonical_schema.tables:
            table.markdown_doc = MarkdownDocGenerator.generate_table_markdown_deterministic(
                table=table,
                all_tables=canonical_schema.tables,
            )

        # 3. Store Snapshot (in standard DatabaseSchema format for UI and endpoint compatibility)
        db_canonical_schema = convert_canonical_to_database_schema(canonical_schema)
        snapshot_data = db_canonical_schema.model_dump(mode="json")
        total_cols = sum(len(t.columns) for t in canonical_schema.tables)

        snapshot = DatabaseSchemaSnapshot(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            db_knowledgebase_id=kb_id,
            schema_version=canonical_schema.fingerprint,
            schema_data=snapshot_data,
            table_count=len(canonical_schema.tables),
            column_count=total_cols,
            relationship_count=sum(len(t.foreign_keys) for t in canonical_schema.tables),
        )
        self.db.add(snapshot)

        # 4. Embed into pgvector
        indexed_count = await TableDocIndexer.index_canonical_schema_docs(
            session=self.db,
            tenant_id=self.tenant_id,
            kb_id=kb_id,
            schema=canonical_schema,
        )

        # 5. Update KB state
        kb.status = "ready"
        kb.schema_version = canonical_schema.fingerprint
        await self.db.commit()

        elapsed = round(time.perf_counter() - start_time, 2)
        return SyncResult(
            success=True,
            kb_id=kb_id,
            schema_version=canonical_schema.fingerprint,
            table_count=len(canonical_schema.tables),
            column_count=total_cols,
            docs_generated=len(canonical_schema.tables),
            embeddings_indexed=indexed_count,
            elapsed_seconds=elapsed,
            message=f"Successfully synced and indexed {len(canonical_schema.tables)} tables in {elapsed}s",
        )

    async def query_database(
        self,
        kb_id: uuid.UUID,
        user_query: str,
        top_k: int = 6,
        model: Optional[str] = None,
        resolved_entities: Optional[List[Dict[str, Any]]] = None,
    ) -> QueryResponse:
        """
        GROUNDED QUERY PIPELINE:
        1. Retrieve top-K table Markdown cheat sheets via pgvector cosine distance.
        2. Resolve live concrete entities (e.g. Arun -> User ID 113).
        3. Generate grounded PostgreSQL via DeepSeek / OpenAI.
        4. Validate read-only AST safety via sqlglot.
        5. Execute query on client database with statement timeout and Zero-Row recovery.
        6. Synthesize executive natural-language answer with evidence rows.
        """
        kb, config = await self.get_connection_config(kb_id)

        # 1. Retrieve top-K table markdown docs from pgvector
        retrieved_docs = await TableDocRetriever.retrieve_relevant_docs(
            session=self.db,
            tenant_id=self.tenant_id,
            kb_id=kb_id,
            user_query=user_query,
            top_k=top_k,
        )

        if not retrieved_docs:
            raise ValueError("No schema context found. Please run sync on this database first.")

        candidate_table_names = [d.get("table_name", "") for d in retrieved_docs]

        # 2. Dynamic Entity Resolution (User identification)
        resolved_users_list: List[Dict[str, Any]] = []
        disambiguation_notice = None
        disambig_options = None

        if resolved_entities:
            for ent in resolved_entities:
                if ent.get("id"):
                    resolved_users_list.append({
                        "id": ent.get("id"),
                        "name": ent.get("name") or ent.get("label"),
                        "role": ent.get("role"),
                        "suggested_columns": ent.get("suggested_columns", ["user_id", "author_id", "assigned_to_id"]),
                    })
        else:
            try:
                users = await EntityResolver.get_all_users(config)
                resolution_res = EntityResolver.resolve_all_user_entities(user_query, users)
                ambiguous = resolution_res.get("ambiguous_entities", [])
                if ambiguous:
                    first_amb = ambiguous[0]
                    disambig_options = [
                        {
                            "id": c.get("id"),
                            "name": f"{c.get('firstname', '')} {c.get('lastname', '')}".strip() or c.get("login"),
                            "login": c.get("login", ""),
                        }
                        for c in first_amb.get("candidates", [])[:8]
                    ]
                    disambiguation_notice = f"Found multiple matching users for '{first_amb.get('matched_term')}'"
                else:
                    resolved_users_list = resolution_res.get("resolved_users", [])
                    if resolution_res.get("notices"):
                        disambiguation_notice = "; ".join(resolution_res.get("notices"))
            except Exception as e:
                logger.debug(f"[NEW_DB] User entity resolution skipped: {e}")

        # 3. Grounded SQL Generation
        generated_sql_raw = await SQLGenerator.generate_sql(
            question=user_query,
            retrieved_docs=retrieved_docs,
            resolved_users=resolved_users_list,
            model=model,
        )

        # 4. AST Validation & Read-Only Policy Enforcement
        validated_sql = SQLValidator.validate_and_sanitize(generated_sql_raw)

        # 5. Read-Only Database Execution (with Zero-Row recovery)
        rows, columns, row_count, exec_ms, truncated, temporal_notice = await QueryExecutor.execute_query(
            config=config,
            sql=validated_sql,
            timeout_seconds=30.0,
            max_rows=200,
        )

        if temporal_notice:
            disambiguation_notice = (
                f"{disambiguation_notice} | {temporal_notice}" if disambiguation_notice else temporal_notice
            )

        # 6. Natural Language Answer Synthesis
        answer_text = await AnswerSynthesizer.synthesize(
            question=user_query,
            sql=validated_sql,
            rows=rows,
            columns=columns,
            row_count=row_count,
            truncated=truncated,
            model=model,
        )

        return QueryResponse(
            success=True,
            query=user_query,
            answer=answer_text,
            sql=validated_sql,
            rows=rows,
            columns=columns,
            row_count=row_count,
            truncated=truncated,
            execution_time_ms=exec_ms,
            candidate_tables=candidate_table_names,
            disambiguation_notice=disambiguation_notice,
            disambiguation_options=disambig_options,
        )

    async def get_table_docs(self, kb_id: uuid.UUID, table_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch generated Markdown cheat sheets for review."""
        stmt = select(
            DatabaseSchemaEmbedding.entity_key,
            DatabaseSchemaEmbedding.document_text,
            DatabaseSchemaEmbedding.metadata_json,
        ).where(
            DatabaseSchemaEmbedding.tenant_id == self.tenant_id,
            DatabaseSchemaEmbedding.db_knowledgebase_id == kb_id,
            DatabaseSchemaEmbedding.entity_type == "table_doc",
        )
        if table_name:
            stmt = stmt.where(DatabaseSchemaEmbedding.entity_key.ilike(f"%{table_name}"))

        res = await self.db.execute(stmt)
        rows = res.all()
        return [
            {
                "table_name": r.entity_key,
                "text": r.document_text,
                "metadata": r.metadata_json,
            }
            for r in rows
        ]
