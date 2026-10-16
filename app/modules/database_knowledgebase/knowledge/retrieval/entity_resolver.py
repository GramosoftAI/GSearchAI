import asyncio
import uuid
import re
import time
import logging
from typing import Optional, List, Dict, Any, Set, Tuple
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from ..models.knowledge_items import KB2EntityValue, KB2KnowledgeItem, KB2SchemaDoc
from ..sensitivity import is_sensitive_column
from .analyzer import QuestionFrame

logger = logging.getLogger(__name__)

# Exclusion set cache per KB: (cache_time, set_of_tokens)
_EXCLUSION_CACHE: Dict[uuid.UUID, Tuple[float, Set[str]]] = {}
_CACHE_TTL_SECONDS = 3600.0


def normalize_table_name(table_name: str) -> str:
    """Normalize table name by stripping schema prefix (e.g. 'public.users' -> 'users')."""
    if not table_name:
        return ""
    return table_name.split(".")[-1].strip().lower()


def get_table_name_variants(table_name: str) -> List[str]:
    """Get stripped and public-prefixed variants for table matching in kb2_entity_values."""
    norm = normalize_table_name(table_name)
    if not norm:
        return []
    return [norm, f"public.{norm}"]


GENERIC_STOP_WORDS: Set[str] = {
    # Questions & modals
    "how", "many", "much", "what", "which", "who", "whom", "whose", "where", "when", "why",
    "can", "could", "would", "should", "will", "shall", "may", "might", "must", "need", "dare",
    "do", "does", "did", "doing", "done",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having",
    # Action / query verbs
    "tell", "show", "give", "list", "find", "get", "got", "see", "check", "view", "fetch",
    "search", "display", "count", "sum", "total", "average", "avg", "min", "max",
    "held", "hold", "holds", "holding", "meet", "meeting", "meetings",
    "work", "worked", "working", "log", "logged", "logging", "spend", "spent", "spending",
    # Temporal
    "yesterday", "yesterdays", "today", "todays", "tomorrow", "tomorrows",
    "day", "days", "week", "weeks", "month", "months", "year", "years",
    "date", "dates", "time", "times", "hour", "hours", "minute", "minutes", "second", "seconds",
    "morning", "afternoon", "evening", "night",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
    "ago", "since", "until", "before", "after", "during", "recent", "recently", "latest", "earliest", "past", "last", "next",
    # Prepositions & articles
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "about", "into", "through", "over", "under", "between", "above", "below", "out", "off", "up", "down",
    # Conjunctions & logic
    "and", "or", "not", "no", "nor", "but", "if", "then", "else", "so", "than", "neither", "either",
    # Pronouns
    "i", "me", "my", "mine", "you", "your", "yours", "he", "him", "his", "she", "her", "hers",
    "it", "its", "we", "us", "our", "ours", "they", "them", "their", "theirs",
    "this", "that", "these", "those",
    # Quantifiers / adverbs
    "all", "any", "some", "every", "each", "both", "few", "more", "most", "less", "least", "several",
    "only", "just", "also", "very", "too", "quite", "really", "already",
    # Common domain status/words
    "active", "inactive", "status", "type", "state", "open", "closed", "pending", "completed",
    "long", "duration",
}

LABEL_LIKE_COLUMNS: Set[str] = {
    "name", "firstname", "first_name", "lastname", "last_name", "fullname", "full_name",
    "login", "username", "user_name", "title", "subject", "identifier", "label", "display_name",
}

TECHNICAL_COLUMNS: Set[str] = {
    "type", "status", "key", "filename", "workspace_type", "journable_type",
    "content_type", "state", "concurrency_key", "data_type", "action",
    "created_at", "updated_at", "id", "options", "digest", "salt",
    "email", "mail", "mail_notification", "notification_email",
}

_TABLE_KINDS_CACHE: Dict[uuid.UUID, Tuple[float, Dict[str, str]]] = {}


