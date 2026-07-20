import os
import re
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from neo4j import AsyncGraphDatabase

from schema.database import AsyncSessionLocal, EpisodicMemory, init_db
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("memory_api")

app = FastAPI(title="Native Vector & Graph Memory Core", version="2.1.0")

# Neo4j Driver Connection Setup
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphmind_password")
neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

EMBED_DIM = 1024


class MemoryProcessRequest(BaseModel):
    query: str
    session_id: str
    agent_id: str
    user_id: str
    tenant_id: str


class MemorySaveRequest(BaseModel):
    query: str
    ai_response: str
    session_id: str
    agent_id: str
    user_id: str
    tenant_id: str
    metadata: Optional[Dict[str, Any]] = None


# ============================================================================
# Ollama Helpers
# ============================================================================
async def get_embedding(text: str) -> List[float]:
    try:
        ollama_base = os.getenv("OLLAMA_HOST", "http://192.168.1.100:11434").rstrip('/')
        embed_model = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3:latest")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{ollama_base}/api/embeddings",
                json={"model": embed_model, "prompt": text},
                timeout=90.0
            )
            if resp.status_code == 200:
                embedding = resp.json()["embedding"]
                # BUG FIX: silently zero-padding/truncating a misconfigured model's
                # output hides real problems. Warn loudly instead of masking it.
                if len(embedding) != EMBED_DIM:
                    logger.warning(
                        f"Embedding model '{embed_model}' returned {len(embedding)} dims, "
                        f"expected {EMBED_DIM}. Check OLLAMA_EMBED_MODEL — padding/truncating "
                        f"will degrade recall quality."
                    )
                return embedding[:EMBED_DIM] if len(embedding) >= EMBED_DIM else embedding + [0.0] * (EMBED_DIM - len(embedding))
            logger.error(f"Ollama embed error ({resp.status_code}): {resp.text}")
    except Exception as e:
        logger.error(f"Embedding failure: {e}")
    return [0.0] * EMBED_DIM


async def run_llm_completion(system_prompt: str, user_prompt: str) -> str:
    try:
        ollama_base = os.getenv("OLLAMA_HOST", "http://192.168.1.100:11434").rstrip('/')
        chat_model = os.getenv("OLLAMA_CHAT_MODEL", "phi4-mini:latest")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{ollama_base}/api/chat",
                json={
                    "model": chat_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "options": {"temperature": 0.0},
                    "stream": False
                },
                timeout=90.0
            )
            if resp.status_code == 200:
                return resp.json()["message"]["content"].strip()
            logger.error(f"Ollama chat error ({resp.status_code}): {resp.text}")
    except Exception as e:
        logger.error(f"LLM failure: {e}")
    return ""


# ============================================================================
# Triplet parsing / normalization (BUG FIX: was previously absent entirely —
# raw LLM JSON went straight into Cypher with no validation or casing)
# ============================================================================
def _extract_json_block(text: str) -> Optional[dict]:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM output as JSON")
        return None


_BLACKLISTED_ENTITIES = {"you", "user", "assistant", "i", "me", "we", "he", "she", "they", "it"}
_BLACKLISTED_RELATIONS = {"REQUEST", "REQUESTED", "ASK", "ASKED", "QUESTION", "MENTIONED", "SAID", "STATED", "HAS_ATTRIBUTE", "HAS_FIELD"}


def _normalize_triplet(t: dict) -> Optional[dict]:
    """Validates + normalizes a single triplet. Returns None to skip garbage
    entries instead of letting them reach Cypher as null/inconsistent nodes.

    Backstop filter (not just prompt-level): small local models like
    phi4-mini won't follow "don't extract meta-facts" instructions 100% of
    the time, so pronoun subjects/objects and known conversational-meta or
    schema-only relations are dropped here regardless of what the LLM did.
    """
    if not isinstance(t, dict):
        return None
    subject = str(t.get("subject", "")).strip()
    obj = str(t.get("object", "")).strip()
    relation = str(t.get("relation", "")).strip().upper().replace(" ", "_")
    relation = re.sub(r"[^A-Z0-9_]", "", relation)  # APOC relationship types must be clean identifiers

    if not subject or not obj or not relation:
        return None
    if len(subject) < 2 or len(obj) < 2:
        return None
    if subject.lower() in _BLACKLISTED_ENTITIES or obj.lower() in _BLACKLISTED_ENTITIES:
        return None
    if relation in _BLACKLISTED_RELATIONS:
        return None

    return {
        "subject": subject.lower(),
        "object": obj.lower(),
        "relation": relation,
    }


