"""

RAG Service - Orchestrates RAG pipeline and LLM generation

Phase 2 Step 4: Transforms retrieved context into generated answers

"""



import logging

from typing import Optional

from uuid import UUID

import asyncio

import hashlib

import json

import random

from datetime import datetime, timedelta

from dataclasses import dataclass, asdict



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





# Simple in-memory cache for RAG results

# Format: (query_hash, agent_id) -> (response, timestamp)

# TTL: 300 seconds (5 minutes) - configurable

_rag_cache = {}  # Dict[cache_key] -> (response, timestamp, insertion_order)

_CACHE_TTL_SECONDS = 300

_MAX_CACHE_SIZE = 1000  # Evict oldest entries if exceeded

_CACHE_INSERTION_ORDER = []  # Track insertion order for LRU eviction

_RAG_TIMEOUT_SECONDS = 180.0  # Professional timeout for remote AI calls + graph compute





# Metrics tracking (optional, for analytics)

@dataclass

class RAGMetrics:

    """Track RAG pipeline performance metrics"""



    retrieval_latency_ms: float  # Time to retrieve context (seed + expansion)

    ranking_latency_ms: float  # Time to score and rank

    total_latency_ms: float  # Total pipeline time

    cache_hit: bool  # Whether result came from cache

    seed_chunks_count: int  # Number of seed chunks retrieved

    expanded_chunks_count: int  # Number of chunks from graph expansion

    final_chunks_count: int  # Number of chunks in final context

    timeout_occurred: bool  # Whether timeout occurred

    partial_result: bool  # Whether result is partial (timeout fallback)



    def __post_init__(self):

        """Validate metrics"""

        if self.total_latency_ms < 0:

            raise ValueError("Latency cannot be negative")





_rag_metrics = []  # List of metrics for analytics