async def get_kb_table_kinds(session: AsyncSession, kb_id: uuid.UUID) -> Dict[str, str]:
    """Fetch and cache table kinds (entity, lookup, link, journal, system) for a KB."""
    now = time.monotonic()
    if kb_id in _TABLE_KINDS_CACHE:
        cached_time, cached_kinds = _TABLE_KINDS_CACHE[kb_id]
        if now - cached_time < _CACHE_TTL_SECONDS:
            return cached_kinds

    kinds: Dict[str, str] = {}
    try:
        stmt = select(KB2KnowledgeItem.item_key, KB2KnowledgeItem.payload).where(
            KB2KnowledgeItem.db_knowledgebase_id == kb_id,
            KB2KnowledgeItem.item_type == "table",
        )
        res = await session.execute(stmt)
        for item_key, payload in res.all():
            payload = payload or {}
            t_name = normalize_table_name(payload.get("table_name") or item_key)
            k = (payload.get("kind") or (payload.get("semantic") or {}).get("kind") or "entity").lower().strip()
            kinds[t_name] = k
    except Exception as e:
        logger.debug(f"[EntityResolution] Could not load table kinds: {e}")

    _TABLE_KINDS_CACHE[kb_id] = (now, kinds)
    return kinds


def is_label_like_column(
    table_name: str,
    column_name: str,
    table_kinds: Optional[Dict[str, str]] = None,
) -> bool:
    """Accept matches only from label-like columns of entity/lookup tables.
    
    Gates by stored table kind (only entity and lookup kinds).
    Ignores enum-like technical columns and email/mail patterns.
    """
    t_clean = normalize_table_name(table_name)
    if table_kinds is not None:
        t_kind = table_kinds.get(t_clean)
        # Gate by the table's stored kind: only entity and lookup kinds allowed
        if t_kind is not None and t_kind not in ("entity", "lookup"):
            return False

    c_low = column_name.lower().strip()
    if (
        c_low in TECHNICAL_COLUMNS
        or c_low.endswith(("_type", "_status", "_key", "_id", "_ids", "_email", "_mail"))
        or "email" in c_low
        or "mail" in c_low
    ):
        return False

    if c_low in LABEL_LIKE_COLUMNS:
        return True
    return bool(re.search(r"\b(name|login|title|subject|identifier|label|display_name)\b", c_low))


async def build_kb_exclusion_set(
    session: AsyncSession,
    kb_id: uuid.UUID,
    tenant_id: Optional[uuid.UUID] = None,
    canonical_schema: Optional[Any] = None,
) -> Set[str]:
    """Build the exclusion set per KB from its own metadata plus generic stop words."""
    now = time.monotonic()
    if kb_id in _EXCLUSION_CACHE:
        cached_time, cached_set = _EXCLUSION_CACHE[kb_id]
        if now - cached_time < _CACHE_TTL_SECONDS:
            return cached_set

    exclusions = set(GENERIC_STOP_WORDS)

    # 1. Schema tables and columns from canonical_schema if provided
    if canonical_schema:
        if hasattr(canonical_schema, "schemas") and isinstance(canonical_schema.schemas, dict):
            for s in canonical_schema.schemas.values():
                for t_name, t_schema in getattr(s, "tables", {}).items():
                    exclusions.add(t_name.lower())
                    for part in re.split(r'[_.\s]+', t_name):
                        if len(part) >= 2:
                            exclusions.add(part.lower())
                    for c_name in getattr(t_schema, "columns", {}).keys():
                        exclusions.add(c_name.lower())
                        for part in re.split(r'[_.\s]+', c_name):
                            if len(part) >= 2:
                                exclusions.add(part.lower())
        elif hasattr(canonical_schema, "all_tables"):
            for t in canonical_schema.all_tables:
                t_name = getattr(t, "table_name", "")
                if t_name:
                    exclusions.add(t_name.lower())
                    for part in re.split(r'[_.\s]+', t_name):
                        if len(part) >= 2:
                            exclusions.add(part.lower())
                for c_name in getattr(t, "columns", {}).keys():
                    exclusions.add(c_name.lower())
                    for part in re.split(r'[_.\s]+', c_name):
                        if len(part) >= 2:
                            exclusions.add(part.lower())

    # 2. Fetch schema docs for tables and columns from local DB
    try:
        stmt_sd = select(KB2SchemaDoc.item_key, KB2SchemaDoc.title).where(
            KB2SchemaDoc.db_knowledgebase_id == kb_id,
        )
        if tenant_id:
            stmt_sd = stmt_sd.where(KB2SchemaDoc.tenant_id == tenant_id)
        res_sd = await session.execute(stmt_sd)
        for ik, title in res_sd.all():
            for part in re.split(r'[_.\s]+', (ik or "").lower()):
                if len(part) >= 2:
                    exclusions.add(part)
            for part in re.split(r'[_.\s]+', (title or "").lower()):
                if len(part) >= 2:
                    exclusions.add(part)
    except Exception as exc:
        logger.debug(f"[EntityResolution] Could not load schema docs for exclusion: {exc}")

    # 3. Fetch glossary terms from local DB
    try:
        stmt_gl = select(KB2KnowledgeItem.payload).where(
            KB2KnowledgeItem.db_knowledgebase_id == kb_id,
            KB2KnowledgeItem.item_type == "glossary",
        )
        if tenant_id:
            stmt_gl = stmt_gl.where(KB2KnowledgeItem.tenant_id == tenant_id)
        res_gl = await session.execute(stmt_gl)
        for (p,) in res_gl.all():
            if isinstance(p, dict):
                term = p.get("term", "")
                for part in re.split(r'[_.\s]+', term.lower()):
                    if len(part) >= 2:
                        exclusions.add(part)
                for a in p.get("aliases", []):
                    for part in re.split(r'[_.\s]+', str(a).lower()):
                        if len(part) >= 2:
                            exclusions.add(part)
    except Exception as exc:
        logger.debug(f"[EntityResolution] Could not load glossary for exclusion: {exc}")

    _EXCLUSION_CACHE[kb_id] = (now, exclusions)
    return exclusions


