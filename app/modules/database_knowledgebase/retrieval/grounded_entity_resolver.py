"""Grounded Entity Resolver for Database Knowledge Base

Resolves specific entity mentions (such as user full names, logins, or tokens)
from database queries to concrete primary keys (e.g. User ID 113), preventing
ambiguity, guesswork, or hallucinated filter values.
Directly implements the pattern from D:\\DB\\main\\app\\pipeline\\entity_resolver.py.
"""

import re
import logging
from typing import List, Dict, Any, Tuple, Optional, Callable
from ..execution.executor import ReadOnlyDatabaseExecutor
from ..schemas.connection import DatabaseConnectionConfig

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "what", "where", "when", "which", "how", "many", "does", "have", "with", "from",
    "show", "list", "give", "find", "get", "each", "tell", "name", "user", "users",
    "project", "projects", "task", "tasks", "work", "package", "packages", "detail",
    "details", "progress", "status", "update", "today", "yesterday", "date", "time",
    "open", "closed", "assign", "assigned", "assignee", "role", "team", "the", "for",
    "and", "all", "are", "there", "in", "on", "at", "to", "by", "is", "a", "an", "of",
    "table", "database", "exist", "created", "updated", "total", "count", "sum", "average"
}


class GroundedEntityResolver:
    """Resolves specific user and entity mentions against the connected database."""

    _user_cache: Dict[str, List[Dict[str, Any]]] = {}

    @classmethod
    async def get_all_users(
        cls,
        conn_config: DatabaseConnectionConfig,
        kb_id: str,
    ) -> List[Dict[str, Any]]:
        """Fetch active users with in-memory caching keyed by KB ID."""
        if kb_id in cls._user_cache:
            return cls._user_cache[kb_id]

        from ..execution.connection_helper import connect_to_database

        sql = """
            SELECT id, login, firstname, lastname, mail 
            FROM public.users 
            WHERE status != 3 
            ORDER BY id
        """
        conn = None
        try:
            conn = await connect_to_database(db_config=conn_config, timeout_seconds=5.0, read_only=True)
            if hasattr(conn, "fetch"):
                records = await conn.fetch(sql)
                users = [
                    {
                        "id": r["id"],
                        "login": r["login"] or "",
                        "firstname": r["firstname"] or "",
                        "lastname": r["lastname"] or "",
                        "mail": r["mail"] or "",
                    }
                    for r in records
                ]
            else:
                async with conn.cursor() as cur:
                    await cur.execute(sql)
                    records = await cur.fetchall()
                    users = [
                        {
                            "id": r.get("id"),
                            "login": r.get("login") or "",
                            "firstname": r.get("firstname") or "",
                            "lastname": r.get("lastname") or "",
                            "mail": r.get("mail") or "",
                        }
                        for r in records
                    ]

            cls._user_cache[kb_id] = users
            return users
        except Exception as exc:
            logger.warning(f"[GroundedEntityResolver] Could not fetch users from DB: {exc}")
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
    def find_user_candidates(
        cls,
        question: str,
        users: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Find matching users in the question.
        Returns (matched_term, list_of_matching_user_dicts).
        """
        if not users:
            return ("", [])

        q_clean = re.sub(r"['’]s\b", "", question.lower())
        q_lower = q_clean

        # 1. Exact full name match: e.g. "arun n", "arun kumar", "girinath rg"
        full_matches = []
        for u in users:
            fn = (u.get("firstname") or "").strip().lower()
            ln = (u.get("lastname") or "").strip().lower()
            full_name = f"{fn} {ln}".strip()

            if full_name and len(full_name) > 2:
                pattern = r'\b' + re.escape(full_name) + r'\b'
                if re.search(pattern, q_lower):
                    full_matches.append(u)

        if full_matches:
            unique_full = list({u["id"]: u for u in full_matches}.values())
            return ("full_name", unique_full)

        # 2. Token match across login, firstname, and lastname
        words = re.findall(r'[a-zA-Z0-9_]+', q_clean)
        candidate_tokens = [w for w in words if len(w) >= 3 and w not in STOP_WORDS]

        for token in candidate_tokens:
            matched = []
            for u in users:
                fn = (u.get("firstname") or "").strip().lower()
                ln = (u.get("lastname") or "").strip().lower()
                login = (u.get("login") or "").strip().lower()

                if token == fn or token == ln or token == login:
                    matched.append(u)

            if matched:
                unique_matched = list({u["id"]: u for u in matched}.values())
                return (token, unique_matched)

        return ("", [])
