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
from ...core.config import get_settings
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
        memory_task: Optional['asyncio.Task'] = None,
    ):
        logger.info(f" RAG Service: Streaming answer for agent={agent_id}, kb={kb_id}")
        
        import time
        trace_start_time = time.time()
        # Ensure query length is safe for logging
        short_query = query[:50] + "..." if len(query) > 50 else query
        logger.info(f"[TRACE_E2E] [ENTRY] ChatService.stream_rag_answer - Input: '{short_query}', Tenant: {self.tenant_id}, Agent: {agent_id}, KB: {kb_id}")
        
        sql_task = None
        vector_task = None
        memory_task = None

        try:
            # 1. Validate KB ownership
            kb_ids = [kb_id] if isinstance(kb_id, str) else kb_id
    
            # 1. Validate KB ownership and separate Excel vs Document KBs
            excel_kbs = []
            doc_kbs = []
            
            kb_results = []
            for kid in kb_ids:
                kb = await self.kb_repo.get_by_id(kid)
                if kb:
                    self.db.expunge(kb)
                kb_results.append((kid, kb))
            
            for kid, kb in kb_results:
                if not kb:
                    yield json.dumps({"error": f"Knowledge Base {kid} not found"})
                    return
                if str(kb.agent_id) != str(agent_id):
                    yield json.dumps(
                        {"error": "Unauthorized: Agent does not own this Knowledge Base"}
                    )
                    return
                if getattr(kb, "description", "") == "excel_parquet":
                    excel_kbs.append(kb)
                else:
                    doc_kbs.append(kb)

            agent = await self.agent_repo.get_by_id(agent_id)
            if agent:
                self.db.expunge(agent)
                agent_name = agent.name
                base_prompt = agent.system_prompt or ""
                personality_description = agent.personality or "You are a warm, approachable, and supportive assistant."
                
                # Fetch personality details early too
                if agent.personality_id:
                    from app.modules.personalities.models import Personality
                    personality = await self.db.get(Personality, agent.personality_id)
                    if personality:
                        personality_description = personality.description or personality.name
            else:
                agent_name = "Unknown"
                base_prompt = ""
                personality_description = "You are a warm, approachable, and supportive assistant."

            from ..ontology.service import OntologyService
            ont_svc = OntologyService(self.tenant_id)
            ontology = await ont_svc.get_ontology()
    
            kb_context_lines = []
            for kb in (doc_kbs + excel_kbs):
                name = getattr(kb, 'name', 'Unknown')
                desc = getattr(kb, 'description', '')
                kb_context_lines.append(f"- {name}: {desc}")
            kb_context = "\n".join(kb_context_lines) if kb_context_lines else "None provided."

            # ============= EARLY QUERY ANALYSIS (ROUTING) =============
            from app.modules.rag.orchestrator.query_analyzer import QueryAnalyzer
            from app.core.embeddings import EmbeddingGenerator
            import time
            
            analyzer_start = time.time()
            analyzer = QueryAnalyzer()
            
            logger.info(f"[TRACE_E2E] [ENTRY] QueryAnalyzer.analyze_query - Input: '{short_query}'")
            
            # Step 2 Latency Fix: Gather QueryAnalyzer and original Query Embedding concurrently
            analysis_task = asyncio.create_task(analyzer.analyze_query(query, kb_context=kb_context, chat_history=chat_history))
            embed_task = asyncio.create_task(EmbeddingGenerator.generate_embedding_with_usage(query))
            
            analysis, embed_res = await asyncio.gather(analysis_task, embed_task)
            
            analyzer_latency = time.time() - analyzer_start
            logger.info(f"[TRACE_E2E] [EXIT] QueryAnalyzer + Embed (Concurrent) - Output: {getattr(analysis, 'intent', 'Unknown')} - Latency: {analyzer_latency:.2f}s")
            logger.info(f"TELEMETRY: QueryAnalyzer + Embed completed in {analyzer_latency:.2f}s")

            # ============= HYBRID RAG: ENTERPRISE SCHEMA-AWARE ROUTING =============
            hybrid_merge_context = ""
            if excel_kbs:
                from app.core.parquet_ingester import ParquetIngester
                from app.modules.rag.pandas_engine import PandasQueryEngine
    
                active_paths = []
                for ekb in excel_kbs:
                    dataset_name = getattr(ekb, "parsed_path", None) or getattr(
                        ekb, "s3_path", None
                    )
                    if dataset_name:
                        p = ParquetIngester.get_active_dataset(dataset_name)
                        if p:
                            active_paths.append(p)
    
                if not active_paths and not doc_kbs:
                    yield json.dumps(
                        {
                            "error": "Active parquet datasets for Excel Knowledge Bases not found."
                        }
                    )
                    return
    
                if active_paths:
                    import pyarrow.parquet as pq
                    
                    schema_col_terms = set()
                    schema_name_terms = set()
                    overlap = False
                    reason = "not_tabular"
                    
                    # Tabular Intent Refinement (Stage 1.6)
                    try:
                        from app.modules.rag.schema_utils import evaluate_schema_overlap, calculate_schema_overlap_score
                        
                        best_score = -1
                        best_kb = None
                        
                        for kb in excel_kbs:
                            ds = getattr(kb, "dataset_schema", None)
                            cv = getattr(kb, "categorical_values", None)
                            name = getattr(kb, "parsed_path", None) or getattr(kb, "name", None)
                            
                            cat_score, gen_score = calculate_schema_overlap_score(query, ds, cv, name)
                            total_score = cat_score * 2 + gen_score  # weight categorical matches higher
                            
                            logger.info(f"[SCHEMA_SCORING] KB: {name} | cat_score: {cat_score} | gen_score: {gen_score} | total_score: {total_score}")
                            
                            if total_score > best_score:
                                best_score = total_score
                                best_kb = kb
                        
                        strict_schema_overlap = False
                        reason = "weak_or_zero_schema_overlap"
                        if best_kb:
                            ds = getattr(best_kb, "dataset_schema", None)
                            cv = getattr(best_kb, "categorical_values", None)
                            paths = [best_kb.parsed_path] if getattr(best_kb, "parsed_path", None) else []
                            strict_schema_overlap, reason, is_tabular = evaluate_schema_overlap(
                                query, ds, cv, paths
                            )
                        
                        if strict_schema_overlap:
                            overlap = True
                            if best_kb:
                                # Ensure downstream pipeline queries only this specific KB
                                analysis.metadata.target_kb_id = str(best_kb.id)
                                logger.info(f"Fast routing pinned exact KB: {getattr(best_kb, 'name', 'Unknown')} ({best_kb.id})")
                            if not analysis.is_tabular:
                                logger.warning(f"⚠️ OVERRIDING LLM INTENT ({getattr(analysis, 'intent', 'UNKNOWN')}) TO TABULAR based on: {reason}")
                            analysis.is_tabular = True
                        else:
                            overlap = False
                            if not doc_kbs:
                                # Fallback: if no PDFs exist, we MUST treat it as tabular anyway so it doesn't fail silently
                                overlap = True
                                reason = "only_kb_available"
                                analysis.is_tabular = True
                                if best_kb:
                                    analysis.metadata.target_kb_id = str(best_kb.id)
                                logger.info("   -> No schema overlap, but only CSVs are available. Forcing tabular.")
                            elif analysis.is_tabular or getattr(analysis.metadata, "tabular_subquery", None):
                                logger.info("   -> LLM classified as TABULAR, but schema overlap was too weak. Trusting LLM but logging as ambiguous.")
                    except Exception as e:
                        logger.error(f"Fast schema check failed: {e}", exc_info=True)
                        if analysis.is_tabular or getattr(analysis.metadata, "tabular_subquery", None):
                            overlap = True # fallback
                            reason = f"schema_check_failed_but_tabular (Error: {e})"
                            
                    # We no longer execute PandasQueryEngine here! We leave it to pipeline.py.
                    logger.info(f"TELEMETRY: schema_overlap_evaluated, result={overlap}, reason={reason}")

            context = None
            is_composite = bool(getattr(analysis.metadata, "tabular_subquery", None)) and bool(getattr(analysis.metadata, "vector_subquery", None))
            
            if is_composite and not skip_search:
                logger.info("TELEMETRY: composite_query_detected (Routing to BOTH tabular and vector engines)")
                
                tabular_subquery = analysis.metadata.tabular_subquery
                vector_subquery = analysis.metadata.vector_subquery
                
                # Pre-strip the tabular subquery to drop non-schema clauses
                import re
                clauses = re.split(r'\s+and\s+|\s*,\s*', tabular_subquery.lower())
                valid_clauses = []
                analytic_verbs = {"average", "total", "sum", "count", "list", "how many", "max", "min"}
                for clause in clauses:
                    clause_terms = set(re.findall(r'[a-zA-Z0-9]+', clause))
                    t_overlap = len(clause_terms & (schema_col_terms | schema_name_terms))
                    c_id_regex = bool(re.search(r'[a-zA-Z]{2,5}[0-9]{3,}', clause))
                    if c_id_regex or t_overlap >= 1: 
                        valid_clauses.append(clause)
                
                stripped_tabular = " and ".join(valid_clauses) if valid_clauses else tabular_subquery
                logger.info(f"Stripped composite tabular query: {tabular_subquery} -> {stripped_tabular}")

                import copy
                vec_analysis = copy.deepcopy(analysis)
                vec_analysis.is_tabular = False 
                
                async def run_vector_leg(subq, name):
                    vec_start = time.time()
                    res = await self.pipeline.query(
                        query=subq,
                        agent_id=agent_id,
                        kb_id=kb_ids,
                        user_id=user_id,
                        top_k=top_k,
                        max_depth=max_depth,
                        kb_context=kb_context,
                        analysis=vec_analysis,
                        query_embedding_tuple=(embed_res if subq == query else None)
                    )
                    logger.info(f"[TRACE_E2E] [EXIT] RAGPipeline.query ({name}) - Latency: {time.time() - vec_start:.2f}s")
                    return res
                    
                async def run_tabular_leg():
                    tab_start = time.time()
                    sql_res = await self.pipeline._execute_table_analytics(stripped_tabular, kb_ids)
                    logger.info(f"[TRACE_E2E] [EXIT] _execute_table_analytics (Composite Tabular) - Latency: {time.time() - tab_start:.2f}s")
                    return sql_res
                    
                gather_start = time.time()
                try:
                    res = await asyncio.gather(
                        asyncio.wait_for(run_vector_leg(vector_subquery, "Vector-Only Subq"), timeout=_RAG_TIMEOUT_SECONDS),
                        asyncio.wait_for(run_vector_leg(tabular_subquery, "Tabular-for-Vector Subq"), timeout=_RAG_TIMEOUT_SECONDS),
                        asyncio.wait_for(run_tabular_leg(), timeout=30.0),
                        return_exceptions=True
                    )
                    logger.info(f"TELEMETRY: Composite engines completed in {time.time() - gather_start:.2f}s")
                    vec1_res, vec2_res, tab_res = res[0], res[1], res[2]
                    
                    merged_chunks = []
                    if not isinstance(vec1_res, Exception) and vec1_res:
                        merged_chunks.extend(vec1_res.chunks)
                    if not isinstance(vec2_res, Exception) and vec2_res:
                        merged_chunks.extend(vec2_res.chunks)
                        
                    if merged_chunks:
                        # deduplicate chunks by chunk_id and sort by hybrid_score
                        seen = set()
                        deduped = []
                        for c in merged_chunks:
                            if c.chunk_id not in seen:
                                seen.add(c.chunk_id)
                                deduped.append(c)
                        deduped.sort(key=lambda x: getattr(x, 'hybrid_score', 0), reverse=True)
                        
                        context = vec1_res if not isinstance(vec1_res, Exception) else vec2_res
                        context.chunks = deduped
                        
                    if not isinstance(tab_res, Exception) and tab_res:
                        unmatched_signals = ["not present in dataset", "no records matched", "error", "0 rows", "empty dataframe"]
                        if not any(sig in str(tab_res).lower() for sig in unmatched_signals):
                            hybrid_merge_context = f"\n\n[ENTERPRISE SPREADSHEET ANALYSIS (TABULAR_SQL INSIGHTS)]\n{str(tab_res)}\nUse the above numerical table results alongside document citations to answer the user query completely.\n"
                except Exception as e:
                    logger.error(f"Composite Execution failed: {e}")
                
                skip_search = True
                
            elif not skip_search and (doc_kbs or not excel_kbs or excel_kbs):
                logger.info("TELEMETRY: single_intent_invoked (Pipeline will handle SQL interception if tabular)")
                
                logger.info(f"[TRACE_E2E] [ENTRY] RAGPipeline.query - Input: '{short_query}'")
                vec_start = time.time()
                try:
                    res = await asyncio.wait_for(
                        self.pipeline.query(
                            query=query,
                            agent_id=agent_id,
                            kb_id=kb_ids,
                            user_id=user_id,
                            top_k=top_k,
                            max_depth=max_depth,
                            kb_context=kb_context,
                            analysis=analysis,
                            query_embedding_tuple=embed_res
                        ),
                        timeout=_RAG_TIMEOUT_SECONDS
                    )
                    vec_latency = time.time() - vec_start
                    logger.info(f"[TRACE_E2E] [EXIT] RAGPipeline.query - Output: {len(res.chunks) if res and res.chunks else 0} chunks - Latency: {vec_latency:.2f}s")
                    context = res
                except asyncio.TimeoutError:
                    logger.error(f"RAG Retrieval timed out after {_RAG_TIMEOUT_SECONDS}s")
                    yield json.dumps({"error": "The AI provider is taking too long to respond. Please try again later."})
                    return
                except Exception as e:
                    logger.error(f"RAG Retrieval failed for stream: {e}")
                    yield json.dumps({"error": f"Retrieval failed: {e}"})
                    return
                    
            skip_search = True  # Bypass redundant sequential search below
    
            if memory_task:
                try:
                    mem_data = await memory_task
                    is_feedback_only = mem_data.get("is_feedback_only", False)
                    is_history_query = mem_data.get("is_history_query", False)
                    episodic_guidance = mem_data.get("guidance_context") or ""
                    
                    if is_feedback_only:
                        ack = "Understood! I've updated your preferences and saved them to my long-term memory."
                        yield json.dumps({"type": "feedback_bypass", "ack": ack, "router_category": mem_data.get("category")})
                        return
                        
                    if is_history_query:
                        history_prompt = (
                            "You are a helpful assistant. The user is asking about past chat history.\n"
                            "Answer their question using ONLY the provided conversation context and graph facts below.\n\n"
                            f"{episodic_guidance if episodic_guidance else 'No previous chat history found for this user.'}\n\n"
                            f"User Question: {query}\n\n"
                            "Provide a clear, concise summary of what was discussed:"
                        )
                        yield json.dumps({"type": "history_bypass", "history_prompt": history_prompt, "episodic_guidance": episodic_guidance})
                        return
                    
                    if episodic_guidance:
                        guidance_block = f"### MANDATORY USER PREFERENCES & MEMORY DIRECTIVES\n{episodic_guidance}\n"
                        chat_history = guidance_block + ("\n" + chat_history if chat_history else "")
                except Exception as mem_err:
                    import logging
                    logger.warning(f"Memory task failed during concurrent execution: {mem_err}")

            if len(kb_ids) > 1:
                logger.info(
                    f" Querying across {len(kb_ids)} Knowledge Bases for agent {agent_id}"
                )
    
            if not agent:
                yield json.dumps(
                    {
                        "error": f"Agent {agent_id} not found or inactive under the current tenant"
                    }
                )
                return
            
            # base_prompt and personality_description are pre-loaded at the top of stream_rag_answer
    
            accuracy_directives = (
                "\n- Enforce 100% factual accuracy based strictly on the retrieved context."
                "\n- Correct any obvious spelling or grammatical errors found in the source documents; do not copy typos."
                "\n- Verify timelines, chronologies, and locations strictly to avoid historical or situational errors."
            )
            if "factual accuracy" not in personality_description.lower():
                personality_description += accuracy_directives
    
            # Ontology Grounding
            try:
                # ontology already pre-loaded
                ontology_rules_str = ""
                if ontology and ontology.get("rules"):
                    rules_list = [
                        f"({r['source_class']})-[:{r['relation']}]->({r['target_class']})"
                        for r in ontology["rules"]
                        if r.get("source_class")
                    ]
                    if rules_list:
                        ontology_rules_str = (
                            "\n\n[ENTERPRISE ONTOLOGY RULES (STRICT GROUNDING)]\n"
                            + "\n".join(rules_list)
                            + "\nAlign your reasoning strictly with these established business relationships. Do not hallucinate relationships outside of this schema."
                        )
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
    MEMORY AUTHORITY (HIGHEST PRIORITY - READ FIRST)
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
    - If the user is asking a factual/document question and the requested information is missing from BOTH the document context AND the user memory section, reply exactly:
      "I couldn't find it."
    - If only part of the answer exists, answer only that part.
    - Mention the relevant source at the end.
    - Answer ONLY the specific question asked by the user. If the user asks a complex or multi-part question, you MUST address EVERY part of the question in your response. Do not provide extra analysis, summaries of unrelated topics, or inferred narratives unless requested.
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
    SOURCE CITATION RULES (STRICT)
    ==================================================
    1. GREETINGS & CASUAL CONVERSATION (CRITICAL):
    - If the user's input is a greeting (e.g. "Hello", "Hi", "Good morning", "How are you?"), polite chitchat, or a general conversational response, respond warmly according to your assigned personality without saying "I couldn't find it", and DO NOT output any source citation tag at all.
    - NEVER include [Source: ...] for greetings, introduction messages, or general chitchat.
    
    2. DOCUMENT CONTENT & ACCURATE CITATIONS:
    - Cite a source ONLY IF information from retrieved document/data chunks was ACTUALLY USED to answer the user's specific question.
    - Cite ONLY the specific filename(s) from which relevant facts were extracted.
    - Single Source: If the answer came from only one document (e.g. ARUN_N.pdf), cite ONLY that single document: [Source: ARUN_N.pdf]. Do NOT list other unused files.
    - Multi Source: If the answer combined information from multiple documents, list only those specific documents: [Source: file1.pdf, file2.pdf].
    - Deduplicate sources so each unique filename appears ONLY ONCE.
    - Format the citation at the very end of your response on its own single line:
      [Source: filename1, filename2]
    
    ==================================================
    FINAL RESPONSE FORMAT
    ==================================================
    <grounded answer>
    
    [Source: <only include source file(s) actually used to answer document questions>]
    """.strip()
    
            agent_persona = {
                "name": agent_name,
                "personality": personality_description,
                "system_prompt": injected_system_prompt,
            }
    
            if chat_history:
                agent_persona[
                    "system_prompt"
                ] += f"\n\n==================================================\nCONVERSATION HISTORY\n==================================================\n{chat_history}\n\nCRITICAL INSTRUCTION: If the user's current question asks to filter, modify, or extract from the 'above' or 'previous' answer, you MUST use the CONVERSATION HISTORY as your primary source of truth and ignore any conflicting retrieved documents below."
    
            # 2. Retrieve Context
            if 'context' not in locals():
                context = None
                
            if not skip_search:
                try:
                    logger.info(f"[TRACE_E2E] [ENTRY] RAGPipeline.query - Input: '{short_query}'")
                    pipeline_start = time.time()
                    context = await asyncio.wait_for(
                        self.pipeline.query(
                            query=query,
                            agent_id=agent_id,
                            kb_id=kb_ids,
                            user_id=user_id,
                            top_k=top_k,
                            max_depth=max_depth,
                        ),
                        timeout=_RAG_TIMEOUT_SECONDS,
                    )
                    pipeline_latency = time.time() - pipeline_start
                    chunk_count_pipeline = len(context.chunks) if context and context.chunks else 0
                    logger.info(f"[TRACE_E2E] [EXIT] RAGPipeline.query - Output: {chunk_count_pipeline} chunks - Latency: {pipeline_latency:.2f}s")

                except asyncio.TimeoutError:
                    logger.error(f"RAG Retrieval timed out after {_RAG_TIMEOUT_SECONDS}s")
                    yield json.dumps(
                        {
                            "error": "The AI provider is taking too long to respond. Please try again later."
                        }
                    )
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
            metadata_yielded = False
            if not metadata_yielded:
                if context:
                    for c in context.chunks:
                        logger.info(f"Chunk={c.chunk_id} Source={c.source} Score={c.hybrid_score}")
    
                    metadata = {
                        "type": "metadata",
                        "sources": [
                            {
                                "chunk_id": c.chunk_id,
                                "source": c.source,
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
            is_table_analytics = (
                context.search_type == "TABLE_ANALYTICS" if context else False
            )
    
            if is_extractive or is_table_analytics:
                logger.info(f"Checking direct extraction for {context.search_type} mode.")
                try:
                    logger.info(f"[DIRECT_EXTRACTION_INPUT] has authoritative_entities: {bool(getattr(context, 'authoritative_entities', None))}, triplet_context length: {len(context.triplet_context) if context.triplet_context else 0}")
                    has_direct_output = False
                    if getattr(context, "authoritative_entities", None):
                        for ent in context.authoritative_entities:
                            clean_name = ent["entity_type"].replace("_", " ").title()
                            clean_src = clean_source_name(
                                ent.get("source", "document_entities")
                            )
                            yield f"**{clean_name}:** {ent['value']} (Page {ent.get('page', 1)}) [Source: {clean_src}]\n"
                            has_direct_output = True
                        if has_direct_output:
                            yield "\n"
        
                    # Strip any <think> tags from triplet_context (gateway LLM leak guard)
                    import re as _re
        
                    clean_triplet = context.triplet_context or ""
                    clean_triplet = _re.sub(
                        r"<think>.*?</think>", "", clean_triplet, flags=_re.DOTALL
                    ).strip()
                    if "<think>" in clean_triplet:
                        clean_triplet = clean_triplet[: clean_triplet.index("<think>")].strip()
        
                    if clean_triplet:
                        if is_extractive:
                            logger.info(f"[DIRECT_EXTRACTION_OUTPUT] yielding clean_triplet length: {len(clean_triplet)}")
                            yield clean_triplet
                            has_direct_output = True
                        elif is_table_analytics:
                            logger.info(f"[TABLE_ANALYTICS] Mapping raw SQL output to hybrid_merge_context for Answer LLM")
                            hybrid_merge_context = f"\n\n[ENTERPRISE SPREADSHEET ANALYSIS (TABULAR_SQL INSIGHTS)]\n{clean_triplet}\nState the numerical/tabular results clearly. DO NOT add any technical explanations about how the data was filtered, derived, or calculated (e.g. do not say 'This information was derived by filtering...').\n"
                            
                    if has_direct_output:
                        # Append source citation for EXTRACTIVE so the frontend source pills appear
                        # Use the kb object already fetched for metadata (line 661 scope)
                        try:
                            _src_name = (
                                kb.name
                                if len(kb_ids) == 1
                                else (kb_ids[0] if kb_ids else "Dataset")
                            )
                            yield f"\n\n[Source: {_src_name}]"
                            logger.info("[DIRECT_EXTRACTION_OUTPUT] yielded source citation")
                        except Exception as e:
                            logger.warning(f"[DIRECT_EXTRACTION] Exception while yielding source citation: {e}")
                            pass
                        return
                    else:
                        logger.warning(
                            f"[{context.search_type}] mode yielded no direct entities or falling through to standard LLM chunk generation!"
                        )
                except Exception as ex:
                    logger.error(f"[DIRECT_EXTRACTION_ERROR] Exception in direct extraction logic: {ex}", exc_info=True)
    
            has_valid_chunks = context and context.chunks
            has_valid_triplets = context and context.triplets
            has_triplet_context = context and context.triplet_context
            if not has_valid_chunks and not has_valid_triplets and not has_triplet_context and not chat_history and not hybrid_merge_context:
                logger.info("Empty context retrieved for stream, returning fallback message.")
                yield "I'm sorry, but the requested information is not available within my current knowledge base. Please try a related query or provide additional context."
                return
    
            # 4. Stream chunks
            formatted_context = self._format_context(context, hybrid_merge_context=hybrid_merge_context) if context else (hybrid_merge_context or "")
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
            confidence = (
                sum(c.hybrid_score for c in context.chunks) / len(context.chunks)
                if (context and context.chunks)
                else 0.0
            )
            status = (
                ResponseStatus.SUCCESS
                if (context and context.chunks)
                else (ResponseStatus.SUCCESS if chat_history else ResponseStatus.UNANSWERED)
            )
    
            llm_input_tokens = token_usage.get("prompt_tokens", 0)
            llm_output_tokens = token_usage.get("completion_tokens", 0)
            embedding_tokens = getattr(context, "query_embedding_tokens", 0) or max(
                1, len(query) // 4
            )
    
            llm_cost_usd = (llm_input_tokens / 1000000.0) * 0.10 + (
                llm_output_tokens / 1000000.0
            ) * 0.15
            embedding_cost_usd = (embedding_tokens / 1000000.0) * 0.01
            total_cost_usd = llm_cost_usd + embedding_cost_usd
    
            try:
                analytics_repo = AnalyticsRepository(self.db, UUID(self.tenant_id))
                await analytics_repo.create_query_log(
                    {
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
                        "total_cost_usd": total_cost_usd,
                        "model_name": self.llm_client.model_answer,
                    }
                )
                await self.db.commit()
            except Exception as ae:
                logger.warning(f"Failed to log analytics for stream: {ae}")
                try:
                    await self.db.rollback()
                except Exception as rollback_err:
                    logger.error(
                        f"Failed to rollback analytics transaction: {rollback_err}"
                    )
        finally:
            import time
            trace_latency = time.time() - trace_start_time
            chunk_count = len(context.chunks) if ('context' in locals() and context and context.chunks) else 0
            logger.info(f"[TRACE_E2E] [EXIT] ChatService.stream_rag_answer - Output: {chunk_count} chunks streamed - Latency: {trace_latency:.2f}s")
            
            current_task = asyncio.current_task()
            
            # memory_task is created earlier in the file (if it exists, cancel it)
            if 'memory_task' in locals() and memory_task and not memory_task.done():
                memory_task.cancel()


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
            self.db.expunge(k_obj)
            if str(k_obj.agent_id) != str(agent_id):
                logger.error(f"Agent {agent_id} does not own KB {kid}")
                return {
                    "error": f"Agent {agent_id} does not own Knowledge Base {kid}",
                    "answer": None,
                    "sources": [],
                }
            if getattr(k_obj, "description", "") == "excel_parquet":
                excel_kbs.append(k_obj)
            else:
                doc_kbs.append(k_obj)

        if not excel_kbs and not doc_kbs:
            return {
                "error": "No valid Knowledge Bases found",
                "answer": None,
                "sources": [],
            }

        kb = doc_kbs[0] if doc_kbs else excel_kbs[0]

        # ============= HYBRID RAG: INTERCEPT EXCEL/PARQUET QUERIES =============
        if excel_kbs:
            from app.core.parquet_ingester import ParquetIngester
            from app.modules.rag.pandas_engine import PandasQueryEngine

            active_paths = []
            for ek in excel_kbs:
                dataset_name = getattr(ek, "parsed_path", None) or getattr(
                    ek, "s3_path", None
                )
                if dataset_name:
                    p = ParquetIngester.get_active_dataset(dataset_name)
                    if p:
                        active_paths.append(p)
            if active_paths:
                engine = PandasQueryEngine(
                    active_paths[0], all_dataset_paths=active_paths
                )
                try:
                    result = await engine.execute_query(query)
                    result_str = str(result)
                    unmatched_signals = [
                        "not present in dataset",
                        "no records matched",
                        "error",
                        "0 rows",
                        "empty dataframe",
                        "could not find",
                        "no matching",
                    ]
                    is_unmatched = any(
                        sig in result_str.lower() for sig in unmatched_signals
                    )
                    explicit_math_keywords = [
                        "sum of",
                        "average of",
                        "count of",
                        "total of",
                        "how many rows",
                        "group by",
                        "calculate the",
                        "what is the average",
                        "what is the sum",
                        "what is the total",
                    ]
                    is_pure_math = any(
                        kw in query.lower() for kw in explicit_math_keywords
                    )
                    if doc_kbs and is_unmatched:
                        logger.info(
                            f"[generate_answer] Excel dataset lacked answer ({result_str}). Falling back to PDF/URL knowledge bases..."
                        )
                    elif doc_kbs and not is_pure_math:
                        logger.info(
                            "[generate_answer] Mixed sources: Injecting tabular result and searching PDFs/URLs..."
                        )
                        hybrid_merge_context = f"\n\n[ENTERPRISE SPREADSHEET ANALYSIS (TABULAR_SQL INSIGHTS)]\n{result_str}\nUse the above numerical table results alongside document citations to answer the user query completely.\n"
                    else:
                        return {
                            "answer": result_str,
                            "sources": [],
                            "context": {"type": "duckdb_parquet"},
                            "stats": {},
                        }
                except Exception as e:
                    logger.error(f"PandasQueryEngine failed in generate_answer: {e}")
                    if not doc_kbs:
                        return {"error": str(e), "answer": None, "sources": []}

        logger.info(f" KB ownership verified: {kb.name}")

        # Fetch Agent details for persona branding (system_prompt, description)

        agent = await self.agent_repo.get_by_id(agent_id)
        if not agent:
            return {
                "error": f"Agent {agent_id} not found or inactive under the current tenant",
                "answer": None,
                "sources": [],
            }
        self.db.expunge(agent)

        base_prompt = agent.system_prompt or ""
        personality_description = (
            agent.personality
            or "You are a warm, approachable, and supportive assistant."
        )

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
                rules_list = [
                    f"({r['source_class']})-[:{r['relation']}]->({r['target_class']})"
                    for r in ontology["rules"]
                    if r.get("source_class")
                ]
                if rules_list:
                    ontology_rules_str = (
                        "\n\n[ENTERPRISE ONTOLOGY RULES (STRICT GROUNDING)]\n"
                        + "\n".join(rules_list)
                        + "\nAlign your reasoning strictly with these established business relationships. Do not hallucinate relationships outside of this schema."
                    )
        except Exception as e:
            logger.warning(f"Failed fetching active ontology for RAG prompt: {e}")
            ontology_rules_str = ""

        # ============= MEMORY-API: BACKGROUND TURN PROCESSING =============
        episodic_guidance = ""
        memory_enabled = (
            str(getattr(get_settings(), "memory_enabled", "True")).strip().lower()
            in ("true", "1", "yes")
        )

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
MEMORY AUTHORITY (HIGHEST PRIORITY - READ FIRST)
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
- If the user is asking a factual/document question and the requested information is missing from BOTH the document context AND the user memory section, reply exactly:
  "I couldn't find it."
- If only part of the answer exists, answer only that part.
- Mention the relevant source at the end.
- Answer ONLY the specific question asked by the user. If the user asks a complex or multi-part question, you MUST address EVERY part of the question in your response. Do not provide extra analysis, summaries of unrelated topics, or inferred narratives unless requested.
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
SOURCE CITATION RULES (STRICT)
==================================================
1. GREETINGS & CASUAL CONVERSATION (CRITICAL):
- If the user's input is a greeting (e.g. "Hello", "Hi", "Good morning", "How are you?"), polite chitchat, or a general conversational response, respond warmly according to your assigned personality without saying "I couldn't find it", and DO NOT output any source citation tag at all.
- NEVER include [Source: ...] for greetings, introduction messages, or general chitchat.

2. DOCUMENT CONTENT & ACCURATE CITATIONS:
- Cite a source ONLY IF information from retrieved document/data chunks was ACTUALLY USED to answer the user's specific question.
- Cite ONLY the specific filename(s) from which relevant facts were extracted.
- Single Source: If the answer came from only one document (e.g. ARUN_N.pdf), cite ONLY that single document: [Source: ARUN_N.pdf]. Do NOT list other unused files.
- Multi Source: If the answer combined information from multiple documents, list only those specific documents: [Source: file1.pdf, file2.pdf].
- Deduplicate sources so each unique filename appears ONLY ONCE.
- Format the citation at the very end of your response on its own single line:
  [Source: filename1, filename2]

==================================================
RESPONSE FORMAT
==================================================
<grounded answer>

[Source: <only include source file(s) actually used to answer document questions>]
""".strip()

        agent_persona = {
            "name": agent.name if agent else "Assistant",
            "personality": personality_description,
            "system_prompt": injected_system_prompt,
        }

        if episodic_guidance:
            logger.debug("Episodic guidance retrieved; will inject into RAG context.")

        # Step 2: Cache check
        cache_key = self._make_cache_key(
            query, agent_id, "|".join(kb_ids), kb_version=kb.total_chunks
        )
        cached_response = self._get_cached_response(cache_key)
        if cached_response:
            self._track_metrics(
                cache_hit=True,
                seed_chunks_count=len(cached_response.get("sources", [])),
            )
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
                        total_tokens=sum(
                            len(c.text.split()) * 1.3 for c in retrieved_chunks
                        ),
                    )
                else:
                    return {
                        "error": "RAG retrieval timed out (query too complex)",
                        "answer": None,
                        "sources": [],
                    }
            except Exception as fallback_e:
                return {
                    "error": "RAG retrieval timed out and fallback failed",
                    "answer": None,
                    "sources": [],
                }
        except Exception as e:
            return {
                "error": f"RAG retrieval failed: {str(e)}",
                "answer": None,
                "sources": [],
            }

        is_social = context.search_type == "SOCIAL" if context else False
        is_support = context.search_type == "SUPPORT_INTENT" if context else False

        if is_support and agent.agent_type == "integrated":
            contact_info = []
            if agent.contact_phone:
                contact_info.append(f"Phone: {agent.contact_phone}")
            if agent.contact_email:
                contact_info.append(f"Email: {agent.contact_email}")
            if agent.website_url:
                contact_info.append(f"Website: {agent.website_url}")

            contact_str = " | ".join(contact_info)
            org_name = agent.organization_name or "our organization"

            msg = (
                f"For support or human assistance, please contact {org_name} directly."
            )
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
        is_table_analytics = (
            context.search_type == "TABLE_ANALYTICS" if context else False
        )

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

        if (not context or not context.chunks) and not is_social and not hybrid_merge_context:
            if agent.agent_type == "integrated":
                if agent.fallback_message_enabled:
                    org_name = agent.organization_name or "our organization"
                    contact_info = []
                    if agent.contact_phone:
                        contact_info.append(f"Phone: {agent.contact_phone}")
                    if agent.contact_email:
                        contact_info.append(f"Email: {agent.contact_email}")
                    if agent.website_url:
                        contact_info.append(f"Website: {agent.website_url}")
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
        formatted_context = (
            self._format_context(context, hybrid_merge_context=hybrid_merge_context)
            if context
            else (hybrid_merge_context or "")
        )
        
        if episodic_guidance:
            formatted_context = (
                "### MANDATORY USER PREFERENCES & MEMORY DIRECTIVES\n"
                f"{episodic_guidance}\n\n"
            ) + formatted_context

        model_to_use = getattr(self.settings, "model_intent", None) if is_social else None
        llm_response = await self._generate_answer_llm(
            query=query,
            context=formatted_context,
            tenant_id=self.tenant_id,
            agent_id=agent_id,
            agent_persona=agent_persona,
            model=model_to_use,
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
                "content_type": getattr(chunk, "content_type", "original"),
            }
            for chunk in context.chunks
        ]

        nodes_used = len(context.chunks) + len(context.entity_mentions)
        confidence = (
            sum(c.hybrid_score for c in context.chunks) / len(context.chunks)
            if context.chunks
            else 0.0
        )

        seed_count = sum(1 for c in context.chunks if "seed" in c.reason.lower())
        exp_count = sum(1 for c in context.chunks if "expanded" in c.reason.lower())

        reasoning_path = (
            "No relevant knowledge found in graph to answer this question."
            if nodes_used == 0
            else f"Found {seed_count} semantic seed chunks. Expanded via graph relationships to find {exp_count} additional chunks and {len(context.entity_mentions)} relevant entities."
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
            "reasoning_path": (
                reasoning_path
                if reasoning_enabled
                else "Reasoning path hidden by user request."
            ),
        }

        if is_billing_enabled():
            response["stats"]["llm_cost_estimate"] = round(
                llm_response.cost_estimate, 6
            )

        try:
            analytics_repo = AnalyticsRepository(self.db, UUID(self.tenant_id))
            await analytics_repo.create_query_log(
                {
                    "query": query,
                    "response_status": (
                        ResponseStatus.SUCCESS
                        if context.chunks
                        else ResponseStatus.UNANSWERED
                    ),
                    "confidence_score": confidence,
                    "latency_ms": (datetime.now() - start_time_total).total_seconds()
                    * 1000,
                    "model_name": self.llm_client.model_answer,
                }
            )
        except Exception as ae:
            logger.warning(f"Failed to log query to analytics: {ae}")

        self._cache_response(cache_key, response)
        return response

    def _make_cache_key(
        self, query: str, agent_id: str, kb_id: str, kb_version: int = 0
    ) -> str:
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

    def _format_context(
        self, context: RAGContext, hybrid_merge_context: Optional[str] = None
    ) -> str:
        context_text = (
            f"QUERY: {context.query}\n"
            + "=" * 60
            + "\nCONTEXT (from Knowledge Base):\n"
        )
        if hybrid_merge_context:
            context_text += f"{hybrid_merge_context}\n" + "=" * 60 + "\n"

        for i, chunk in enumerate(context.chunks, 1):
            s3_path = getattr(chunk, "s3_path", None)
            source_info = s3_path if s3_path else (clean_source_name(chunk.source) if chunk.source else "Unknown Source")
            context_text += f"\n[Chunk {i}/{len(context.chunks)} - Source: {source_info} - Position {chunk.position}]"
            context_text += f"\nScore: {chunk.hybrid_score:.3f} (Semantic: {chunk.embedding_similarity:.3f}, Graph: {chunk.graph_score:.3f})"
            context_text += f"\n{'-' * 40}\n{chunk.text}\n"

        if context.entity_mentions:
            context_text += "\n" + "=" * 60 + "\nENTITIES MENTIONED:\n"
            for entity, chunk_ids in context.entity_mentions.items():
                context_text += f"- {entity} (mentioned in {len(chunk_ids)} chunks)\n"

        if context.triplet_context:
            context_text += (
                f"\n[KNOWLEDGE GRAPH RELATIONSHIPS]:\n{context.triplet_context}\n"
            )
        if getattr(context, "authoritative_entities", None):
            context_text += (
                "\n" + "=" * 60 + "\n[VERIFIED DATA ENTITIES (HIGH TRUST)]\n"
            )
            context_text += "The following entities are verified from the document/database. Use these values to answer the user's query if they are relevant:\n"
            for ent in context.authoritative_entities:
                clean_src = clean_source_name(ent.get("source", "document_entities"))
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
                    "delta": weight_delta,
                },
            )
            logger.info(
                f" Updated feedback weight ({weight_delta}) for {len(chunk_ids)} chunks"
            )
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
        **kwargs,
    ) -> LLMResponse:
        try:
            llm_response = await self.llm_client.generate_answer(
                query=query,
                context=context,
                tenant_id=tenant_id,
                agent_id=agent_id,
                agent_persona=agent_persona,
                enable_thinking=False,
                **kwargs,
            )
            return llm_response
        except Exception as e:
            logger.warning(
                f"Phase 3 failed ({e}). Falling back to template generation..."
            )
            return self._generate_answer_template(query, context, tenant_id, agent_id)

    def _generate_answer_template(
        self, query: str, context: str, tenant_id: str, agent_id: str
    ) -> LLMResponse:
        if not context or not context.strip():
            answer = (
                "I couldn't find enough grounded information to answer that question."
            )
        else:
            answer_lines = []
            for line in context.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if (
                    stripped.startswith("QUERY:")
                    or stripped.startswith("CONTEXT")
                    or stripped.startswith("=")
                ):
                    continue
                if stripped.startswith("[") and stripped.endswith("]"):
                    continue
                if stripped.startswith("Chunk") or stripped.startswith("Score"):
                    continue
                if (
                    stripped.startswith("ENTITIES")
                    or stripped.startswith("KNOWLEDGE GRAPH")
                    or stripped.startswith("VERIFIED")
                ):
                    continue
                answer_lines.append(stripped)

            answer = (
                "\n".join(answer_lines[:8])
                if answer_lines
                else "I couldn't find enough grounded information to answer that question."
            )
            if not answer:
                answer = "I couldn't find enough grounded information to answer that question."
            elif not answer.lower().startswith(
                ("based on", "i couldn't", "the following")
            ):
                answer = (
                    f"Based on the retrieved context, here is what I found:\n\n{answer}"
                )

        return LLMResponse(
            answer=answer,
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