def extract_candidate_spans(question: str, exclusion_set: Set[str]) -> List[str]:
    """Candidate spans = tokens/phrases (max 3 words, max 4 spans per question) containing at least one non-excluded token."""
    spans: List[str] = []

    # 1. Quoted strings from user
    quoted = re.findall(r'["\']([^"\']{2,})["\']', question)
    for q in quoted:
        q_clean = q.strip()
        if q_clean and q_clean not in spans:
            spans.append(q_clean)

    # 2. Extract words
    tokens = re.findall(r"\b[a-zA-Z0-9_-]+\b", question)
    non_excluded = [t for t in tokens if t.lower() not in exclusion_set and len(t) >= 2]

    if not non_excluded:
        return spans[:4]

    # Contiguous sequences of non-excluded tokens
    i = 0
    while i < len(tokens):
        if tokens[i].lower() not in exclusion_set and len(tokens[i]) >= 2:
            chunk = [tokens[i]]
            j = i + 1
            while j < len(tokens) and j < i + 3:
                t_next = tokens[j]
                if t_next.lower() not in exclusion_set or len(t_next) <= 2:
                    chunk.append(t_next)
                    j += 1
                else:
                    break
            phrase = " ".join(chunk).strip()
            if phrase not in spans:
                spans.append(phrase)
            if tokens[i] not in spans and len(chunk) > 1:
                spans.append(tokens[i])
            i = j
        else:
            i += 1

    return spans[:4]


class DisambiguationChoice(BaseModel):
    pk_value: Any = None
    display_label: str
    row_data: Dict[str, Any] = Field(default_factory=dict)


class ResolvedEntity(BaseModel):
    table_name: str
    column_name: str
    matched_value: str
    pk_column: str = "id"
    pk_value: Optional[Any] = None
    ambiguous: bool = False
    choices: List[DisambiguationChoice] = Field(default_factory=list)
    match_type: str = "exact"  # exact, trigram
    similarity: float = 1.0
    confidence: float = 1.0


class LiteralFilter(BaseModel):
    literal_value: str
    literal_type: str  # quoted, email, phone, number
    candidate_columns: List[str] = Field(default_factory=list)


