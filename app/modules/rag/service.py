"""
RAG Service - Orchestrates RAG pipeline and LLM generation
Phase 2 Step 4: Transforms retrieved context into generated answers
"""

import logging
import os
from typing import Optional, Callable
from uuid import UUID
import asyncio
import hashlib
import json
import random
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from .pipeline import RAGPipeline, RAGContext
from ..knowledge_bases.repository import KnowledgeBaseRepository
from ..agents.repository import AgentRepository
from ..personalities.models import Personality
from ...core.database import AsyncSessionLocal
from ...core.embeddings import EmbeddingGenerator
from ...core.llm.deepinfra_llm import DeepInfraLLMClient, LLMResponse
from ...core.billing.utils import is_billing_enabled

# Analytics Integration
from ..analytics.repository import AnalyticsRepository
from ..analytics.schemas import AnalyticsQueryLogCreate
from ..analytics.models import ResponseStatus

logger = logging.getLogger(__name__)


def clean_source_name(source: str) -> str:
    if not source:
        return "Unknown Source"
    if ":" in source and not source.startswith("http"):
        parts = source.split(":", 1)
        source = parts[1].strip()
    
    try:
        parsed = urlparse(source)
        if parsed.scheme and parsed.netloc:
            path_part = os.path.basename(parsed.path)
            if path_part:
                return path_part
    except Exception:
        pass
        
    return os.path.basename(source)


_rag_cache = {}
_CACHE_TTL_SECONDS = 300
_MAX_CACHE_SIZE = 1000
_CACHE_INSERTION_ORDER = []
_RAG_TIMEOUT_SECONDS = 180.0


@dataclass
class RAGMetrics:
    retrieval_latency_ms: float
    ranking_latency_ms: float
    total_latency_ms: float
    cache_hit: bool
    seed_chunks_count: int
    expanded_chunks_count: int
    final_chunks_count: int
    timeout_occurred: bool
    partial_result: bool

    def __post_init__(self):
        if self.total_latency_ms < 0:
            raise ValueError("Latency cannot be negative")


_rag_metrics = []


