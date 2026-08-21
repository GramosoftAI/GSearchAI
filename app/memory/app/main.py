import os
import re
import json
import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, delete
from neo4j import AsyncGraphDatabase
from dotenv import load_dotenv

# Find and load the root .env file
current_dir = os.path.dirname(os.path.abspath(__file__))
for _ in range(5):
    env_path = os.path.join(current_dir, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break
    current_dir = os.path.dirname(current_dir)

from schema.database import AsyncSessionLocal, EpisodicMemory, UserPreference, init_db
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("memory_api")

app = FastAPI(title="Native Vector & Graph Memory Core", version="2.5.0")

# Neo4j Driver Connection Setup
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphmind_password")

logger.info(f"[NEO4J INIT] Initializing Neo4j Driver connecting to: {NEO4J_URI}")
neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

EMBED_DIM = int(os.getenv("EMBEDDING_DIMENSION", "768"))

LIVE_SEMAPHORE = asyncio.Semaphore(int(os.getenv("LLM_LIVE_CONCURRENCY", "10")))
BACKGROUND_SEMAPHORE = asyncio.Semaphore(int(os.getenv("LLM_BACKGROUND_CONCURRENCY", "5")))


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
    is_feedback_only: bool = False


# ============================================================================
# INTENT ROUTING PATTERNS: Structural, Preferences, Updates & Deletions
# ============================================================================
HISTORY_QUERY_PATTERN = re.compile(
    r"\b(last\s+(\d+\s+)?.{0,15}?(chat|char|session|conversation|turn|discussion)s?|"
    r"previous\s+(\d+\s+)?.{0,15}?(chat|char|session|discussion)s?|"
    r"what\s+.{0,15}?(discuss|discussion|talk|talking)|"
    r"summarize\s+.{0,30}?(last|previous)\s+(\d+\s+)?.{0,15}?(chat|char|session|conversation)s?)\b",
    re.IGNORECASE
)

_PREFERENCE_PATTERNS = re.compile(
    r"\b(remember|please remember|note (that|down)|"
    r"always (respond|answer|reply|format|use)|"
    r"from now on|i prefer|my preferred|please (always|remember)|"
    r"don'?t (use|do)|stop (using|doing)|never (use|do)|"
    r"not\s+.+\s+it'?s|upgrade\s+my|update\s+my|change\s+my|my\s+.*is|upgrad|upgrade|change|update)\b",
    re.IGNORECASE,
)

_DELETE_PATTERNS = re.compile(
    r"\b(delete|forget|remove|clear|erase)\s+(this|my|our|the)?\s*"
    r"(conversation|chat|history|session|memory|preference|mark|grade|details|info)?\b",
    re.IGNORECASE
)

_QUESTION_INDICATOR = re.compile(
    r"^\s*(what|how|when|where|why|who|which|is|are|do|does|did|can|could|would|will)\b|\?\s*$",
    re.IGNORECASE,
)

# Broadened dynamic regex parser pattern for fallback key-value extraction
_DYNAMIC_FACT_PATTERN = re.compile(
    r".*?\b(?:my\s+)?(?P<key>[a-zA-Z0-9_\-'\s]+?)\s+"
    r"(?:is|are|=|:|was|not\s+.*?\s+(?:it'?s|into|to)|to|into|changed?\s+to|upgraded?\s+to|upgrad\s+into)\s+"
    r"(?P<value>[a-zA-Z0-9%\s_\-'\.]+)",
    re.IGNORECASE,
)


def _is_deterministic_preference_statement(query: str) -> bool:
    if _QUESTION_INDICATOR.search(query):
        return False
    if _PREFERENCE_PATTERNS.search(query):
        return True
    if _DYNAMIC_FACT_PATTERN.search(query):
        return True
    return False


def _is_delete_statement(query: str) -> bool:
    return bool(_DELETE_PATTERNS.search(query))


# ============================================================================
# LLM & Embedding Helpers
# ============================================================================
def strip_think_tags(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()


async def get_embedding(text: str, priority: str = "live") -> List[float]:
    semaphore = LIVE_SEMAPHORE if priority == "live" else BACKGROUND_SEMAPHORE
    async with semaphore:
        try:
            llm_base = os.getenv("EMBEDDING_BASE_URL", os.getenv("LLM_BASE_URL", "https://api.deepinfra.com/v1/openai")).rstrip('/')
            api_key = os.getenv("EMBEDDING_API_KEY", os.getenv("LLM_GATEWAY_API_KEY", os.getenv("DEEPINFRA_API_KEY", "")))
            embed_model = os.getenv("DEEPINFRA_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            
            endpoint = f"{llm_base}/embeddings" if not llm_base.endswith("/embeddings") else llm_base
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    endpoint,
                    headers=headers,
                    json={"model": embed_model, "input": text},
                    timeout=90.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    embedding = data["data"][0]["embedding"]
                    if len(embedding) != EMBED_DIM:
                        logger.warning(
                            f"Embedding model '{embed_model}' returned {len(embedding)} dims, "
                            f"expected {EMBED_DIM}."
                        )
                    return embedding[:EMBED_DIM] if len(embedding) >= EMBED_DIM else embedding + [0.0] * (EMBED_DIM - len(embedding))
                logger.error(f"LLM embed error ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Embedding failure: {type(e).__name__}: {e}")
    return [0.0] * EMBED_DIM


async def run_llm_completion(system_prompt: str, user_prompt: str, priority: str = "live") -> str:
    semaphore = LIVE_SEMAPHORE if priority == "live" else BACKGROUND_SEMAPHORE
    async with semaphore:
        try:
            llm_base = os.getenv("LLM_BASE_URL", os.getenv("DEEPINFRA_API_URL", "https://api.deepinfra.com/v1/openai")).rstrip('/')
            api_key = os.getenv("LLM_GATEWAY_API_KEY", os.getenv("DEEPINFRA_API_KEY", ""))
            chat_model = os.getenv("MEMORY_CHAT_MODEL", os.getenv("MODEL_MEMORY", "meta-llama/Meta-Llama-3.1-8B-Instruct"))
            max_tokens = int(os.getenv("MAX_TOKENS_MEMORY", "512"))
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            endpoint = f"{llm_base}/chat/completions" if llm_base.endswith("/openai") else f"{llm_base}/v1/chat/completions"
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    endpoint,
                    headers=headers,
                    json={
                        "model": chat_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "max_tokens": max_tokens,
                        "temperature": 0.0,
                        "stream": False,
                        "enable_thinking": False,
                        "reasoning_effort": "none"
                    },
                    timeout=90.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    return strip_think_tags(content)
                logger.error(f"LLM chat error ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"LLM failure: {type(e).__name__}: {e}")
    return ""


# ============================================================================
# Triplet parsing & User Preference Helpers
# ============================================================================
def _extract_json_block(text: str) -> Optional[dict]:
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?\n?", "", text).strip("` \n\r\t")
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM output as JSON: {text!r}")
        return None

_PRONOUNS_TO_NORMALIZE = {"i", "me", "my", "myself", "mine"}
_BLACKLISTED_ENTITIES = {
    "you", "assistant", "we", "he", "she", "they", "it",
    "your", "his", "her", "their", "our", "yours"
}
_BLACKLISTED_RELATIONS = {"REQUEST", "REQUESTED", "ASK", "ASKED", "QUESTION", "MENTIONED", "SAID", "STATED"}
_INVALID_OBJECTS = {"none", "null", "unknown", "n/a", "not_present", "not present", "no information", "no info"}


def _normalize_triplet(t: dict) -> Optional[dict]:
    if not isinstance(t, dict):
        return None
    subject = str(t.get("subject", "")).strip()
    obj = str(t.get("object", "")).strip()
    relation = str(t.get("relation", "")).strip().upper().replace(" ", "_")
    relation = re.sub(r"[^A-Z0-9_]", "", relation)

    # Filter out missing/negative value triplets
    if obj.lower() in _INVALID_OBJECTS or "not_present" in obj.lower():
        return None

    # Coreference normalization: Map first-person pronouns to 'user'
    if subject.lower() in _PRONOUNS_TO_NORMALIZE:
        subject = "user"
    if obj.lower() in _PRONOUNS_TO_NORMALIZE:
        obj = "user"

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
        return []
    raw_triplets = data.get("triplets", [])
    if not isinstance(raw_triplets, list):
        return []

    normalized = []
    for t in raw_triplets[:8]:
        n = _normalize_triplet(t)
        if n:
            normalized.append(n)
    return normalized


async def map_to_ontology(raw_triplets: List[dict]) -> List[dict]:
    if not raw_triplets:
        return []

    fallback_entity = "MemoryEntity"
    fallback_relation = "RELATED_TO"

    prompt = (
        "You are a Dynamic Ontology Mapping Engine. Categorize the following open-domain knowledge triplets "
        "by inventing logical Upper-Level categorical labels on the fly.\n\n"
        "Rules:\n"
        "1. Categorize the 'subject' and 'object' into broad, logical Entity Types (e.g., AviationVehicle, SoftwareFramework, PersonalMetric, FinancialAsset) as 'subject_type' and 'object_type'. Use PascalCase.\n"
        "2. Keep the original 'subject' and 'object' strings exactly as they are for value storage.\n"
        "3. Define a logical 'relation' connecting them in UPPER_SNAKE_CASE (e.g., HAS_SERIAL_NUMBER, DEVELOPED_BY, GRADUATED_FROM).\n"
        "4. Return EXACTLY a JSON object with a key 'mapped_triplets' containing the array of mapped triplets:\n"
        '{"mapped_triplets": [{"subject": "engine serial number", "subject_type": "AircraftComponent", '
        '"object": "23-4583", "object_type": "Identifier", "relation": "HAS_VALUE"}]}\n\n'
        f"Raw Triplets to map:\n{json.dumps(raw_triplets, indent=2)}\n"
    )
    
    raw_response = await run_llm_completion(
        "You are a strict data normalizer. Output ONLY a valid JSON object.",
        prompt,
        priority="background"
    )
    
    mapped_data = _extract_json_block(raw_response)
    if isinstance(mapped_data, dict) and "mapped_triplets" in mapped_data:
        triplet_list = mapped_data["mapped_triplets"]
    else:
        triplet_list = []

    if not isinstance(triplet_list, list) or not triplet_list:
        # fallback to generic mapping if llm fails
        return [{"subject": t["subject"], "subject_type": fallback_entity, "object": t["object"], "object_type": fallback_entity, "relation": fallback_relation} for t in raw_triplets]
    
    validated = []
    for t in triplet_list:
        subj = t.get("subject")
        obj = t.get("object")
        subj_type = t.get("subject_type", fallback_entity)
        obj_type = t.get("object_type", fallback_entity)
        rel = t.get("relation", fallback_relation)
        
        # Ensure proper formatting of dynamic types
        if not isinstance(subj_type, str) or len(subj_type) < 2: subj_type = fallback_entity
        if not isinstance(obj_type, str) or len(obj_type) < 2: obj_type = fallback_entity
        if not isinstance(rel, str) or len(rel) < 2: rel = fallback_relation
        
        # Normalize dynamically generated relation names
        rel = rel.upper().replace(" ", "_")
        rel = re.sub(r"[^A-Z0-9_]", "", rel)
        if not rel: rel = fallback_relation
        
        # Normalize dynamic entity types
        subj_type = re.sub(r"[^a-zA-Z0-9]", "", subj_type)
        obj_type = re.sub(r"[^a-zA-Z0-9]", "", obj_type)
        if not subj_type: subj_type = fallback_entity
        if not obj_type: obj_type = fallback_entity
        
        if subj and obj:
            validated.append({
                "subject": subj,
                "subject_type": subj_type,
                "object": obj,
                "object_type": obj_type,
                "relation": rel
            })
    return validated


def _extract_entity_names(raw_json_text: str) -> List[str]:
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


PREFERENCE_EXTRACTION_PROMPT = (
    "You are a strict JSON extractor for preference/fact updates and corrections.\n"
    "CRITICAL INSTRUCTION: DO NOT extract anything for standard search queries, questions, or one-off commands (e.g. 'i need full detail about this company pincode 110025'). ONLY extract persistent facts, personal facts, or explicit preferences.\n"
    "If the query is just a search question or command, return an empty JSON object: {}\n"
    "Otherwise, extract the updated preference or fact into EXACTLY ONE JSON object with two keys: 'key' and 'value'.\n"
    "CRITICAL: The 'key' MUST be a clean canonical attribute name (e.g. 'wife_name', 'user_name', 'grade_10_mark', 'ceo_tamil_nadu', 'vijay_role').\n"
    "NEVER append action words like '_update', '_change', '_correction', or '_error' to the key name.\n"
    "DO NOT use keys like 'context', 'name', 'details', or 'instruction'. ONLY use 'key' and 'value'.\n\n"
    "Schema:\n"
    "{\"key\": \"short_snake_case_name\", \"value\": \"the exact updated fact or preference\"}\n\n"
    "Examples:\n"
    "1. Query: 'upgrade wife name from julie to angle'\n"
    "   JSON: {\"key\": \"wife_name\", \"value\": \"angle\"}\n"
    "2. Query: 'sorry, my name is not arun can you upgrad into vijay'\n"
    "   JSON: {\"key\": \"user_name\", \"value\": \"vijay\"}\n"
    "3. Query: 'sorry, my 10th mark is not 70% it is 86%, please upgrade'\n"
    "   JSON: {\"key\": \"grade_10_mark\", \"value\": \"86%\"}\n"
    "4. Query: 'I prefer using PostgreSQL over MongoDB'\n"
    "   JSON: {\"key\": \"database_preference\", \"value\": \"PostgreSQL over MongoDB\"}\n"
    "5. Query: 'i need full detail about this company pincode 110025'\n"
    "   JSON: {}\n"
    "6. Query: 'please remember vijay is Chief Executive Officer of Tamil Nadu'\n"
    "   JSON: {\"key\": \"ceo_tamil_nadu\", \"value\": \"vijay\"}\n\n"
    "Return ONLY valid JSON. No explanations, no markdown block syntax."
)


def _dynamic_fallback_extraction(query: str) -> Optional[Dict[str, str]]:
    """
    Dynamic regex parser handling phrases like:
    'upgrad into vijay', 'change my name to vijay', 'my score is 90%'
    """
    match = _DYNAMIC_FACT_PATTERN.search(query.strip())
    if not match:
        return None
    key = match.group("key").strip().lower().replace(" ", "_").replace("-", "_")
    value = match.group("value").strip()
    key = re.sub(r"[^a-z0-9_]", "", key)
    
    if not key or not value:
        return None
    return {"key": key, "value": value}


# ============================================================================
# Memory Deletion Handlers
# ============================================================================
async def handle_memory_deletion(payload: MemorySaveRequest) -> str:
    query_lower = payload.query.lower()
    
    # CASE A: Full Conversation / Session Deletion (Agent-scoped)
    if "conversation" in query_lower or "chat" in query_lower or "history" in query_lower or "session" in query_lower:
        logger.info(f"[DELETE] Purging session history for agent_id={payload.agent_id}, session_id={payload.session_id}")
        
        # 1. Purge Relational Episodic Memory
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(EpisodicMemory).filter(
                    EpisodicMemory.tenant_id == payload.tenant_id,
                    EpisodicMemory.user_id == payload.user_id,
                    EpisodicMemory.agent_id == payload.agent_id,
                    EpisodicMemory.session_id == payload.session_id
                )
            )
            await db.commit()

        # 2. Purge Agent-Scoped Session Nodes in Neo4j
        cypher_delete_session = """
        MATCH (s:Session {id: $session_id, tenant_id: $tenant_id, agent_id: $agent_id})
        OPTIONAL MATCH (s)-[r:CONTAINS_FACT]->(m:MemoryEntity)
        DETACH DELETE s, m
        """
        try:
            async with neo4j_driver.session() as session:
                await session.run(
                    cypher_delete_session, 
                    session_id=payload.session_id, 
                    tenant_id=payload.tenant_id, 
                    agent_id=payload.agent_id
                )
        except Exception as e:
            logger.error(f"[DELETE ERROR] Neo4j session purge failed: {e}")

        return f"Successfully deleted chat session {payload.session_id}."

    # CASE B: Targeted Fact / Preference Deletion (Agent-scoped)
    extracted_raw = await run_llm_completion(
        "Extract the exact concept, entity, or preference key to delete. Return JSON: {\"key\": \"concept_name\"}", 
        payload.query, 
        priority="background"
    )
    data = _extract_json_block(extracted_raw) or {}
    key_to_delete = str(data.get("key") or "").strip().lower().replace(" ", "_")
    if not key_to_delete:
        key_to_delete = payload.query.lower().replace("delete", "").replace("forget", "").strip().replace(" ", "_")

    if key_to_delete:
        logger.info(f"[DELETE] Deleting key='{key_to_delete}' for agent_id={payload.agent_id}")
        
        # 1. Delete from UserPreference DB
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(UserPreference).filter(
                    UserPreference.tenant_id == payload.tenant_id,
                    UserPreference.user_id == payload.user_id,
                    UserPreference.agent_id == payload.agent_id,
                    UserPreference.preference_key.ilike(f"%{key_to_delete}%")
                )
            )
            await db.commit()

        # 2. Detach/Delete Agent-Scoped Graph Entity Nodes in Neo4j
        cypher_delete_entity = """
        MATCH (m:MemoryEntity {tenant_id: $tenant_id, user_id: $user_id, agent_id: $agent_id})
        WHERE toLower(m.name) CONTAINS toLower($key)
        DETACH DELETE m
        """
        try:
            async with neo4j_driver.session() as session:
                await session.run(
                    cypher_delete_entity, 
                    tenant_id=payload.tenant_id, 
                    user_id=payload.user_id, 
                    agent_id=payload.agent_id, 
                    key=key_to_delete
                )
        except Exception as e:
            logger.error(f"[DELETE ERROR] Neo4j entity delete failed: {e}")

        return f"Successfully deleted '{key_to_delete}' from long-term memory."

    return "Memory deletion request processed."


async def save_user_preference(payload: MemorySaveRequest):
    if _is_delete_statement(payload.query):
        msg = await handle_memory_deletion(payload)
        logger.info(f"Memory Deletion completed: {msg}")
        return

    extracted_raw = await run_llm_completion(
        PREFERENCE_EXTRACTION_PROMPT, payload.query, priority="background"
    )
    data = _extract_json_block(extracted_raw) or {}
    
    # Universal Key Normalization for generic JSON structure mapping
    key = str(data.get("key") or data.get("field") or data.get("preference") or "").strip().lower().replace(" ", "_")
    value = str(data.get("value") or data.get("name") or data.get("fact") or "").strip()

    # Dynamic Fallback: Check regex if LLM extraction returned empty or failed
    if not key or not value:
        fallback = _dynamic_fallback_extraction(payload.query)
        if fallback:
            key, value = fallback["key"], fallback["value"]

    # Strip action suffixes like _update, _change, _correction, _modification
    for suffix in ["_update", "_change", "_correction", "_modification", "_error"]:
        if key.endswith(suffix):
            key = key[:-len(suffix)]

    # Special heuristic normalization for common entities
    query_lower = payload.query.lower()
    if "wife" in query_lower and ("wife" in key or key in ["name", "user_name"]):
        key = "wife_name"
    elif "name" in query_lower and not key:
        key = "user_name"

    if not key or not value:
        logger.error(
            f"Preference extraction FAILED for user={payload.user_id} "
            f"query={payload.query!r} — nothing was persisted."
        )
        return

    # Upsert into UserPreference with Smart Subject Matching (Overwrites older conflicting values)
    async with AsyncSessionLocal() as db:
        stmt = select(UserPreference).filter(
            UserPreference.tenant_id == payload.tenant_id,
            UserPreference.user_id == payload.user_id,
            UserPreference.agent_id == payload.agent_id,
        )
        result = await db.execute(stmt)
        all_prefs = result.scalars().all()

        existing = None
        for p in all_prefs:
            pk = p.preference_key.lower()
            if pk == key:
                existing = p
                break
            # Smart overlap detection (e.g., wife_name matches name_update or wife)
            if ("wife" in pk and "wife" in key) or ("mark" in pk and "mark" in key and (("10" in pk and "10" in key) or ("12" in pk and "12" in key))):
                existing = p
                break

        if existing:
            existing.preference_key = key
            existing.preference_value = value
            existing.raw_statement = payload.query
            existing.updated_at = datetime.now(timezone.utc)
            logger.info(f"Successfully UPDATED user preference: {key} = {value} (replaced key '{existing.preference_key}')")
        else:
            db.add(UserPreference(
                tenant_id=payload.tenant_id,
                user_id=payload.user_id,
                agent_id=payload.agent_id,
                preference_key=key,
                preference_value=value,
                raw_statement=payload.query,
            ))
            logger.info(f"Successfully INSERTED new user preference: {key} = {value}")
        await db.commit()

    # Also push preference triplet into Neo4j Knowledge Graph for hybrid graph search!
    try:
        subject_name = key.replace("_", " ")
        triplet_payload = json.dumps({
            "triplets": [
                {"subject": subject_name, "relation": "HAS_VALUE", "object": value},
                {"subject": "user", "relation": f"HAS_{key.upper()}", "object": value}
            ]
        })
        await push_triplets_to_isolated_graph(
            payload.tenant_id, payload.user_id, payload.agent_id, payload.session_id, triplet_payload
        )
    except Exception as ge:
        logger.error(f"[NEO4J PREFERENCE PUSH ERROR] Failed to push preference to graph: {ge}")


async def get_user_preferences(tenant_id: str, user_id: str, agent_id: str) -> List[Dict]:
    async with AsyncSessionLocal() as db:
        stmt = select(UserPreference).filter(
            UserPreference.tenant_id == tenant_id,
            UserPreference.user_id == user_id,
            UserPreference.agent_id == agent_id,
        )
        result = await db.execute(stmt)
        prefs = result.scalars().all()
        return [{"key": p.preference_key, "value": p.preference_value} for p in prefs]


# ============================================================================
# Neo4j Graph Helpers with Detach/Delete Support
# ============================================================================
async def push_triplets_to_isolated_graph(
    tenant_id: str, user_id: str, agent_id: str, session_id: str, triplets_json: str
):
    logger.info(f"[NEO4J WRITE START] Session: {session_id} | Parsing raw triplet payload...")
    triplets = _parse_and_normalize_triplets(triplets_json)
    
    if not triplets:
        logger.warning(f"[NEO4J WRITE SKIPPED] No valid triplets extracted for session {session_id}. Payload: {triplets_json!r}")
        return

    mapped_triplets = await map_to_ontology(triplets)
    logger.info(f"[NEO4J WRITE EXECUTING] session_id={session_id} | Valid Triplets to insert ({len(mapped_triplets)}): {mapped_triplets}")

    # Cypher syntax with complete agent-level isolation
    query = """
    MERGE (t:Tenant {id: $tenant_id})
    MERGE (u:User {id: $user_id, tenant_id: $tenant_id})
    MERGE (a:Agent {id: $agent_id, tenant_id: $tenant_id})
    MERGE (s:Session {id: $session_id, tenant_id: $tenant_id, agent_id: $agent_id})
    
    MERGE (u)-[:BELONGS_TO]->(t)
    MERGE (u)-[:HAS_SESSION]->(s)
    MERGE (s)-[:MANAGED_BY]->(a)
    
    WITH s
    UNWIND $triplets AS trip
    MERGE (sub:MemoryEntity {name: trip.subject, tenant_id: $tenant_id, user_id: $user_id, agent_id: $agent_id})
    MERGE (s)-[:CONTAINS_FACT]->(sub)
    
    WITH s, sub, trip
    OPTIONAL MATCH (sub)-[oldRel]->(oldObj:MemoryEntity {tenant_id: $tenant_id, user_id: $user_id, agent_id: $agent_id})
    WHERE type(oldRel) = trip.relation AND oldObj.name <> trip.object
    DETACH DELETE oldObj
    
    WITH s, sub, trip
    MERGE (obj:MemoryEntity {name: trip.object, tenant_id: $tenant_id, user_id: $user_id, agent_id: $agent_id})
    
    WITH s, sub, obj, trip
    CALL apoc.create.addLabels(sub, [trip.subject_type]) YIELD node AS subNode
    CALL apoc.create.addLabels(obj, [trip.object_type]) YIELD node AS objNode
    
    WITH subNode AS sub, objNode AS obj, trip
    CALL apoc.create.relationship(sub, trip.relation, {}, obj) YIELD rel
    RETURN count(rel)
    """
    
    try:
        async with neo4j_driver.session() as neo_session:
            await neo_session.run(
                query,
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                triplets=mapped_triplets
            )
        logger.info(f"[NEO4J WRITE SUCCESS] Created/Updated {len(mapped_triplets)} mapped relationships in Neo4j for session_id={session_id}")
    except Exception as e:
        logger.error(f"[NEO4J WRITE ERROR] Failed to push triplets to Neo4j for session_id={session_id}: {e}", exc_info=True)


async def query_session_history_graph(tenant_id: str, user_id: str, agent_id: str, session_id: str) -> List[str]:
    cypher_query = """
    MATCH (s:Session {id: $session_id, tenant_id: $tenant_id, agent_id: $agent_id})-[r:CONTAINS_FACT]->(sub:MemoryEntity)-[rel]->(obj:MemoryEntity)
    RETURN sub.name + ' ' + type(rel) + ' ' + obj.name AS fact
    LIMIT 15
    """
    try:
        async with neo4j_driver.session() as session:
            result = await session.run(
                cypher_query, 
                tenant_id=tenant_id, 
                user_id=user_id, 
                agent_id=agent_id, 
                session_id=session_id
            )
            return [record["fact"] async for record in result]
    except Exception as e:
        logger.error(f"[NEO4J SEARCH ERROR] Session recall query failed: {e}", exc_info=True)
        return []


async def _query_graph_relations(tenant_id: str, user_id: str, agent_id: str, concepts: List[str]) -> List[str]:
    if not concepts:
        return []

    logger.info(f"[NEO4J CONCEPT SEARCH] Searching graph relations for agent={agent_id}, concepts: {concepts}")

    graph_query = """
    UNWIND $concepts AS concept
    MATCH (s:MemoryEntity {tenant_id: $tenant_id, user_id: $user_id, agent_id: $agent_id})-[r]->(o:MemoryEntity {tenant_id: $tenant_id, user_id: $user_id, agent_id: $agent_id})
    WHERE toLower(s.name) CONTAINS toLower(concept) 
       OR toLower(o.name) CONTAINS toLower(concept)
       OR toLower(concept) CONTAINS toLower(s.name)
    RETURN DISTINCT s.name + ' ' + type(r) + ' ' + o.name AS relationship_str
    LIMIT 10
    """
    try:
        async with neo4j_driver.session() as session:
            result = await session.run(
                graph_query, tenant_id=tenant_id, user_id=user_id, agent_id=agent_id, concepts=concepts
            )
            relationships = [record["relationship_str"] async for record in result]
            logger.info(f"[NEO4J CONCEPT SEARCH RESULT] Retrieved {len(relationships)} matching entity relationships.")
            return relationships
    except Exception as ge:
        logger.error(f"[NEO4J CONCEPT SEARCH ERROR] Failed reading graph relations: {ge}", exc_info=True)
        return []


@app.on_event("startup")
async def startup_event():
    logger.info("[STARTUP] Initializing Relational DB schemas...")
    await init_db()
    logger.info("[STARTUP] Memory Core API ready.") 


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("[SHUTDOWN] Closing Neo4j Driver Connection...")
    await neo4j_driver.close()
    logger.info("[SHUTDOWN] Neo4j Driver closed successfully.")


# ============================================================================
# API ENDPOINTS
# ============================================================================
@app.post("/api/v1/memory/process-turn")
async def process_turn(payload: MemoryProcessRequest):
    if _is_delete_statement(payload.query):
        is_feedback_only = True
    else:
        triage_prompt = (
            "You are a precise agent memory router. Analyze the user's message and categorize it.\n\n"
            "Reply with EXACTLY 'FEEDBACK_ONLY' if the user's message is doing one of the following:\n"
            "1. Stating a personal fact, instruction, preference, or rule for you to remember (e.g., 'remember that I am a developer', 'from now on, use python', 'always reply in markdown').\n"
            "2. Providing corrective feedback or adjustments to your behavior.\n"
            "3. Giving a simple conversational acknowledgement or greeting/closing that does not ask for information (e.g., 'got it', 'thanks', 'ok', 'good job').\n"
            "4. Requesting to delete, forget, or clear memories (e.g., 'forget my name').\n\n"
            "Reply with EXACTLY 'NORMAL_QUERY' if the user's message is:\n"
            "1. Asking a question, requesting information, or looking up facts about the organization, database, documents, or team members (e.g., 'who is CCO', 'tell me about Arun', 'who is CEO', 'what is the capital of France').\n"
            "2. Directing you to analyze data, search documents, or extract records.\n"
            "3. Stating a short keyword, search term, ID, serial number, or code (e.g., 'SL.NO 5402', '5402', 'ID-203', 'invoice').\n\n"
            "CRITICAL: If the message is a question, search query, serial number, ID, code, or generic keyword (even if it is extremely short or lacks grammar/question words), you MUST output 'NORMAL_QUERY'.\n"
            "Output ONLY the category name ('FEEDBACK_ONLY' or 'NORMAL_QUERY') with no other text, explanation, or quotes."
        )
        triage_decision = await run_llm_completion(triage_prompt, payload.query, priority="live")
        is_feedback_only = "FEEDBACK_ONLY" in triage_decision

    if is_feedback_only:
        return {
            "session_id": payload.session_id,
            "is_feedback_only": True,
            "is_history_query": False,
            "guidance_context": "",
            "status": "success"
        }

    is_history_query = bool(HISTORY_QUERY_PATTERN.search(payload.query))
    guidance_blocks = []
    graph_context_elements = []

    if is_history_query:
        async with AsyncSessionLocal() as db:
            query_stmt = (
                select(EpisodicMemory.summarization)
                .filter(
                    EpisodicMemory.tenant_id == payload.tenant_id,
                    EpisodicMemory.user_id == payload.user_id,
                    EpisodicMemory.agent_id == payload.agent_id
                )
                .order_by(EpisodicMemory.created_at.desc())
                .limit(5)
            )
            result = await db.execute(query_stmt)
            matched = result.scalars().all()
            guidance_blocks = list(reversed([s for s in matched if s]))

        graph_context_elements = await query_session_history_graph(
            payload.tenant_id, payload.user_id, payload.agent_id, payload.session_id
        )

    else:
        query_embedding = await get_embedding(payload.query, priority="live")
        async with AsyncSessionLocal() as db:
            query_stmt = (
                select(EpisodicMemory.summarization)
                .filter(
                    EpisodicMemory.tenant_id == payload.tenant_id,
                    EpisodicMemory.user_id == payload.user_id,
                    EpisodicMemory.agent_id == payload.agent_id
                )
                .order_by(EpisodicMemory.summary_vector.cosine_distance(query_embedding))
                .limit(4)
            )
            result = await db.execute(query_stmt)
            guidance_blocks = [s for s in result.scalars().all() if s]

        entity_extraction_prompt = (
            "You are a strict data parsing tool. Extract named entities, key concepts, or topics "
            "from the user query. Do NOT answer the question. Do NOT chat. "
            "Return ONLY a JSON object: {\"entities\": [\"entity1\", \"entity2\"]}\n"
            "Example Query: 'what is my 10th grade mark?' -> JSON: {\"entities\": [\"10th grade mark\", \"10th grade\", \"mark\"]}"
        )
        entities_raw = await run_llm_completion(entity_extraction_prompt, payload.query, priority="live")
        entity_names = _extract_entity_names(entities_raw)

        if entity_names:
            graph_context_elements = await _query_graph_relations(
                payload.tenant_id, payload.user_id, payload.agent_id, entity_names
            )

    # COMPOUND QUERY SUPPORT: If user is updating a preference AND asking a question in the same turn,
    # save the preference immediately so it's included in guidance_context for this turn!
    if _PREFERENCE_PATTERNS.search(payload.query):
        try:
            logger.info(f"[COMPOUND QUERY] Extracting and saving preference immediately for turn query: {payload.query!r}")
            save_req = MemorySaveRequest(
                query=payload.query,
                ai_response="",
                session_id=payload.session_id,
                agent_id=payload.agent_id,
                user_id=payload.user_id,
                tenant_id=payload.tenant_id
            )
            await save_user_preference(save_req)
        except Exception as pe:
            logger.error(f"[COMPOUND QUERY PREFERENCE ERROR] Failed inline preference update: {pe}")

    preferences = await get_user_preferences(payload.tenant_id, payload.user_id, payload.agent_id)

    guidance_context = ""
    if preferences or guidance_blocks or graph_context_elements:
        guidance_context = "## PERSISTENT EPISODIC & USER PREFERENCE CONTEXT\n"
        if preferences:
            guidance_context += "### Stored User Profile & Preferences (Active Overrides):\n" + \
                "\n".join([f"- {p['key']}: {p['value']}" for p in preferences]) + "\n"
        if guidance_blocks:
            guidance_context += "### Historic Conversation Summaries:\n" + \
                "\n".join([f"- {s}" for s in guidance_blocks]) + "\n"
        if graph_context_elements:
            guidance_context += "### Knowledge Graph Facts:\n" + \
                "\n".join([f"- {g}" for g in graph_context_elements])

    return {
        "session_id": payload.session_id,
        "is_feedback_only": False,
        "is_history_query": is_history_query,
        "guidance_context": guidance_context,
        "status": "success"
    }


@app.post("/api/v1/memory/save-turn")
async def save_turn(payload: MemorySaveRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(async_ingest_turn, payload)
    return {"status": "queued"}


async def async_ingest_turn(payload: MemorySaveRequest):
    if payload.is_feedback_only or _is_delete_statement(payload.query):
        await save_user_preference(payload)
        return

    user_interaction = f"User: {payload.query}\nAssistant: {payload.ai_response}"
    
    # Check if the AI response indicates a failure to find information or missing data
    negative_indicators = [
        "couldn't find", "could not find", "don't know", "do not know",
        "no mention", "no information", "not present in dataset",
        "not found", "unable to find", "no matching record",
        "does not exist", "unanswered",
        "don't have any specific information", "don’t have any specific information"
    ]
    ai_resp_lower = payload.ai_response.lower()
    if any(indicator in ai_resp_lower for indicator in negative_indicators):
        logger.info(f"[INGEST BYPASS] Skipping memory storage because AI response indicates info is missing or not found: {payload.ai_response!r}")
        return

    combined_prompt = (
        "Analyze this conversation turn and produce BOTH of the following in ONE JSON response:\n\n"
        "1. SUMMARY: Compress the interaction into a single concise, factual declarative statement. "
        "Explicitly include the specific topic, entities, numbers, and answers discussed. "
        "Example: 'User asked about their serial number; Assistant confirmed serial number 23-4583.' "
        "CRITICAL: Do NOT use placeholder letters like X or Y. Always write out the real topics, parameters, and details.\n\n"
        "2. TRIPLETS: Extract concrete knowledge triplets. Modify entity subject descriptors dynamically so sub-categories stay attached "
        "(e.g., use '10th grade mark' as the subject rather than generic 'user').\n"
        "STRICT RULES for triplets:\n"
        "- Do NOT create triplets for negative, missing, or empty information (e.g. 'none', 'unknown', 'not present').\n"
        "- Replace personal pronouns ('I', 'me', 'my') with 'user' or the specific dynamic subject entity.\n"
        "- Relation must be UPPER_SNAKE_CASE (e.g. HAS_VALUE, HAS_SCORE, IS_NAMED).\n\n"
        "Return strict JSON only:\n"
        '{"summary": "User asked X; Answer was Y.", '
        '"triplets": [{"subject": "10th grade mark", "relation": "HAS_VALUE", "object": "90%"}]}\n\n'
        f"CONVERSATION:\n{user_interaction}"
    )
    combined_raw = await run_llm_completion(
        "You are a strict extraction system. Return ONLY valid JSON.",
        combined_prompt,
        priority="background",
    )
    combined_data = _extract_json_block(combined_raw) or {}

    summary_text = str(combined_data.get("summary", "")).strip()
    if not summary_text:
        summary_text = f"User interacted regarding: {payload.query[:50]}"

    raw_vector = await get_embedding(f"{payload.query} {payload.ai_response}", priority="background")
    summary_vector = await get_embedding(summary_text, priority="background")

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

    triplets_json = json.dumps({"triplets": combined_data.get("triplets", [])})
    await push_triplets_to_isolated_graph(
        payload.tenant_id, payload.user_id, payload.agent_id, payload.session_id, triplets_json
    )