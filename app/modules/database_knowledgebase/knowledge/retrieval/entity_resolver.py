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
    "assign", "assigned", "assigning", "assignment", "assignments",
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
    # Pronouns & locatives
    "i", "me", "my", "mine", "you", "your", "yours", "he", "him", "his", "she", "her", "hers",
    "it", "its", "we", "us", "our", "ours", "they", "them", "their", "theirs",
    "this", "that", "these", "those",
    "there", "here", "where", "everywhere", "somewhere", "anywhere", "nowhere",
    # Quantifiers / adverbs / aggregates
    "all", "any", "some", "every", "each", "both", "few", "more", "most", "less", "least", "several",
    "only", "just", "also", "very", "too", "quite", "really", "already",
    "total", "totals", "overall", "sum", "sums", "count", "counts", "number", "numbers", "amount", "amounts", "quantity", "quantities", "together",
    "exist", "exists", "existed", "existing", "available", "present", "please",
    # Common domain status/words & concepts
    "active", "inactive", "status", "statuses", "type", "types", "state", "states",
    "open", "closed", "pending", "completed", "long", "duration",
    "progress", "progresses", "progression",
    "update", "updates", "updated", "updating",
    "activity", "activities",
    "task", "tasks",
    "ticket", "tickets",
    "issue", "issues",
    "item", "items",
    "story", "stories",
    "bug", "bugs",
    "workpackage", "workpackages", "work_package", "work_packages",
    "report", "reports", "reported", "reporting",
    "detail", "details", "detailed",
    "history", "histories", "historical",
    "overview", "summary", "summaries",
    "review", "reviews",
    "target", "targets",
    "action", "actions",
    "note", "notes",
    "info", "information",
    "record", "records",
    "profile", "profiles",
    "priority", "priorities",
    "entry", "entries",
    "timesheet", "timesheets",
    "job", "jobs",
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
        or c_low.endswith((
            "_type", "_status", "_key", "_id", "_ids", "_email", "_mail",
            "_on", "_at", "_date", "_time", "_timestamp", "_count", "_num", "_cnt",
            "_total", "_amount", "_rate", "_flag", "_url", "_path"
        ))
        or c_low.startswith(("is_", "has_"))
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
    """Candidate spans = tokens/phrases (max 3 words, max 6 spans per question) containing at least one non-excluded token."""
    spans: List[str] = []

    def _is_non_excluded(tok: str) -> bool:
        if len(tok) < 2:
            return False
        # Pure numeric strings (like days '19', months '08', years '2026', numbers) are not named entity candidate names
        if tok.isdigit() or not re.search(r"[a-zA-Z]", tok):
            return False
        tok_low = tok.lower()
        if tok_low in GENERIC_STOP_WORDS:
            return False
        # Do not drop tokens that are capitalized in the question (proper nouns/names)
        if tok[0].isupper():
            return True
        return tok_low not in exclusion_set

    # 1. Quoted strings from user (must contain alphabetic characters)
    quoted = re.findall(r'["\']([^"\']{2,})["\']', question)
    for q in quoted:
        q_clean = q.strip()
        if q_clean and re.search(r"[a-zA-Z]", q_clean) and q_clean not in spans:
            spans.append(q_clean)

    # 2. Extract words
    tokens = re.findall(r"\b[a-zA-Z0-9_-]+\b", question)
    non_excluded = [t for t in tokens if _is_non_excluded(t)]

    if not non_excluded:
        return spans[:4]

    # Prioritize single non-excluded tokens first (e.g. proper names like 'arun', 'girinath')
    for t in non_excluded:
        if t not in spans:
            spans.append(t)

    # Contiguous sequences of non-excluded tokens
    i = 0
    while i < len(tokens):
        if _is_non_excluded(tokens[i]):
            chunk = [tokens[i]]
            j = i + 1
            while j < len(tokens) and j < i + 3:
                t_next = tokens[j]
                if _is_non_excluded(t_next):
                    chunk.append(t_next)
                    j += 1
                else:
                    break
            phrase = " ".join(chunk).strip()
            if phrase not in spans:
                spans.append(phrase)
            i = j
        else:
            i += 1

    return spans[:6]


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
    timeout_ms: int = 1500,
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
        except asyncio.TimeoutError:
            logger.warning(f"[EntityResolution] Exact query timed out after {timeout_ms}ms")
            try:
                await target_session.rollback()
            except Exception:
                pass
        except Exception as exc:
            logger.warning(f"[EntityResolution] Exact query failed: {exc!r}")
            try:
                await target_session.rollback()
            except Exception:
                pass

        # 2. Trigram fallback ONLY if nothing exact matches
        if not raw_matches and spans:
            # Sort spans single-token first, try up to 4
            ordered_spans = sorted(spans, key=lambda s: (len(s.strip().split()) > 1, len(s.strip().split())))[:4]
            for span_text in ordered_spans:
                clean_s = span_text.lower().strip()
                fuzzy_params: Dict[str, Any] = {"kb_id": kb_uuid, "q": clean_s}
                tenant_clause = ""
                if tenant_uuid:
                    tenant_clause = "AND tenant_id = :tenant_id"
                    fuzzy_params["tenant_id"] = tenant_uuid

                sql_fuzzy = text(f"""
                    SELECT table_name, column_name, raw_value, normalized_value,
                            similarity(normalized_value, :q) AS sim
                    FROM kb2_entity_values
                    WHERE db_knowledgebase_id = :kb_id
                      {tenant_clause}
                      AND normalized_value % :q
                    ORDER BY similarity(normalized_value, :q) DESC
                    LIMIT 5;
                """)
                try:
                    queries_count += 1
                    res_f = await asyncio.wait_for(
                        target_session.execute(sql_fuzzy, fuzzy_params),
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
                except asyncio.TimeoutError:
                    logger.warning(f"[EntityResolution] Trigram fallback timed out after {timeout_ms}ms on span '{clean_s}'")
                    try:
                        await target_session.rollback()
                    except Exception:
                        pass
                except Exception as exc:
                    logger.warning(f"[EntityResolution] Trigram fallback failed on span '{clean_s}': {exc!r}")
                    try:
                        await target_session.rollback()
                    except Exception:
                        pass

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


# ── Label-like columns eligible for live fallback queries ──────────────
_LIVE_FALLBACK_LABEL_COLUMNS: Set[str] = {
    "name", "firstname", "first_name", "lastname", "last_name",
    "fullname", "full_name", "login", "username", "user_name",
    "title", "subject", "identifier", "label", "display_name",
}

# Roles that indicate a column holds human-readable name values (enum excluded)
_LIVE_FALLBACK_ROLES: Set[str] = {"name", "code"}

LABEL_COLUMN_PRIORITY: List[str] = [
    "login", "firstname", "first_name", "lastname", "last_name",
    "name", "username", "user_name", "full_name", "fullname",
    "display_name", "title", "subject", "identifier", "label",
]


async def _get_label_columns_from_knowledge(
    session: AsyncSession,
    kb_id: uuid.UUID,
    tenant_id: Optional[uuid.UUID] = None,
) -> List[Dict[str, str]]:
    """Fetch label-like columns from kb2_knowledge_items (schema knowledge).

    Restricted to entity and lookup tables. Prioritizes login/names before truncating.
    """
    stmt = select(
        KB2KnowledgeItem.item_key,
        KB2KnowledgeItem.payload,
        KB2KnowledgeItem.is_sensitive,
    ).where(
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_type == "column",
    )
    if tenant_id:
        stmt = stmt.where(KB2KnowledgeItem.tenant_id == tenant_id)

    try:
        res = await session.execute(stmt)
        raw_col_items = res.all()
    except Exception as sess_err:
        logger.warning(f"Error querying column items on session ({sess_err!r}), falling back to fresh session")
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as fresh_sess:
            res = await fresh_sess.execute(stmt)
            raw_col_items = res.all()

    # Load table kinds
    try:
        table_kinds = await get_kb_table_kinds(session, kb_id)
    except Exception:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as fresh_sess:
            table_kinds = await get_kb_table_kinds(fresh_sess, kb_id)

    # First pass: identify tables with login or firstname columns (force entity kind)
    # and map primary key columns per table
    table_pk_map: Dict[str, str] = {}
    for item_key, payload, is_sens in raw_col_items:
        payload = payload or {}
        col_name = (payload.get("column_name") or "").lower().strip()
        tbl_raw = normalize_table_name(payload.get("table_name") or "")
        if not col_name or not tbl_raw:
            continue
        if col_name in ("login", "firstname", "first_name"):
            table_kinds[tbl_raw] = "entity"
        if payload.get("is_primary_key") or col_name == "id":
            table_pk_map[tbl_raw] = payload.get("column_name", "id")

    label_cols: List[Dict[str, str]] = []

    NON_LABEL_DATA_TYPES = (
        "timestamp", "timestamptz", "date", "time", "interval",
        "int", "integer", "bigint", "smallint", "numeric", "decimal", "real",
        "double", "float", "bool", "boolean", "uuid", "json", "jsonb", "bytea"
    )
    NON_LABEL_ROLES = {"temporal", "metric", "quantity", "id", "fk", "pk", "audit", "enum", "boolean", "flag"}
    NON_LABEL_SUFFIXES = (
        "_on", "_at", "_date", "_time", "_timestamp",
        "_count", "_num", "_cnt", "_total", "_amount", "_rate",
        "_id", "_ids", "_key", "_type", "_status", "_state", "_flag", "_url", "_path"
    )

    for item_key, payload, is_sens in raw_col_items:
        if is_sens:
            continue
        payload = payload or {}
        col_name = payload.get("column_name", "")
        table_name_raw = payload.get("table_name", "")
        role = (payload.get("role") or "").lower().strip()
        data_type = (payload.get("data_type") or "").lower().strip()
        if not col_name or not table_name_raw:
            continue

        # Dynamic data type gating: reject temporal, numeric, boolean, or complex types
        if any(d_t in data_type for d_t in NON_LABEL_DATA_TYPES):
            continue

        # Reject non-label roles
        if role in NON_LABEL_ROLES:
            continue

        # Parse schema.table format
        parts = table_name_raw.split(".")
        if len(parts) == 2:
            schema_name, tbl_name = parts
        else:
            schema_name = "public"
            tbl_name = parts[-1]

        norm_tbl = normalize_table_name(tbl_name)

        # Restrict to entity/lookup tables (or default to entity if unknown)
        t_kind = table_kinds.get(norm_tbl, "entity")
        if t_kind not in ("entity", "lookup"):
            continue

        col_lower = col_name.lower().strip()

        # Reject technical and non-label suffixes or boolean prefixes
        if (
            col_lower in TECHNICAL_COLUMNS
            or col_lower.endswith(NON_LABEL_SUFFIXES)
            or col_lower.startswith(("is_", "has_"))
            or "email" in col_lower
            or "mail" in col_lower
        ):
            continue

        is_label = (
            col_lower in _LIVE_FALLBACK_LABEL_COLUMNS
            or role in _LIVE_FALLBACK_ROLES
            or col_lower.endswith(("_name", "_title", "_login", "_username", "_label", "_display_name"))
        )
        if not is_label:
            continue

        # Skip sensitive columns
        if is_sensitive_column(col_name):
            continue

        label_cols.append({
            "schema_table": f"{schema_name}.{tbl_name}",
            "schema_name": schema_name,
            "table_name": tbl_name,
            "column_name": col_name,
            "pk_col": table_pk_map.get(norm_tbl, "id"),
        })

    # Sort columns by priority BEFORE truncating
    def _col_priority(c_info: Dict[str, str]) -> int:
        c_low = c_info["column_name"].lower().strip()
        t_low = c_info["table_name"].lower().strip()
        # Entity tables like users, employees should have much higher priority than lookup tables
        t_is_user = any(u in t_low for u in ("user", "employee", "member", "person", "staff"))
        base = 0 if t_is_user else 100
        if c_low in LABEL_COLUMN_PRIORITY:
            return base + LABEL_COLUMN_PRIORITY.index(c_low)
        parts = re.split(r"[_\s]+", c_low)
        for idx, p in enumerate(LABEL_COLUMN_PRIORITY):
            if p in parts:
                return base + idx + 50
        return base + 150

    label_cols.sort(key=_col_priority)
    return label_cols


async def resolve_entities_live(
    spans: List[str],
    kb_id: uuid.UUID,
    tenant_id: uuid.UUID,
    adapter: Any,
    session: AsyncSession,
    timeout_ms: int = 2000,
    max_columns: int = 30,
    max_results: int = 10,
) -> List[ResolvedEntity]:
    """Live Entity Fallback: query customer database directly for name-like spans.

    This runs ONLY when kb2_entity_values returns 0 matches.
    Uses schema knowledge to identify label-like columns of entity/lookup tables,
    then runs targeted queries against the customer database with strict safety guards.
    """
    if not spans or not adapter:
        return []

    # 1. Get label-like columns from schema knowledge
    label_cols = await _get_label_columns_from_knowledge(session, kb_id, tenant_id)
    if not label_cols:
        logger.debug("[EntityResolution:LiveFallback] No label-like columns found in schema knowledge.")
        logger.info("[EntityResolution:LiveFallback] 0 live matches found.")
        return []

    # Limit to max_columns (raised 10 -> 30) after priority sorting
    label_cols = label_cols[:max_columns]

    chosen_cols_str = ", ".join(f"{c['table_name']}.{c['column_name']}" for c in label_cols)
    logger.info(f"[EntityResolution:LiveFallback] Chosen columns ({len(label_cols)}): {chosen_cols_str}")

    resolved: List[ResolvedEntity] = []
    # Prioritize single-token spans (e.g. 'arun') first
    search_spans = sorted(
        [s.strip() for s in spans if s.strip() and len(s.strip()) >= 2],
        key=lambda s: (len(s.split()) > 1, len(s.split())),
    )[:4]
    if not search_spans:
        logger.info("[EntityResolution:LiveFallback] 0 live matches found.")
        return []

    logger.info(
        f"[EntityResolution:LiveFallback] Querying customer DB for spans {search_spans} "
        f"across {len(label_cols)} label columns"
    )

    try:
        async with adapter.open_readonly_connection(tenant_id, kb_id) as conn:
            for span_text in search_spans:
                if len(resolved) >= max_results:
                    break

                # Build targeted UNION ALL subqueries selecting id + matched column
                union_parts = []
                params = []
                param_idx = 1

                for col_info in label_cols:
                    schema_name = col_info["schema_name"]
                    tbl_name = col_info["table_name"]
                    col_name = col_info["column_name"]
                    pk_col = col_info.get("pk_col") or "id"
                    quoted_tbl = f'"{schema_name}"."{tbl_name}"'
                    quoted_col = f'"{col_name}"'
                    quoted_pk = f'"{pk_col}"'

                    union_parts.append(
                        f"(SELECT '{tbl_name}' AS tbl, '{col_name}' AS col, "
                        f"'{pk_col}' AS pk_col, {quoted_pk}::text AS row_id, "
                        f"{quoted_col}::text AS matched_val "
                        f"FROM {quoted_tbl} "
                        f"WHERE {quoted_col} IS NOT NULL "
                        f"AND LOWER({quoted_col}::text) LIKE ${param_idx} "
                        f"LIMIT 5)"
                    )
                    params.append(f"%{span_text.lower()}%")
                    param_idx += 1

                if not union_parts:
                    continue

                full_query = " UNION ALL ".join(union_parts) + f" LIMIT {max_results * 5};"

                try:
                    rows = await asyncio.wait_for(
                        conn.fetch(full_query, *params),
                        timeout=timeout_ms / 1000.0,
                    )

                    # Group matches by table -> row_id
                    # table_matches: tbl -> {row_id: {"row_data": {col: val}, "pk_col": pk_col}}
                    table_matches: Dict[str, Dict[str, Dict[str, Any]]] = {}
                    for r in rows:
                        tbl = r["tbl"]
                        col = r["col"]
                        pk_col = r["pk_col"]
                        row_id = str(r["row_id"]) if r["row_id"] is not None else ""
                        matched_val = r["matched_val"]
                        if not row_id or not matched_val:
                            continue
                        # Never accept raw timestamps or dates as entity matched display values
                        if re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}", str(matched_val).strip()):
                            continue

                        tbl_dict = table_matches.setdefault(tbl, {})
                        row_dict = tbl_dict.setdefault(row_id, {"row_data": {}, "pk_col": pk_col, "first_col": col})
                        row_dict["row_data"][col] = matched_val

                    # Construct ResolvedEntity objects per table, prioritizing user/employee tables
                    sorted_tables = sorted(
                        table_matches.items(),
                        key=lambda item: 0 if any(u in item[0].lower() for u in ("user", "employee", "member", "person", "staff")) else 1
                    )
                    for tbl, row_map in sorted_tables:
                        choices: List[DisambiguationChoice] = []
                        best_col = None
                        pk_col = "id"

                        for row_id, r_info in row_map.items():
                            pk_col = r_info["pk_col"]
                            row_data = r_info["row_data"]
                            if not best_col:
                                best_col = r_info["first_col"]

                            # Determine display label in priority: login -> username -> name -> firstname -> first value
                            display_val = (
                                row_data.get("login")
                                or row_data.get("username")
                                or row_data.get("user_name")
                                or row_data.get("name")
                                or row_data.get("full_name")
                                or row_data.get("fullname")
                                or row_data.get("firstname")
                                or row_data.get("first_name")
                                or row_data.get("title")
                                or row_data.get("subject")
                                or next(iter(row_data.values()))
                            )
                            # Convert integer IDs
                            pk_val: Any = int(row_id) if row_id.isdigit() else row_id
                            display_label = f"{display_val} (id {row_id})"

                            choices.append(DisambiguationChoice(
                                pk_value=pk_val,
                                display_label=display_label,
                                row_data=row_data,
                            ))

                        if not choices:
                            continue

                        is_ambiguous = len(choices) > 1
                        matched_display = choices[0].display_label.split(" (id")[0] if choices else span_text
                        all_pks = [c.pk_value for c in choices]
                        entity_pk = all_pks if is_ambiguous else choices[0].pk_value

                        resolved.append(ResolvedEntity(
                            table_name=tbl,
                            column_name=best_col or "name",
                            matched_value=matched_display,
                            pk_column=pk_col,
                            pk_value=entity_pk,
                            ambiguous=is_ambiguous,
                            choices=choices,
                            match_type="live",
                            similarity=0.95,
                            confidence=0.95,
                        ))

                    if len(resolved) >= max_results:
                        break

                except asyncio.TimeoutError:
                    logger.warning(
                        f"[EntityResolution:LiveFallback] Timeout querying customer DB for span '{span_text}'"
                    )
                except Exception as exc:
                    logger.warning(
                        f"[EntityResolution:LiveFallback] Query failed for span '{span_text}': {exc!r}"
                    )

    except Exception as conn_exc:
        logger.warning(f"[EntityResolution:LiveFallback] Could not open customer DB connection: {conn_exc!r}")
        raise conn_exc

    # Sort resolved entities so user/person entities always come before lookup tables
    resolved.sort(
        key=lambda e: 0 if any(u in e.table_name.lower() for u in ("user", "employee", "member", "person", "staff")) else 1
    )

    if not resolved:
        logger.info("[EntityResolution:LiveFallback] 0 live matches found.")

    return resolved


