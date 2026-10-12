import logging
import time
from app.modules.rag.graph.state import GraphState

logger = logging.getLogger(__name__)

async def build_system_prompt(state: GraphState) -> tuple[str, str]:
    from app.core.database import get_db_with_tenant
    from app.modules.agents.repository import AgentRepository
    
    agent_id = state.get("agent_id")
    tenant_id = state.get("tenant_id")
    
    personality_description = "You are a helpful assistant."
    base_prompt = ""
    ontology_rules_str = ""
    
    if agent_id and tenant_id:
        async with get_db_with_tenant(tenant_id) as db:
            agent_repo = AgentRepository(db, tenant_id)
            agent = await agent_repo.get_by_id(agent_id)
            if agent:
                personality_description = getattr(agent, "description", personality_description) or personality_description
                base_prompt = getattr(agent, "base_prompt", "") or ""
                ontology = getattr(agent, "ontology", {})
                
                if ontology and ontology.get("rules"):
                    rules_list = [
                        f"({r.get('source_class', '')})-[:{r.get('relation', '')}]->({r.get('target_class', '')})"
                        for r in ontology["rules"]
                        if r.get("source_class")
                    ]
                    if rules_list:
                        ontology_rules_str = (
                            "\n\n[ENTERPRISE ONTOLOGY RULES (STRICT GROUNDING)]\n"
                            + "\n".join(rules_list)
                            + "\nAlign your reasoning strictly with these established business relationships. Do not hallucinate relationships outside of this schema."
                        )

    accuracy_directives = (
        "\n- Enforce 100% factual accuracy based strictly on the retrieved context."
        "\n- Correct any obvious spelling or grammatical errors found in the source documents; do not copy typos."
        "\n- Verify timelines, chronologies, and locations strictly to avoid historical or situational errors."
    )
    if "factual accuracy" not in personality_description.lower():
        personality_description += accuracy_directives

    tabular_rules = ""
    if state.get("excel_kbs") or state.get("csv_kbs"):
        tabular_rules = """
- TRANSACTION CLASSIFICATION: Categorize transactions strictly:
  * Credit (Deposit/Incoming): Salary, interest, deposits, incoming transfers.
  * Debit (Withdrawal/Outgoing/Payment): ATM withdrawals, payments to merchants, fees, taxes, outgoing transfers."""

    enumeration_rules = ""
    if state.get("intent") == "ENUMERATION":
        enumeration_rules = """
- ENUMERATION DIRECTIVE: The user has asked you to list items (e.g. current openings, available roles). You MUST list EACH distinct item by name. DO NOT generalize, DO NOT summarize, and DO NOT group them together. State every single item retrieved from the context explicitly."""

    injected_system_prompt = f"""
[PERSONALITY MODE: STRICT]
You MUST strictly reflect this personality:
{personality_description}

Base Instruction:
{base_prompt}{ontology_rules_str}

You are an enterprise AI assistant. Follow these core directives:

1. MEMORY AUTHORITY (HIGHEST PRIORITY):
- If the prompt contains "### MANDATORY USER PREFERENCES & MEMORY DIRECTIVES", treat it as authoritative verified ground truth about the user overriding documents.
- Answer user personal facts directly (e.g., name, marks). Say "Based on your saved profile, ..." when answering from memory.

2. GROUNDING & ANTI-HALLUCINATION:
- Answer ONLY using the provided document context or verified user memory. Never use outside world knowledge, internet facts, or mythology.
- Never invent, infer, estimate, or assume facts. If retrieved passages conflict, state the conflict without resolving it yourself.
- For compound questions, evaluate each part independently: answer grounded parts, and explicitly state if a specific part is missing or left blank in the documents.
- Extract exact numbers, counts, and metrics (e.g. "50+ Certified RPA Developers", "100K+ Documents").
- Missing Information: If a person, entity, or topic is not found in the context or memory, state clearly: "I don't have information about [topic/person] in my current knowledge base." NEVER guess or offer outside commentary.
- Be direct and concise without omitting facts, conditions, or qualifiers. Never include internal relevance scores (e.g. "(relevance: 0.65)").{tabular_rules}{enumeration_rules}

3. AMBIGUITY SURFACING & MULTI-CLAUSE INTERACTION:
- If a calculation or term is scoped narrowly or defined ambiguously in the source, state the calculation under literal wording, then add one line flagging the ambiguity.
- If multiple retrieved clauses interact (e.g. age limits and coverage amounts), state both applicable clauses and whether precedence is defined in the source.

4. ENTITY DISAMBIGUATION (PRIMARY ORGANIZATION):
- For generic executive questions (e.g. "who is the CTO?" or "who is the CEO?"), answer strictly for the primary organization (e.g., Gramosoft).
- IGNORE executives from third-party clients, partners, or testimonials (e.g., "CTO of X company") unless specifically asked for by company name.

5. FORMATTING & SOURCE CITATIONS:
- Use Markdown tables for comparisons, bullet lists for items/conditions, and paragraphs for explanations.
- Greetings: NEVER include any source citation for greetings or polite conversation.
- Source Specificity:
  * Services/Offerings -> cite the services page.
  * Leadership/Executives/About -> cite the about/team page.
  * General company overview -> cite the main landing page.
  * NEVER cite /contact unless the user explicitly asks for contact/visit/call information.
- Format:
  * For documents/PDFs: cite clean filename (e.g. [Source: filename.pdf]). Never cite internal storage/S3 URLs.
  * For websites: cite clean URL (e.g. [Source: https://example.com/page]).
  * Put the citation at the very end of your response on its own single line:
    [Source: filename.pdf] or [Source: https://example.com/page]

FINAL RESPONSE FORMAT:
<grounded answer>

[Source: filename.pdf] or [Source: https://example.com/page]
""".strip()

    return injected_system_prompt, personality_description