class RAGService:
    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = str(tenant_id)

        self.pipeline = RAGPipeline(self.tenant_id, db=self.db)
        self.kb_repo = KnowledgeBaseRepository(db, self.tenant_id)
        self.agent_repo = AgentRepository(db, self.tenant_id)
        self.llm_client = DeepInfraLLMClient()

    async def stream_rag_answer(
        self,
        query: str,
        agent_id: str,
        kb_id: str | list[str],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        top_k: int = 30,
        max_depth: int = 2,
        on_usage_callback: Optional[Callable[[dict], None]] = None,
        chat_history: Optional[str] = None,
        skip_search: bool = False,
        memory_enabled: bool = True,
    ):
        logger.info(f" RAG Service: Streaming answer for agent={agent_id}, kb={kb_id}")

        # 1. Validate KB ownership
        kb_ids = [kb_id] if isinstance(kb_id, str) else kb_id
        
        # 1. Validate KB ownership and separate Excel vs Document KBs
        excel_kbs = []
        doc_kbs = []
        for kid in kb_ids:
            kb = await self.kb_repo.get_by_id(kid)
            if not kb:
                yield json.dumps({"error": f"Knowledge Base {kid} not found"})
                return
            if str(kb.agent_id) != str(agent_id):
                yield json.dumps({"error": "Unauthorized: Agent does not own this Knowledge Base"})
                return
            if getattr(kb, "description", "") == "excel_parquet":
                excel_kbs.append(kb)
            else:
                doc_kbs.append(kb)

        # ============= MEMORY-API: RECALL USER PREFERENCES & EPISODIC GUIDANCE =============
        episodic_guidance = await self._fetch_episodic_guidance(query, agent_id, user_id, memory_enabled)

        # Upfront Query Classification and Decomposition
        from app.modules.rag.orchestrator.query_analyzer import QueryAnalyzer
        analyzer = QueryAnalyzer()
        tabular_query = query
        vector_query = query
        try:
            analysis_res = await analyzer.analyze_query(query)
            if analysis_res and analysis_res.metadata:
                corrected = getattr(analysis_res.metadata, "corrected_query", None)
                if corrected:
                    query = corrected
                    tabular_query = corrected
                    vector_query = corrected
                
                tab_sub = getattr(analysis_res.metadata, "tabular_subquery", None)
                vec_sub = getattr(analysis_res.metadata, "vector_subquery", None)
                if tab_sub:
                    logger.info(f"Decomposed tabular sub-query: {tab_sub}")
                    tabular_query = tab_sub
                if vec_sub:
                    logger.info(f"Decomposed vector sub-query: {vec_sub}")
                    vector_query = vec_sub
        except Exception as e:
            logger.error(f"QueryAnalyzer upfront decomposition failed: {e}")

        # ============= HYBRID RAG: ENTERPRISE SCHEMA-AWARE ROUTING =============
        hybrid_merge_context = ""
        sql_task = None
        if excel_kbs:
            is_tabular = True
            if analysis_res is not None:
                is_tabular = getattr(analysis_res, "is_tabular", True)
            if not doc_kbs:
                is_tabular = True
                
            if is_tabular:
                from app.core.parquet_ingester import ParquetIngester
                from app.modules.rag.pandas_engine import PandasQueryEngine
                import os
                active_paths = []
                path_mapping = {}
                for ekb in excel_kbs:
                    dataset_name = getattr(ekb, "parsed_path", None) or getattr(ekb, "s3_path", None)
                    if dataset_name:
                        p = ParquetIngester.get_active_dataset(dataset_name)
                        if p:
                            active_paths.append(p)
                            # Clean original filename from "Spreadsheet: " prefix
                            orig_name = getattr(ekb, "name", "dataset")
                            if orig_name.startswith("Spreadsheet: "):
                                orig_name = orig_name[len("Spreadsheet: "):]
                            elif orig_name.startswith("PDF: "):
                                orig_name = orig_name[len("PDF: "):]
                            path_mapping[os.path.basename(p)] = orig_name
                            
                if not active_paths and not doc_kbs:
                    yield json.dumps({"error": "Active parquet datasets for Excel Knowledge Bases not found."})
                    return
                    
                if active_paths:
                    engine = PandasQueryEngine(active_paths[0], all_dataset_paths=active_paths, path_mapping=path_mapping)
                    sql_task = asyncio.create_task(engine.execute_query(tabular_query, synthesize=(not doc_kbs), episodic_guidance=episodic_guidance))

        vector_task = None
        if not skip_search and (doc_kbs or not excel_kbs):
            vector_task = asyncio.create_task(
                self.pipeline.query(
                    query=vector_query,
                    agent_id=agent_id,
                    kb_id=kb_ids,
                    user_id=user_id,
                    top_k=top_k,
                    max_depth=max_depth,
                )
            )

        context = None
        metadata_yielded = False
        if excel_kbs and sql_task and vector_task:
            logger.info("Executing Parallel Hybrid RAG (TABULAR_SQL + VECTOR_DOCS simultaneously)...")
            
            # Wait for vector_task first to yield metadata early
            try:
                context_res = await asyncio.wait_for(vector_task, timeout=_RAG_TIMEOUT_SECONDS)
            except Exception as e:
                context_res = e
            
            if not isinstance(context_res, Exception):
                context = context_res
                
                # Yield metadata immediately so the UI doesn't hang!
                metadata = {
                    "type": "metadata",
                    "sources": [
                        {
                            "chunk_id": c.chunk_id,
                            "source": clean_source_name(getattr(c, "s3_path", None) or c.source),
                            "score": round(c.hybrid_score, 3),
                            "position": c.position,
                            "reason": c.reason,
                            "kb_id": c.kb_id,
                            "content_type": getattr(c, "content_type", "original")
                        }
                        for c in context.chunks
                    ] + [
                        {
                            "chunk_id": f"tabular_{ek.id}",
                            "source": getattr(ek, "name", "").replace("Spreadsheet: ", "").replace("PDF: ", "") if getattr(ek, "name", None) else "Excel Parquet",
                            "score": 1.0,
                            "position": 0,
                            "reason": "Tabular query match",
                            "kb_id": str(ek.id),
                            "content_type": "tabular"
                        }
                        for ek in excel_kbs
                    ],
                    "triplets": [
                        {"subject": t["subject"], "predicate": t["predicate"], "object": t["object"]}
                        for t in (context.triplets or [])
                    ],
                    "kb_name": kb.name if len(kb_ids) == 1 else f"Multi-KB ({len(kb_ids)})",
                    "augmented_query": query,
                    "authoritative_entities": context.authoritative_entities or []
                }
                yield json.dumps(metadata)
                metadata_yielded = True
            else:
                logger.error(f"Parallel RAG Retrieval failed: {context_res}")
                yield json.dumps({"error": f"Retrieval failed: {str(context_res)}"})
                return

            # Now wait for SQL task which is running in parallel
            try:
                sql_res = await asyncio.wait_for(sql_task, timeout=120.0)
            except Exception as e:
                sql_res = e
                
            if not isinstance(sql_res, Exception) and sql_res:
                unmatched_signals = ["not present in dataset", "no records matched", "error", "0 rows", "empty dataframe"]
                if not any(sig in str(sql_res).lower() for sig in unmatched_signals):
                    excel_filenames = ", ".join(getattr(ek, "name", "dataset") for ek in excel_kbs if getattr(ek, "name", None))
                    hybrid_merge_context = f"\n\n[ENTERPRISE SPREADSHEET ANALYSIS ({excel_filenames})]\n{str(sql_res)}\nUse the above numerical table results alongside document citations to answer the user query completely.\n"
            elif isinstance(sql_res, Exception):
                logger.warning(f"Parallel TABULAR_SQL failed: {sql_res}")

        elif sql_task:
            logger.info("Executing TABULAR_SQL standalone...")
            try:
                sql_res = await asyncio.wait_for(sql_task, timeout=120.0)
                unmatched_signals = ["not present in dataset", "no records matched", "error", "0 rows", "empty dataframe"]
                is_unmatched = any(sig in str(sql_res).lower() for sig in unmatched_signals)
                if is_unmatched:
                    logger.info(f"Excel dataset lacked answer ({sql_res}).")
                else:
                    yield json.dumps({
                        "type": "metadata",
                        "sources": [
                            {
                                "chunk_id": f"tabular_{ek.id}",
                                "source": getattr(ek, "name", "").replace("Spreadsheet: ", "").replace("PDF: ", "") if getattr(ek, "name", None) else "Excel Parquet",
                                "score": 1.0,
                                "position": 0,
                                "reason": "Tabular query match",
                                "kb_id": str(ek.id),
                                "content_type": "tabular"
                            }
                            for ek in excel_kbs
                        ],
                        "kb_name": ", ".join(getattr(ek, "name", "").replace("Spreadsheet: ", "").replace("PDF: ", "") for ek in excel_kbs if getattr(ek, "name", None)),
                        "context_type": "duckdb_parquet"
                    })
                    yield str(sql_res)
                    return
            except Exception as e:
                logger.error(f"PandasQueryEngine stream failed: {e}")
                yield json.dumps({"error": str(e)})
                return

        elif vector_task:
            logger.info("Executing VECTOR_DOCS standalone...")
            try:
                context = await asyncio.wait_for(vector_task, timeout=_RAG_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.error(f"RAG Retrieval timed out after {_RAG_TIMEOUT_SECONDS}s")
                yield json.dumps({"error": "The AI provider is taking too long to respond. Please try again later."})
                return
            except Exception as e:
                logger.error(f"RAG Retrieval failed for stream: {e}")
                yield json.dumps({"error": f"Retrieval failed: {e}"})
                return

        skip_search = True  # Bypass redundant sequential search below
            
        if len(kb_ids) > 1:
            logger.info(f" Querying across {len(kb_ids)} Knowledge Bases for agent {agent_id}")

        agent = await self.agent_repo.get_by_id(agent_id)
        if not agent:
            yield json.dumps({"error": f"Agent {agent_id} not found or inactive under the current tenant"})
            return
        
        base_prompt = agent.system_prompt or ""
        personality_description = agent.personality or "You are a warm, approachable, and supportive assistant."

        if agent.personality_id:
            personality = await self.db.get(Personality, agent.personality_id)
            if personality:
                personality_description = personality.description or personality.name

        accuracy_directives = (
            "\n- Enforce 100% factual accuracy based strictly on the retrieved context."
            "\n- Correct any obvious spelling or grammatical errors found in the source documents; do not copy typos."
            "\n- Verify timelines, chronologies, and locations strictly to avoid historical or situational errors."
        )
        if "factual accuracy" not in personality_description.lower():
            personality_description += accuracy_directives

        # Ontology Grounding
        from ..ontology.service import OntologyService
        try:
            ont_svc = OntologyService(self.tenant_id)
            ontology = await ont_svc.get_ontology()
            ontology_rules_str = ""
            if ontology and ontology.get("rules"):
                rules_list = [f"({r['source_class']})-[:{r['relation']}]->({r['target_class']})" for r in ontology["rules"] if r.get("source_class")]
                if rules_list:
                    ontology_rules_str = "\n\n[ENTERPRISE ONTOLOGY RULES (STRICT GROUNDING)]\n" + "\n".join(rules_list) + "\nAlign your reasoning strictly with these established business relationships. Do not hallucinate relationships outside of this schema."
        except Exception as e:
            logger.warning(f"Failed fetching active ontology for RAG prompt: {e}")
            ontology_rules_str = ""

        injected_system_prompt = f"""
[PERSONALITY MODE: STRICT]

You MUST strictly follow the personality defined below.
Every response MUST reflect this personality strongly in tone, wording, and structure.
Deviation is NOT allowed.

Personality Definition:
{personality_description}

Base Instruction:
{base_prompt}{ontology_rules_str}

{hybrid_merge_context}

You are an enterprise AI assistant.

==================================================
MEMORY AUTHORITY (HIGHEST PRIORITY — READ FIRST)
==================================================
If the user's message contains a section beginning with:
  "### MANDATORY USER PREFERENCES & MEMORY DIRECTIVES"
then you MUST treat everything in that section as VERIFIED GROUND TRUTH about the user.
- These facts are authoritative and override document context.
- Use them to answer personal questions directly (e.g., "what is my name?", "what is my 10th grade mark?").
- You are ALLOWED and REQUIRED to answer from this memory section even if the answer is not in the documents.
- Do NOT say "I couldn't find it" if the answer is present in the memory/preferences section.
- When answering from memory, say "Based on your saved profile, ..." to be transparent.

==================================================
GROUNDING RULES & HALLUCINATION PREVENTION
==================================================
Never complete missing information using prior knowledge.
If retrieved passages conflict, state the conflict. Do not resolve it yourself.
- Answer ONLY using the provided context OR verified user memory (see MEMORY AUTHORITY above).
- Before answering, verify that every factual statement in your response is explicitly supported by the retrieved context or user memory.
- If a statement is not directly supported by either source, do not include it.
- Do not combine information from your general knowledge with the retrieved context.
- Never use outside knowledge.
- Never invent, infer, estimate, or assume facts.
- If the requested information is missing from BOTH the document context AND the user memory section, reply exactly:
  "I couldn't find it."
- If only part of the answer exists, answer only that part.
- Mention the relevant source at the end.
- Answer ONLY the specific question asked by the user. Do not provide extra analysis, summaries of unrelated topics, or inferred narratives unless requested.
- Be concise. Focus strictly on direct answers and avoid filler.
- TRANSACTION CLASSIFICATION: Categorize transactions strictly:
  * Credit (Deposit/Incoming): Salary, interest, deposits, incoming transfers.
  * Debit (Withdrawal/Outgoing/Payment): ATM withdrawals, payments to merchants, fees, taxes, outgoing transfers.

==================================================
FORMATTING RULES
==================================================
Use Markdown tables whenever information is easier to compare in rows and columns.
Use bullet points when listing multiple items.
Use paragraphs for explanations.

==================================================
SOURCE CITATION RULES
==================================================
Cite all the UNIQUE document/data sources that were used to formulate your answer.
Format each citation at the very end of your response on a single line:
[Source: <source_1>, <source_2>]

Rules:
- List every unique source used (e.g. clean file names like ARUN_N.pdf, data.xlsx).
- Deduplicate sources so each unique filename appears ONLY ONCE.
- Do NOT repeat the same filename multiple times.
- If tabular database/spreadsheet insights were used, cite the specific filename(s) shown in the header (e.g. "[Source: employees.csv]" or "[Source: data.xlsx]") as the source.
- The source citation line must appear only once at the very end of the response.

==================================================
FINAL RESPONSE FORMAT
==================================================
Answer:
<grounded answer>

If you'd like, I can also:
- ...
- ...

[Source: <source_1>, <source_2>]
""".strip()

        agent_persona = {
            "name": agent.name if agent else "Assistant",
            "personality": personality_description,
            "system_prompt": injected_system_prompt
        }

        if chat_history:
            agent_persona["system_prompt"] += f"\n\n==================================================\nCONVERSATION HISTORY\n==================================================\n{chat_history}\n\nCRITICAL INSTRUCTION: If the user's current question asks to filter, modify, or extract from the 'above' or 'previous' answer, you MUST use the CONVERSATION HISTORY as your primary source of truth and ignore any conflicting retrieved documents below."

        # 2. Retrieve Context
        if 'context' not in locals():
            context = None
            
        if not skip_search:
            try:
                context = await asyncio.wait_for(
                    self.pipeline.query(
                        query=vector_query,
                        agent_id=agent_id,
                        kb_id=kb_ids,
                        user_id=user_id,
                        top_k=top_k,
                        max_depth=max_depth,
                    ),
                    timeout=_RAG_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(f"RAG Retrieval timed out after {_RAG_TIMEOUT_SECONDS}s")
                yield json.dumps({"error": "The AI provider is taking too long to respond. Please try again later."})
                return
            except Exception as e:
                error_msg = str(e) if str(e) else e.__class__.__name__
                logger.error(f"RAG Retrieval failed for stream: {error_msg}")
                yield json.dumps({"error": f"Retrieval failed: {error_msg}"})
                return
                
        # ==================================================
        # RELEVANCE FILTER (Context Poisoning Protection)
        # ==================================================
        import os
        min_score = float(os.getenv("RAG_MIN_RELEVANCE_SCORE", "0.6"))
        if context and context.chunks:
            original_count = len(context.chunks)
            context.chunks = [c for c in context.chunks if getattr(c, "hybrid_score", 0.0) >= min_score]
            dropped = original_count - len(context.chunks)
            if dropped > 0:
                logger.info(f"Relevance Filter: Dropped {dropped} irrelevant chunks (score < {min_score}) to prevent hallucination.")

        # 3. Yield metadata first
        if not metadata_yielded:
            if context:
                for c in context.chunks:
                    logger.info(f"Chunk={c.chunk_id} Source={c.source} Score={c.hybrid_score}")

                metadata = {
                    "type": "metadata",
                    "sources": [
                        {
                            "chunk_id": c.chunk_id,
                            "source": clean_source_name(getattr(c, "s3_path", None) or c.source),
                            "score": round(c.hybrid_score, 3),
                            "position": c.position,
                            "reason": c.reason,
                            "kb_id": c.kb_id,
                            "content_type": getattr(c, "content_type", "original")
                        }
                        for c in context.chunks
                    ],
                    "triplets": [
                        {"subject": t["subject"], "predicate": t["predicate"], "object": t["object"]}
                        for t in (context.triplets or [])
                    ],
                    "kb_name": kb.name if len(kb_ids) == 1 else f"Multi-KB ({len(kb_ids)})",
                    "augmented_query": query,
                    "authoritative_entities": context.authoritative_entities or []
                }
            else:
                metadata = {
                    "type": "metadata",
                    "sources": [],
                    "triplets": [],
                    "kb_name": kb.name if len(kb_ids) == 1 else f"Multi-KB ({len(kb_ids)})",
                    "augmented_query": query,
                    "authoritative_entities": []
                }

            yield json.dumps(metadata)

        is_extractive = context.search_type == "EXTRACTIVE" if context else False
        is_table_analytics = context.search_type == "TABLE_ANALYTICS" if context else False

        if is_extractive or is_table_analytics:
            logger.info(f"Bypassing LLM stream for {context.search_type} mode.")
            if getattr(context, "authoritative_entities", None):
                for ent in context.authoritative_entities:
                    clean_name = ent['entity_type'].replace('_', ' ').title()
                    clean_src = clean_source_name(ent.get('source', 'document_entities'))
                    yield f"**{clean_name}:** {ent['value']} (Page {ent.get('page', 1)}) [Source: {clean_src}]\n"
                yield "\n"

            # Strip any <think> tags from triplet_context (gateway LLM leak guard)
            import re as _re
            clean_triplet = context.triplet_context or ""
            clean_triplet = _re.sub(r'<think>.*?</think>', '', clean_triplet, flags=_re.DOTALL).strip()
            if '<think>' in clean_triplet:
                clean_triplet = clean_triplet[:clean_triplet.index('<think>')].strip()

            yield clean_triplet

            # Append source citation for TABLE_ANALYTICS so the frontend source pills appear
            # Collect unique clean source file names from context chunks if available
            try:
                unique_srcs = []
                if context and context.chunks:
                    for chk in context.chunks:
                        s_name = clean_source_name(getattr(chk, "s3_path", None) or chk.source)
                        if s_name and s_name not in unique_srcs:
                            unique_srcs.append(s_name)
                if not unique_srcs:
                    unique_srcs = [kb.name if kb else ("Dataset" if not kb_ids else kb_ids[0])]
                _src_name = ", ".join(unique_srcs)
                yield f"\n\n[Source: {_src_name}]"
            except Exception:
                pass
            return

        if (not context or not context.chunks) and not chat_history and not hybrid_merge_context and not episodic_guidance:
            logger.info("Empty context retrieved for stream, returning fallback message.")
            yield "I'm sorry, but the requested information is not available within my current knowledge base. Please try a related query or provide additional context."
            return

        # 4. Stream chunks
        formatted_context = self._format_context(context, hybrid_merge_context=hybrid_merge_context) if context else (hybrid_merge_context or "")
        if episodic_guidance:
            formatted_context = (
                "### MANDATORY USER PREFERENCES & MEMORY DIRECTIVES\n"
                f"{episodic_guidance}\n\n"
            ) + formatted_context

        start_time = datetime.now()

        full_answer = []
        token_usage = {}
        def handle_usage(usage_dict):
            token_usage.update(usage_dict)
            if on_usage_callback:
                on_usage_callback(usage_dict)
        async for chunk in self.llm_client.stream_answer(
            query, 
            formatted_context, 
            agent_persona=agent_persona,
            enable_thinking=False,
            on_usage_callback=handle_usage,
        ):
            yield chunk

        # 5. ASYNC LOGGING (Background)
        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
        confidence = sum(c.hybrid_score for c in context.chunks) / len(context.chunks) if (context and context.chunks) else 0.0
        status = ResponseStatus.SUCCESS if (context and context.chunks) else (ResponseStatus.SUCCESS if chat_history else ResponseStatus.UNANSWERED)

        llm_input_tokens = token_usage.get("prompt_tokens", 0)
        llm_output_tokens = token_usage.get("completion_tokens", 0)
        embedding_tokens = getattr(context, "query_embedding_tokens", 0) or max(1, len(query) // 4)

        llm_cost_usd = (llm_input_tokens / 1000000.0) * 0.10 + (llm_output_tokens / 1000000.0) * 0.15
        embedding_cost_usd = (embedding_tokens / 1000000.0) * 0.01
        total_cost_usd = llm_cost_usd + embedding_cost_usd

        try:
            analytics_repo = AnalyticsRepository(self.db, UUID(self.tenant_id))
            await analytics_repo.create_query_log({
                "query": query,
                "response_status": status,
                "confidence_score": confidence,
                "latency_ms": latency_ms,
                "session_id": UUID(session_id) if session_id else None,
                "user_id": UUID(user_id) if user_id else None,
                "llm_input_tokens": llm_input_tokens,
                "llm_output_tokens": llm_output_tokens,
                "embedding_tokens": embedding_tokens,
                "llm_cost_usd": llm_cost_usd,
                "embedding_cost_usd": embedding_cost_usd,
                "total_cost_usd": total_cost_usd
            })
            await self.db.commit()
        except Exception as ae:
            logger.warning(f"Failed to log analytics for stream: {ae}")
            try:
                await self.db.rollback()
            except Exception as rollback_err:
                logger.error(f"Failed to rollback analytics transaction: {rollback_err}")

    async def generate_answer(
        self,
        query: str,
        agent_id: str,
        kb_id: str | list[str],
        user_id: Optional[str] = None,
        top_k: int = 15,
        max_depth: int = 2,
        reasoning_enabled: bool = True,
        memory_enabled: bool = True,
    ) -> dict:
        logger.info(f" RAG Service: Generating answer for agent={agent_id}, kb={kb_id}")
        start_time_total = datetime.now()

        kb_ids = [kb_id] if isinstance(kb_id, str) else kb_id
        hybrid_merge_context = ""
        
        excel_kbs = []
        doc_kbs = []
        for kid in kb_ids:
            k_obj = await self.kb_repo.get_by_id(kid)
            if not k_obj:
                continue
            if str(k_obj.agent_id) != str(agent_id):
                logger.error(f"Agent {agent_id} does not own KB {kid}")
                return {"error": f"Agent {agent_id} does not own Knowledge Base {kid}", "answer": None, "sources": []}
            if getattr(k_obj, "description", "") == "excel_parquet":
                excel_kbs.append(k_obj)
            else:
                doc_kbs.append(k_obj)

        if not excel_kbs and not doc_kbs:
            return {"error": "No valid Knowledge Bases found", "answer": None, "sources": []}

        # ============= HYBRID RAG: INTERCEPT EXCEL/PARQUET QUERIES =============
        if excel_kbs:
            from app.core.parquet_ingester import ParquetIngester
            from app.modules.rag.pandas_engine import PandasQueryEngine
            import os
            active_paths = []
            path_mapping = {}
            for ek in excel_kbs:
                dataset_name = getattr(ek, "parsed_path", None) or getattr(ek, "s3_path", None)
                if dataset_name:
                    p = ParquetIngester.get_active_dataset(dataset_name)
                    if p:
                        active_paths.append(p)
                        # Clean original filename from "Spreadsheet: " prefix
                        orig_name = getattr(ek, "name", "dataset")
                        if orig_name.startswith("Spreadsheet: "):
                            orig_name = orig_name[len("Spreadsheet: "):]
                        elif orig_name.startswith("PDF: "):
                            orig_name = orig_name[len("PDF: "):]
                        path_mapping[os.path.basename(p)] = orig_name
            if active_paths:
                engine = PandasQueryEngine(active_paths[0], all_dataset_paths=active_paths, path_mapping=path_mapping)
                try:
                    result = await engine.execute_query(query, synthesize=(not doc_kbs))
                    result_str = str(result)
                    unmatched_signals = [
                        "not present in dataset", "no records matched", "error", 
                        "0 rows", "empty dataframe", "could not find", "no matching"
                    ]
                    is_unmatched = any(sig in result_str.lower() for sig in unmatched_signals)
                    explicit_math_keywords = ["sum of", "average of", "count of", "total of", "how many rows", "group by"]
                    is_pure_math = any(kw in query.lower() for kw in explicit_math_keywords)
                    if doc_kbs and is_unmatched:
                        logger.info(f"[generate_answer] Excel dataset lacked answer ({result_str}). Falling back to PDF/URL knowledge bases...")
                    elif doc_kbs and not is_pure_math:
                        logger.info("[generate_answer] Mixed sources: Injecting tabular result and searching PDFs/URLs...")
                        excel_filenames = ", ".join(getattr(ek, "name", "dataset") for ek in excel_kbs if getattr(ek, "name", None))
                        hybrid_merge_context = f"\n\n[ENTERPRISE SPREADSHEET ANALYSIS ({excel_filenames})]\n{result_str}\nUse the above numerical table results alongside document citations to answer the user query completely.\n"
                    else:
                        excel_filenames = ", ".join(getattr(ek, "name", "dataset") for ek in excel_kbs if getattr(ek, "name", None))
                        return {
                            "answer": result_str,
                            "sources": [
                                {
                                    "chunk_id": f"tabular_{ek.id}",
                                    "source": getattr(ek, "name", "").replace("Spreadsheet: ", "").replace("PDF: ", "") if getattr(ek, "name", None) else "Excel Parquet",
                                    "score": 1.0,
                                    "position": 0,
                                    "reason": "Tabular query match",
                                    "kb_id": str(ek.id),
                                    "content_type": "tabular"
                                }
                                for ek in excel_kbs
                            ],
                            "context": {"type": "duckdb_parquet"},
                            "stats": {}
                        }
                except Exception as e:
                    logger.error(f"PandasQueryEngine failed in generate_answer: {e}")
                    if not doc_kbs:
                        return {"error": str(e), "answer": None, "sources": []}



        logger.info(f" KB ownership verified: {kb.name}")



        # Fetch Agent details for persona branding (system_prompt, description)

        agent = await self.agent_repo.get_by_id(agent_id)
        if not agent:
            return {"error": f"Agent {agent_id} not found or inactive under the current tenant", "answer": None, "sources": []}

        base_prompt = agent.system_prompt or ""
        personality_description = agent.personality or "You are a warm, approachable, and supportive assistant."

        if agent.personality_id:
            personality = await self.db.get(Personality, agent.personality_id)
            if personality:
                personality_description = personality.description or personality.name

        accuracy_directives = (
            "\n- Enforce 100% factual accuracy based strictly on the retrieved context."
            "\n- Correct any obvious spelling or grammatical errors found in the source documents; do not copy typos."
            "\n- Verify timelines, chronologies, and locations strictly to avoid historical or situational errors."
        )
        if "factual accuracy" not in personality_description.lower():
            personality_description += accuracy_directives

        # Ontology Grounding
        from ..ontology.service import OntologyService
        try:
            ont_svc = OntologyService(self.tenant_id)
            ontology = await ont_svc.get_ontology()
            ontology_rules_str = ""
            if ontology and ontology.get("rules"):
                rules_list = [f"({r['source_class']})-[:{r['relation']}]->({r['target_class']})" for r in ontology["rules"] if r.get("source_class")]
                if rules_list:
                    ontology_rules_str = "\n\n[ENTERPRISE ONTOLOGY RULES (STRICT GROUNDING)]\n" + "\n".join(rules_list) + "\nAlign your reasoning strictly with these established business relationships. Do not hallucinate relationships outside of this schema."
        except Exception as e:
            logger.warning(f"Failed fetching active ontology for RAG prompt: {e}")
            ontology_rules_str = ""

        # episodic_guidance was fetched at the start of the stream to support parallel tasks.

        injected_system_prompt = f"""
[PERSONALITY MODE: STRICT]

You MUST strictly follow the personality defined below.
Every response MUST reflect this personality strongly in tone, wording, and structure.
Deviation is NOT allowed.

Personality Definition:
{personality_description}

Base Instruction:
{base_prompt}{ontology_rules_str}

You are an enterprise AI assistant.

==================================================
MEMORY AUTHORITY (HIGHEST PRIORITY — READ FIRST)
==================================================
If the user's message contains a section beginning with:
  "### MANDATORY USER PREFERENCES & MEMORY DIRECTIVES"
then you MUST treat everything in that section as VERIFIED GROUND TRUTH about the user.
- These facts are authoritative and override document context.
- Use them to answer personal questions directly (e.g., "what is my name?", "what is my 10th grade mark?").
- You are ALLOWED and REQUIRED to answer from this memory section even if the answer is not in the documents.
- Do NOT say "I couldn't find it" if the answer is present in the memory/preferences section.
- When answering from memory, say "Based on your saved profile, ..." to be transparent.

==================================================
GROUNDING RULES & HALLUCINATION PREVENTION
==================================================
Never complete missing information using prior knowledge.
If retrieved passages conflict, state the conflict. Do not resolve it yourself.
- Answer ONLY using the provided context OR verified user memory (see MEMORY AUTHORITY above).
- Before answering, verify that every factual statement in your response is explicitly supported by the retrieved context or user memory.
- If a statement is not directly supported by either source, do not include it.
- Do not combine information from your general knowledge with the retrieved context.
- Never use outside knowledge.
- Never invent, infer, estimate, or assume facts.
- If the requested information is missing from BOTH the document context AND the user memory section, reply exactly:
  "I couldn't find it."
- If only part of the answer exists, answer only that part.
- Mention the relevant source at the end.
- Answer ONLY the specific question asked by the user. Do not provide extra analysis, summaries of unrelated topics, or inferred narratives unless requested.
- Be concise. Focus strictly on direct answers and avoid filler.
- TRANSACTION CLASSIFICATION: Categorize transactions strictly:
  * Credit (Deposit/Incoming): Salary, interest, deposits, incoming transfers.
  * Debit (Withdrawal/Outgoing/Payment): ATM withdrawals, payments to merchants, fees, taxes, outgoing transfers.

==================================================
FORMATTING RULES
==================================================
- Use Markdown tables whenever information is easier to compare.
- Use bullet points for lists.

==================================================
SOURCE CITATION RULES
==================================================
Cite all the UNIQUE document/data sources that were used to formulate your answer.
Format each citation at the very end of your response on a single line:
[Source: <source_1>, <source_2>]

Rules:
- List every unique source used (e.g. clean file names like ARUN_N.pdf, data.xlsx).
- Deduplicate sources so each unique filename appears ONLY ONCE.
- Do NOT repeat the same filename multiple times.
- If tabular database/spreadsheet insights were used, cite the specific filename(s) shown in the header (e.g. "[Source: employees.csv]" or "[Source: data.xlsx]") as the source.
- The source citation line must appear only once at the very end of the response.

==================================================
RESPONSE FORMAT
==================================================
Answer:
<grounded answer>

If you'd like, I can also:
- ...
- ...

[Source: <source_1>, <source_2>]
""".strip()

        agent_persona = {
            "name": agent.name if agent else "Assistant",
            "personality": personality_description,
            "system_prompt": injected_system_prompt
        }

        if episodic_guidance:
            logger.debug("Episodic guidance retrieved; will inject into RAG context.")

        # Step 2: Cache check
        cache_key = self._make_cache_key(query, agent_id, "|".join(kb_ids), kb_version=kb.total_chunks)
        cached_response = self._get_cached_response(cache_key)
        if cached_response:
            self._track_metrics(cache_hit=True, seed_chunks_count=len(cached_response.get("sources", [])))
            return cached_response

        # Step 3: Retrieve context
        context = None
        try:
            context = await asyncio.wait_for(
                self.pipeline.query(
                    query=query,
                    agent_id=agent_id,
                    kb_id=kb_id,
                    user_id=user_id,
                    top_k=top_k,
                    max_depth=max_depth,
                ),
                timeout=_RAG_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            try:
                query_embedding = await EmbeddingGenerator.generate_embedding(query)
                seed_chunks = await self.pipeline._retrieve_seed_chunks(
                    kb_ids=kb_ids,
                    query_embedding=query_embedding,
                    top_k=top_k,
                    query=query,
                )

                if seed_chunks:
                    retrieved_chunks = [
                        self.pipeline.RetrievedChunk(
                            chunk_id=chunk["chunk_id"],
                            text=chunk["text"],
                            kb_id=chunk["kb_id"],
                            position=chunk["position"],
                            embedding_similarity=chunk["similarity"],
                            graph_score=1.0,
                            hybrid_score=chunk["similarity"],
                            reason="Seed chunk (timeout fallback - no expansion)",
                        )
                        for chunk in seed_chunks
                    ]

                    context = RAGContext(
                        query=query,
                        chunks=retrieved_chunks,
                        entity_mentions={},
                        total_tokens=sum(len(c.text.split()) * 1.3 for c in retrieved_chunks),
                    )
                else:
                    return {"error": "RAG retrieval timed out (query too complex)", "answer": None, "sources": []}
            except Exception as fallback_e:
                return {"error": "RAG retrieval timed out and fallback failed", "answer": None, "sources": []}
        except Exception as e:
            return {"error": f"RAG retrieval failed: {str(e)}", "answer": None, "sources": []}

        is_social = context.search_type == "SOCIAL" if context else False
        is_support = context.search_type == "SUPPORT_INTENT" if context else False
        
        if is_support and agent.agent_type == "integrated":
            contact_info = []
            if agent.contact_phone: contact_info.append(f"Phone: {agent.contact_phone}")
            if agent.contact_email: contact_info.append(f"Email: {agent.contact_email}")
            if agent.website_url: contact_info.append(f"Website: {agent.website_url}")
            
            contact_str = " | ".join(contact_info)
            org_name = agent.organization_name or "our organization"
            
            msg = f"For support or human assistance, please contact {org_name} directly."
            if contact_str:
                msg += f" You can reach us at: {contact_str}"
                
            return {
                "answer": msg,
                "sources": [],
                "context": {
                    "kb_id": kb_id,
                    "kb_name": kb.name,
                    "chunks_used": 0,
                    "entities_mentioned": [],
                    "reasoning_path": "Bypassed retrieval for integrated support intent.",
                },
                "stats": {
                    "total_chunks": 0,
                    "total_tokens": 0,
                    "entity_count": 0,
                    "llm_tokens": 0,
                    "llm_input_tokens": 0,
                    "llm_output_tokens": 0,
                    "llm_source": "SupportFallback",
                    "search_strategy": "SUPPORT_INTENT",
                },
                "confidence": 1.0,
                "nodes_used": 0,
                "reasoning_path": "Bypassed retrieval for integrated support intent.",
            }
        
        is_extractive = context.search_type == "EXTRACTIVE" if context else False
        is_table_analytics = context.search_type == "TABLE_ANALYTICS" if context else False

        if is_extractive or is_table_analytics:
            result = {
                "answer": context.triplet_context,
                "sources": [],
                "context": {
                    "kb_id": kb_id,
                    "kb_name": kb.name,
                    "chunks_used": 0,
                    "entities_mentioned": [],
                    "reasoning_path": f"Bypassed retrieval for {context.search_type}.",
                },
                "stats": {
                    "total_chunks": 0,
                    "total_tokens": 0,
                    "entity_count": 0,
                    "llm_tokens": 0,
                    "llm_input_tokens": 0,
                    "llm_output_tokens": 0,
                    "llm_source": "DirectExtraction",
                    "search_strategy": context.search_type,
                },
                "confidence": 1.0,
                "nodes_used": 0,
                "reasoning_path": f"Bypassed retrieval for {context.search_type}.",
            }
            self._cache_response(cache_key, result)
            return result

        if (not context or not context.chunks) and not is_social:
            if agent.agent_type == "integrated":
                if agent.fallback_message_enabled:
                    org_name = agent.organization_name or "our organization"
                    contact_info = []
                    if agent.contact_phone: contact_info.append(f"Phone: {agent.contact_phone}")
                    if agent.contact_email: contact_info.append(f"Email: {agent.contact_email}")
                    if agent.website_url: contact_info.append(f"Website: {agent.website_url}")
                    contact_str = " | ".join(contact_info)
                    
                    fallback_msg = f"I am unable to find information regarding your query. Please contact {org_name} for more details."
                    if contact_str:
                        fallback_msg += f" You can reach us at: {contact_str}"
                else:
                    fallback_msg = "I'm sorry, but I don't have enough information to answer that question."
            else:
                fallback_msg = "I'm sorry, but I don't have that specific information in my current knowledge base."
            
            return {
                "answer": fallback_msg,
                "sources": [],
                "context": {
                    "kb_id": kb_id,
                    "kb_name": kb.name,
                    "chunks_used": 0,
                    "entities_mentioned": [],
                    "reasoning_path": "No relevant knowledge found in graph to answer this question.",
                },
                "stats": {
                    "total_chunks": 0,
                    "total_tokens": 0,
                    "entity_count": 0,
                    "llm_tokens": 0,
                    "llm_input_tokens": 0,
                    "llm_output_tokens": 0,
                    "llm_source": "Fallback",
                    "search_strategy": context.search_type if context else "DEFAULT",
                },
                "confidence": 0.0,
                "nodes_used": 0,
                "reasoning_path": "No relevant knowledge found in graph to answer this question.",
            }

        # Step 4: Format Context & LLM Generation
        formatted_context = self._format_context(context, hybrid_merge_context=hybrid_merge_context) if context else (hybrid_merge_context or "")
        
        if episodic_guidance:
            formatted_context = (
                "### MANDATORY USER PREFERENCES & MEMORY DIRECTIVES\n"
                f"{episodic_guidance}\n\n"
            ) + formatted_context
        llm_response = await self._generate_answer_llm(
            query=query,
            context=formatted_context,
            tenant_id=self.tenant_id,
            agent_id=agent_id,
            agent_persona=agent_persona,
        )
        answer = llm_response.answer

        from app.modules.rag.orchestrator.validator import NumericValidator
        validator = NumericValidator()
        if not validator.validate(answer, context):
            answer += "\n\n> [!WARNING]\n> Some numbers in this response could not be strictly verified against the retrieved context. Please double check the source documents."

        sources = [
            {
                "chunk_id": chunk.chunk_id,
                "score": chunk.hybrid_score,
                "position": chunk.position,
                "reason": chunk.reason,
                "source": chunk.source,
                "s3_path": getattr(chunk, "s3_path", None),
                "kb_id": chunk.kb_id,
                "content_type": getattr(chunk, "content_type", "original")
            }
            for chunk in context.chunks
        ]
        if excel_kbs:
            for ek in excel_kbs:
                sources.append({
                    "chunk_id": f"tabular_{ek.id}",
                    "score": 1.0,
                    "position": 0,
                    "reason": "Tabular query match",
                    "source": getattr(ek, "name", "").replace("Spreadsheet: ", "").replace("PDF: ", "") if getattr(ek, "name", None) else "Excel Parquet",
                    "s3_path": getattr(ek, "s3_path", None),
                    "kb_id": str(ek.id),
                    "content_type": "tabular"
                })

        nodes_used = len(context.chunks) + len(context.entity_mentions)
        confidence = sum(c.hybrid_score for c in context.chunks) / len(context.chunks) if context.chunks else 0.0

        seed_count = sum(1 for c in context.chunks if "seed" in c.reason.lower())
        exp_count = sum(1 for c in context.chunks if "expanded" in c.reason.lower())

        reasoning_path = (
            "No relevant knowledge found in graph to answer this question."
            if nodes_used == 0 else
            f"Found {seed_count} semantic seed chunks. Expanded via graph relationships to find {exp_count} additional chunks and {len(context.entity_mentions)} relevant entities."
        )

        response = {
            "answer": answer,
            "sources": sources,
            "context": {
                "kb_id": kb_id,
                "kb_name": kb.name if len(kb_ids) == 1 else "Multi-Source Context",
                "chunks_used": len(context.chunks),
                "entities_mentioned": list(context.entity_mentions.keys()),
                "reasoning_path": reasoning_path,
                "augmented_query": query,
            },
            "stats": {
                "total_chunks": len(context.chunks),
                "total_tokens": int(context.total_tokens),
                "entity_count": len(context.entity_mentions),
                "llm_tokens": llm_response.total_tokens,
                "llm_input_tokens": llm_response.prompt_tokens,
                "llm_output_tokens": llm_response.completion_tokens,
                "llm_source": llm_response.source,
                "llm_prompt_version": llm_response.prompt_version,
                "search_strategy": context.search_type,
            },
            "confidence": confidence,
            "nodes_used": nodes_used,
            "reasoning_path": reasoning_path if reasoning_enabled else "Reasoning path hidden by user request.",
        }

        if is_billing_enabled():
            response["stats"]["llm_cost_estimate"] = round(llm_response.cost_estimate, 6)

        try:
            analytics_repo = AnalyticsRepository(self.db, UUID(self.tenant_id))
            await analytics_repo.create_query_log({
                "query": query,
                "response_status": ResponseStatus.SUCCESS if context.chunks else ResponseStatus.UNANSWERED,
                "confidence_score": confidence,
                "latency_ms": (datetime.now() - start_time_total).total_seconds() * 1000
            })
        except Exception as ae:
            logger.warning(f"Failed to log query to analytics: {ae}")

        self._cache_response(cache_key, response)
        return response

    async def _fetch_episodic_guidance(self, query: str, agent_id: str, user_id: Optional[str], memory_enabled: bool) -> str:
        if not memory_enabled or not user_id:
            return ""
        import httpx
        import uuid
        import os
        MEMORY_API_BASE_URL = os.getenv("MEMORY_API_BASE_URL", "http://memory-api:8001").rstrip("/")
        MEMORY_API_URL = f"{MEMORY_API_BASE_URL}/api/v1/memory"
        async with httpx.AsyncClient() as client:
            try:
                mem_resp = await client.post(
                    f"{MEMORY_API_URL}/process-turn",
                    json={
                        "query": query,
                        "session_id": str(uuid.uuid4()),
                        "agent_id": agent_id,
                        "user_id": user_id,
                        "tenant_id": self.tenant_id
                    },
                    timeout=8.0
                )
                if mem_resp.status_code == 200:
                    mem_data = mem_resp.json()
                    guidance = mem_data.get("guidance_context") or ""
                    logger.info(f"Memory API returned guidance_context: {guidance!r}")
                    return guidance
                else:
                    logger.warning(f"memory-api process-turn status={mem_resp.status_code}: {mem_resp.text}")
            except Exception as e:
                logger.warning(f"memory-api process-turn unreachable, continuing without memory: {e}")
        return ""

    def _make_cache_key(self, query: str, agent_id: str, kb_id: str, kb_version: int = 0) -> str:
        key_str = f"{query}|{agent_id}|{kb_id}|v{kb_version}"
        return hashlib.sha256(key_str.encode()).hexdigest()

    def _get_cached_response(self, cache_key: str) -> Optional[dict]:
        if cache_key not in _rag_cache:
            return None

        response, timestamp = _rag_cache[cache_key]
        age = (datetime.now() - timestamp).total_seconds()
        if age > _CACHE_TTL_SECONDS:
            del _rag_cache[cache_key]
            return None

        return response

    def _cache_response(self, cache_key: str, response: dict) -> None:
        global _CACHE_INSERTION_ORDER
        _rag_cache[cache_key] = (response, datetime.now())

        if cache_key not in _CACHE_INSERTION_ORDER:
            _CACHE_INSERTION_ORDER.append(cache_key)

        while len(_rag_cache) > _MAX_CACHE_SIZE:
            oldest_key = _CACHE_INSERTION_ORDER.pop(0)
            if oldest_key in _rag_cache:
                del _rag_cache[oldest_key]

    def _format_context(self, context: RAGContext, hybrid_merge_context: Optional[str] = None) -> str:
        context_text = f"QUERY: {context.query}\n" + "=" * 60 + "\nCONTEXT (from Knowledge Base):\n"
        if hybrid_merge_context:
            context_text += f"{hybrid_merge_context}\n" + "=" * 60 + "\n"

        for i, chunk in enumerate(context.chunks, 1):
            s3_path = getattr(chunk, "s3_path", None)
            raw_src = s3_path or chunk.source
            source_info = clean_source_name(raw_src) if raw_src else "Unknown Source"
            context_text += f"\n[Chunk {i}/{len(context.chunks)} - Source: {source_info} - Position {chunk.position}]"
            context_text += f"\nScore: {chunk.hybrid_score:.3f} (Semantic: {chunk.embedding_similarity:.3f}, Graph: {chunk.graph_score:.3f})"
            context_text += f"\n{'-' * 40}\n{chunk.text}\n"

        if context.entity_mentions:
            context_text += "\n" + "=" * 60 + "\nENTITIES MENTIONED:\n"
            for entity, chunk_ids in context.entity_mentions.items():
                context_text += f"- {entity} (mentioned in {len(chunk_ids)} chunks)\n"

        if context.triplet_context:
            context_text += f"\n[KNOWLEDGE GRAPH RELATIONSHIPS]:\n{context.triplet_context}\n"
        if getattr(context, "authoritative_entities", None):
            context_text += "\n" + "=" * 60 + "\n[VERIFIED DATA ENTITIES (HIGH TRUST)]\n"
            context_text += "The following entities are verified from the document/database. Use these values to answer the user's query if they are relevant:\n"
            for ent in context.authoritative_entities:
                clean_src = clean_source_name(ent.get('source', 'document_entities'))
                context_text += f"- {ent['entity_type']}: {ent['value']} (Page: {ent.get('page', 1)}, Source: {clean_src})\n"
            context_text += "=" * 60 + "\n"

        if context.personal_memories:
            pm_text = "\n".join([f"- {m}" for m in context.personal_memories])
            context_text += f"\n[USER PERSONAL PREFERENCES & HABITS]:\n{pm_text}\n"

        return context_text

    async def process_feedback(self, chunk_ids: list[str], rating: int) -> None:
        if not chunk_ids:
            return
            
        weight_delta = 0.1 if rating > 0 else -0.1
        
        query = """
        UNWIND $chunk_ids AS chunk_id
        MATCH (c:Chunk {id: chunk_id, tenant_id: $tenant_id})
        SET c.weight = CASE 
            WHEN coalesce(c.weight, 1.0) + $delta > 2.0 THEN 2.0
            WHEN coalesce(c.weight, 1.0) + $delta < 0.1 THEN 0.1
            ELSE coalesce(c.weight, 1.0) + $delta 
        END
        """
        
        try:
            await self.pipeline.neo4j_repo.execute_write(
                query,
                {
                    "chunk_ids": chunk_ids,
                    "tenant_id": self.tenant_id,
                    "delta": weight_delta
                }
            )
            logger.info(f" Updated feedback weight ({weight_delta}) for {len(chunk_ids)} chunks")
        except Exception as e:
            logger.error(f" Failed to update feedback weights: {e}")
            raise

    async def _generate_answer_llm(
        self,
        query: str,
        context: str,
        tenant_id: str,
        agent_id: str,
        agent_persona: Optional[dict] = None,
    ) -> LLMResponse:
        try:
            llm_response = await self.llm_client.generate_answer(
                query=query,
                context=context,
                tenant_id=tenant_id,
                agent_id=agent_id,
                agent_persona=agent_persona,
                enable_thinking=False,
            )
            return llm_response
        except Exception as e:
            logger.warning(f"Phase 3 failed ({e}). Falling back to template generation...")
            return self._generate_answer_template(query, context, tenant_id, agent_id)

    def _generate_answer_template(
        self, query: str, context: str, tenant_id: str, agent_id: str
    ) -> LLMResponse:
        lines = context.split("\n")
        relevant_lines = [line for line in lines if line.strip() and not line.startswith("[")]

        answer_parts = ["Based on the knowledge base, here's what I found:\n\n"]
        chunk_count = 0
        for line in relevant_lines:
            if line.startswith("Chunk") or line.startswith("Score"):
                chunk_count += 1
                continue
            if line.startswith("-"):
                answer_parts.append(f" {line[1:].strip()}\n")
            elif line.strip() and chunk_count < 3:
                answer_parts.append(line + "\n")

        answer = "".join(answer_parts)

        return LLMResponse(
            answer=answer or "No answer could be generated from the knowledge base.",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_estimate=0.0,
            prompt_version="v1",
            source="Template",
            tenant_id=tenant_id,
            agent_id=agent_id,
        )

    def _track_metrics(
        self,
        cache_hit: bool = False,
        seed_chunks_count: int = 0,
        expanded_chunks_count: int = 0,
        final_chunks_count: int = 0,
        timeout_occurred: bool = False,
        partial_result: bool = False,
        retrieval_latency_ms: float = 0.0,
        ranking_latency_ms: float = 0.0,
        total_latency_ms: float = 0.0,
    ) -> None:
        try:
            metric = RAGMetrics(
                retrieval_latency_ms=retrieval_latency_ms,
                ranking_latency_ms=ranking_latency_ms,
                total_latency_ms=total_latency_ms,
                cache_hit=cache_hit,
                seed_chunks_count=seed_chunks_count,
                expanded_chunks_count=expanded_chunks_count,
                final_chunks_count=final_chunks_count,
                timeout_occurred=timeout_occurred,
                partial_result=partial_result,
            )
            _rag_metrics.append(metric)
            if len(_rag_metrics) % 10 == 0:
                self._log_metrics_summary()
        except Exception as e:
            logger.warning(f"Failed to track metrics: {e}")

    def _log_metrics_summary(self) -> None:
        if not _rag_metrics or len(_rag_metrics) < 10:
            return

        recent = _rag_metrics[-10:]
        avg_latency = sum(m.total_latency_ms for m in recent) / len(recent)
        cache_hit_rate = sum(1 for m in recent if m.cache_hit) / len(recent)
        timeout_count = sum(1 for m in recent if m.timeout_occurred)
        partial_count = sum(1 for m in recent if m.partial_result)
        avg_expanded = sum(m.expanded_chunks_count for m in recent) / len(recent)

        logger.info(
            f" RAG Metrics (last 10): latency={avg_latency:.0f}ms, cache_hit_rate={cache_hit_rate:.0%}, "
            f"timeouts={timeout_count}, partial_results={partial_count}, avg_expanded_chunks={avg_expanded:.1f}"
        )

    def get_metrics(self) -> list:
        return _rag_metrics.copy()

    def clear_metrics(self) -> None:
        global _rag_metrics
        _rag_metrics.clear()

    def get_health_metrics(self) -> dict:
        if not _rag_metrics:
            return {
                "avg_latency_ms": 0.0,
                "cache_hit_rate": 0.0,
                "total_queries": 0,
                "cache_size": len(_rag_cache),
                "timeout_rate": 0.0,
                "partial_result_rate": 0.0,
            }

        total = len(_rag_metrics)
        avg_latency = sum(m.total_latency_ms for m in _rag_metrics) / total
        cache_hits = sum(1 for m in _rag_metrics if m.cache_hit)
        cache_hit_rate = cache_hits / total if total > 0 else 0.0
        timeouts = sum(1 for m in _rag_metrics if m.timeout_occurred)
        timeout_rate = timeouts / total if total > 0 else 0.0
        partials = sum(1 for m in _rag_metrics if m.partial_result)
        partial_rate = partials / total if total > 0 else 0.0

        return {
            "avg_latency_ms": round(avg_latency, 2),
            "cache_hit_rate": f"{cache_hit_rate:.0%}",
            "total_queries": total,
            "cache_size": len(_rag_cache),
            "timeout_rate": f"{timeout_rate:.1%}",
            "partial_result_rate": f"{partial_rate:.1%}",
        }