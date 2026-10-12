"""Phase 3 In-Memory Cache for Step 3.10

Caches per (kb_id, schema_version):
- Relationship graph
- Glossary map
- Table and column doc metadata
In-memory with TTL and maximum size cap. Automatically invalidates on schema_version change.
"""

import time
import uuid
from typing import Dict, Any, Optional


class KnowledgeCache:
    """Thread-safe LRU-like in-memory cache with TTL and capacity limits."""

    def __init__(self, default_ttl_sec: float = 300.0, max_entries: int = 500):
        self.default_ttl = default_ttl_sec
        self.max_entries = max_entries
        self._store: Dict[str, Dict[str, Any]] = {}
        # Track current active schema_version per kb_id for instant cache invalidation
        self._active_versions: Dict[str, str] = {}

    def _make_key(self, kb_id: uuid.UUID | str, schema_version: str, item_type: str) -> str:
        return f"{kb_id}:{schema_version}:{item_type}"

    def check_version_invalidation(self, kb_id: uuid.UUID | str, current_version: str):
        """Invalidate all cached items for this kb_id if schema_version changed."""
        s_kb = str(kb_id)
        last_ver = self._active_versions.get(s_kb)
        if last_ver and last_ver != current_version:
            # Drop all keys starting with this kb_id
            keys_to_del = [k for k in self._store if k.startswith(f"{s_kb}:")]
            for k in keys_to_del:
                self._store.pop(k, None)
        self._active_versions[s_kb] = current_version

    def get(self, kb_id: uuid.UUID | str, schema_version: str, item_type: str) -> Optional[Any]:
        self.check_version_invalidation(kb_id, schema_version)
        key = self._make_key(kb_id, schema_version, item_type)
        entry = self._store.get(key)
        if not entry:
            return None

        if time.time() > entry["expires_at"]:
            self._store.pop(key, None)
            return None

        return entry["value"]

    def set(
        self,
        kb_id: uuid.UUID | str,
        schema_version: str,
        item_type: str,
        value: Any,
        ttl_sec: Optional[float] = None,
    ):
        self.check_version_invalidation(kb_id, schema_version)
        key = self._make_key(kb_id, schema_version, item_type)

        # Evict oldest if exceeding max entries
        if len(self._store) >= self.max_entries:
            oldest_key = min(self._store.keys(), key=lambda k: self._store[k]["expires_at"])
            self._store.pop(oldest_key, None)

        ttl = ttl_sec if ttl_sec is not None else self.default_ttl
        self._store[key] = {
            "value": value,
            "expires_at": time.time() + ttl,
        }

    def clear(self):
        self._store.clear()
        self._active_versions.clear()


# Global singleton cache instance for retrieval
knowledge_cache = KnowledgeCache()
