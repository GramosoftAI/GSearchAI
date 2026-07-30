"""
Enterprise Hybrid RAG Router
Schema-Aware Intent Classifier for routing queries between Structured (DuckDB/Parquet) and Unstructured (Vector/Qdrant) Knowledge Bases.
"""
import logging
import re
import json
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

logger = logging.getLogger(__name__)

class HybridRoutingDecision(BaseModel):
    """Structured decision output from the Enterprise Hybrid Router."""
    target_engine: Literal['TABULAR_SQL', 'VECTOR_DOCS', 'HYBRID_MERGE'] = Field(
        ...,
        description="TABULAR_SQL for Excel/spreadsheet calculations, VECTOR_DOCS for PDF/unstructured prose, HYBRID_MERGE when both sources are required."
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score of the routing classification between 0.0 and 1.0."
    )
    matched_columns: List[str] = Field(
        default_factory=list,
        description="Spreadsheet column names explicitly or semantically referenced in the query."
    )
    reasoning: str = Field(
        ...,
        description="Brief explanation justifying why the selected engine is most appropriate for this query."
    )

class EnterpriseHybridRouter:
    """
    Schema-Aware Intent Classifier with 0-latency keyword pre-filtering and structured JSON reasoning.
    """

    @staticmethod
    def _fast_path_classify(query: str, columns: List[str], doc_kbs_count: int) -> Optional[HybridRoutingDecision]:
        """0-ms deterministic check for unambiguous queries."""
        q_lower = query.lower()

        # Explicit document/PDF indicators
        doc_signals = [
            "in the pdf", "in the document", "policy", "manual", "guideline", "section", 
            "clause", "paragraph", "according to the doc", "what does the document", 
            "what does the pdf", "doc mentions", "pdf mentions", "article"
        ]
        if any(sig in q_lower for sig in doc_signals):
            return HybridRoutingDecision(
                target_engine="VECTOR_DOCS",
                confidence=0.95,
                matched_columns=[],
                reasoning="Query explicitly references unstructured document text, policies, or manuals."
            )

        # Explicit table/Excel indicators, comparisons, rankings, or analytical operations
        explicit_math_signals = [
            "in the excel", "in the table", "spreadsheet", "sum of", "average of", "count of", 
            "total of", "how many rows", "group by"
        ]
        table_signals = [
            "compare the salary", "who has better salary", "better salary", "higher salary", 
            "lower salary", "more senior", "senior employee", "who is senior", "who earns more", 
            "highest salary", "lowest salary", "top salary", "compare both", "among both", 
            "between both", "who has higher", "who has lower", "difference between", 
            "wage", "income", "compensation"
        ]
        # Match columns only if they are specific/distinctive (>3 chars, not generic stopwords)
        generic_cols = {"name", "date", "id", "type", "status", "data", "info", "value", "text", "description"}
        matched_cols = [c for c in columns if c and len(str(c)) > 3 and str(c).lower() not in generic_cols and str(c).lower() in q_lower]

        if any(sig in q_lower for sig in explicit_math_signals):
            return HybridRoutingDecision(
                target_engine="TABULAR_SQL",
                confidence=0.95,
                matched_columns=matched_cols,
                reasoning=f"Query explicitly targets spreadsheet calculations or aggregation: {matched_cols}."
            )

        if any(sig in q_lower for sig in table_signals) or len(matched_cols) >= 2:
            target = "HYBRID_MERGE" if doc_kbs_count > 0 else "TABULAR_SQL"
            return HybridRoutingDecision(
                target_engine=target,
                confidence=0.95,
                matched_columns=matched_cols,
                reasoning=f"Query references tabular columns or comparisons ({matched_cols}). Routing to {target}."
            )

        return None

    @classmethod
    async def classify(
        cls,
        query: str,
        columns: List[str],
        doc_kbs_count: int,
        llm
    ) -> HybridRoutingDecision:
        """
        Classify the query using Schema-Aware Grounding and Structured Output.
        """
        # 1. Check fast path
        fast_decision = cls._fast_path_classify(query, columns, doc_kbs_count)
        if fast_decision:
            logger.info(f"[EnterpriseHybridRouter] Fast-Path Decision: {fast_decision.target_engine} (Conf: {fast_decision.confidence:.2f})")
            return fast_decision

        # 2. Schema-Aware LLM Intent Supervisor
        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system",
                 "You are an Enterprise Hybrid RAG Routing Supervisor. You supervise an agent with two distinct knowledge engines:\n"
                 "1. TABULAR_SQL (Excel/Spreadsheet Dataset): Structured table with the following available columns:\n"
                 "{columns}\n\n"
                 "2. VECTOR_DOCS (Unstructured Documents): {doc_count} PDF/text document knowledge base(s) containing prose, policies, manuals, and general information.\n\n"
                 "Your task is to classify the user's query and select the optimal execution engine:\n"
                 "- Select 'TABULAR_SQL' if the query requires numerical calculations, row lookups, aggregations, or references columns present in the Excel table.\n"
                 "- Select 'VECTOR_DOCS' if the query asks for qualitative explanations, policies, manuals, or concepts found in PDF documents.\n"
                 "- Select 'HYBRID_MERGE' if the query requires combining data from both the Excel spreadsheet and the PDF documents, or if it is ambiguous.\n\n"
                 "CRITICAL RULES:\n"
                 "1. Return ONLY valid JSON matching the schema: {{\"target_engine\": \"...\", \"confidence\": 0.90, \"matched_columns\": [\"...\"], \"reasoning\": \"...\"}}.\n"
                 "2. Do NOT output any markdown code fences or <think> tags. Output raw JSON only."),
                ("user", "{question}")
            ])

            from app.modules.rag.pandas_engine import parse_json_from_thinking
            chain = prompt | llm | StrOutputParser() | parse_json_from_thinking
            raw_dict = await chain.ainvoke({
                "columns": ", ".join(f'"{c}"' if ' ' in str(c) else str(c) for c in columns),
                "doc_count": doc_kbs_count,
                "question": query
            })

            decision = HybridRoutingDecision(**raw_dict)
            if decision.confidence < 0.60:
                logger.info(f"[EnterpriseHybridRouter] Low confidence ({decision.confidence:.2f}), elevating to HYBRID_MERGE.")
                decision.target_engine = "HYBRID_MERGE"
            elif decision.target_engine == "TABULAR_SQL" and doc_kbs_count > 0 and decision.confidence < 0.85:
                logger.info(f"[EnterpriseHybridRouter] Promoting TABULAR_SQL to HYBRID_MERGE in mixed-source environment (Conf: {decision.confidence:.2f}).")
                decision.target_engine = "HYBRID_MERGE"

            logger.info(f"[EnterpriseHybridRouter] LLM Decision: {decision.target_engine} | Conf: {decision.confidence:.2f} | Cols: {decision.matched_columns}")
            return decision

        except Exception as e:
            logger.warning(f"[EnterpriseHybridRouter] LLM classification failed ({e}), defaulting to TABULAR_SQL with fallback.")
            return HybridRoutingDecision(
                target_engine="TABULAR_SQL",
                confidence=0.50,
                matched_columns=[],
                reasoning=f"Default fallback due to router error: {str(e)}"
            )