def _parse_and_normalize_triplets(raw_json_text: str) -> List[dict]:
    data = _extract_json_block(raw_json_text)
    if not data:
        logger.warning(f"Triplet extraction: no parseable JSON. Raw LLM output: {raw_json_text[:500]}")
        return []
    raw_triplets = data.get("triplets", [])
    if not isinstance(raw_triplets, list):
        return []

    logger.info(f"Triplet extraction: LLM proposed {len(raw_triplets)} raw triplets: {raw_triplets}")

    normalized = []
    dropped = []
    for t in raw_triplets[:8]:  # cap per-turn, same ceiling as doc-KB extractor
        n = _normalize_triplet(t)
        if n:
            normalized.append(n)
        else:
            dropped.append(t)

    if dropped:
        logger.info(f"Triplet extraction: dropped {len(dropped)} by filter: {dropped}")

    return normalized


def _extract_entity_names(raw_json_text: str) -> List[str]:
    """Parses a lightweight {'entities': [...]} response into a clean name list."""
    data = _extract_json_block(raw_json_text)
    if not data:
        return []
    entities = data.get("entities", [])
    if not isinstance(entities, list):
        return []
    names = []
    for e in entities:
        name = str(e).strip().lower() if not isinstance(e, dict) else str(e.get("name", "")).strip().lower()
        if name and len(name) >= 2:
            names.append(name)
    return names[:10]