class RAGService:

    """

    High-level RAG orchestration service.



    Responsible for:

    1. Validating query + KB ownership

    2. Orchestrating RAG pipeline (retrieval)

    3. Formatting context for LLM

    4. Generating answers via LLM



    MULTI-TENANCY:

    - tenant_id passed at init (from middleware)

    - KB ownership validated before retrieval

    - All Neo4j queries validated against tenant_id

    """



    def __init__(self, db: AsyncSession, tenant_id: str):

        """

        Initialize RAG service for tenant.



        Args:

            db: Database session (for PostgreSQL KB retrieval)

            tenant_id: Tenant UUID (from middleware, never from request)

        """

        self.db = db

        self.tenant_id = str(tenant_id)



        # Initialize core components

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

        top_k: int = 15,

        max_depth: int = 2,

    ):

        """

        Stream answer using RAG pipeline (for WebSockets).

        Yields chunks of text.

        """

        logger.info(f" RAG Service: Streaming answer for agent={agent_id}, kb={kb_id}")



        # 1. Validate KB ownership

        kb_ids = [kb_id] if isinstance(kb_id, str) else kb_id

        

        # We'll just verify the first one exists and belongs to the agent for security

        # (The pipeline will filter by these IDs anyway)

        kb = await self.kb_repo.get_by_id(kb_ids[0])

        if not kb:

            yield json.dumps({"error": f"Knowledge Base {kb_ids[0]} not found"})

            return

        if str(kb.agent_id) != str(agent_id):

            yield json.dumps({"error": "Unauthorized: Agent does not own this Knowledge Base"})

            return

            

        # Optional: Log if multiple KBs are being used

        if len(kb_ids) > 1:

            logger.info(f" Querying across {len(kb_ids)} Knowledge Bases for agent {agent_id}")



        # Fetch Agent details for persona branding (system_prompt, description)

        agent = await self.agent_repo.get_by_id(agent_id)

        if not agent:

            yield json.dumps({"error": f"Agent {agent_id} not found or inactive under the current tenant"})

            return

        

        base_prompt = agent.system_prompt or ""

        personality_description = agent.personality or "You are a warm, approachable, and supportive assistant." # Fallback



        if agent.personality_id:

            personality = await self.db.get(Personality, agent.personality_id)

            if personality:

                personality_description = personality.description or personality.name



        # Ensure accuracy, grammar, and spelling directives are included in the personality description
        accuracy_directives = (
            "\n- Enforce 100% factual accuracy based strictly on the retrieved context."
            "\n- Correct any obvious spelling or grammatical errors found in the source documents; do not copy typos."
            "\n- Verify timelines, chronologies, and locations strictly to avoid historical or situational errors."
        )
        if "factual accuracy" not in personality_description.lower():
            personality_description += accuracy_directives



        # --- ONTOLOGY GROUNDING (Phase 4B Enhancement) ---
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
        # ------------------------------------------------

        injected_system_prompt = f"""

[PERSONALITY MODE: STRICT]

You MUST strictly follow the personality defined below.
Every response MUST reflect this personality strongly in tone, wording, and structure.
Deviation is NOT allowed.

Personality Definition:
{personality_description}

Base Instruction:
{base_prompt}

You are an enterprise AI assistant.

==================================================
GROUNDING RULES & HALLUCINATION PREVENTION
==================================================
Never complete missing information
using prior knowledge.
If retrieved passages conflict,
state the conflict.
Do not resolve it yourself.
- Answer ONLY using the provided context.
- Before answering, verify that every factual statement in your response is explicitly supported by the retrieved context.
- If a statement is not directly supported by the retrieved context, do not include it.
- Do not combine information from your general knowledge with the retrieved context.
- Never use outside knowledge.
- Never invent, infer, estimate, or assume facts.
- If the requested information is missing from the provided context, reply exactly:
  "I couldn't find it."
- If only part of the answer exists, answer only that part.
- Mention the relevant source at the end.

==================================================
FORMATTING RULES
==================================================

Use the most appropriate format for the answer.

Use Markdown tables whenever information is easier to compare in rows and columns.

Examples:
- Financial metrics
- Comparisons
- Product specifications
- Rankings
- Lists with attributes
- Structured summaries

Example:

| Company | Revenue | Growth |
|----------|----------|--------|
| Intel | ... | ... |
| AMD | ... | ... |

Use bullet points when listing multiple items.

Use paragraphs for explanations.

==================================================
CLARIFICATION RULES
==================================================

Ask ONE clarification question instead of guessing whenever:

- "this", "that", "it", "they", or similar references are ambiguous
- multiple documents could satisfy the request
- the requested section is not specified
- the filter is ambiguous
- the requested file is unclear
- the requested image or attachment is unavailable

Examples:

User:
summarize this

Assistant:
Which document would you like me to summarize?

---
Never guess what the user meant.

==================================================
SOURCE CITATION RULES
==================================================

For files ending in:
- .pdf
- .csv
- .xlsx
- .xls

The source citation MUST be strictly formatted as:

[Source: <filename>]

Example:

[Source: Intel_Q3_2023.pdf]

Do NOT include:
- Position numbers
- Chunk numbers
- Page numbers
- "Sources:"
- "PDF:"
- "Document:"
- Any additional labels or metadata

The source citation must appear only once at the very end of the response.

For emails include:

Source: Gmail inbox/sent
Sender:
Receiver:
Date:
Subject:

==================================================
GREETING RULE
==================================================

If the user's message is only a greeting or conversational pleasantry
(hi, hello, good morning, thanks, etc.)

- Respond naturally.
- Do NOT output any source citation.
- Do NOT output follow-up recommendations.

==================================================
RANKING RULES
==================================================

Whenever the user asks for:

- highest
- lowest
- top
- bottom
- rank
- largest
- smallest
- most
- least

Do NOT rely on textual order.

Sort using the actual numeric values found in the context before generating the response.



==================================================
FOLLOW-UP RECOMMENDATIONS
==================================================

After answering the user's question, suggest 1–3 relevant follow-up questions or actions based ONLY on the retrieved content.

Rules:

- Begin with:
  "If you'd like, I can also:"
- Recommendations must be directly related to the current answer.
- Never recommend topics outside the available context.
- Keep each recommendation short.
- Do NOT repeat the user's original question.
- Do NOT include source citations for recommendations.
- Skip recommendations if the answer is:
  - a greeting,
  - a clarification question,
  - "I couldn't find it."

Examples:
Technical manuals:
If you'd like, I can also:
- summarize the installation steps,
- explain troubleshooting procedures,
- list important safety precautions.


==================================================
FINAL RESPONSE FORMAT
==================================================

Answer:
<grounded answer>

If you'd like, I can also:
- ...
- ...
- ...

[Source: <filename>]

""".strip()



        agent_persona = {

            "name": agent.name if agent else "Assistant",

            "personality": personality_description,

            "system_prompt": injected_system_prompt

        }



        # 2. Retrieve Context (No cache for streaming for simplicity in Phase 1)

        try:

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

        except asyncio.TimeoutError:
            logger.error(f"RAG Retrieval timed out after {_RAG_TIMEOUT_SECONDS}s")
            yield json.dumps({"error": f"The AI provider is taking too long to respond. Please try again later."})
            return
        except Exception as e:
            error_msg = str(e) if str(e) else e.__class__.__name__
            logger.error(f"RAG Retrieval failed for stream: {error_msg}")
            yield json.dumps({"error": f"Retrieval failed: {error_msg}"})
            return

        # 3. Yield metadata first (sources)
        for c in context.chunks:
            logger.info(
        f"Chunk={c.chunk_id} Source={c.source} Score={c.hybrid_score}"
    )
        metadata = {

            "type": "metadata",

            "sources": [

                {  "chunk_id": c.chunk_id,
            "source": c.source,
            "score": round(c.hybrid_score, 3),
            "position": c.position,
            "reason": c.reason,
            "kb_id": c.kb_id,
            "content_type": getattr(c, "content_type", "original") }

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

        yield json.dumps(metadata)



        # 3.5 Check for empty context or bypass intents
        is_extractive = context.search_type == "EXTRACTIVE" if context else False
        is_table_analytics = context.search_type == "TABLE_ANALYTICS" if context else False

        if is_extractive or is_table_analytics:
            logger.info(f"Bypassing LLM stream for {context.search_type} mode.")
            # Yield any structured data if available
            if getattr(context, "authoritative_entities", None):
                yield "\n**System Verified Data (100% Trust):**\n"
                for ent in context.authoritative_entities:
                    yield f"- **{ent['entity_type']}**: `{ent['value']}` (Source: {ent.get('source', 'document_entities')}, Page: {ent.get('page', 1)}, Confidence: {ent.get('confidence', 1.0)})\n"
                yield "\n"
            yield context.triplet_context
            return

        if not context or not context.chunks:

            logger.info("Empty context retrieved for stream, returning fallback message.")

            yield "Im sorry, but the requested information is not available within my current knowledge base. Please try a related query or provide additional context."

            return

        # System-Level Value Injection
        if getattr(context, "authoritative_entities", None):
            yield "\n**System Verified Data (100% Trust):**\n"
            for ent in context.authoritative_entities:
                yield f"- **{ent['entity_type']}**: `{ent['value']}` (Source: {ent.get('source', 'document_entities')}, Page: {ent.get('page', 1)}, Confidence: {ent.get('confidence', 1.0)})\n"
            yield "\n**AI Analysis (Hybrid Retrieval):**\n"



        # 4. Stream chunks

        formatted_context = self._format_context(context)

        

        # Track start time for latency

        start_time = datetime.now()

        full_answer = []

        

        async for chunk in self.llm_client.stream_answer(

            query, 

            formatted_context, 

            agent_persona=agent_persona,

            enable_thinking=False,

        ):

            full_answer.append(chunk)

            yield chunk



        # 5. ASYNC LOGGING (Background)

        # Log to analytics in background to avoid blocking the stream completion

        latency_ms = (datetime.now() - start_time).total_seconds() * 1000

        confidence = sum(c.hybrid_score for c in context.chunks) / len(context.chunks) if context.chunks else 0.0

        status = ResponseStatus.SUCCESS if context.chunks else ResponseStatus.UNANSWERED

        

        try:

            analytics_repo = AnalyticsRepository(self.db, UUID(self.tenant_id))

            await analytics_repo.create_query_log({

                "query": query,

                "response_status": status,

                "confidence_score": confidence,

                "latency_ms": latency_ms

            })

            await self.db.commit()

        except Exception as ae:
            logger.warning(f" Failed to log analytics for stream: {ae}")
            # CRITICAL: Prevent PendingRollbackError from crashing the subsequent db.commit() in websocket routes!
            try:
                await self.db.rollback()
            except Exception as rollback_err:
                logger.error(f" Failed to rollback analytics transaction: {rollback_err}")



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

        """

        Generate answer to query using RAG pipeline.



        FLOW:

        1. Check result cache (query, agent_id)  if hit, return cached

        2. Validate KB ownership (agent_id owns KB)

        3. Execute RAG pipeline with timeout (max 2 seconds)

        4. Format context for LLM

        5. Generate answer

        6. Cache result before return

        7. Return answer + source annotations



        IMPROVEMENTS (Phase 2 Step 4 optimizations):

        -  Result caching: Avoid recomputing identical queries

        -  Timeout guard: Prevent slow queries from blocking

        -  Source attribution: Show why each chunk was retrieved



        Args:

            query: User query string

            agent_id: Agent UUID (ownership verification)

            kb_id: Knowledge Base UUID

            user_id: User UUID (for personalized memory retrieval)

            top_k: Initial seed chunks

            max_depth: Graph expansion depth



        Returns:

            Dict with:

            - answer (str): Generated answer

            - sources (list): [{"chunk_id": str, "score": float, "position": int, "reason": str}, ...]

            - context (dict): Retrieved context metadata

            - stats (dict): Pipeline statistics

        """

        logger.info(

            f" RAG Service: Generating answer for agent={agent_id}, kb={kb_id}"

        )

        start_time_total = datetime.now()



        # ============= STEP 1: VALIDATION: KB ownership (required for cache key with version) =============

        kb_ids = [kb_id] if isinstance(kb_id, str) else kb_id

        

        logger.debug("Validating KB ownership...")

        kb = await self.kb_repo.get_by_id(kb_ids[0])

        if not kb:

            logger.error(f" KB {kb_ids[0]} not found")

            return {

                "error": f"Knowledge Base {kb_ids[0]} not found",

                "answer": None,

                "sources": [],

            }



        if str(kb.agent_id) != str(agent_id):

            logger.error(f" Agent {agent_id} does not own KB {kb_ids[0]}")

            return {

                "error": "Unauthorized: Agent does not own this Knowledge Base",

                "answer": None,

                "sources": [],

            }



        logger.info(f" KB ownership verified: {kb.name}")



        # Fetch Agent details for persona branding (system_prompt, description)

        agent = await self.agent_repo.get_by_id(agent_id)

        if not agent:

            logger.error(f" Agent {agent_id} not found or inactive under the current tenant")

            return {

                "error": f"Agent {agent_id} not found or inactive under the current tenant",

                "answer": None,

                "sources": [],

            }

        

        base_prompt = agent.system_prompt or ""

        personality_description = agent.personality or "You are a warm, approachable, and supportive assistant." # Fallback



        if agent.personality_id:

            personality = await self.db.get(Personality, agent.personality_id)

            if personality:

                personality_description = personality.description or personality.name



        # Ensure accuracy, grammar, and spelling directives are included in the personality description
        accuracy_directives = (
            "\n- Enforce 100% factual accuracy based strictly on the retrieved context."
            "\n- Correct any obvious spelling or grammatical errors found in the source documents; do not copy typos."
            "\n- Verify timelines, chronologies, and locations strictly to avoid historical or situational errors."
        )
        if "factual accuracy" not in personality_description.lower():
            personality_description += accuracy_directives



        # --- ONTOLOGY GROUNDING (Phase 4B Enhancement) ---
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
        # ------------------------------------------------

        injected_system_prompt = f"""
[PERSONALITY MODE: STRICT]

You MUST strictly follow the personality defined below.
Every response MUST reflect this personality strongly in tone, wording, and structure.
Deviation is NOT allowed.

Personality Definition:
{personality_description}

Base Instruction:
{base_prompt}

==================================================
CORE RULES
==================================================

- Answer ONLY using the provided context.
- Never use external knowledge.
- Never invent, infer, estimate, or assume facts.
- If the requested information is not available in the provided context, reply:
  "I couldn't find it."
- If only part of the answer exists, answer only that part.
- Keep responses clear, accurate, and well-structured.

==================================================
FORMATTING RULES
==================================================

Use the format that best improves readability.

- Use Markdown tables whenever information is easier to compare in rows and columns.

Examples:
- Financial metrics
- Product comparisons
- Lists with attributes
- Rankings
- Structured summaries

- Use bullet points for lists.
- Use numbered steps for procedures.
- Use short paragraphs for explanations.

If the retrieved content is JSON, CSV rows, database records, dictionaries, or structured objects:

- NEVER return raw JSON unless the user explicitly requests JSON or raw data.
- Convert the structured data into a readable answer.
- Use Markdown tables when multiple records are involved.
- Summarize key insights after the table whenever appropriate.

==================================================
CLARIFICATION RULES
==================================================

Ask ONE concise clarification question instead of guessing when:

- "this", "that", "it", or similar references are ambiguous.
- Multiple documents could satisfy the request.
- The requested section is not specified.
- Filters are ambiguous.
- The requested file is unclear.
- The user requests an unavailable image or attachment.

Never guess missing information.

If clarification is required:
- Ask only ONE concise question.
- Wait for the user's response.
- Do NOT answer yet.

==================================================
FOLLOW-UP RECOMMENDATIONS
==================================================

After providing a complete answer, suggest 1–3 relevant follow-up questions based ONLY on the available context.

Begin with:

"If you'd like, I can also:"

Recommendations should:
- Be directly related to the current answer.
- Be short and actionable.
- Not repeat the user's original question.

Skip recommendations when:
- replying to greetings,
- asking for clarification,
- replying with "I couldn't find it."

==================================================
SOURCE CITATION RULES
==================================================

For files ending in:
- .pdf
- .csv
- .xlsx
- .xls

The source citation MUST be:

[Source: <filename>]

Example:

[Source: Intel_Q3_2023.pdf]

Do NOT include:
- Position numbers
- Chunk numbers
- Page numbers
- "Sources:"
- "PDF:"
- Any additional labels

Place the source citation ONLY once at the very end of the response.

For emails include:

Source: Gmail inbox/sent
Sender:
Receiver:
Date:
Subject:

==================================================
GREETING RULE
==================================================

If the user's message is only a greeting or conversational pleasantry
(e.g., "hi", "hello", "good morning", "thanks"):

- Respond naturally.
- Do NOT include source citations.
- Do NOT include follow-up recommendations.

==================================================
RESPONSE FORMAT
==================================================

Answer:
<grounded answer>

If you'd like, I can also:
- ...
- ...

[Source: <filename>]

""".strip()



        agent_persona = {

            "name": agent.name if agent else "Assistant",

            "personality": personality_description,

            "system_prompt": injected_system_prompt

        }



        # ============= STEP 2: CHECK CACHE (with KB version for auto-invalidation) =============

        logger.debug("Checking result cache...")

        cache_key = self._make_cache_key(

            query, agent_id, "|".join(kb_ids), kb_version=kb.total_chunks

        )

        cached_response = self._get_cached_response(cache_key)

        if cached_response:

            logger.info(

                f" Cache HIT: Returning cached result (KB version: {kb.total_chunks})"

            )

            # Track cache hit metric

            self._track_metrics(

                cache_hit=True,

                seed_chunks_count=len(cached_response.get("sources", [])),

            )

            return cached_response



        # ============= STEP 3: RETRIEVE CONTEXT VIA RAG PIPELINE (WITH TIMEOUT) =============

        logger.debug("Executing RAG pipeline (timeout=2.0s)...")

        context = None

        partial_result = False

        try:

            # TIMEOUT GUARD: Prevent slow queries from blocking

            # If query takes >RAG_TIMEOUT_SECONDS, timeout and return partial result (seed chunks only)

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

            logger.warning(

                f" RAG pipeline timed out (>{_RAG_TIMEOUT_SECONDS}s). Returning seed chunks only (partial fallback)..."

            )



            # PARTIAL FALLBACK: Return seed chunks to avoid complete error

            # Seed retrieval should be fast (<100ms), so this should succeed

            try:

                query_embedding = await EmbeddingGenerator.generate_embedding(query)

                seed_chunks = await self.pipeline._retrieve_seed_chunks(
                    kb_ids=kb_ids,
                    query_embedding=query_embedding,
                    top_k=top_k,
                    query=query,
                )



                if seed_chunks:

                    # Build minimal context from seed chunks only

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

                    partial_result = True

                    logger.info(

                        f" Fallback: Returning {len(retrieved_chunks)} seed chunks (partial result)"

                    )

                else:

                    # Even seed retrieval failed, return error

                    logger.error(

                        f" Seed retrieval also failed during timeout fallback"

                    )

                    return {

                        "error": "RAG retrieval timed out (query too complex, seed retrieval also failed)",

                        "answer": None,

                        "sources": [],

                    }

            except Exception as fallback_e:

                logger.error(f" Timeout fallback failed: {fallback_e}")

                return {

                    "error": "RAG retrieval timed out and fallback failed",

                    "answer": None,

                    "sources": [],

                }

        except Exception as e:

            logger.error(f" RAG pipeline failed: {e}")

            return {
                "error": f"RAG retrieval failed: {str(e)}",
                "answer": None,
                "sources": [],
            }

        # ============= STEP 3.5: CHECK IF CONTEXT IS EMPTY OR INTENT BYPASS =============
        # EXCEPTION: If the router identified this as a SOCIAL query (greeting),
        # we proceed to the LLM to provide a human-like response even with no context.
        is_social = context.search_type == "SOCIAL" if context else False
        is_support = context.search_type == "SUPPORT_INTENT" if context else False
        
        # BYPASS: Support Intent for Integrated Agents
        if is_support and agent.agent_type == "integrated":
            logger.info("Integrated agent handling SUPPORT_INTENT directly.")
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
            logger.info(f"Bypassing LLM generation for {context.search_type} mode.")
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
                    "llm_source": "DirectExtraction",
                    "search_strategy": context.search_type,
                },
                "confidence": 1.0,
                "nodes_used": 0,
                "reasoning_path": f"Bypassed retrieval for {context.search_type}.",
            }
            # Cache the result
            _rag_cache[cache_key] = (result, datetime.now(), len(_CACHE_INSERTION_ORDER))
            _CACHE_INSERTION_ORDER.append(cache_key)
            if len(_CACHE_INSERTION_ORDER) > _MAX_CACHE_SIZE:
                oldest_key = _CACHE_INSERTION_ORDER.pop(0)
                _rag_cache.pop(oldest_key, None)
                
            return result

        if (not context or not context.chunks) and not is_social:
            logger.info("Empty context retrieved and not social, returning fallback message.")
            
            # Determine fallback message based on agent_type
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
                    "llm_source": "Fallback",
                    "search_strategy": context.search_type if context else "DEFAULT",
                },
                "confidence": 0.0,
                "nodes_used": 0,
                "reasoning_path": "No relevant knowledge found in graph to answer this question.",
            }
            
        if is_social and (not context or not context.chunks):
            logger.info("Social query detected with empty context, proceeding to LLM for conversational response.")

        # ============= STEP 4: FORMAT CONTEXT FOR LLM =============

        logger.debug("Formatting context for LLM...")

        formatted_context = self._format_context(context)

        logger.info(

            f" Context formatted: {len(context.chunks)} chunks, {context.total_tokens} tokens"

        )



        # ============= STEP 5: GENERATE ANSWER =============

        logger.debug("Generating answer...")

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
            logger.warning("NumericValidator failed! Appending hallucination warning.")
            answer += "\n\n> [!WARNING]\n> Some numbers in this response could not be strictly verified against the retrieved context. Please double check the source documents."

        logger.info(

            f" Answer generated ({len(answer) // 4} words, {llm_response.total_tokens} tokens, ${llm_response.cost_estimate:.6f})"

        )



        # ============= STEP 6: BUILD RESPONSE WITH SOURCES (WITH ATTRIBUTION) =============

        sources = [

            {

                "chunk_id": chunk.chunk_id,

                "score": chunk.hybrid_score,

                "position": chunk.position,

                "reason": chunk.reason,  # Why this chunk was retrieved
                
                "source": chunk.source,

                "kb_id": chunk.kb_id,

                "content_type": getattr(chunk, "content_type", "original")

            }

            for chunk in context.chunks

        ]



        # ============= STEP 6: CALCULATE PRODUCT DASHBOARD METRICS (confidence, nodes, reasoning) =============

        nodes_used = len(context.chunks) + len(context.entity_mentions)

        

        # Confidence: average hybrid score of chunks (0 if none)

        confidence = sum(c.hybrid_score for c in context.chunks) / len(context.chunks) if context.chunks else 0.0

        

        # Reasoning path: explain what just happened in plain english

        seed_count = sum(1 for c in context.chunks if "seed" in c.reason.lower())

        exp_count = sum(1 for c in context.chunks if "expanded" in c.reason.lower())

        

        if nodes_used == 0:

            reasoning_path = "No relevant knowledge found in graph to answer this question."

        else:

            reasoning_path = f"Found {seed_count} semantic seed chunks. Expanded via graph relationships to find {exp_count} additional chunks and {len(context.entity_mentions)} relevant entities."



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

                "llm_source": llm_response.source,

                "llm_prompt_version": llm_response.prompt_version,

                "search_strategy": context.search_type,

            },

            "confidence": confidence,

            "nodes_used": nodes_used,

            "reasoning_path": reasoning_path if reasoning_enabled else "Reasoning path hidden by user request.",

        }



        # Add billing info only if billing is enabled (feature flag)

        if is_billing_enabled():

            response["stats"]["llm_cost_estimate"] = round(

                llm_response.cost_estimate, 6

            )



        logger.info(f" RAG complete: {len(context.chunks)} chunks  answer")



        # ============= STEP 6.5: LOG TO ANALYTICS (PERSISTENT) =============

        try:

            analytics_repo = AnalyticsRepository(self.db, UUID(self.tenant_id))

            await analytics_repo.create_query_log({

                "query": query,

                "response_status": ResponseStatus.SUCCESS if context.chunks else ResponseStatus.UNANSWERED,

                "confidence_score": confidence,

                "latency_ms": (datetime.now() - start_time_total).total_seconds() * 1000

            })

            # Note: We don't commit here, we let the caller or Step 9 handle it

            # Actually, RAGService should probably commit its own analytics if it's independent

        except Exception as ae:

            logger.warning(f" Failed to log query to analytics: {ae}")



        # ============= STEP 7: CACHE RESULT (FOR REPEATED QUERIES) =============

        self._cache_response(cache_key, response)

        logger.debug(f" Cached result (TTL={_CACHE_TTL_SECONDS}s)")



        # ============= STEP 8: SAMPLE LOGGING (1 in 50 QUERIES) =============

        # Log query + result summary at low rate (~2%) for debugging

        # Helps understand real user behavior & improve retrieval

        if random.random() < 0.02:  # ~1 in 50 queries

            logger.info(

                f" SAMPLE: query={query[:60]}... | "

                f"chunks={len(context.chunks)} | "

                f"answer={answer[:80]}..."

            )



        return response



    def _make_cache_key(

        self, query: str, agent_id: str, kb_id: str, kb_version: int = 0

    ) -> str:

        """

        Create cache key from query parameters with KB version for auto-invalidation.



        Uses hash to keep key compact and avoid sensitive data exposure.



        CACHE INVALIDATION ON KB UPDATE:

         kb_version = KB.total_chunks (increases every ingestion)

         When KB updated: cache key changes  cache miss

         No stale responses after KB updates

         Transparent invalidation (no manual cache clearing)



        Args:

            query: User query

            agent_id: Agent UUID

            kb_id: KB UUID

            kb_version: KB version hint (typically total_chunks count)



        Returns:

            Cache key string

        """

        # Include kb_version to allow per-KB-version caching

        # When KB is updated (chunks added), version changes  cache invalidates

        key_str = f"{query}|{agent_id}|{kb_id}|v{kb_version}"

        return hashlib.sha256(key_str.encode()).hexdigest()



    def _get_cached_response(self, cache_key: str) -> Optional[dict]:

        """

        Retrieve cached response if not expired.



        Args:

            cache_key: Cache key from _make_cache_key()



        Returns:

            Cached response dict, or None if not found / expired

        """

        if cache_key not in _rag_cache:

            return None



        response, timestamp = _rag_cache[cache_key]



        # Check TTL

        age = (datetime.now() - timestamp).total_seconds()

        if age > _CACHE_TTL_SECONDS:

            logger.debug(f"  Cache expired (age={age:.0f}s)")

            del _rag_cache[cache_key]

            return None



        logger.debug(f" Cache valid (age={age:.0f}s, TTL={_CACHE_TTL_SECONDS}s)")

        return response



    def _cache_response(self, cache_key: str, response: dict) -> None:

        """

        Store response in cache with LRU eviction.



        MAX_CACHE_SIZE: Evict oldest entries if exceeded

        Prevents memory creep in long-running service



        Args:

            cache_key: Cache key from _make_cache_key()

            response: Response dict to cache

        """

        global _CACHE_INSERTION_ORDER



        _rag_cache[cache_key] = (response, datetime.now())



        # Track insertion order for LRU eviction

        if cache_key not in _CACHE_INSERTION_ORDER:

            _CACHE_INSERTION_ORDER.append(cache_key)



        # Evict oldest if exceeded MAX_CACHE_SIZE

        while len(_rag_cache) > _MAX_CACHE_SIZE:

            oldest_key = _CACHE_INSERTION_ORDER.pop(0)

            if oldest_key in _rag_cache:

                del _rag_cache[oldest_key]

                logger.debug(

                    f"  Evicted oldest cache entry (cache size > {_MAX_CACHE_SIZE})"

                )



        # Log cache size (for monitoring)

        if len(_rag_cache) % 50 == 0:

            logger.info(f" Cache size: {len(_rag_cache)}/{_MAX_CACHE_SIZE} entries")



    def _format_context(self, context: RAGContext) -> str:

        """

        Format retrieved context for LLM input.



        Includes chunk text with position markers and entity mentions.



        Args:

            context: RAG context with chunks and entities



        Returns:

            Formatted context string

        """

        context_text = f"QUERY: {context.query}\n" + "=" * 60 + "\nCONTEXT (from Knowledge Base):\n"



        # Add chunks with position and source

        for i, chunk in enumerate(context.chunks, 1):
            source_info = chunk.source if chunk.source else "Unknown Source"
            context_text += f"\n[Chunk {i}/{len(context.chunks)} - Source: {source_info} - Position {chunk.position}]"

            context_text += f"\nScore: {chunk.hybrid_score:.3f} (Semantic: {chunk.embedding_similarity:.3f}, Graph: {chunk.graph_score:.3f})"

            context_text += f"\n{'-' * 40}\n{chunk.text}\n"



        # Add entity mentions summary

        if context.entity_mentions:

            context_text += "\n" + "=" * 60 + "\nENTITIES MENTIONED:\n"

            for entity, chunk_ids in context.entity_mentions.items():

                context_text += f"- {entity} (mentioned in {len(chunk_ids)} chunks)\n"



        # Phase 4A: Add triplet-derived knowledge graph relationships

        if context.triplet_context:

            context_text += f"\n[KNOWLEDGE GRAPH RELATIONSHIPS]:\n{context.triplet_context}\n"

        if getattr(context, "authoritative_entities", None):
            context_text += "\n" + "=" * 60 + "\n[SYSTEM INSTRUCTION: ALREADY VERIFIED DATA]\n"
            context_text += "The system has already verified and securely injected the following fields into the final response.\n"
            context_text += "DO NOT include these fields in your generation. ONLY answer for the REMAINING missing fields.\n"
            for ent in context.authoritative_entities:
                context_text += f"- {ent['entity_type']}\n"
            context_text += "=" * 60 + "\n"

        if context.personal_memories:

            pm_text = "\n".join([f"- {m}" for m in context.personal_memories])

            context_text += f"\n[USER PERSONAL PREFERENCES & HABITS]:\n{pm_text}\n"



        return context_text



    async def process_feedback(self, chunk_ids: list[str], rating: int) -> None:

        """

        Process user feedback and update graph node weights.

        Positive feedback (+1) increases weight by 0.1

        Negative feedback (-1) decreases weight by 0.1

        """

        if not chunk_ids:

            return

            

        weight_delta = 0.1 if rating > 0 else -0.1

        

        query = """

        UNWIND $chunk_ids AS chunk_id

        MATCH (c:Chunk {id: chunk_id, tenant_id: $tenant_id})

        // Cap the weight between 0.1 and 2.0 to prevent runaway scoring

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

        """

        AI-driven answer generation (Phase 3).



        1. Call DeepInfra API via specialized client

        2. On success: Return AI-generated answer with metrics

        3. On failure: Fallback to template-based answer (graceful degradation)

        4. Track costs per tenant/agent for multi-tenant billing



        MULTI-TENANCY:

        - LLM client tracks costs per tenant (for billing)

        - Context already filtered by tenant (from RAG pipeline)

        - No data leakage possible



        Args:

            query: Original user query

            context: Formatted context (already tenant-filtered)

            tenant_id: Tenant UUID (for cost tracking)

            agent_id: Agent UUID (for usage analytics)

            agent_persona: Agent name, description, system_prompt (optional)



        Returns:

            LLMResponse: Response with answer + metrics (tokens, cost, version, source)

        """

        # Attempt Phase 3: Real LLM generation via DeepInfra

        logger.debug("Attempting Phase 3: DeepInfra LLM generation...")

        try:

            llm_response = await self.llm_client.generate_answer(

                query=query,

                context=context,

                tenant_id=tenant_id,

                agent_id=agent_id,

                agent_persona=agent_persona,

                enable_thinking=False,

            )

            logger.info(

                f" Phase 3 SUCCESS: Generated answer via DeepInfra LLM (tokens={llm_response.total_tokens})"

            )

            return llm_response



        except Exception as e:

            # Fallback: If LLM generation fails, use template-based answer

            logger.warning(

                f"  Phase 3 failed ({e}). Falling back to Phase 2 template-based generation..."

            )

            return self._generate_answer_template(query, context, tenant_id, agent_id)



    def _generate_answer_template(

        self, query: str, context: str, tenant_id: str, agent_id: str

    ) -> LLMResponse:

        """

        Generate answer using template (Phase 2 fallback).



        Used when:

        - LLM API is down

        - Rate limited

        - Timeout

        - Any other failure



        Provides graceful degradation (never fail without answer).

        Tracks fallback usage per tenant/agent for billing.



        Args:

            query: User query

            context: Formatted context

            tenant_id: Tenant UUID (for cost tracking)

            agent_id: Agent UUID (for usage analytics)



        Returns:

            LLMResponse: Template-based answer (source="Template", no token cost)

        """

        logger.debug("Using Phase 2: Template-based answer generation (FALLBACK)")



        # Extract key information from context

        lines = context.split("\n")

        relevant_lines = [

            line for line in lines if line.strip() and not line.startswith("[")

        ]



        # Build answer from context

        answer_parts = [

            f"Based on the knowledge base, here's what I found:\n\n",

        ]



        # Add first 2-3 chunks as main answer

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

        """

        Track RAG pipeline metrics for analytics.



        METRICS FOR PRODUCT INSIGHTS:

         retrieval_latency_ms: Time to retrieve seed + expand graph

         cache_hit: Whether result came from cache (reduces latency)

         seed_chunks_count: Number of semantic search results

         expanded_chunks_count: Chunks added via graph expansion

         timeout_occurred: If query exceeded 2s timeout

         partial_result: If fallback seed-only result was returned

         total_latency_ms: End-to-end time including formatting



        INSIGHTS ENABLED:

          Identify slow queries (outliers)

          Cache effectiveness (hit rate)

          Graph expansion value (expanded vs seed)

          Timeout patterns (which KBs/queries timeout)

          Optimization opportunities

          Usage patterns & trends



        Args:

            cache_hit: Whether cache returned result

            seed_chunks_count: Number of seed chunks

            expanded_chunks_count: Number of expanded chunks

            final_chunks_count: Number of chunks in context

            timeout_occurred: If timeout happened

            partial_result: If fallback fallback was used

            retrieval_latency_ms: Retrieval time

            ranking_latency_ms: Scoring/ranking time

            total_latency_ms: Total end-to-end time

        """

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



            # Log every 10 metrics

            if len(_rag_metrics) % 10 == 0:

                self._log_metrics_summary()

        except Exception as e:

            logger.warning(f" Failed to track metrics: {e}")



    def _log_metrics_summary(self) -> None:

        """

        Log summary of recent metrics for monitoring.



        Used for:

         Performance dashboards

         Alerting on slow queries

         Cache effectiveness tracking

         Product insights

        """

        if not _rag_metrics or len(_rag_metrics) < 10:

            return



        recent = _rag_metrics[-10:]



        # Calculate averages

        avg_latency = sum(m.total_latency_ms for m in recent) / len(recent)

        cache_hit_rate = sum(1 for m in recent if m.cache_hit) / len(recent)

        timeout_count = sum(1 for m in recent if m.timeout_occurred)

        partial_count = sum(1 for m in recent if m.partial_result)

        avg_expanded = sum(m.expanded_chunks_count for m in recent) / len(recent)



        logger.info(

            f" RAG Metrics (last 10): "

            f"latency={avg_latency:.0f}ms, "

            f"cache_hit_rate={cache_hit_rate:.0%}, "

            f"timeouts={timeout_count}, "

            f"partial_results={partial_count}, "

            f"avg_expanded_chunks={avg_expanded:.1f}"

        )



    def get_metrics(self) -> list:

        """

        Retrieve all tracked metrics.



        Returns:

            List of RAGMetrics objects (for external analytics)

        """

        return _rag_metrics.copy()



    def clear_metrics(self) -> None:

        """Clear metrics (for testing or periodic cleanup)"""

        global _rag_metrics

        _rag_metrics.clear()

        logger.info(" Metrics cleared")



    def get_health_metrics(self) -> dict:

        """

        Get health metrics for monitoring endpoint.



        Returns metrics useful for /rag/health endpoint:

        - avg_latency: Average total latency in milliseconds

        - cache_hit_rate: Percentage of cache hits

        - total_queries: Total number of queries tracked

        - cache_size: Current cache size

        - timeout_rate: Percentage of queries that timed out

        - partial_result_rate: Percentage using fallback



        Returns:

            Dict with health metrics

        """

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

