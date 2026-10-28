
"""Grounded Entity Resolver for Database Knowledge Base

Dynamically discovers dimension and lookup tables from the canonical database schema
(DDL, primary keys, text label columns, and foreign key relationships) and resolves
natural-language entity mentions to concrete primary keys (e.g. Project ID 95, User ID 104,
Type ID 7).

100% schema-driven and generalizable to any relational database (OpenProject, CRM, E-commerce,
HR, Healthcare) without hardcoded domain tables.
"""

import re
import logging
from typing import List, Dict, Any, Tuple, Optional, Set
from dataclasses import dataclass
from ..execution.executor import ReadOnlyDatabaseExecutor
from ..schemas.connection import DatabaseConnectionConfig
from ..schemas.canonical import DatabaseSchema

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "what", "where", "when", "which", "how", "many", "does", "have", "with", "from",
    "show", "list", "give", "find", "get", "each", "tell", "name", "user", "users",
    "project", "projects", "task", "tasks", "work", "package", "packages", "detail",
    "details", "progress", "status", "update", "today", "yesterday", "date", "time",
    "open", "closed", "assign", "assigned", "assignee", "role", "team", "the", "for",
    "and", "all", "are", "there", "in", "on", "at", "to", "by", "is", "a", "an", "of",
    "table", "database", "exist", "created", "updated", "total", "count", "sum", "average",
    "most", "recently", "recent", "create", "creates", "created", "did"
}

LABEL_COL_PAT = re.compile(
    r'^(name|title|label|login|first_?name|last_?name|identifier|mail|email|code|slug|display_?name|username|subject)$',
    re.I
)
SYSTEM_TABLE_PREFIXES = ('ar_internal_', 'schema_migrat', 'good_job', 'session', 'token', 'delayed_job')

AUTHOR_PATTERN = re.compile(
    r"\b(author(?:ed)?\s+by|author\s*(?:is|=|:)?|created\s+by|creator\s*(?:is|=|:)?|reported\s+by|reporter\s*(?:is|=|:)?|logged\s+by|submitted\s+by|opened\s+by|raised\s+by|by)\s*$",
    re.IGNORECASE,
)
ASSIGNEE_PATTERN = re.compile(
    r"\b(assigned\s+to|assignee\s*(?:is|=|:)?|assigned\s*(?:is|=|:)?|for|owned\s+by|owner\s*(?:is|=|:)?|working\s+on)\s*$",
    re.IGNORECASE,
)
UPDATER_PATTERN = re.compile(
    r"\b(updated\s+by|modified\s+by|edited\s+by|changed\s+by)\s*$",
    re.IGNORECASE,
)
REVIEWER_PATTERN = re.compile(
    r"\b(reviewed\s+by|reviewer\s*(?:is|=|:)?)\s*$",
    re.IGNORECASE,
)


@dataclass
class DimensionTableMeta:
    table_name: str
    pk_col: str
    label_cols: List[str]
    inbound_fks: int