def resolve_display_name_and_source(raw_source: str, url: str, chunk_id: str = "") -> str:
    target = (url or raw_source or "").strip()
    if not target:
        return f"Document_{chunk_id or 'Unknown'}"

    target_low = target.lower()
    clean_target = target.split("?")[0].replace("\\", "/")

    # Check if this points to an S3 bucket or internal upload storage
    is_storage = any(
        m in target_low for m in [
            ".s3.", ".s3-", "s3.amazonaws.com", "amazonaws.com",
            "s3://", "/grag/uploads/", "/uploads/"
        ]
    )

    doc_extensions = (
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv",
        ".txt", ".ppt", ".pptx", ".png", ".jpg", ".jpeg",
        ".webp", ".gif"
    )
    is_doc_file = any(clean_target.lower().endswith(ext) for ext in doc_extensions)

    if is_storage or is_doc_file:
        fname = clean_target.split("/")[-1].strip()
        return fname or f"Document_{chunk_id or 'Unknown'}"

    # Genuine web URL
    if target.startswith("http://") or target.startswith("https://"):
        return target

    fname = clean_target.split("/")[-1].strip()
    return fname or f"Document_{chunk_id or 'Unknown'}"


async def generation_node(state: GraphState) -> dict:
    """
    Constructs the prompt and executes LLM generation.
    - Includes memory guidance if provided by the memory node.
    - Handles [Source: Knowledge Graph] citation rules.
    """
    t_entry = time.perf_counter()
    if state.get("requires_clarification"):
        logger.info("[GENERATION] Skipping LLM generation because clarification is required.")
        return {"generation": ""}

    if state.get("system_prompt"):
        system_prompt = state["system_prompt"]
        personality = "You are a helpful assistant."
    else:
        system_prompt, personality = await build_system_prompt(state)
    
    # 1. Memory Context Injection
    memory_guidance = state.get("memory_guidance")
    if memory_guidance:
        system_prompt += f"\n\n[MEMORY CONTEXT]\n{memory_guidance}"

    # 2. Chat History 4th Layer Injection
    chat_history = state.get("chat_history")
    if chat_history:
        system_prompt += "\n\n[CONVERSATION HISTORY]\nUse the provided history to answer contextual follow-up questions."
        
    # Format Context from chunks
    # Keep chunks in relevance ranking order so the most relevant page is presented first to the LLM
    reranked_chunks = state.get("reranked_chunks") or state.get("retrieved_chunks") or []
    reranked_chunks = sorted(
        reranked_chunks,
        key=lambda c: getattr(c, "final_relevance_score", 0.0) or getattr(c, "hybrid_score", 0.0) or 0.0,
        reverse=True
    )
    
    # Cap to top 7 most relevant chunks to optimize prompt prefill while maintaining 100% answer accuracy
    top_context_chunks = reranked_chunks[:7]
    
    present_chunks = {
        (str(getattr(c, "kb_id", "")), getattr(c, "position", getattr(c, "chunk_index", 0)) or 0)
        for c in top_context_chunks
    }

    context_text = ""
    for c in top_context_chunks:
        prov = getattr(c, "provenance_metadata", {}) or {}
        raw_source = getattr(c, "source", "") or prov.get("source", "")
        url = prov.get("url", "") or prov.get("source_url", "")
        
        filename = resolve_display_name_and_source(
            raw_source=str(raw_source) if raw_source else "",
            url=str(url) if url else "",
            chunk_id=str(getattr(c, "chunk_id", "Unknown"))
        )
            
        content = getattr(c, "content", "") or getattr(c, "text", "")

        
        # Phase 2: Strip overlap only if the previous chunk is also retrieved
        prov_metadata = getattr(c, "provenance_metadata", {}) or {}
        overlap_len = prov_metadata.get("overlap_prefix_len", 0)
        if overlap_len and len(content) > overlap_len:
            c_kb_id = str(getattr(c, "kb_id", ""))
            c_pos = getattr(c, "position", getattr(c, "chunk_index", 0)) or 0
            
            # If the chunk immediately preceding this one is in the context, we strip the redundant overlap.
            # If it's missing, we KEEP the overlap so this chunk has complete context.
            if (c_kb_id, c_pos - 1) in present_chunks:
                content = content[overlap_len:]
                
        # Enforce max chunk length to prevent LLM prefill bottlenecks (massive stories)
        if len(content) > 2500:
            content = content[:2500] + "... [truncated for brevity]"
        context_text += f"Document: {filename}\n{content}\n\n"
        
    tabular_results = state.get("tabular_results", "")
    tabular_sources = state.get("tabular_sources", [])
    if tabular_results:
        if tabular_sources:
            context_text += f"\n\n[ENTERPRISE SPREADSHEET ANALYSIS]\nDocuments: {', '.join(tabular_sources)}\n{tabular_results}\n"
        else:
            context_text += f"\n\n[ENTERPRISE SPREADSHEET ANALYSIS]\n{tabular_results}\n"

    # Streaming Generation
    from app.core.llm.deepinfra_llm import DeepInfraLLMClient
    
    llm_client = DeepInfraLLMClient.get_instance()
    agent_persona = {
        "name": "Assistant",
        "personality": personality,
        "system_prompt": system_prompt,
    }
    
    query = state["query"]
    full_answer = []
    stream_queue = state.get("stream_queue")
    
    t_start = time.perf_counter()
    logger.info(f"[TIMING] generation_node prompt assembly took {t_start - t_entry:.3f}s")
    ttft_logged = False
    
    try:
        async for chunk in llm_client.stream_answer(
            query=query,
            context=context_text,
            tenant_id=state.get("tenant_id"),
            agent_id=state.get("agent_id"),
            agent_persona=agent_persona,
            enable_thinking=False,
        ):
            if not ttft_logged:
                t_ttft = time.perf_counter()
                logger.info(f"[TIMING] generation_node TTFT (Time To First Token): {t_ttft - t_start:.3f}s")
                ttft_logged = True
            
            full_answer.append(chunk)
            if stream_queue is not None:
                await stream_queue.put(chunk)
    finally:
        t_end = time.perf_counter()
        logger.info(f"[TIMING] generation_node full stream duration: {t_end - t_start:.3f}s")
        # Ensure sentinel is sent to stream_queue even if streaming errors or aborts
        if stream_queue is not None:
            await stream_queue.put(None)

    final_answer_text = "".join(full_answer).strip()
    if not final_answer_text:
        final_answer_text = "I'm sorry, but I don't have that specific information in my current knowledge base."

    # 3. Citation Formatting (only for real information queries, never for greetings)
    import re
    clean_q = state.get("query", "").strip().lower()
    is_greeting = bool(re.fullmatch(r"(hello|hi|hey|good\s+morning|good\s+afternoon|good\s+evening|howdy|greetings|thanks|thank\s+you|how\s+are\s+you)(\s+(there|everyone|all|friend))?[!.,?]*", clean_q))

    sources = []
    source_documents = []
    if not is_greeting:
        graph_triplets = state.get("graph_triplets", [])
        if graph_triplets:
            sources.append("Knowledge Graph")
            source_documents.append({"source": "Knowledge Graph", "name": "Knowledge Graph", "kb_id": ""})
            
        for c in top_context_chunks:
            prov = getattr(c, "provenance_metadata", {}) or {}
            raw_source = getattr(c, "source", "") or prov.get("source", "") or getattr(c, "metadata", {}).get("source", "")
            url = prov.get("url", "") or prov.get("source_url", "") or getattr(c, "metadata", {}).get("url", "") or getattr(c, "metadata", {}).get("source_url", "")
            c_kb_id = str(getattr(c, "kb_id", "") or prov.get("kb_id", ""))
            
            clean_name = resolve_display_name_and_source(
                raw_source=str(raw_source) if raw_source else "",
                url=str(url) if url else "",
                chunk_id=str(getattr(c, "chunk_id", "Unknown"))
            )
            
            if getattr(c, "is_stitched_neighbor", False):
                clean_name = f"{clean_name} (Neighbor Context)"
                
            if clean_name not in sources:
                sources.append(clean_name)
                source_documents.append({
                    "source": clean_name,
                    "name": clean_name,
                    "kb_id": c_kb_id,
                })
                
        tabular_sources = state.get("tabular_sources", [])
        for ts in tabular_sources:
            if ts not in sources:
                sources.append(ts)
                source_documents.append({"source": ts, "name": ts, "kb_id": ""})
            
    return {
        "system_prompt": system_prompt,
        "final_answer": final_answer_text,
        "sources": sources,
        "source_documents": source_documents,
    }