class EntityResolutionResult(BaseModel):
    resolved_entities: List[ResolvedEntity] = Field(default_factory=list)
    literal_filters: List[LiteralFilter] = Field(default_factory=list)
    unanswerable: bool = False
    unanswerable_reason: Optional[str] = None
    timings_ms: float = 0.0
    queries_count: int = 0
    spans_tried: List[str] = Field(default_factory=list)


async def resolve_entities(
    question: str,
    kb_id: uuid.UUID | str,
    session: Optional[AsyncSession] = None,
    canonical_schema: Optional[Any] = None,
    tenant_id: Optional[uuid.UUID | str] = None,
    timeout_ms: int = 300,
) -> EntityResolutionResult:
    """
    Unified, single query-path entity resolution function.
    
    Invariants:
    1. Resolves against local kb2_entity_values ONLY. Zero customer-DB connections.
    2. Span gating: candidate spans extracted using per-KB exclusion set.
    3. One batched query for all spans (exact, then trigram fallback only if nothing exact).
    4. Match scope: label-like columns of entity/lookup tables only.
    5. Table names normalized (stripped of schema prefixes).
    6. Group duplicates, returning top candidates into <grounded_context>.
    """
    t0 = time.perf_counter()
    kb_uuid = uuid.UUID(str(kb_id)) if isinstance(kb_id, str) else kb_id
    tenant_uuid = uuid.UUID(str(tenant_id)) if tenant_id and isinstance(tenant_id, str) else tenant_id

    # Check sensitive columns for unanswerable guard
    raw_tokens = re.findall(r"\b[a-zA-Z0-9_]+\b", question.lower())
    for tok in raw_tokens:
        if is_sensitive_column(tok) or tok in ("salary", "password", "hash", "secret", "cvv", "token"):
            return EntityResolutionResult(
                unanswerable=True,
                unanswerable_reason=f"Question asks for restricted sensitive/protected field '{tok}'. Access denied.",
                timings_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            )

    # Acquire session if not passed
    close_session = False
    target_session = session
    if target_session is None:
        from app.core.database import AsyncSessionLocal
        target_session = AsyncSessionLocal()
        close_session = True

    queries_count = 0
    try:
        # Build exclusion set and extract spans
        exclusion_set = await build_kb_exclusion_set(
            session=target_session,
            kb_id=kb_uuid,
            tenant_id=tenant_uuid,
            canonical_schema=canonical_schema,
        )
        spans = extract_candidate_spans(question, exclusion_set)

        # Quoted literals extracted for LiteralFilter
        quoted_literals = [
            LiteralFilter(literal_value=q.strip(), literal_type="quoted")
            for q in re.findall(r'["\']([^"\']{2,})["\']', question)
            if q.strip()
        ]

        if not spans:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.info(
                f"[EntityResolution] {elapsed_ms:.2f} ms | spans tried: [] | matches found: 0 | queries executed: 0"
            )
            return EntityResolutionResult(
                resolved_entities=[],
                literal_filters=quoted_literals,
                unanswerable=False,
                timings_ms=round(elapsed_ms, 2),
                queries_count=0,
                spans_tried=[],
            )

        norm_spans = [s.lower().strip() for s in spans]
        raw_matches: List[Dict[str, Any]] = []

        # Load table kinds for stored kind gating (entity & lookup only)
        table_kinds = await get_kb_table_kinds(target_session, kb_uuid)

        # 1. Batched Exact Query
        stmt_exact = select(
            KB2EntityValue.table_name,
            KB2EntityValue.column_name,
            KB2EntityValue.raw_value,
            KB2EntityValue.normalized_value,
            KB2EntityValue.frequency_count,
        ).where(
            KB2EntityValue.db_knowledgebase_id == kb_uuid,
            KB2EntityValue.normalized_value.in_(norm_spans),
        )
        if tenant_uuid:
            stmt_exact = stmt_exact.where(KB2EntityValue.tenant_id == tenant_uuid)

        try:
            queries_count += 1
            res_exact = await asyncio.wait_for(
                target_session.execute(stmt_exact),
                timeout=timeout_ms / 1000.0,
            )
            for r in res_exact.all():
                t_name, c_name, raw_v, norm_v, freq = r
                if is_label_like_column(t_name, c_name, table_kinds=table_kinds):
                    raw_matches.append({
                        "table_name": normalize_table_name(t_name),
                        "column_name": c_name,
                        "matched_value": raw_v,
                        "normalized_value": norm_v,
                        "similarity": 1.0,
                        "match_type": "exact",
                        "frequency": freq or 1,
                    })
        except Exception as exc:
            logger.warning(f"[EntityResolution] Exact query failed: {exc}")

        # 2. Trigram fallback ONLY if nothing exact matches
        if not raw_matches and spans:
            try:
                for span_text in spans[:2]:
                    clean_s = span_text.lower().strip()
                    sql_fuzzy = text("""
                        SELECT table_name, column_name, raw_value, normalized_value,
                                similarity(normalized_value, :q) AS sim
                        FROM kb2_entity_values
                        WHERE db_knowledgebase_id = :kb_id
                          AND normalized_value % :q
                        ORDER BY similarity(normalized_value, :q) DESC
                        LIMIT 5;
                    """)
                    queries_count += 1
                    res_f = await asyncio.wait_for(
                        target_session.execute(sql_fuzzy, {"kb_id": kb_uuid, "q": clean_s}),
                        timeout=timeout_ms / 1000.0,
                    )
                    for r in res_f.fetchall():
                        t_name, c_name, raw_v, norm_v, sim = r[0], r[1], r[2], r[3], float(r[4])
                        if sim >= 0.50 and is_label_like_column(t_name, c_name, table_kinds=table_kinds):
                            raw_matches.append({
                                "table_name": normalize_table_name(t_name),
                                "column_name": c_name,
                                "matched_value": raw_v,
                                "normalized_value": norm_v,
                                "similarity": sim,
                                "match_type": "trigram",
                                "frequency": 1,
                            })
                    if raw_matches:
                        break
            except Exception as exc:
                logger.debug(f"[EntityResolution] Trigram fallback failed: {exc}")

        # 3. Deduplicate and group matches by (table_name, column_name, raw_value)
        unique_matches = []
        seen = set()
        for m in raw_matches:
            k = (m["table_name"], m["column_name"], m["matched_value"].lower())
            if k not in seen:
                seen.add(k)
                unique_matches.append(m)

        # Sort matches by exact match > similarity > frequency
        unique_matches.sort(
            key=lambda x: (x["match_type"] == "exact", x["similarity"], x.get("frequency", 1)),
            reverse=True,
        )

        top_candidates = unique_matches[:3]
        resolved_entities = [
            ResolvedEntity(
                table_name=c["table_name"],
                column_name=c["column_name"],
                matched_value=c["matched_value"],
                pk_column="id",
                pk_value=None,  # No live ID lookup on query path
                ambiguous=False,
                match_type=c["match_type"],
                similarity=c["similarity"],
                confidence=c["similarity"],
            )
            for c in top_candidates
        ]

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        logger.info(
            f"[EntityResolution] {elapsed_ms:.2f} ms | spans tried: {spans} | "
            f"matches found: {len(resolved_entities)} | queries executed: {queries_count}"
        )

        return EntityResolutionResult(
            resolved_entities=resolved_entities,
            literal_filters=quoted_literals,
            unanswerable=False,
            timings_ms=round(elapsed_ms, 2),
            queries_count=queries_count,
            spans_tried=spans,
        )

    finally:
        if close_session and target_session:
            await target_session.close()


class LiveEntityResolver:
    """Backwards-compatible wrapper delegating to unified resolve_entities."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str | uuid.UUID,
        adapter: Optional[Any] = None,
        min_fuzzy_similarity: float = 0.50,
    ):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id)) if tenant_id else None
        self.adapter = adapter
        self.min_fuzzy_similarity = min_fuzzy_similarity

    async def resolve(
        self,
        db_knowledgebase_id: uuid.UUID,
        frame: QuestionFrame,
        session: Optional[AsyncSession] = None,
    ) -> EntityResolutionResult:
        """Resolve entity values using unified local-only resolver."""
        return await resolve_entities(
            question=frame.original_question,
            kb_id=db_knowledgebase_id,
            session=session or self.db,
            tenant_id=self.tenant_id,
        )
