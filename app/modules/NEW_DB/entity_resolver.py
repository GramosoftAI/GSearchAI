"""Entity Resolver and Disambiguation for NEW_DB

Queries the target database's user directory to resolve concrete entity names
(e.g., 'Arun' -> User ID 113) and flags ambiguous entity references.
"""

import re
import logging
from typing import List, Dict, Any, Optional, Tuple

from .schemas import DBConnectionConfig
from .connection import DatabaseConnector

logger = logging.getLogger(__name__)

# Cache users per connection for 5 minutes
_USERS_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}


class EntityResolver:
    """Resolves natural-language entity mentions to concrete database primary keys."""

    @classmethod
    async def get_all_users(cls, config: DBConnectionConfig) -> List[Dict[str, Any]]:
        """Fetch all users from target database if a users table exists."""
        cache_key = f"{config.host}:{config.port}:{config.database_name}"
        import time
        now = time.time()

        if cache_key in _USERS_CACHE:
            ts, users = _USERS_CACHE[cache_key]
            if now - ts < 300:  # 5 min cache
                return users

        conn = await DatabaseConnector.get_asyncpg_connection(config)
        try:
            # Check if users table exists
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users');"
            )
            if not exists:
                return []

            # Check available columns
            cols = await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'users';"
            )
            col_set = {r['column_name'].lower() for r in cols}

            # Build safe select query
            select_cols = ["id"]
            for col in ("login", "firstname", "lastname", "mail", "name", "username"):
                if col in col_set:
                    select_cols.append(col)

            sql = f"SELECT {', '.join(select_cols)} FROM users LIMIT 1000;"
            rows = await conn.fetch(sql)
            users = [dict(r) for r in rows]
            _USERS_CACHE[cache_key] = (now, users)
            return users
        except Exception as e:
            logger.debug(f"[NEW_DB] EntityResolver: users table scan skipped: {e}")
            return []
        finally:
            await conn.close()

    @classmethod
    def resolve_all_user_entities(
        cls,
        user_query: str,
        users: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Dynamically find ALL users mentioned in the question, identify their specific roles
        (e.g., author, assignee, updater, reviewer) from natural language context, and
        detect any ambiguities.
        """
        if not users:
            return {"resolved_users": [], "ambiguous_entities": [], "notices": []}

        q_clean = re.sub(r"['’]s\b", "", user_query.lower())
        q_raw = user_query
        q_lower = q_clean

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

        def detect_role_for_span(start_idx: int) -> Tuple[Optional[str], List[str]]:
            preceding = q_raw[max(0, start_idx - 45):start_idx].strip()
            if AUTHOR_PATTERN.search(preceding):
                return "author", ["author_id", "created_by_id", "reporter_id"]
            if ASSIGNEE_PATTERN.search(preceding):
                return "assigned_to", ["assigned_to_id", "user_id"]
            if UPDATER_PATTERN.search(preceding):
                return "updater", ["updated_by_id", "updater_id"]
            if REVIEWER_PATTERN.search(preceding):
                return "reviewer", ["reviewer_id"]
            return None, ["user_id", "author_id", "assigned_to_id"]

        matched_spans: List[Tuple[int, int]] = []
        resolved_users: List[Dict[str, Any]] = []
        ambiguous_entities: List[Dict[str, Any]] = []
        seen_user_ids = set()

        def overlaps(s: int, e: int) -> bool:
            return any(not (e <= ms or s >= me) for ms, me in matched_spans)

        # 1. Multi-word Full Name Matching
        users_by_fullname = []
        for u in users:
            fn = str(u.get("firstname") or "").strip()
            ln = str(u.get("lastname") or "").strip()
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
                            "login": u.get("login") or u.get("username") or "",
                            "mail": u.get("mail") or "",
                            "role": role,
                            "suggested_columns": col_hints,
                            "matched_text": fn_orig,
                        })

        # 2. Token Matching
        stop_words = {"what", "were", "when", "show", "tell", "list", "have", "been", "done", "this", "week", "month", "task", "work", "package", "project", "open", "closed", "todo"}
        tokens_in_q = []
        for m in re.finditer(r'\b[a-zA-Z0-9_]{3,}\b', q_clean):
            tok = m.group(0).lower()
            s, e = m.start(), m.end()
            if tok not in stop_words and not overlaps(s, e):
                tokens_in_q.append((tok, s, e))

        for tok, s, e in tokens_in_q:
            if overlaps(s, e):
                continue

            candidates = []
            for u in users:
                fn = str(u.get("firstname") or "").strip().lower()
                ln = str(u.get("lastname") or "").strip().lower()
                login = str(u.get("login") or u.get("username") or "").strip().lower()
                if tok == fn or tok == ln or tok == login:
                    if u["id"] not in [c["id"] for c in candidates]:
                        candidates.append(u)

            if len(candidates) == 1:
                u = candidates[0]
                matched_spans.append((s, e))
                if u["id"] not in seen_user_ids:
                    seen_user_ids.add(u["id"])
                    fn = str(u.get("firstname") or "").strip()
                    ln = str(u.get("lastname") or "").strip()
                    display_name = f"{fn} {ln}".strip() or u.get("login") or u.get("username") or tok
                    role, col_hints = detect_role_for_span(s)
                    resolved_users.append({
                        "id": u["id"],
                        "name": display_name,
                        "firstname": u.get("firstname") or "",
                        "lastname": u.get("lastname") or "",
                        "login": u.get("login") or u.get("username") or "",
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
    def resolve_user_mention(
        cls, user_query: str, users: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Backward-compatible single user resolution wrapper.
        """
        res = cls.resolve_all_user_entities(user_query, users)
        if res["ambiguous_entities"]:
            amb = res["ambiguous_entities"][0]
            options = [
                {
                    "id": c.get("id"),
                    "name": f"{c.get('firstname', '')} {c.get('lastname', '')}".strip() or c.get("login"),
                    "login": c.get("login", ""),
                }
                for c in amb["candidates"][:8]
            ]
            return None, options, f"Found multiple matching users for '{amb['matched_term']}': {', '.join(o['name'] for o in options)}"

        if res["resolved_users"]:
            first_user = res["resolved_users"][0]
            notice = "; ".join(res["notices"])
            return first_user, [first_user], notice

        return None, [], None
