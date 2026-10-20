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
    def resolve_user_mention(
        cls, user_query: str, users: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Match words in query against users.
        Returns: (resolved_user, candidates, notice_or_error)
        """
        if not users:
            return None, [], None

        tokens = re.findall(r'[a-zA-Z]{3,}', user_query.lower())
        stop_words = {"what", "were", "when", "show", "tell", "list", "have", "been", "done", "this", "week", "month", "task", "work", "package", "project", "open", "closed", "todo"}
        tokens = [t for t in tokens if t not in stop_words]

        candidates = []
        for u in users:
            fn = str(u.get("firstname") or "").lower()
            ln = str(u.get("lastname") or "").lower()
            login = str(u.get("login") or u.get("username") or "").lower()
            full_name = f"{fn} {ln}".strip()

            for tok in tokens:
                if tok in full_name or tok in login:
                    if u not in candidates:
                        candidates.append(u)
                    break

        if len(candidates) == 1:
            cand = candidates[0]
            display_name = f"{cand.get('firstname', '')} {cand.get('lastname', '')}".strip() or cand.get('login')
            notice = f"Targeting resolved user '{display_name}' (ID: {cand.get('id')})"
            return cand, candidates, notice

        elif len(candidates) > 1:
            options = [
                {
                    "id": c.get("id"),
                    "name": f"{c.get('firstname', '')} {c.get('lastname', '')}".strip() or c.get("login"),
                    "login": c.get("login", ""),
                }
                for c in candidates[:8]
            ]
            return None, options, f"Found multiple matching users: {', '.join(o['name'] for o in options)}"

        return None, [], None
