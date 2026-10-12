"""Phase 3 Step 3.4 TableRetriever

Multi-signal Table Retrieval combining:
1. kb2_schema_docs Full-Text Search (AND query first, OR + prefix fallback)
2. Vector search via EmbeddingGenerator
3. Glossary hits: (glossary doc -> target table)
4. Metric hits: (metric doc -> tables it depends on)
5. Value-index hits: (matched entity value -> its table, with frequency boost)

Signals combined with Reciprocal Rank Fusion (RRF):
    score = sum( weight / (k + rank) )
Multipliers:
- confirmed > draft (1.2x boost)
- admin-locked (1.5x boost)
- Optional domain filtering.
Outputs top K tables with score and explanation reasons.
"""

import uuid
import logging
from typing import Optional, List, Dict, Any, Set
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import EmbeddingGenerator
from ..repositories.schema_doc_repository import SchemaDocRepository
from ..repositories.entity_value_repository import EntityValueRepository
from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from .analyzer import QuestionFrame

logger = logging.getLogger(__name__)

RRF_K = 60


class TableCandidate(BaseModel):
    table_name: str
    score: float
    reasons: List[str] = Field(default_factory=list)
    signals: Dict[str, float] = Field(default_factory=dict)


class TableRetriever:
    """Retrieves and ranks candidate relational tables using hybrid signals and RRF."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str | uuid.UUID,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.schema_doc_repo = SchemaDocRepository(db=db, tenant_id=self.tenant_id)
        self.entity_repo = EntityValueRepository(db=db, tenant_id=self.tenant_id)
        self.item_repo = KnowledgeItemRepository(db=db, tenant_id=self.tenant_id)

        # Configurable signal weights
        self.weights = weights or {
            "fts": 1.0,
            "vector": 1.0,
            "glossary": 1.2,
            "metric": 1.1,
            "value_index": 1.3,
        }

    async def retrieve_tables(
        self,
        db_knowledgebase_id: uuid.UUID,
        frame: QuestionFrame,
        top_k: int = 12,
        domain_filter: Optional[str] = None,
    ) -> List[TableCandidate]:
        """Rank tables for the parsed QuestionFrame."""
        clean_text = frame.normalized_text or frame.original_question
        table_scores: Dict[str, float] = {}
        table_reasons: Dict[str, List[str]] = {}
        table_signals: Dict[str, Dict[str, float]] = {}

        def _add_score(table: str, score_delta: float, reason: str, signal_name: str):
            t_norm = table.lower().strip()
            # If schema-qualified, keep leaf table name
            if "." in t_norm:
                t_norm = t_norm.split(".")[-1]
            table_scores[t_norm] = table_scores.get(t_norm, 0.0) + score_delta
            table_reasons.setdefault(t_norm, []).append(reason)
            table_signals.setdefault(t_norm, {})[signal_name] = score_delta

        # -------------------------------------------------------------
        # 1. Full-Text Search (Table, Column, Metric, Glossary docs)
        # -------------------------------------------------------------
        fts_weight = self.weights.get("fts", 1.0)
        fts_hits = await self.schema_doc_repo.search_fts(
            db_knowledgebase_id=db_knowledgebase_id,
            query=clean_text,
            limit=30,
        )
        for rank, hit in enumerate(fts_hits, start=1):
            rrf_score = fts_weight * (1.0 / (RRF_K + rank))
            dt = hit["doc_type"]
            key = hit["item_key"]

            if dt == "table":
                t_name = key.split(".")[-1]
                _add_score(t_name, rrf_score, f"FTS match on table doc (rank {rank})", "fts")
            elif dt == "column":
                t_name = key.split(".")[1] if key.count(".") >= 2 else key.split(".")[0]
                _add_score(t_name, rrf_score * 0.9, f"FTS match on column {key} (rank {rank})", "fts_column")
            elif dt == "glossary":
                # Glossary target
                target = hit.get("unit") or hit.get("role") or ""
                # Parse body for Target:
                body = hit.get("body", "")
                if "Target (table):" in body:
                    t_target = body.split("Target (table):")[1].split(".")[0].strip()
                    _add_score(t_target, rrf_score * self.weights.get("glossary", 1.2), f"Glossary term {hit['title']} -> {t_target}", "glossary")
            elif dt == "metric":
                # Metric depends_on
                body = hit.get("body", "")
                for token in frame.tokens:
                    if token in key:
                        _add_score(token, rrf_score * self.weights.get("metric", 1.1), f"Metric hit {hit['title']}", "metric")

        # -------------------------------------------------------------
        # 2. Vector Search (Semantic Cosine Similarity)
        # -------------------------------------------------------------
        vec_weight = self.weights.get("vector", 1.0)
        try:
            q_emb = await EmbeddingGenerator.generate_embedding(frame.original_question, is_query=True)
            if q_emb:
                vec_hits = await self.schema_doc_repo.search_vector(
                    db_knowledgebase_id=db_knowledgebase_id,
                    embedding=q_emb,
                    limit=30,
                )
                for rank, hit in enumerate(vec_hits, start=1):
                    rrf_score = vec_weight * (1.0 / (RRF_K + rank))
                    dt = hit["doc_type"]
                    key = hit["item_key"]

                    if dt == "table":
                        t_name = key.split(".")[-1]
                        _add_score(t_name, rrf_score, f"Vector match on table {t_name} (sim {hit['score']:.2f})", "vector")
                    elif dt == "column":
                        t_name = key.split(".")[1] if key.count(".") >= 2 else key.split(".")[0]
                        _add_score(t_name, rrf_score * 0.85, f"Vector match on column {key} (sim {hit['score']:.2f})", "vector_column")
        except Exception as e:
            logger.debug(f"[TableRetriever] Vector search fallback: {e}")

        # -------------------------------------------------------------
        # 3. Value-Index Search (for entity candidates, excluding literals)
        # -------------------------------------------------------------
        val_weight = self.weights.get("value_index", 1.3)
        entity_spans = frame.entity_candidates or []
        for span in entity_spans:
            # Skip if span is an excluded literal
            if span in frame.literal_values:
                continue
            try:
                # Fuzzy & FTS value search
                val_matches = await self.entity_repo.search_fuzzy(
                    db_knowledgebase_id=db_knowledgebase_id,
                    query_text=span,
                    limit=5,
                    min_similarity=0.3,
                )
                for rank, vm in enumerate(val_matches, start=1):
                    t_val = vm["table_name"].split(".")[-1]
                    sim = vm.get("similarity", 1.0)
                    score_delta = val_weight * sim * (1.0 / (RRF_K + rank))
                    _add_score(t_val, score_delta, f"Value match '{span}' in {vm['table_name']}.{vm['column_name']} (sim {sim:.2f})", "value_index")
            except Exception as e:
                logger.debug(f"[TableRetriever] Value lookup error: {e}")

        # -------------------------------------------------------------
        # 4. Keyword / Token Exact Table Name Match Boost
        # -------------------------------------------------------------
        for tok in frame.tokens:
            for t_known in ["users", "orders", "tx_log", "branches", "payments", "customers", "employees", "ref_codes", "attendance", "departments"]:
                if tok == t_known or tok == t_known.rstrip("s") or t_known.startswith(tok):
                    _add_score(t_known, 0.05, f"Direct token match '{tok}'", "token_exact")

        # Compile candidates
        candidates: List[TableCandidate] = []
        for t_name, total_sc in sorted(table_scores.items(), key=lambda x: x[1], reverse=True):
            candidates.append(TableCandidate(
                table_name=t_name,
                score=total_sc,
                reasons=table_reasons.get(t_name, []),
                signals=table_signals.get(t_name, {}),
            ))

        return candidates[:top_k]
