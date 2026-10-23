"""Schema Document Retriever using PostgreSQL pgvector

Retrieves AI-understandable table Markdown documents using cosine distance
against db_schema_embeddings, directly implementing the semantic retrieval
pattern proven in D:\\DB\\main.
"""

import re
import uuid
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

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

        # Fetch up to 16 candidates to allow filtering out noisy integration tables
        fetch_limit = max(top_k * 2, 16)
        stmt = stmt.order_by(DatabaseSchemaEmbedding.embedding.cosine_distance(query_vector)).limit(fetch_limit)

        res = await session.execute(stmt)
        rows = res.all()

        if rows:
            hits = []
            q_lower = user_query.lower()
            
            # Check if user explicitly asked for third-party integration / background job tables
            has_github = any(w in q_lower for w in ("github", "pull request", " pr ", " prs", "pr#"))
            has_gitlab = any(w in q_lower for w in ("gitlab", "merge request", " mr ", " mrs"))
            has_scim = "scim" in q_lower
            has_jobs = any(w in q_lower for w in ("job", "batch", "background", "queue", "worker"))
            has_bcf = any(w in q_lower for w in ("bcf", "bim", "viewpoint"))
            has_wiki = any(w in q_lower for w in ("wiki", "wikis", "documentation", "docs"))

            for r in rows:
                meta = r.metadata_json or {}
                table_name = meta.get("table_name", r.entity_key.split(".")[-1]).lower()
                
                # Filter out noisy third-party integration tables unless explicitly requested
                if table_name.startswith("github_") and not has_github:
                    continue
                if table_name.startswith("gitlab_") and not has_gitlab:
                    continue
                if table_name.startswith("scim_") and not has_scim:
                    continue
                if (table_name.startswith("good_job_") or table_name == "good_jobs") and not has_jobs:
                    continue
                if table_name.startswith("bcf_") and not has_bcf:
                    continue
                if (table_name.startswith("wiki_") or table_name == "wikis") and not has_wiki:
                    continue
                if table_name in ("ar_internal_metadata", "schema_migrations"):
                    continue

                hits.append({
                    "source": meta.get("source", f"{r.entity_key}.md"),
                    "title": meta.get("title", r.entity_key),
                    "text": r.document_text,
                    "score": float(r.similarity) if r.similarity is not None else 0.0,
                    "table_name": meta.get("table_name", r.entity_key.split(".")[-1]),
                    "schema_name": meta.get("schema_name", "public"),
                    "column_names": meta.get("column_names", []),
                })
                if len(hits) >= top_k:
                    break

            # Dynamic Schema Graph Augmentation:
            # Traverses canonical schema to discover:
            # 1. Direct table matches (singular/plural) from user query tokens
            # 2. 1-hop foreign key parent dimension tables referenced by primary retrieved tables
            retrieved_names = {h["table_name"].lower() for h in hits}
            candidate_additions: List[Tuple[str, float]] = []

            if canonical_schema and hasattr(canonical_schema, "all_tables"):
                q_tokens = set(re.findall(r'\b[a-z0-9]+\b', q_lower))

                # 1. Direct Table Concept Matching from DDL (Exact name or singular/plural)
                for t in canonical_schema.all_tables:
                    t_name = t.table_name.split(".")[-1].lower()
                    if t_name in retrieved_names:
                        continue
                    # Match exact table name or singular/plural
                    if t_name in q_tokens or (t_name.endswith('s') and t_name[:-1] in q_tokens) or (f"{t_name}s" in q_tokens):
                        candidate_additions.append((t_name, 0.88))

                # 2. 1-Hop Foreign Key Graph Expansion (only from the top 3 highest-scoring seed tables)
                top_seed_names = [h["table_name"].lower() for h in sorted(hits, key=lambda x: x["score"], reverse=True)[:3]]
                for t_name in top_seed_names:
                    t_schema = canonical_schema.get_table(t_name)
                    if t_schema:
                        for fk in t_schema.foreign_keys:
                            ref_tbl = fk.referred_table.split(".")[-1].lower()
                            if ref_tbl not in retrieved_names and not any(c[0] == ref_tbl for c in candidate_additions):
                                candidate_additions.append((ref_tbl, 0.85))

            for tbl, aug_score in candidate_additions:
                if tbl not in retrieved_names:
                    dim_stmt = select(
                        DatabaseSchemaEmbedding.entity_key,
                        DatabaseSchemaEmbedding.document_text,
                        DatabaseSchemaEmbedding.metadata_json,
                    ).where(
                        DatabaseSchemaEmbedding.tenant_id == tenant_id,
                        DatabaseSchemaEmbedding.db_knowledgebase_id == kb_id,
                        DatabaseSchemaEmbedding.entity_type == "table_doc",
                        or_(
                            DatabaseSchemaEmbedding.entity_key.ilike(f"%.{tbl}"),
                            DatabaseSchemaEmbedding.entity_key == tbl,
                        ),
                    ).limit(1)
                    dim_res = await session.execute(dim_stmt)
                    dim_row = dim_res.first()
                    if dim_row:
                        meta = dim_row.metadata_json or {}
                        hits.append({
                            "source": meta.get("source", f"{dim_row.entity_key}.md"),
                            "title": meta.get("title", dim_row.entity_key),
                            "text": dim_row.document_text,
                            "score": aug_score,
                            "table_name": meta.get("table_name", tbl),
                            "schema_name": meta.get("schema_name", "public"),
                            "column_names": meta.get("column_names", []),
                        })
                        retrieved_names.add(tbl)
                        logger.info(f"[SchemaDocRetriever] Dynamically augmented schema docs with '{tbl}' table")

            # Rank and cap final schema context to top_k (max 8)
            hits.sort(key=lambda h: h.get("score", 0.0), reverse=True)
            max_context_tables = max(top_k, 8)
            hits = hits[:max_context_tables]
            return hits

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