class GroundedEntityResolver:
    """Dynamically discovers and resolves entity mentions against the connected database."""

    # In-memory caches keyed by (kb_id, table_name)
    _dimension_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    _user_cache: Dict[str, List[Dict[str, Any]]] = {}
    _project_cache: Dict[str, List[Dict[str, Any]]] = {}

    @classmethod
    def discover_dimension_tables(cls, canonical_schema: DatabaseSchema) -> List[DimensionTableMeta]:
        """
        Dynamically analyzes the canonical schema to discover dimension/master-data tables.
        Identifies tables with a single primary key, text label columns, and foreign key
        references from other tables.
        """
        inbound_fks: Dict[str, int] = {}
        for t in canonical_schema.all_tables:
            for fk in t.foreign_keys:
                ref = fk.referred_table.split('.')[-1].lower()
                inbound_fks[ref] = inbound_fks.get(ref, 0) + 1

        dims: List[DimensionTableMeta] = []
        for t in canonical_schema.all_tables:
            t_name = t.table_name.split('.')[-1].lower()
            if any(t_name.startswith(p) for p in SYSTEM_TABLE_PREFIXES):
                continue
            pks = t.primary_key_columns
            if not pks or len(pks) > 1:
                continue
            pk_col = pks[0]

            text_cols = [c.name for c in t.columns.values() if c.data_type.value in ('VARCHAR', 'TEXT', 'CHAR')]
            if not text_cols:
                continue

            priority_labels = [c for c in text_cols if LABEL_COL_PAT.match(c)]
            label_cols = priority_labels if priority_labels else text_cols[:2]

            dims.append(DimensionTableMeta(
                table_name=t_name,
                pk_col=pk_col,
                label_cols=label_cols,
                inbound_fks=inbound_fks.get(t_name, 0),
            ))

        # Sort by inbound foreign key references descending, then number of label columns
        dims.sort(key=lambda d: (d.inbound_fks, len(d.label_cols)), reverse=True)
        return dims

    @classmethod
    async def get_dimension_rows(
        cls,
        conn_config: DatabaseConnectionConfig,
        kb_id: str,
        dim: DimensionTableMeta,
        limit: int = 2000,
        tenant_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch dimension rows with in-memory caching keyed by (tenant_id, kb_id, table_name)."""
        cache_key = (str(tenant_id or ""), str(kb_id), dim.table_name)
        if cache_key in cls._dimension_cache:
            return cls._dimension_cache[cache_key]

        from ..execution.connection_helper import connect_to_database

        sql = f"SELECT {dim.pk_col}, {', '.join(dim.label_cols)} FROM {dim.table_name} LIMIT {limit}"
        conn = None
        try:
            conn = await connect_to_database(
                db_config=conn_config,
                timeout_seconds=5.0,
                read_only=True,
                tenant_id=tenant_id or "00000000-0000-0000-0000-000000000000",
            )
            if hasattr(conn, "fetch"):
                records = await conn.fetch(sql)
                rows = [dict(r) for r in records]
            else:
                async with conn.cursor() as cur:
                    await cur.execute(sql)
                    records = await cur.fetchall()
                    rows = [dict(r) for r in records]

            cls._dimension_cache[cache_key] = rows
            return rows
        except Exception as exc:
            logger.warning(f"[GroundedEntityResolver] Could not fetch rows from {dim.table_name}: {exc}")
            return []
        finally:
            if conn:
                try:
                    if hasattr(conn, "ensure_closed"):
                        await conn.ensure_closed()
                    elif hasattr(conn, "close"):
                        await conn.close()
                except Exception:
                    pass

    @classmethod
    def _levenshtein_similarity(cls, s1: str, s2: str) -> float:
        """Compute normalized Levenshtein similarity between two strings [0.0, 1.0]."""
        if s1 == s2:
            return 1.0
        len1, len2 = len(s1), len(s2)
        if len1 == 0 or len2 == 0:
            return 0.0
        # Prevent expensive matrix allocations for very disparate lengths
        if abs(len1 - len2) / max(len1, len2) > 0.6:
            return 0.0

        prev_row = list(range(len2 + 1))
        for i, c1 in enumerate(s1):
            curr_row = [i + 1] * (len2 + 1)
            for j, c2 in enumerate(s2):
                cost = 0 if c1 == c2 else 1
                curr_row[j + 1] = min(
                    curr_row[j] + 1,       # insertion
                    prev_row[j + 1] + 1,    # deletion
                    prev_row[j] + cost     # substitution
                )
            prev_row = curr_row

        dist = prev_row[len2]
        max_len = max(len1, len2)
        return max(0.0, 1.0 - (dist / max_len))

    @classmethod
    def _extract_query_spans(cls, query: str) -> List[str]:
        """Extract multi-word and single-word n-gram candidate spans from the user query."""
        words = re.findall(r'[a-zA-Z0-9_\-]+', query)
        spans = []
        n = len(words)
        # Extract spans of length 1, 2, 3, 4
        for length in range(min(4, n), 0, -1):
            for i in range(n - length + 1):
                chunk = words[i:i + length]
                # Filter out pure stop words
                non_stop = [w for w in chunk if w.lower() not in STOP_WORDS]
                if non_stop:
                    spans.append(" ".join(chunk))
        return spans

    @classmethod
    async def resolve_entities_in_query(
        cls,
        user_query: str,
        canonical_schema: DatabaseSchema,
        conn_config: DatabaseConnectionConfig,
        kb_id: str,
        tenant_id: Optional[str] = None,
        relevant_tables: Optional[List[str]] = None,
        fuzzy_threshold: float = 0.80,
        ambiguity_margin: float = 0.10,
    ) -> Dict[str, Any]:
        """
        Dynamically discovers dimension tables and resolves natural language entity mentions
        using a strict Exact-First priority:
          - Stage A: Exact Match (case/punctuation/spacing sensitive word boundary)
          - Stage B: Safe Normalization (case-insensitive, whitespace/punctuation, singular/plural)
          - Stage C: Bounded Fuzzy Match (Levenshtein similarity >= fuzzy_threshold with ambiguity margin)
        Zero domain hardcoding.
        """
        import time
        t_total_start = time.perf_counter()

        timings = {
            "exact_latency_ms": 0.0,
            "normalized_latency_ms": 0.0,
            "fuzzy_latency_ms": 0.0,
            "total_resolution_latency_ms": 0.0,
        }

        if not canonical_schema or not conn_config or not user_query.strip():
            timings["total_resolution_latency_ms"] = (time.perf_counter() - t_total_start) * 1000.0
            return {
                "resolved_entities": [],
                "ambiguous_entities": [],
                "notices": [],
                "timings": timings,
            }

        dims = cls.discover_dimension_tables(canonical_schema)
        q_clean = re.sub(r"['’]s\b", "", user_query.lower())
        q_tokens = set(re.findall(r'\b[a-zA-Z0-9_]{3,}\b', q_clean)) - STOP_WORDS
        rel_tbls_clean = {t.lower() for t in relevant_tables or [] if t}

        # Select candidate dimension tables dynamically:
        # If relevant_tables (from schema retrieval) is provided, prioritize them directly
        candidate_dims: List[DimensionTableMeta] = []
        if rel_tbls_clean:
            for d in dims:
                t_name = d.table_name.lower()
                if t_name in rel_tbls_clean or t_name in q_clean or (t_name.rstrip('s') in q_clean):
                    candidate_dims.append(d)
        else:
            for d in dims:
                t_name = d.table_name.lower()
                if t_name in q_clean or (t_name.rstrip('s') in q_clean):
                    candidate_dims.append(d)
                elif d.inbound_fks >= 1:
                    candidate_dims.append(d)

        # Fallback: if none matched, evaluate top discovered dimensions
        if not candidate_dims and dims:
            candidate_dims = dims[:5]

        # De-duplicate while preserving priority order
        seen_dim_names = set()
        deduped_candidate_dims = []
        for d in candidate_dims:
            if d.table_name not in seen_dim_names:
                seen_dim_names.add(d.table_name)
                deduped_candidate_dims.append(d)

        candidate_dims = deduped_candidate_dims[:8]

        # Fetch dimension rows concurrently to minimize latency
        dim_row_tasks = [
            cls.get_dimension_rows(
                conn_config=conn_config,
                kb_id=kb_id,
                dim=dim,
                tenant_id=tenant_id,
            )
            for dim in candidate_dims
        ]
        import asyncio
        dim_rows_results = await asyncio.gather(*dim_row_tasks, return_exceptions=True)

        resolved: List[Dict[str, Any]] = []
        ambiguous_entities: List[Dict[str, Any]] = []
        seen_entities: Set[Tuple[str, Any]] = set()

        q_spans = cls._extract_query_spans(user_query)

        for dim, rows in zip(candidate_dims, dim_rows_results):
            if isinstance(rows, Exception) or not rows:
                continue

            # ==================================================================
            # STAGE A: Exact Match
            # Check whether original user query contains the exact database value
            # with strict casing, spacing, and word boundaries.
            # ==================================================================
            t_exact_start = time.perf_counter()
            exact_matches: List[Tuple[Any, str, str, Dict[str, Any]]] = []

            for r in rows:
                pk_val = r.get(dim.pk_col)
                if (dim.table_name, pk_val) in seen_entities:
                    continue

                for col in dim.label_cols:
                    val = r.get(col)
                    if val is None or not isinstance(val, (str, bytes)):
                        continue
                    val_str = str(val).strip()
                    if len(val_str) < 2:
                        continue

                    # Exact substring match bounded by word boundaries or punctuation
                    pattern = r'(?<![a-zA-Z0-9_])' + re.escape(val_str) + r'(?![a-zA-Z0-9_])'
                    if re.search(pattern, user_query):
                        exact_matches.append((pk_val, val_str, val_str, r))
                        break

            timings["exact_latency_ms"] += (time.perf_counter() - t_exact_start) * 1000.0

            if exact_matches:
                # Group exact matches by matched text to detect identical vs ambiguous hits
                grouped_exact: Dict[str, List[Any]] = {}
                for pk_val, m_val, m_text, raw_r in exact_matches:
                    grouped_exact.setdefault(m_val, []).append((pk_val, m_val, m_text, raw_r))

                for term, recs in grouped_exact.items():
                    if len(recs) == 1:
                        pk_val, m_val, m_text, raw_r = recs[0]
                        seen_entities.add((dim.table_name, pk_val))
                        role, col_hints = cls._detect_entity_role(dim, m_val, user_query)
                        resolved.append({
                            "table": dim.table_name,
                            "id": pk_val,
                            "name": m_val,
                            "matched_term": m_text,
                            "column": dim.pk_col,
                            "match_stage": "EXACT",
                            "confidence": 1.0,
                            "role": role,
                            "suggested_columns": col_hints,
                        })
                    else:
                        # Multiple distinct rows sharing the exact same text
                        ambiguous_entities.append({
                            "dimension_table": dim.table_name,
                            "matched_term": term,
                            "match_stage": "EXACT",
                            "candidates": [
                                {
                                    "id": r_pk,
                                    "name": r_name,
                                    "table": dim.table_name,
                                    "column": dim.pk_col,
                                    "score": 1.0,
                                }
                                for r_pk, r_name, _, _ in recs
                            ]
                        })
                # Stage A succeeded for this dimension table; strictly skip Stage B & C
                continue

            # ==================================================================
            # STAGE B: Safe Normalization
            # Normalized candidate discovery: case-insensitive, whitespace/punctuation,
            # singular/plural forms. Avoid substring false positives (e.g. bug vs Debug).
            # ==================================================================
            t_norm_start = time.perf_counter()
            norm_matches: List[Tuple[Any, str, str, Dict[str, Any]]] = []

            for r in rows:
                pk_val = r.get(dim.pk_col)
                if (dim.table_name, pk_val) in seen_entities:
                    continue

                matched = False
                matched_val = ""
                matched_text = ""

                # Composite full name check if firstname and lastname exist
                if "firstname" in dim.label_cols and "lastname" in dim.label_cols:
                    fn = str(r.get("firstname") or "").strip()
                    ln = str(r.get("lastname") or "").strip()
                    fullname = f"{fn} {ln}".strip()
                    if fullname and len(fullname) >= 3:
                        fn_pat = r'\b' + re.escape(fullname.lower()) + r'\b'
                        if re.search(fn_pat, q_clean):
                            matched = True
                            matched_val = fullname
                            matched_text = fullname

                if not matched:
                    for col in dim.label_cols:
                        val = r.get(col)
                        if val is None or not isinstance(val, (str, bytes)):
                            continue
                        val_orig = str(val).strip()
                        if len(val_orig) < 2:
                            continue

                        val_clean = val_orig.lower()
                        val_words = [w for w in re.split(r'[^a-z0-9]+', val_clean) if w]

                        # 1. Whole term word-boundary match (case-insensitive)
                        pat_word = r'(?<![a-z0-9_])' + re.escape(val_clean) + r'(?![a-z0-9_])'
                        if re.search(pat_word, q_clean):
                            matched = True
                            matched_val = val_orig
                            matched_text = val_orig
                            break

                        # 2. Singular / Plural variation with word boundaries
                        # e.g., user asks 'bugs' -> db has 'Bug' or 'Bugs'
                        singular_form = val_clean[:-1] if val_clean.endswith('s') and len(val_clean) > 3 else val_clean
                        plural_form = f"{val_clean}s" if not val_clean.endswith('s') else val_clean

                        pat_singular = r'(?<![a-z0-9_])' + re.escape(singular_form) + r'(?![a-z0-9_])'
                        pat_plural = r'(?<![a-z0-9_])' + re.escape(plural_form) + r'(?![a-z0-9_])'

                        if (singular_form != val_clean and re.search(pat_singular, q_clean)) or \
                           (plural_form != val_clean and re.search(pat_plural, q_clean)):
                            matched = True
                            matched_val = val_orig
                            matched_text = val_orig
                            break

                        # 3. Separator-normalized match (e.g. CREAM_Reward <-> CREAM Reward)
                        norm_sep_val = re.sub(r'[\s_\-]+', ' ', val_clean)
                        pat_sep = r'(?<![a-z0-9_])' + re.escape(norm_sep_val) + r'(?![a-z0-9_])'
                        if re.search(pat_sep, q_clean):
                            matched = True
                            matched_val = val_orig
                            matched_text = val_orig
                            break

                        # 4. Multi-word constituent match (all non-stop words of entity in query tokens)
                        sub_words = [w for w in val_words if len(w) >= 3 and w not in STOP_WORDS]
                        if len(sub_words) >= 2 and all(w in q_tokens for w in sub_words):
                            matched = True
                            matched_val = val_orig
                            matched_text = val_orig
                            break

                if matched:
                    norm_matches.append((pk_val, matched_val, matched_text, r))

            timings["normalized_latency_ms"] += (time.perf_counter() - t_norm_start) * 1000.0

            if norm_matches:
                grouped_norm: Dict[str, List[Any]] = {}
                for pk_val, m_val, m_text, raw_r in norm_matches:
                    key = m_val.lower().strip()
                    grouped_norm.setdefault(key, []).append((pk_val, m_val, m_text, raw_r))

                for key_term, recs in grouped_norm.items():
                    if len(recs) == 1:
                        pk_val, m_val, m_text, raw_r = recs[0]
                        seen_entities.add((dim.table_name, pk_val))
                        role, col_hints = cls._detect_entity_role(dim, m_val, user_query)
                        resolved.append({
                            "table": dim.table_name,
                            "id": pk_val,
                            "name": m_val,
                            "matched_term": m_text,
                            "column": dim.pk_col,
                            "match_stage": "NORMALIZED",
                            "confidence": 0.95,
                            "role": role,
                            "suggested_columns": col_hints,
                        })
                    else:
                        ambiguous_entities.append({
                            "dimension_table": dim.table_name,
                            "matched_term": recs[0][1],
                            "match_stage": "NORMALIZED",
                            "candidates": [
                                {
                                    "id": r_pk,
                                    "name": r_name,
                                    "table": dim.table_name,
                                    "column": dim.pk_col,
                                    "score": 0.95,
                                }
                                for r_pk, r_name, _, _ in recs
                            ]
                        })
                # Stage B succeeded; strictly skip Stage C
                continue

            # ==================================================================
            # STAGE C: Bounded Fuzzy Matching
            # Only executed when Stages A & B find no matches.
            # Evaluates candidate similarity against query spans with ambiguity margin.
            # Never scan non-string columns or short strings (<= 2 chars).
            # ==================================================================
            t_fuzzy_start = time.perf_counter()
            scored_candidates: List[Dict[str, Any]] = []

            for r in rows:
                pk_val = r.get(dim.pk_col)
                if (dim.table_name, pk_val) in seen_entities:
                    continue

                for col in dim.label_cols:
                    val = r.get(col)
                    if val is None or not isinstance(val, (str, bytes)):
                        continue
                    val_str = str(val).strip()
                    # Skip short strings to avoid low-entropy false positives
                    if len(val_str) <= 2:
                        continue

                    val_lower = val_str.lower()
                    best_sim = 0.0
                    best_span = ""

                    for span in q_spans:
                        span_lower = span.lower()
                        # Short span guard
                        if len(span_lower) <= 2:
                            continue

                        # Substring false positive guard:
                        # If one is a strict substring of the other but lengths differ significantly (e.g. bug vs Debug),
                        # do not treat as a fuzzy match unless similarity is genuinely high
                        sim = cls._levenshtein_similarity(val_lower, span_lower)
                        if sim > best_sim:
                            best_sim = sim
                            best_span = span

                    if best_sim >= fuzzy_threshold:
                        scored_candidates.append({
                            "id": pk_val,
                            "name": val_str,
                            "table": dim.table_name,
                            "column": dim.pk_col,
                            "matched_term": best_span,
                            "score": round(best_sim, 4),
                            "raw_row": r,
                        })

            timings["fuzzy_latency_ms"] += (time.perf_counter() - t_fuzzy_start) * 1000.0

            if scored_candidates:
                # Sort descending by similarity score
                scored_candidates.sort(key=lambda c: c["score"], reverse=True)
                top_candidate = scored_candidates[0]

                # Check ambiguity margin if multiple candidates were found
                if len(scored_candidates) > 1:
                    second_candidate = scored_candidates[1]
                    score_gap = top_candidate["score"] - second_candidate["score"]
                    if score_gap < ambiguity_margin and top_candidate["name"].lower() != second_candidate["name"].lower():
                        # Ambiguous: top candidates are too close in score
                        ambiguous_entities.append({
                            "dimension_table": dim.table_name,
                            "matched_term": top_candidate["matched_term"],
                            "match_stage": "FUZZY_AMBIGUOUS",
                            "candidates": [
                                {
                                    "id": c["id"],
                                    "name": c["name"],
                                    "table": dim.table_name,
                                    "column": dim.pk_col,
                                    "score": c["score"],
                                }
                                for c in scored_candidates[:5]
                            ],
                        })
                        continue

                # Distinct high-confidence fuzzy match
                pk_val = top_candidate["id"]
                seen_entities.add((dim.table_name, pk_val))
                role, col_hints = cls._detect_entity_role(dim, top_candidate["name"], user_query)
                resolved.append({
                    "table": dim.table_name,
                    "id": pk_val,
                    "name": top_candidate["name"],
                    "matched_term": top_candidate["matched_term"],
                    "column": dim.pk_col,
                    "match_stage": "FUZZY",
                    "confidence": top_candidate["score"],
                    "role": role,
                    "suggested_columns": col_hints,
                })

        timings["total_resolution_latency_ms"] = (time.perf_counter() - t_total_start) * 1000.0

        notices = []
        for ent in resolved:
            role_desc = f" as {ent['role']}" if ent.get("role") else ""
            stage_desc = f" [{ent.get('match_stage', 'EXACT')}]"
            notices.append(f"Targeting {ent['table']} '{ent['name']}' (ID {ent['id']}){role_desc}{stage_desc}")

        return {
            "resolved_entities": resolved,
            "ambiguous_entities": ambiguous_entities,
            "notices": notices,
            "timings": timings,
        }

    @classmethod
    def _detect_entity_role(
        cls,
        dim: DimensionTableMeta,
        m_val: str,
        user_query: str,
    ) -> Tuple[Optional[str], List[str]]:
        """Context-aware role detection for person/user-like dimensions."""
        role = None
        col_hints = []
        if any(c in dim.label_cols for c in ("login", "firstname", "mail", "username", "display_name")):
            m = re.search(r'\b' + re.escape(m_val) + r'\b', user_query, re.I)
            idx = m.start() if m else 0
            preceding = user_query[max(0, idx - 45):idx]
            if AUTHOR_PATTERN.search(preceding) or "create" in user_query.lower() or "created" in user_query.lower():
                role = "author"
                col_hints = ["author_id", "created_by_id", "reporter_id"]
            elif ASSIGNEE_PATTERN.search(preceding):
                role = "assignee"
                col_hints = ["assigned_to_id", "user_id"]
            elif UPDATER_PATTERN.search(preceding):
                role = "updater"
                col_hints = ["author_id", "assigned_to_id", "responsible_id"]
            elif REVIEWER_PATTERN.search(preceding):
                role = "reviewer"
                col_hints = ["assigned_to_id", "responsible_id"]
            else:
                col_hints = ["author_id", "assigned_to_id", "user_id"]
        return role, col_hints

    # --------------------------------------------------------------------------
    # Backward Compatibility Methods (kept for existing callers/unit tests)
    # --------------------------------------------------------------------------
    @classmethod
    async def get_all_projects(
        cls,
        conn_config: DatabaseConnectionConfig,
        kb_id: str,
    ) -> List[Dict[str, Any]]:
        """Fetch active projects with in-memory caching keyed by KB ID."""
        if kb_id in cls._project_cache:
            return cls._project_cache[kb_id]

        dim = DimensionTableMeta(table_name="projects", pk_col="id", label_cols=["name", "identifier"], inbound_fks=10)
        rows = await cls.get_dimension_rows(conn_config=conn_config, kb_id=kb_id, dim=dim)
        cls._project_cache[kb_id] = rows
        return rows

    @classmethod
    def resolve_all_project_entities(
        cls,
        question: str,
        projects: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Dynamically find projects mentioned in the question using normalized matching."""
        q_norm = re.sub(r'[^a-z0-9]', '', question.lower())
        matched = []
        seen_ids = set()

        sorted_projects = sorted(projects, key=lambda p: len(p.get("name") or ""), reverse=True)

        for p in sorted_projects:
            p_name = p.get("name") or ""
            p_id = p["id"]
            p_ident = p.get("identifier") or ""

            norm_name = re.sub(r'[^a-z0-9]', '', p_name.lower())
            base_name = p_name.split('(')[0].strip()
            norm_base = re.sub(r'[^a-z0-9]', '', base_name.lower())
            norm_ident = re.sub(r'[^a-z0-9]', '', p_ident.lower())

            if (norm_name and len(norm_name) >= 3 and norm_name in q_norm) or \
               (norm_base and len(norm_base) >= 3 and norm_base in q_norm) or \
               (norm_ident and len(norm_ident) >= 3 and norm_ident in q_norm):
                if p_id not in seen_ids:
                    seen_ids.add(p_id)
                    matched.append({
                        "id": p_id,
                        "name": p_name,
                        "identifier": p_ident,
                    })

        return matched

    @classmethod
    async def get_all_users(
        cls,
        conn_config: DatabaseConnectionConfig,
        kb_id: str,
    ) -> List[Dict[str, Any]]:
        """Fetch active users with in-memory caching keyed by KB ID."""
        if kb_id in cls._user_cache:
            return cls._user_cache[kb_id]

        dim = DimensionTableMeta(
            table_name="users",
            pk_col="id",
            label_cols=["login", "firstname", "lastname", "mail"],
            inbound_fks=50,
        )
        rows = await cls.get_dimension_rows(conn_config=conn_config, kb_id=kb_id, dim=dim)
        cls._user_cache[kb_id] = rows
        return rows

    @classmethod
    def resolve_all_user_entities(
        cls,
        question: str,
        users: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Dynamically find users mentioned in the question and identify roles."""
        if not users:
            return {"resolved_users": [], "ambiguous_entities": [], "notices": []}

        q_clean = re.sub(r"['’]s\b", "", question.lower())
        q_raw = question
        q_lower = q_clean

        def detect_role_for_span(start_idx: int) -> Tuple[Optional[str], List[str]]:
            preceding = q_raw[max(0, start_idx - 45):start_idx].strip()
            if AUTHOR_PATTERN.search(preceding) or "create" in q_raw.lower() or "created" in q_raw.lower():
                return "author", ["author_id", "created_by_id", "reporter_id"]
            if ASSIGNEE_PATTERN.search(preceding):
                return "assigned_to", ["assigned_to_id", "user_id"]
            if UPDATER_PATTERN.search(preceding):
                return "updater", ["author_id", "assigned_to_id", "responsible_id"]
            if REVIEWER_PATTERN.search(preceding):
                return "reviewer", ["assigned_to_id", "responsible_id"]
            return None, ["author_id", "assigned_to_id", "responsible_id"]

        matched_spans: List[Tuple[int, int]] = []
        resolved_users: List[Dict[str, Any]] = []
        ambiguous_entities: List[Dict[str, Any]] = []
        seen_user_ids = set()

        def overlaps(s: int, e: int) -> bool:
            return any(not (e <= ms or s >= me) for ms, me in matched_spans)

        # 1. Multi-word Full Name Matching
        users_by_fullname = []
        for u in users:
            fn = (u.get("firstname") or "").strip()
            ln = (u.get("lastname") or "").strip()
            full_name = f"{fn} {ln}".strip()
            if full_name and len(full_name) > 2:
                users_by_fullname.append((full_name.lower(), full_name, u))

        users_by_fullname.sort(key=lambda x: len(x[0]), reverse=True)

        for fn_lower, fn_orig, u in users_by_fullname:
            pattern = r'\b' + re.escape(fn_lower) + r'\b'
            for m in re.finditer(pattern, q_lower):
                s, e = m.start(), m.end()
                if not overlaps(s, e):
                    matched_spans.append((s, e))
                    if u["id"] not in seen_user_ids:
                        seen_user_ids.add(u["id"])
                        role, col_hints = detect_role_for_span(s)
                        resolved_users.append({
                            "id": u["id"],
                            "name": fn_orig,
                            "firstname": u.get("firstname") or "",
                            "lastname": u.get("lastname") or "",
                            "login": u.get("login") or "",
                            "mail": u.get("mail") or "",
                            "role": role,
                            "suggested_columns": col_hints,
                            "matched_text": fn_orig,
                        })

        # 2. Token Matching (firstname, lastname, login)
        tokens_in_q = []
        for m in re.finditer(r'\b[a-zA-Z0-9_]{3,}\b', q_clean):
            tok = m.group(0).lower()
            s, e = m.start(), m.end()
            if tok not in STOP_WORDS and not overlaps(s, e):
                tokens_in_q.append((tok, s, e))

        for tok, s, e in tokens_in_q:
            if overlaps(s, e):
                continue

            candidates = []
            for u in users:
                fn = (u.get("firstname") or "").strip().lower()
                ln = (u.get("lastname") or "").strip().lower()
                login = (u.get("login") or "").strip().lower()
                if tok == fn or tok == ln or tok == login:
                    if u["id"] not in [c["id"] for c in candidates]:
                        candidates.append(u)

            if len(candidates) == 1:
                u = candidates[0]
                matched_spans.append((s, e))
                if u["id"] not in seen_user_ids:
                    seen_user_ids.add(u["id"])
                    fn = (u.get("firstname") or "").strip()
                    ln = (u.get("lastname") or "").strip()
                    display_name = f"{fn} {ln}".strip() or u.get("login") or tok
                    role, col_hints = detect_role_for_span(s)
                    resolved_users.append({
                        "id": u["id"],
                        "name": display_name,
                        "firstname": u.get("firstname") or "",
                        "lastname": u.get("lastname") or "",
                        "login": u.get("login") or "",
                        "mail": u.get("mail") or "",
                        "role": role,
                        "suggested_columns": col_hints,
                        "matched_text": tok,
                    })
            elif len(candidates) > 1:
                matched_spans.append((s, e))
                ambiguous_entities.append({
                    "matched_term": tok,
                    "candidates": candidates,
                })

        notices = []
        for ru in resolved_users:
            role_desc = f" as {ru['role']}" if ru.get("role") else ""
            notices.append(f"Targeting user '{ru['name']}' (ID {ru['id']}){role_desc}")

        return {
            "resolved_users": resolved_users,
            "ambiguous_entities": ambiguous_entities,
            "notices": notices,
        }

    @classmethod
    def find_user_candidates(
        cls,
        question: str,
        users: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Backward-compatible helper: finds users in question."""
        res = cls.resolve_all_user_entities(question, users)
        if res["ambiguous_entities"]:
            amb = res["ambiguous_entities"][0]
            return (amb["matched_term"], amb["candidates"])
        if res["resolved_users"]:
            first_user = res["resolved_users"][0]
            return (first_user["matched_text"], [first_user])
        return ("", [])
