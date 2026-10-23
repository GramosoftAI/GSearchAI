
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
    async def resolve_entities_in_query(
        cls,
        user_query: str,
        canonical_schema: DatabaseSchema,
        conn_config: DatabaseConnectionConfig,
        kb_id: str,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Dynamically discovers dimension tables and resolves natural language entity mentions
        into concrete primary keys and suggested foreign key columns.
        """
        if not canonical_schema or not conn_config:
            return {"resolved_entities": [], "ambiguous_entities": [], "notices": []}

        dims = cls.discover_dimension_tables(canonical_schema)
        q_clean = re.sub(r"['’]s\b", "", user_query.lower())
        q_norm = re.sub(r'[^a-z0-9]', '', user_query.lower())
        q_tokens = set(re.findall(r'\b[a-zA-Z0-9_]{3,}\b', q_clean)) - STOP_WORDS

        # Select candidate dimension tables for this query
        candidate_dims: List[DimensionTableMeta] = []
        for d in dims:
            # Top dimensions by inbound foreign keys (e.g. users, projects, types, statuses)
            if d.inbound_fks >= 5:
                candidate_dims.append(d)
            # Or dimension table name explicitly mentioned in query
            elif d.table_name in q_clean or (d.table_name.rstrip('s') in q_clean):
                candidate_dims.append(d)

        resolved: List[Dict[str, Any]] = []
        ambiguous_entities: List[Dict[str, Any]] = []
        seen_entities: Set[Tuple[str, Any]] = set()

        for dim in candidate_dims:
            rows = await cls.get_dimension_rows(
                conn_config=conn_config,
                kb_id=kb_id,
                dim=dim,
                tenant_id=tenant_id,
            )
            if not rows:
                continue

            # Greedy matching: sort records by max length of label values descending
            sorted_rows = sorted(
                rows,
                key=lambda r: max((len(str(r.get(c) or "")) for c in dim.label_cols), default=0),
                reverse=True
            )

            matched_dim_records = []

            for r in sorted_rows:
                pk_val = r.get(dim.pk_col)
                if (dim.table_name, pk_val) in seen_entities:
                    continue

                matched = False
                matched_val = ""
                matched_text = ""

                # Check composite full name if firstname and lastname exist
                if "firstname" in dim.label_cols and "lastname" in dim.label_cols:
                    fn = (r.get("firstname") or "").strip()
                    ln = (r.get("lastname") or "").strip()
                    fullname = f"{fn} {ln}".strip()
                    if fullname and len(fullname) >= 3:
                        fn_norm = re.sub(r'[^a-z0-9]', '', fullname.lower())
                        if fn_norm in q_norm:
                            matched = True
                            matched_val = fullname
                            matched_text = fullname

                if not matched:
                    for col in dim.label_cols:
                        val = str(r.get(col) or "").strip()
                        if not val or len(val) < 2:
                            continue

                        val_norm = re.sub(r'[^a-z0-9]', '', val.lower())
                        base_val = val.split('(')[0].strip()
                        base_norm = re.sub(r'[^a-z0-9]', '', base_val.lower())

                        val_plural_norm = f"{val_norm}s" if not val_norm.endswith('s') else val_norm
                        val_singular_norm = val_norm[:-1] if val_norm.endswith('s') else val_norm

                        # 1. Normalized separator- and case-agnostic match
                        if (val_norm and len(val_norm) >= 3 and val_norm in q_norm) or \
                           (base_norm and len(base_norm) >= 3 and base_norm in q_norm):
                            matched = True
                            matched_val = val
                            matched_text = val
                            break
                        # 2. Multi-word constituent matching (all significant words of the entity are in the query)
                        val_words = [w for w in re.split(r'[^a-z0-9]+', val.lower()) if len(w) >= 3 and w not in STOP_WORDS]
                        if val_words and len(val_words) >= 2 and all(w in q_tokens for w in val_words):
                            matched = True
                            matched_val = val
                            matched_text = val
                            break
                        # 3. Singular/plural match (e.g. user asks 'bugs' but table has 'Bug')
                        elif (val_plural_norm and len(val_plural_norm) >= 3 and val_plural_norm in q_norm) or \
                             (val_singular_norm and len(val_singular_norm) >= 3 and val_singular_norm in q_norm):
                            matched = True
                            matched_val = val
                            matched_text = val
                            break

                if matched:
                    matched_dim_records.append((pk_val, matched_val, matched_text, r))

            # Detect if multiple records matched the exact same term (Ambiguity)
            term_buckets: Dict[str, List[Any]] = {}
            for pk_val, m_val, m_text, raw_r in matched_dim_records:
                norm_term = re.sub(r'[^a-z0-9]', '', m_val.lower())
                term_buckets.setdefault(norm_term, []).append((pk_val, m_val, m_text, raw_r))

            for norm_term, recs in term_buckets.items():
                if len(recs) == 1:
                    pk_val, m_val, m_text, raw_r = recs[0]
                    seen_entities.add((dim.table_name, pk_val))

                    role = None
                    col_hints = []
                    # Context-aware role detection for user/person-like dimensions
                    if any(c in dim.label_cols for c in ("login", "firstname", "mail", "username")):
                        m = re.search(r'\b' + re.escape(norm_term) + r'\b', q_clean)
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

                    resolved.append({
                        "table": dim.table_name,
                        "id": pk_val,
                        "name": m_val,
                        "matched_term": m_text,
                        "column": dim.pk_col,
                        "role": role,
                        "suggested_columns": col_hints,
                    })
                elif len(recs) > 1:
                    ambiguous_entities.append({
                        "dimension_table": dim.table_name,
                        "matched_term": recs[0][2],
                        "candidates": [
                            {
                                "id": r_pk,
                                "name": r_name,
                                "table": dim.table_name,
                                "column": dim.pk_col,
                            }
                            for r_pk, r_name, _, _ in recs
                        ]
                    })

        notices = []
        for ent in resolved:
            role_desc = f" as {ent['role']}" if ent.get("role") else ""
            notices.append(f"Targeting {ent['table']} '{ent['name']}' (ID {ent['id']}){role_desc}")

        return {
            "resolved_entities": resolved,
            "ambiguous_entities": ambiguous_entities,
            "notices": notices,
        }

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
