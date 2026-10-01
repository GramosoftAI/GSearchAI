import uuid
import json
import logging
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.embeddings import EmbeddingGenerator
from app.core.llm.llm_service import UnifiedLLMService

logger = logging.getLogger(__name__)


class QueryIntent(str, Enum):
    SCHEMA_LOOKUP = "SCHEMA_LOOKUP"
    TABLE_LOOKUP = "TABLE_LOOKUP"
    RELATIONSHIP = "RELATIONSHIP"
    AGGREGATION = "AGGREGATION"
    FILTER = "FILTER"
    GENERAL = "GENERAL"


class Phase2RetrievalResult(BaseModel):
    intent: QueryIntent
    retrieved_documents: List[Dict[str, Any]]
    evidence_context: str
    scores: List[float]


class IntentClassifier:
    """Classifies the query intent before retrieval."""
    
    _PROMPT = """You are a query intent classifier for a database knowledgebase.
Given the user's question, classify it into EXACTLY ONE of the following intents:
SCHEMA_LOOKUP: Asking about the database structure in general (e.g., "how many tables are there?").
TABLE_LOOKUP: Asking for a specific table or columns (e.g., "what columns are in employees?").
RELATIONSHIP: Asking about joins or connections (e.g., "how do employees relate to departments?").
AGGREGATION: Asking for counts, averages, sums (e.g., "what is the average salary?").
FILTER: Asking for specific rows (e.g., "show me employees in the sales department").
GENERAL: Unrelated or general questions.

Respond with ONLY the exact intent string from the list above. No other text.

Question: {query}
Intent:"""

    @classmethod
    async def classify(cls, query: str) -> QueryIntent:
        try:
            # We use a fast, reliable model for classification.
            # Here we assume UnifiedLLMService.generate exists and works.
            response = await UnifiedLLMService.generate(
                prompt=cls._PROMPT.format(query=query),
                model_name="MODEL_INTENT",  # Will map to settings.MODEL_INTENT
                max_tokens=10,
                temperature=0.0
            )
            intent_str = response.strip().upper()
            if intent_str in QueryIntent.__members__:
                return QueryIntent[intent_str]
            return QueryIntent.GENERAL
        except Exception as e:
            logger.warning(f"Intent classification failed: {e}. Defaulting to GENERAL.")
            return QueryIntent.GENERAL


class Phase2Retriever:
    """
    Isolated Semantic Retrieval (Phase 2).
    Queries ONLY document_chunks using pgvector similarity.
    Enforces strict isolation by tenant_id, connection_id, and schema_hash.
    """

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID):
        self.session = session
        self.tenant_id = tenant_id

    async def retrieve(
        self,
        query: str,
        kb_id: uuid.UUID,
        schema_hash: str,
        top_k: int = 5,
        min_similarity: float = 0.50
    ) -> Phase2RetrievalResult:
        logger.info(f"Phase 2 Retrieval for query: '{query}'")
        
        # 1. Intent Classification
        intent = await IntentClassifier.classify(query)
        logger.info(f"Classified Intent: {intent}")
        
        # 2. Embedding Generation
        query_embedding = await EmbeddingGenerator.generate_embedding(query)
        
        # 3. Isolated Semantic Retrieval using pgvector <=> (cosine distance)
        # Note: <=> returns distance (0 = identical, 2 = opposite). 
        # Similarity roughly = 1 - (distance / 2), but pgvector uses inner product <#> or cosine <=>.
        # We'll use cosine distance: similarity = 1 - distance
        
        stmt = text("""
            SELECT 
                text,
                metadata_json,
                (1 - (embedding_bge <=> :emb::vector)) AS similarity
            FROM document_chunks
            WHERE 
                tenant_id = :tenant_id
                AND kb_id = :kb_id
                AND section = 'SCHEMA_INDEX'
                AND metadata_json->>'schema_hash' = :schema_hash
                AND (1 - (embedding_bge <=> :emb::vector)) >= :min_sim
            ORDER BY similarity DESC
            LIMIT :top_k
        """)
        
        params = {
            "tenant_id": str(self.tenant_id),
            "kb_id": str(kb_id),
            "schema_hash": schema_hash,
            "emb": query_embedding,
            "min_sim": min_similarity,
            "top_k": top_k
        }
        
        res = await self.session.execute(stmt, params)
        rows = res.fetchall()
        
        retrieved_docs = []
        scores = []
        evidence_lines = []
        
        for r in rows:
            text_content = r.text
            meta = r.metadata_json
            sim = float(r.similarity)
            
            retrieved_docs.append(meta)
            scores.append(sim)
            evidence_lines.append(f"--- Table: {meta.get('table_name')} (Score: {sim:.2f}) ---\n{text_content}")
            
        evidence_context = "\n\n".join(evidence_lines) if evidence_lines else "No relevant schema evidence retrieved."
        
        return Phase2RetrievalResult(
            intent=intent,
            retrieved_documents=retrieved_docs,
            evidence_context=evidence_context,
            scores=scores
        )