class LiveEntityResolver:
    """Backwards-compatible wrapper delegating to unified resolve_entities.

    Two-tier resolution:
    1. Cache-first: query pre-indexed kb2_entity_values (fast, < 10ms)
    2. Live fallback: if cache returns 0 matches AND adapter is available,
       query customer database directly for name-like spans (< 2s)
    """

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
        """Resolve entity values: cache-first, then live fallback if needed."""
        effective_session = session or self.db

        # Tier 1: Cache-first resolution from kb2_entity_values
        result = await resolve_entities(
            question=frame.original_question,
            kb_id=db_knowledgebase_id,
            session=effective_session,
            tenant_id=self.tenant_id,
        )

        # Tier 2: Live fallback if cache returned 0 matches and adapter is available
        live_conn_error: Optional[str] = None
        if (
            not result.resolved_entities
            and not result.unanswerable
            and result.spans_tried
            and self.adapter is not None
        ):
            logger.info(
                f"[EntityResolution] Cache returned 0 matches for spans {result.spans_tried}. "
                f"Falling back to live customer DB query."
            )
            try:
                live_entities = await resolve_entities_live(
                    spans=result.spans_tried,
                    kb_id=db_knowledgebase_id,
                    tenant_id=self.tenant_id,
                    adapter=self.adapter,
                    session=effective_session,
                )
                if live_entities:
                    result.resolved_entities = live_entities
                    logger.info(
                        f"[EntityResolution] Live fallback resolved {len(live_entities)} entities: "
                        f"{[(e.table_name, e.column_name, e.matched_value) for e in live_entities]}"
                    )
            except Exception as exc:
                live_conn_error = str(exc) or exc.__class__.__name__
                logger.warning(f"[EntityResolution] Live fallback failed: {exc!r}")

        # Fail-closed guard: ONLY trigger if an EXPLICIT named entity (quoted string or capitalized proper noun) was searched and not found!
        # General aggregate questions and lowercase common words must NEVER fail closed.
        def _is_explicit_named_entity(span: str) -> bool:
            # 1. Quoted string in original question
            if any(q in frame.original_question for q in (f'"{span}"', f"'{span}'", f'“{span}”', f'’{span}’')):
                return True
            tokens = span.split()
            # 2. Capitalized proper noun (not sentence-initial grammatical word)
            for tok in tokens:
                if tok.lower() in GENERIC_STOP_WORDS:
                    continue
                m = re.search(rf"\b{re.escape(tok)}\b", frame.original_question)
                if m and tok[0].isupper() and m.start() > 0:
                    return True
            return False

        explicit_missing_entities = [s for s in result.spans_tried if _is_explicit_named_entity(s)]

        if not result.resolved_entities and not result.unanswerable and explicit_missing_entities:
            target_span = explicit_missing_entities[0]
            result.unanswerable = True
            if live_conn_error:
                result.unanswerable_reason = (
                    f"Customer database connection timed out or failed while searching for '{target_span}'. "
                    f"Please verify your database server is running and accessible."
                )
            else:
                result.unanswerable_reason = f"Couldn't find '{target_span}' in the data."
            logger.info(f"[EntityResolution] Fail closed for named entity '{target_span}': {result.unanswerable_reason}")

        return result
