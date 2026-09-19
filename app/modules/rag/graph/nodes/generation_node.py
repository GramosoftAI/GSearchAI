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
- For multi-part or compound questions (e.g., asking for multiple facts/attributes like defining event and phase of operation), evaluate each part independently:
  * Answer EVERY part that has grounded information present in the context.
  * For any part where the specific field or information is missing, unstated, or blank in the document, explicitly state that specific part is not specified or left blank in the document (do NOT refuse the entire answer).
- If the user is asking a factual/document question and the requested information is ENTIRELY missing for ALL parts from BOTH the document context AND the user memory section, reply exactly:
  "I couldn't find it."
- Mention the relevant source at the end.
- Answer ONLY the specific question asked by the user. Do not provide extra analysis, summaries of unrelated topics, or inferred narratives unless requested.
- Be concise. Focus strictly on direct answers and avoid filler.
- NEVER include internal relevance scores or confidence numbers (e.g. "(relevance: 0.65)", "(relevance: 0.58)", or "score: 0.61") in your output text. Relevance scores are for internal search ranking only and must never be shown to the user.{tabular_rules}{enumeration_rules}

==================================================
ENTITY DISAMBIGUATION RULES
==================================================
When the user asks generic questions about team members, roles, or executives (e.g. "who is the CTO?"), assume they are asking about the primary company/organization.
If the retrieved context contains executives from both the primary company and third-party clients (e.g. inside testimonials or case studies), ONLY return the primary company's executive. Do not list client executives unless explicitly asked.

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
- Cite a source ONLY IF information from retrieved document/data chunks or Knowledge Graph was ACTUALLY USED to answer the user's specific question.
- If the answer came from document chunks, cite ONLY the specific filename(s) from which relevant facts were extracted.
- Single Source: If the answer came from only one document (e.g. ARUN_N.pdf), cite ONLY that single document: [Source: ARUN_N.pdf]. Do NOT list other unused files.
- Multi Source: If the answer combined information from multiple documents, list only those specific documents: [Source: file1.pdf, file2.pdf].
- Knowledge Graph: If the answer came exclusively from the Knowledge Graph relationships without document chunks, cite: [Source: Knowledge Graph].
- Deduplicate sources so each unique filename appears ONLY ONCE.
- Format the citation at the very end of your response on its own single line:
  [Source: filename1, filename2]

==================================================
FINAL RESPONSE FORMAT
==================================================
<grounded answer>

[Source: <only include source file(s) or Knowledge Graph actually used to answer document/graph questions>]
""".strip()

    return injected_system_prompt, personality_description


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
    reranked_chunks = state.get("reranked_chunks") or state.get("retrieved_chunks") or []
    # Sort chunks by kb_id and chunk_index to ensure stitched neighbors are contiguous
    reranked_chunks = sorted(
        reranked_chunks, 
        key=lambda c: (str(getattr(c, "kb_id", "")), getattr(c, "chunk_index", 0) or 0)
    )
    
    # Precompute set of (kb_id, position) for adjacency checks
    present_chunks = {
        (str(getattr(c, "kb_id", "")), getattr(c, "position", getattr(c, "chunk_index", 0)) or 0)
        for c in reranked_chunks
    }
    
    context_text = ""
    for c in reranked_chunks:
        raw_source = getattr(c, "source", "") or getattr(c, "metadata", {}).get("source", "Unknown Document")
        filename = raw_source.split("/")[-1]
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

    # 3. Citation Formatting
    sources = []
    graph_triplets = state.get("graph_triplets", [])
    if graph_triplets:
        sources.append("Knowledge Graph")
        
    for c in reranked_chunks:
        raw_source = getattr(c, "source", "") or getattr(c, "metadata", {}).get("source", "Unknown Document")
        clean_name = raw_source.split("/")[-1]
        
        if getattr(c, "is_stitched_neighbor", False):
            clean_name = f"{clean_name} (Neighbor Context)"
            
        if clean_name not in sources:
            sources.append(clean_name)
            
    tabular_sources = state.get("tabular_sources", [])
    for ts in tabular_sources:
        if ts not in sources:
            sources.append(ts)
            
    return {
        "system_prompt": system_prompt,
        "final_answer": final_answer_text,
        "sources": sources
    }

