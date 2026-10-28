"""Grounded Schema Document Retriever using PostgreSQL pgvector

Retrieves the top-K most relevant table Markdown documents for a natural-language
query, ensuring the SQL generator LLM has only the minimal necessary context.
"""

import uuid
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.embeddings import EmbeddingGenerator
from app.modules.database_knowledgebase.models.embeddings import DatabaseSchemaEmbedding
from .schemas import CanonicalSchema
from .doc_generator import MarkdownDocGenerator

logger = logging.getLogger(__name__)


class TableDocRetriever:
    """Retrieves relevant table documentation using pgvector cosine distance."""

    @classmethod
    async def retrieve_relevant_docs(
        cls,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
        user_query: str,
        top_k: int = 6,
        schema: Optional[CanonicalSchema] = None,
    ) -> List[Dict[str, Any]]:
        """
        Embeds the question and retrieves top_k table Markdown docs via pgvector.
        Falls back to keyword matching if pgvector has no embeddings yet.
        """
        try:
            query_vector = await EmbeddingGenerator.generate_embedding(user_query)

            stmt = select(
                DatabaseSchemaEmbedding.entity_key,
                DatabaseSchemaEmbedding.document_text,
                DatabaseSchemaEmbedding.metadata_json,
                (1 - DatabaseSchemaEmbedding.embedding.cosine_distance(query_vector)).label("similarity"),
            ).where(
                DatabaseSchemaEmbedding.tenant_id == tenant_id,
                DatabaseSchemaEmbedding.db_knowledgebase_id == kb_id,
                DatabaseSchemaEmbedding.entity_type == "table_doc",
            ).order_by(
                DatabaseSchemaEmbedding.embedding.cosine_distance(query_vector)
            ).limit(top_k)

            res = await session.execute(stmt)
            rows = res.all()

            if rows:
                docs = []
                for r in rows:
                    meta = r.metadata_json or {}
                    docs.append({
                        "source": meta.get("source", f"{r.entity_key}.md"),
                        "title": meta.get("title", f"Table: {r.entity_key}"),
                        "text": r.document_text,
                        "score": float(r.similarity) if r.similarity is not None else 0.0,
                        "table_name": meta.get("table_name", r.entity_key.split(".")[-1]),
                        "schema_name": meta.get("schema_name", "public"),
                        "column_names": meta.get("column_names", []),
                    })
                logger.info(f"[NEW_DB] Retrieved {len(docs)} table docs via pgvector for query: '{user_query[:50]}'")
                return docs
        except Exception as e:
            logger.warning(f"[NEW_DB] pgvector retrieval encountered error or empty index: {e}")

        # Fallback: if no embeddings exist, match against schema tables in memory
        if schema and schema.tables:
            logger.info(f"[NEW_DB] Using fallback in-memory matching for {len(schema.tables)} tables")
            q_lower = user_query.lower()
            scored = []
            for t in schema.tables:
                score = 0.0
                t_low = t.table_name.lower()
                if t_low in q_lower:
                    score += 10.0
                for c in t.columns:
                    if c.name.lower() in q_lower:
                        score += 2.0
                doc_text = t.markdown_doc or MarkdownDocGenerator.generate_table_markdown_deterministic(t, schema.tables)
                scored.append((score, {
                    "source": f"{t.table_name}.md",
                    "title": f"Table: {t.table_name}",
                    "text": doc_text,
                    "score": score,
                    "table_name": t.table_name,
                    "schema_name": t.schema_name,
                    "column_names": [c.name for c in t.columns],
                }))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [d for _, d in scored[:top_k]]

        return []