# ============================================================================
# Neo4j write path
# ============================================================================
async def push_triplets_to_isolated_graph(
    tenant_id: str, user_id: str, session_id: str, triplets_json: str
):
    triplets = _parse_and_normalize_triplets(triplets_json)
    if not triplets:
        return

    query = """
    UNWIND $triplets AS t
    MERGE (s:MemoryEntity {name: t.subject, tenant_id: $tenant_id, user_id: $user_id})
    MERGE (o:MemoryEntity {name: t.object, tenant_id: $tenant_id, user_id: $user_id})
    WITH s, o, t
    CALL apoc.create.relationship(s, t.relation, {
        created_at: timestamp(),
        session_id: $session_id
    }, o) YIELD rel
    RETURN count(rel)
    """
    try:
        async with neo4j_driver.session() as session:
            await session.run(
                query,
                triplets=triplets,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
            logger.info(f"Wrote {len(triplets)} normalized triplets to memory graph.")
    except Exception as e:
        logger.error(f"Neo4j memory graph write failed: {e}", exc_info=True)


async def _query_graph_relations(tenant_id: str, user_id: str, concepts: List[str]) -> List[str]:
    """BUG FIX: `await res.records()` is not a valid method on the async
    Neo4j driver's Result — it's an async iterator itself. This silently
    threw an AttributeError before, caught by the outer try/except, meaning
    graph recall has likely never returned a result until now."""
    if not concepts:
        return []

    graph_query = """
    MATCH (s:MemoryEntity {tenant_id: $tenant_id, user_id: $user_id})-[r]->(o:MemoryEntity)
    WHERE s.name IN $concepts OR o.name IN $concepts
    RETURN s.name + ' ' + type(r) + ' ' + o.name AS relationship_str
    LIMIT 10
    """
    try:
        async with neo4j_driver.session() as session:
            result = await session.run(
                graph_query, tenant_id=tenant_id, user_id=user_id, concepts=concepts
            )
            return [record["relationship_str"] async for record in result]
    except Exception as ge:
        logger.error(f"Neo4j memory graph read failed: {ge}", exc_info=True)
        return []


@app.on_event("startup")
async def startup_event():
    await init_db()


@app.on_event("shutdown")
async def shutdown_event():
    # BUG FIX: driver was never closed, leaking connections on reload/restart
    await neo4j_driver.close()


@app.post("/api/v1/memory/process-turn")
async def process_turn(payload: MemoryProcessRequest):
    # 1. Feedback Router Triage
    triage_prompt = (
        "You are an agent memory router. Analyze the user's message. "
        "If the user is ONLY giving corrective feedback, instructions, adjustments, or acknowledgements "
        "to your previous behavior, reply with EXACTLY 'FEEDBACK_ONLY'. Otherwise, reply with 'NORMAL_QUERY'."
    )
    triage_decision = await run_llm_completion(triage_prompt, payload.query)
    is_feedback_only = "FEEDBACK_ONLY" in triage_decision

    # 2. Semantic Search Recall via Conceptual Summary (pgvector)
    query_embedding = await get_embedding(payload.query)
    guidance_blocks = []

    async with AsyncSessionLocal() as db:
        query_stmt = (
            select(EpisodicMemory.summarization)
            .filter(
                EpisodicMemory.tenant_id == payload.tenant_id,
                EpisodicMemory.user_id == payload.user_id
            )
            .order_by(EpisodicMemory.summary_vector.cosine_distance(query_embedding))
            .limit(4)
        )
        result = await db.execute(query_stmt)
        matched_summaries = result.scalars().all()

        for summary in matched_summaries:
            if summary:
                guidance_blocks.append(summary)

    # 3. Graph Relational Fact Recall
    # BUG FIX: previously matched full summary SENTENCES against entity NAMES
    # in Cypher — that comparison could never succeed (exact-string match
    # of a sentence vs a short name). Extract actual entity names from the
    # current query first, then match those.
    graph_context_elements = []
    entity_names: List[str] = []
    if guidance_blocks:
        entity_extraction_prompt = (
            "Extract the key named entities (people, departments, roles, products, "
            "concepts) mentioned or implied in this message. Return ONLY JSON: "
            '{"entities": ["name1", "name2"]}'
        )
        entities_raw = await run_llm_completion(entity_extraction_prompt, payload.query)
        entity_names = _extract_entity_names(entities_raw)

        if entity_names:
            relations = await _query_graph_relations(payload.tenant_id, payload.user_id, entity_names)
            graph_context_elements = relations

    # Build bundled context
    guidance_context = ""
    if guidance_blocks or graph_context_elements:
        guidance_context = "## PERSISTENT EPISODIC CONTEXT\n"
        if guidance_blocks:
            guidance_context += "### Historic Summaries:\n" + "\n".join([f"- {s}" for s in guidance_blocks]) + "\n"
        if graph_context_elements:
            guidance_context += "### Associated Knowledge Relations:\n" + "\n".join([f"- {g}" for g in graph_context_elements])

    return {
        "session_id": payload.session_id,
        "is_feedback_only": is_feedback_only,
        "guidance_context": guidance_context,
        "status": "success"
    }


@app.post("/api/v1/memory/save-turn")
async def save_turn(payload: MemorySaveRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(async_ingest_turn, payload)
    return {"status": "queued"}


async def async_ingest_turn(payload: MemorySaveRequest):
    user_interaction = f"User: {payload.query}\nAssistant: {payload.ai_response}"

    # Step A: Summarization (for pgvector recall — deliberately lossy/compact)
    summary_prompt = (
        "Compress the following interaction into a single, clean declarative factual statement "
        "capturing parameters and information explicitly discussed. Format: 'User asked X; Answer was Y.'"
    )
    summary_text = await run_llm_completion(summary_prompt, user_interaction)
    if not summary_text:
        summary_text = f"User interacted regarding: {payload.query[:50]}"

    # Step B: Dual Vectors
    raw_vector = await get_embedding(f"{payload.query} {payload.ai_response}")
    summary_vector = await get_embedding(summary_text)

    # Step C: Persist to Postgres
    async with AsyncSessionLocal() as db:
        new_memory = EpisodicMemory(
            user_id=payload.user_id,
            session_id=payload.session_id,
            tenant_id=payload.tenant_id,
            agent_id=payload.agent_id,
            user_query=payload.query,
            ai_response=payload.ai_response,
            summarization=summary_text,
            raw_vector=raw_vector,
            summary_vector=summary_vector,
            metadata_json=payload.metadata or {}
        )
        db.add(new_memory)
        await db.commit()

    # Step D: Knowledge Graph Triplet Extraction
    # BUG FIX: was extracting from `summary_text` (one lossy sentence) —
    # now extracts from the RAW query+response so facts that didn't survive
    # summarization still make it into the graph.
    ontology_prompt = (
        "Extract factual (subject, relation, object) triplets from this conversation.\n\n"
        "STRICT RULES:\n"
        "1. Extract ONLY concrete facts with actual VALUES — e.g. "
        "(\"Joseph Moore\", \"HAS_SALARY\", \"63032\"), never schema-level statements like "
        "(\"Joseph Moore\", \"HAS_ATTRIBUTE\", \"salary\"). If the assistant only listed field "
        "names without giving actual values, extract NOTHING for those fields.\n"
        "2. NEVER use \"you\", \"user\", \"assistant\", \"I\", or pronouns as a subject or object. "
        "Do not extract meta-facts about the conversation itself (e.g. the user asking a question, "
        "requesting a summary, or the assistant explaining something).\n"
        "3. Only extract facts the assistant's answer explicitly stated as true — do not extract "
        "the user's question itself as a fact.\n"
        "4. Skip entirely if the exchange contains no concrete extractable facts (e.g. small talk, "
        "a request for a menu of options, an error message). Return {\"triplets\": []} in that case.\n"
        "5. Relation must be UPPER_SNAKE_CASE.\n\n"
        "Examples of what NOT to extract:\n"
        "  BAD: (\"you\", \"REQUEST\", \"employee data\")  ← meta, not a fact\n"
        "  BAD: (\"emp1002\", \"HAS_ATTRIBUTE\", \"salary\")  ← schema, no value\n"
        "Examples of what TO extract:\n"
        "  GOOD: (\"Joseph Moore\", \"HAS_SALARY\", \"63032\")\n"
        "  GOOD: (\"Joseph Moore\", \"WORKS_IN\", \"Engineering\")\n\n"
        "Return strict JSON only: "
        '{"triplets": [{"subject": "entity1", "relation": "RELATION_TYPE", "object": "entity2"}]}'
    )
    triplets_json = await run_llm_completion(ontology_prompt, user_interaction)

    await push_triplets_to_isolated_graph(
        payload.tenant_id, payload.user_id, payload.session_id, triplets_json
    )