"""Schema Vector Retrieval using pgvector

Performs dense vector similarity search across db_schema_embeddings, scoped strictly
by tenant_id, database_knowledgebase_id, and schema_version.
"""

import uuid
import logging
from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from ..models.embeddings import DatabaseSchemaEmbedding

logger = logging.getLogger(__name__)


class VectorMatchResult:
    """Represents vector retrieval result aggregated at the table level."""

    def __init__(
        self,
        table_name: str,
        schema_name: str,
        table_similarity: float,
        best_column_similarity: float,
        matched_columns: List[str],
        retrieval_reason: str,
    ):
        self.table_name = table_name
        self.schema_name = schema_name
        self.table_similarity = table_similarity
        self.best_column_similarity = best_column_similarity
        self.matched_columns = matched_columns
        self.retrieval_reason = retrieval_reason

    @property
    def combined_vector_score(self) -> float:
        """Combines direct table embedding score and top column embedding score."""
        if self.table_similarity > 0 and self.best_column_similarity > 0:
            return max(self.table_similarity, 0.6 * self.table_similarity + 0.4 * self.best_column_similarity)
        return max(self.table_similarity, self.best_column_similarity)


class SchemaVectorSearch:
    """
    Executes scoped vector search over indexed database schema embeddings.
    """

    @classmethod
    async def search(
        cls,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
        schema_version: str,
        query_embedding: List[float],
        top_k: int = 15,
        min_similarity: float = 0.10,
    ) -> Dict[str, VectorMatchResult]:
        """
        Search table, column, and relationship embeddings for query_embedding.

        Returns:
            Dictionary of table_key ('public.customers') -> VectorMatchResult
        """
        similarity_expr = (1.0 - DatabaseSchemaEmbedding.embedding.cosine_distance(query_embedding)).label("similarity")

        stmt = (
            select(
                DatabaseSchemaEmbedding.entity_type,
                DatabaseSchemaEmbedding.entity_key,
                DatabaseSchemaEmbedding.metadata_json,
                similarity_expr,
            )
            .where(
                and_(
                    DatabaseSchemaEmbedding.tenant_id == tenant_id,
                    DatabaseSchemaEmbedding.db_knowledgebase_id == kb_id,
                    DatabaseSchemaEmbedding.schema_version == schema_version,
                )
            )
            .order_by(similarity_expr.desc())
            .limit(top_k * 4)  # Fetch sufficient candidate records for table/column aggregation
        )

        result = await session.execute(stmt)
        rows = result.fetchall()

        table_results: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            entity_type = row.entity_type
            entity_key = row.entity_key
            metadata = row.metadata_json or {}
            sim = float(row.similarity)

            if sim < min_similarity:
                continue

            if entity_type == "table":
                tech = metadata.get("technical_facts", {})
                s_name = tech.get("schema_name", "public")
                t_name = tech.get("table_name", entity_key.split(".")[-1])
                t_key = f"{s_name}.{t_name}"

                if t_key not in table_results:
                    table_results[t_key] = {
                        "table_name": t_name,
                        "schema_name": s_name,
                        "table_similarity": sim,
                        "best_column_similarity": 0.0,
                        "matched_columns": [],
                        "reasons": [f"Direct table semantic similarity ({sim:.2f})"],
                    }
                else:
                    table_results[t_key]["table_similarity"] = max(table_results[t_key]["table_similarity"], sim)
                    table_results[t_key]["reasons"].append(f"Direct table semantic similarity ({sim:.2f})")

            elif entity_type == "column":
                tech = metadata.get("technical_facts", {})
                s_name = tech.get("schema_name", "public")
                t_name = tech.get("table_name", "")
                c_name = tech.get("column_name", "")
                t_key = f"{s_name}.{t_name}"

                if t_key not in table_results:
                    table_results[t_key] = {
                        "table_name": t_name,
                        "schema_name": s_name,
                        "table_similarity": 0.0,
                        "best_column_similarity": sim,
                        "matched_columns": [c_name],
                        "reasons": [f"Column '{c_name}' semantic similarity ({sim:.2f})"],
                    }
                else:
                    table_results[t_key]["best_column_similarity"] = max(
                        table_results[t_key]["best_column_similarity"], sim
                    )
                    if c_name and c_name not in table_results[t_key]["matched_columns"]:
                        table_results[t_key]["matched_columns"].append(c_name)
                    table_results[t_key]["reasons"].append(f"Column '{c_name}' similarity ({sim:.2f})")

        # Convert to VectorMatchResult objects
        output: Dict[str, VectorMatchResult] = {}
        for t_key, data in table_results.items():
            output[t_key] = VectorMatchResult(
                table_name=data["table_name"],
                schema_name=data["schema_name"],
                table_similarity=data["table_similarity"],
                best_column_similarity=data["best_column_similarity"],
                matched_columns=data["matched_columns"],
                retrieval_reason=" | ".join(data["reasons"]),
            )

        return output
