"""Schema Document Retriever using PostgreSQL pgvector

Retrieves AI-understandable table Markdown documents using cosine distance
against db_schema_embeddings, directly implementing the semantic retrieval
pattern proven in D:\\DB\\main.
"""

import uuid
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.embeddings import EmbeddingGenerator
from ..models.embeddings import DatabaseSchemaEmbedding
from ..models.database_knowledgebase import DatabaseSchemaSnapshot
from ..schemas.canonical import DatabaseSchema
from ..schema.markdown_doc_generator import SchemaMarkdownGenerator

logger = logging.getLogger(__name__)


class SchemaDocRetriever:
    """Retrieves AI-understandable schema markdown documents via pgvector."""

    @classmethod
    async def retrieve_schema_docs(
        cls,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
        user_query: str,
        top_k: int = 6,
        schema_version: Optional[str] = None,
        canonical_schema: Optional[DatabaseSchema] = None,
    ) -> List[Dict[str, Any]]:
        """
        Embeds user query and retrieves top_k table markdown documents from pgvector.
        If table_doc embeddings are not found, generates documents on-the-fly from
        canonical_schema snapshot.
        """
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
        )

        if schema_version:
            stmt = stmt.where(DatabaseSchemaEmbedding.schema_version == schema_version)

        stmt = stmt.order_by(DatabaseSchemaEmbedding.embedding.cosine_distance(query_vector)).limit(top_k)

        res = await session.execute(stmt)
        rows = res.all()

        if rows:
            hits = []
            for r in rows:
                meta = r.metadata_json or {}
                hits.append({
                    "source": meta.get("source", f"{r.entity_key}.md"),
                    "title": meta.get("title", r.entity_key),
                    "text": r.document_text,
                    "score": float(r.similarity) if r.similarity is not None else 0.0,
                    "table_name": meta.get("table_name", r.entity_key.split(".")[-1]),
                    "schema_name": meta.get("schema_name", "public"),
                    "column_names": meta.get("column_names", []),
                })
            logger.info(f"[SchemaDocRetriever] Retrieved {len(hits)} table docs from pgvector for query: '{user_query[:50]}'")
            return hits

        # Fallback: if no 'table_doc' embeddings exist yet, generate from canonical schema
        logger.warning(f"[SchemaDocRetriever] No 'table_doc' embeddings found in pgvector for KB {kb_id}. Generating on-the-fly from schema snapshot.")
        if canonical_schema is None:
            snap_stmt = select(DatabaseSchemaSnapshot).where(
                DatabaseSchemaSnapshot.tenant_id == tenant_id,
                DatabaseSchemaSnapshot.db_knowledgebase_id == kb_id,
            ).order_by(DatabaseSchemaSnapshot.created_at.desc()).limit(1)
            snap_res = await session.execute(snap_stmt)
            snapshot = snap_res.scalar_one_or_none()
            if snapshot and snapshot.schema_data:
                canonical_schema = DatabaseSchema(**snapshot.schema_data)

        if not canonical_schema:
            return []

        all_docs = SchemaMarkdownGenerator.generate_all_table_documents(canonical_schema)
        import re

        # Clean query tokens
        raw_tokens = re.findall(r'[a-zA-Z0-9_]+', user_query.lower())
        stop_words = {"what", "was", "is", "are", "there", "in", "the", "a", "an", "for", "to", "of", "and", "how", "many", "give", "show", "get", "tell", "on", "at", "by", "yesterday", "today"}
        q_tokens = [tok for tok in raw_tokens if tok not in stop_words and len(tok) >= 3]

        # Concept synonyms
        concept_boosts = {}
        if any(tok in ("progress", "task", "tasks", "work", "package", "packages", "ticket", "issue", "todo") for tok in raw_tokens):
            concept_boosts["work_packages"] = 25.0
            concept_boosts["users"] = 15.0
            concept_boosts["projects"] = 10.0
        if any(tok in ("project", "projects") for tok in raw_tokens):
            concept_boosts["projects"] = 25.0
        if any(tok in ("user", "users", "employee", "member", "staff", "person", "arun", "girinath") for tok in raw_tokens):
            concept_boosts["users"] = 20.0
            concept_boosts["work_packages"] = 10.0

        scored_docs = []
        for d in all_docs:
            t_name = d["table_name"].lower()
            score = concept_boosts.get(t_name, 0.0)

            # Table name exact match
            for tok in q_tokens:
                if tok == t_name or (tok.endswith("s") and tok[:-1] == t_name) or (t_name.endswith("s") and t_name[:-1] == tok):
                    score += 20.0
                elif tok in t_name:
                    score += 10.0

            # Column name match
            col_names = [c.lower() for c in d.get("column_names", [])]
            for tok in q_tokens:
                if tok in col_names:
                    score += 5.0

            # Body text overlap
            t_text = d["text"].lower()
            text_matches = sum(1 for tok in q_tokens if tok in t_text)
            score += text_matches * 1.0

            scored_docs.append((score, d))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        top_docs = [d for _, d in scored_docs[:top_k]]
        return [
            {
                "source": d["source"],
                "title": d["title"],
                "text": d["text"],
                "score": round(score, 2),
                "table_name": d["table_name"],
                "schema_name": d["schema_name"],
                "column_names": d.get("column_names", []),
            }
            for score, d in scored_docs[:top_k]
        ]
