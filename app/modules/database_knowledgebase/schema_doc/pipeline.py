"""Schema Documentation ("Cheat Sheet") Pipeline Orchestrator

Executes Step 1 background pipeline after schema introspection:
1. RELATIONSHIPS FIRST: builds map of PKs, FKs, self-references, standalone tables,
   infers missing FKs (labeled 'inferred'), topological sort (parents before children).
2. PER TABLE, parents before children:
   a. FACTS by SQL/code (never LLM): data type, nullable, PK/FK, distinct count, null %, min/max, distinct values.
   b. SAMPLES: 10-20 random rows, read-only conn, statement timeout, sensitive deny-list and PII masked.
   c. LLM EXPLANATION: exact name guarantee, batched if > 20 cols, Pydantic validated, retry on missing col.
   d. EXAMPLES: questions (short, vague, synonyms, typos, multi-table) + verified SELECT returning rows > 0.
3. DENY-LIST: sensitive columns (salary, national_id, etc.) show no sample values or distinct indexes.
4. STORE: new tables (schema_doc_tables, schema_doc_columns, schema_doc_examples), status=draft|approved|stale|failed.
   Per-table hash so re-sync regenerates only changed tables.
5. EMBED: batch 32-64, starts with exact schema.table.column name, stored in schema_doc_embeddings (with tsvector).
6. LOGGING: token tracking per LLM call, job status API.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_

from app.core.database import AsyncSessionLocal
from app.core.config import get_settings
from ..schemas.canonical import DatabaseSchema, TableSchema
from ..schemas.connection import DatabaseConnectionConfig
from ..connectors.factory import ConnectorFactory
from ..models.database_knowledgebase import DatabaseKnowledgebase
from ..models.schema_doc import (
    SchemaDocJob,
    SchemaDocTable,
    SchemaDocColumn,
    SchemaDocExample,
    SchemaDocEmbedding,
)
from .mapper import RelationshipMapper, SchemaTopology, TableRelationshipMap
from .profiler import FactProfiler, TableFacts
from .sensitivity import SensitivityGuard
from .explainer import SchemaExplainer, TableExplanationOutput
from .examples import ExampleGenerator, VerifiedExample
from .embedder import SchemaDocEmbedder, DocEmbeddingItem

logger = logging.getLogger(__name__)
settings = get_settings()


class SchemaDocPipeline:
    """Orchestrates the entire schema cheat sheet generation pipeline."""

    @classmethod
    def compute_table_hash(cls, table: TableSchema) -> str:
        """Computes deterministic hash of a table's structure to skip unchanged tables on re-sync."""
        cols_summary = [
            f"{c.name}:{c.raw_data_type}:{c.is_nullable}:{c.is_primary_key}:{c.is_foreign_key}"
            for c in sorted(table.columns.values(), key=lambda x: x.name)
        ]
        fks_summary = [
            f"{f.referred_table}:{','.join(sorted(f.constrained_columns))}:{','.join(sorted(f.referred_columns))}"
            for f in sorted(table.foreign_keys, key=lambda x: (x.referred_table, str(x.constrained_columns)))
        ]
        raw_repr = f"{table.table_name}|{'|'.join(cols_summary)}|{'|'.join(fks_summary)}"
        return hashlib.sha256(raw_repr.encode("utf-8")).hexdigest()

    @classmethod
    async def run_pipeline_background(
        cls,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
        schema: DatabaseSchema,
        config: DatabaseConnectionConfig,
        job_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Entrypoint for background task execution with isolated session."""
        try:
            async with AsyncSessionLocal() as session:
                pipeline = cls(session=session, tenant_id=tenant_id, kb_id=kb_id, schema=schema, config=config, job_id=job_id)
                await pipeline.execute()
        except Exception as e:
            logger.error(f"Fatal error in SchemaDocPipeline for KB {kb_id}: {e}", exc_info=True)

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
        schema: DatabaseSchema,
        config: DatabaseConnectionConfig,
        job_id: Optional[uuid.UUID] = None,
    ):
        self.session = session
        self.tenant_id = tenant_id
        self.kb_id = kb_id
        self.schema = schema
        self.config = config
        self.schema_version = schema.fingerprint
        self.job_id = job_id or uuid.uuid4()
        self.explainer = SchemaExplainer()
        self.example_gen = ExampleGenerator()
        self.tokens_tracker: Dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0}

    async def execute(self) -> None:
        """Executes the full pipeline stages."""
        logger.info(f"Starting SchemaDocPipeline for KB {self.kb_id}, schema_version={self.schema_version[:8]}")

        # 1. Initialize Job record
        job = await self._get_or_create_job()
        table_errors: Dict[str, str] = {}

        try:
            # Stage 1: RELATIONSHIPS FIRST
            await self._update_job_status("mapping", step="Analyzing relationships and topology", progress_current=0)
            topology: SchemaTopology = RelationshipMapper.build_topology(self.schema)
            logger.info(f"Topology built: {len(topology.tables)} tables, order: {topology.processing_order}")

            # Mark old schema_version records as stale
            await self._mark_old_versions_stale()

            # Connect to target DB for facts profiling and example query execution
            connector = ConnectorFactory.create_connector(self.config)
            conn = await connector._get_raw_connection()

            all_embedding_items: List[DocEmbeddingItem] = []
            tables_to_process = topology.processing_order
            total_tables = len(tables_to_process)
            await self._update_job_status("explaining", total=total_tables, progress_current=0)

            try:
                for idx, t_name in enumerate(tables_to_process):
                    table_schema = self.schema.get_table(t_name)
                    if not table_schema:
                        continue

                    rel_map = topology.tables.get(t_name, TableRelationshipMap(table_name=t_name))
                    current_hash = self.compute_table_hash(table_schema)

                    await self._update_job_status(
                        "explaining",
                        step=f"Processing table {idx+1}/{total_tables}: {t_name}",
                        progress_current=idx,
                    )

                    # Check if table already documented with identical hash in this version (idempotent / unchanged)
                    existing_table = await self._get_existing_table_doc(t_name)
                    if existing_table and existing_table.table_hash == current_hash and existing_table.status in ("approved", "draft"):
                        logger.info(f"Table '{t_name}' unchanged (hash match {current_hash[:8]}). Skipping LLM regeneration.")
                        continue

                    # a. Compute Facts & Masked Samples
                    facts: TableFacts = await FactProfiler.profile_table(conn, table_schema)

                    # b. LLM Explanation (exact names, batched if > 20 cols, validated with Pydantic)
                    explanation: Optional[TableExplanationOutput] = await self.explainer.explain_table(
                        tenant_id=str(self.tenant_id),
                        facts=facts,
                        relationship_map=rel_map,
                        total_tokens_tracker=self.tokens_tracker,
                    )

                    if not explanation:
                        table_errors[t_name] = "LLM explanation failed or missed columns after retry"
                        # Record failed table doc
                        await self._save_table_doc(
                            table=table_schema,
                            table_hash=current_hash,
                            status="failed",
                            facts=facts,
                            rel_map=rel_map,
                            explanation=None,
                        )
                        continue

                    # c. Example Questions & SQL Verification
                    verified_examples: List[VerifiedExample] = await self.example_gen.generate_and_verify_examples(
                        conn=conn,
                        tenant_id=str(self.tenant_id),
                        table=table_schema,
                        schema=self.schema,
                        relationship_map=rel_map,
                        total_tokens_tracker=self.tokens_tracker,
                    )

                    # d. Store in DB
                    table_doc = await self._save_table_doc(
                        table=table_schema,
                        table_hash=current_hash,
                        status="draft",
                        facts=facts,
                        rel_map=rel_map,
                        explanation=explanation,
                    )

                    # Save Columns docs
                    await self._save_column_docs(table_doc=table_doc, facts=facts, explanation=explanation)

                    # Save Examples
                    await self._save_example_docs(table_doc=table_doc, examples=verified_examples)

                    # Prepare embedding items
                    # 1) Table doc text
                    table_embed_text = (
                        f"Table {table_doc.table_name}: {table_doc.ai_purpose}. "
                        f"Synonyms: {', '.join(table_doc.ai_synonyms or [])}. "
                        f"Relationships: {rel_map.relationship_summary}."
                    )
                    all_embedding_items.append(
                        DocEmbeddingItem(
                            item_type="table_doc",
                            item_key=f"{table_schema.schema_name}.{table_schema.table_name}",
                            exact_identifier=f"{table_schema.schema_name}.{table_schema.table_name}",
                            document_text=table_embed_text,
                            metadata_json={"table_name": table_schema.table_name, "status": "draft"},
                        )
                    )

                    # 2) Column doc texts
                    for col_doc in explanation.columns:
                        c_info = facts.columns.get(col_doc.column_id, {})
                        is_sens = c_info.get("is_sensitive", False)
                        col_text = f"Column {table_schema.table_name}.{col_doc.column_id} ({c_info.get('data_type')}): {col_doc.meaning}."
                        if col_doc.synonyms:
                            col_text += f" Synonyms: {', '.join(col_doc.synonyms)}."
                        if not is_sens and c_info.get("distinct_values"):
                            col_text += f" Distinct values: {c_info.get('distinct_values')}."

                        all_embedding_items.append(
                            DocEmbeddingItem(
                                item_type="column_doc",
                                item_key=f"{table_schema.schema_name}.{table_schema.table_name}.{col_doc.column_id}",
                                exact_identifier=f"{table_schema.schema_name}.{table_schema.table_name}.{col_doc.column_id}",
                                document_text=col_text,
                                metadata_json={"table_name": table_schema.table_name, "column_name": col_doc.column_id, "is_sensitive": is_sens},
                            )
                        )

                    # 3) Example questions
                    for ex in verified_examples:
                        ex_text = f"Question for {table_schema.table_name}: {ex.question}. SQL: {ex.sql_query}"
                        all_embedding_items.append(
                            DocEmbeddingItem(
                                item_type="example_question",
                                item_key=f"{table_schema.schema_name}.{table_schema.table_name}.ex_{uuid.uuid4().hex[:8]}",
                                exact_identifier=f"{table_schema.schema_name}.{table_schema.table_name}",
                                document_text=ex_text,
                                metadata_json={"table_name": table_schema.table_name, "question": ex.question, "sql": ex.sql_query},
                            )
                        )

            finally:
                if conn:
                    await conn.close()

            # Stage 5: EMBEDDING
            if all_embedding_items:
                await self._update_job_status("embedding", step=f"Embedding {len(all_embedding_items)} documentation entities")
                await SchemaDocEmbedder.embed_and_store_items(
                    session=self.session,
                    tenant_id=self.tenant_id,
                    kb_id=self.kb_id,
                    schema_version=self.schema_version,
                    items=all_embedding_items,
                )

            # Finalize Job
            final_status = "done" if not table_errors else ("failed" if len(table_errors) == total_tables else "done")
            await self._update_job_status(
                final_status,
                step="Pipeline execution completed",
                progress_current=total_tables,
                table_errors=table_errors,
            )
            await self.session.commit()
            logger.info(f"SchemaDocPipeline finished for KB {self.kb_id} with status={final_status}")

        except Exception as e:
            await self.session.rollback()
            logger.error(f"Pipeline error for KB {self.kb_id}: {e}", exc_info=True)
            await self._update_job_status("failed", step="Pipeline failed", error_message=str(e), table_errors=table_errors)
            await self.session.commit()

    async def _get_or_create_job(self) -> SchemaDocJob:
        job = await self.session.get(SchemaDocJob, self.job_id)
        if not job:
            job = SchemaDocJob(
                id=self.job_id,
                tenant_id=self.tenant_id,
                db_knowledgebase_id=self.kb_id,
                schema_version=self.schema_version,
                status="queued",
                progress_current=0,
                progress_total=len(self.schema.all_tables),
                current_step="Queued",
                tokens_used=self.tokens_tracker,
            )
            self.session.add(job)
            await self.session.flush()
        return job

    async def _update_job_status(
        self,
        status: str,
        step: Optional[str] = None,
        progress_current: Optional[int] = None,
        total: Optional[int] = None,
        error_message: Optional[str] = None,
        table_errors: Optional[Dict[str, str]] = None,
    ) -> None:
        job = await self.session.get(SchemaDocJob, self.job_id)
        if job:
            job.status = status
            if step is not None:
                job.current_step = step
            if progress_current is not None:
                job.progress_current = progress_current
            if total is not None:
                job.progress_total = total
            if error_message is not None:
                job.error_message = error_message
            if table_errors is not None:
                job.table_errors = table_errors
            job.tokens_used = dict(self.tokens_tracker)
            await self.session.flush()

    async def _mark_old_versions_stale(self) -> None:
        """Mark previous schema version tables as 'stale'."""
        stale_stmt = (
            update(SchemaDocTable)
            .where(
                SchemaDocTable.tenant_id == self.tenant_id,
                SchemaDocTable.db_knowledgebase_id == self.kb_id,
                SchemaDocTable.schema_version != self.schema_version,
            )
            .values(status="stale")
        )
        await self.session.execute(stale_stmt)
        await self.session.flush()

    async def _get_existing_table_doc(self, table_name: str) -> Optional[SchemaDocTable]:
        stmt = select(SchemaDocTable).where(
            SchemaDocTable.tenant_id == self.tenant_id,
            SchemaDocTable.db_knowledgebase_id == self.kb_id,
            SchemaDocTable.schema_version == self.schema_version,
            SchemaDocTable.table_name == table_name,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def _save_table_doc(
        self,
        table: TableSchema,
        table_hash: str,
        status: str,
        facts: TableFacts,
        rel_map: TableRelationshipMap,
        explanation: Optional[TableExplanationOutput],
    ) -> SchemaDocTable:
        existing = await self._get_existing_table_doc(table.table_name)
        
        # Facts json summary
        facts_data = {
            "total_rows": facts.total_rows,
            "column_count": len(facts.columns),
            "columns": facts.columns,
        }
        rel_data = rel_map.model_dump()

        if existing:
            existing.table_hash = table_hash
            existing.status = status
            existing.facts_json = facts_data
            existing.relationships_json = rel_data
            if explanation:
                existing.ai_purpose = explanation.table_purpose
                existing.ai_synonyms = explanation.synonyms
                existing.ai_caveats = explanation.caveats
                existing.ai_raw_explanation = explanation.model_dump()
            await self.session.flush()
            return existing

        table_doc = SchemaDocTable(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            db_knowledgebase_id=self.kb_id,
            schema_version=self.schema_version,
            table_schema=table.schema_name,
            table_name=table.table_name,
            table_hash=table_hash,
            status=status,
            facts_json=facts_data,
            relationships_json=rel_data,
            ai_purpose=explanation.table_purpose if explanation else None,
            ai_synonyms=explanation.synonyms if explanation else [],
            ai_caveats=explanation.caveats if explanation else None,
            ai_raw_explanation=explanation.model_dump() if explanation else None,
        )
        self.session.add(table_doc)
        await self.session.flush()
        return table_doc

    async def _save_column_docs(
        self,
        table_doc: SchemaDocTable,
        facts: TableFacts,
        explanation: TableExplanationOutput,
    ) -> None:
        # Delete existing columns for clean idempotency
        del_stmt = delete(SchemaDocColumn).where(SchemaDocColumn.table_doc_id == table_doc.id)
        await self.session.execute(del_stmt)

        expl_map = {c.column_id: c for c in explanation.columns}

        col_records = []
        for cname, cinfo in facts.columns.items():
            c_expl = expl_map.get(cname)
            is_sens = cinfo.get("is_sensitive", False)

            col_rec = SchemaDocColumn(
                id=uuid.uuid4(),
                tenant_id=self.tenant_id,
                db_knowledgebase_id=self.kb_id,
                schema_version=self.schema_version,
                table_doc_id=table_doc.id,
                table_schema=table_doc.table_schema,
                table_name=table_doc.table_name,
                column_name=cname,
                is_sensitive=is_sens,
                data_type=cinfo.get("data_type", "unknown"),
                is_nullable=cinfo.get("is_nullable", True),
                is_primary_key=cinfo.get("is_primary_key", False),
                is_foreign_key=cinfo.get("is_foreign_key", False),
                distinct_count=None if is_sens else cinfo.get("distinct_count"),
                null_percentage=None if is_sens else cinfo.get("null_percentage"),
                min_value=None if is_sens else cinfo.get("min_value"),
                max_value=None if is_sens else cinfo.get("max_value"),
                distinct_values=None if is_sens else cinfo.get("distinct_values"),
                ai_meaning=c_expl.meaning if c_expl else None,
                ai_synonyms=c_expl.synonyms if c_expl else [],
                ai_coded_values=c_expl.coded_values if c_expl else None,
            )
            col_records.append(col_rec)

        self.session.add_all(col_records)
        await self.session.flush()

    async def _save_example_docs(
        self,
        table_doc: SchemaDocTable,
        examples: List[VerifiedExample],
    ) -> None:
        del_stmt = delete(SchemaDocExample).where(SchemaDocExample.table_doc_id == table_doc.id)
        await self.session.execute(del_stmt)

        ex_records = []
        for ex in examples:
            rec = SchemaDocExample(
                id=uuid.uuid4(),
                tenant_id=self.tenant_id,
                db_knowledgebase_id=self.kb_id,
                schema_version=self.schema_version,
                table_doc_id=table_doc.id,
                question=ex.question,
                question_type=ex.question_type,
                sql_query=ex.sql_query,
                status=ex.status,
                execution_row_count=ex.row_count,
                execution_time_ms=ex.execution_time_ms,
            )
            ex_records.append(rec)

        self.session.add_all(ex_records)
        await self.session.flush()
