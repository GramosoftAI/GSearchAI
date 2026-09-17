"""Tenant-Isolated Schema Retrieval LRU Cache for Phase 3C

Provides an in-memory, thread-safe, bounded LRU cache for SchemaRetrievalResult objects.
Enforces strict multi-tenant isolation, version pinning, query normalization, and automatic
invalidation upon schema updates.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import logging
import re
import threading
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .retriever import SchemaRetrievalResult

logger = logging.getLogger(__name__)


class CacheEntry:
    """Internal container for cached schema retrieval outcome and expiration metadata."""
    __slots__ = ("result", "expires_at", "tenant_id", "kb_id")

    def __init__(self, result: Any, expires_at: float, tenant_id: str, kb_id: str):
        self.result = result
        self.expires_at = expires_at
        self.tenant_id = tenant_id
        self.kb_id = kb_id


class SchemaRetrievalCache:
    """
    Thread-safe, tenant-isolated, bounded LRU cache for sub-schema retrieval results.
    Keyed by: sha256(tenant_id : kb_id : schema_version : top_k_tables : top_k_cols : normalized_query).
    """

    _instance: Optional["SchemaRetrievalCache"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self, max_capacity: int = 1000, default_ttl_seconds: int = 3600):
        self.max_capacity = max_capacity
        self.default_ttl = default_ttl_seconds
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._entry_lock = threading.Lock()

        # Telemetry metrics
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    @classmethod
    def get_instance(cls, max_capacity: int = 1000, default_ttl_seconds: int = 3600) -> "SchemaRetrievalCache":
        """Thread-safe singleton accessor."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(max_capacity=max_capacity, default_ttl_seconds=default_ttl_seconds)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Testing utility to clear singleton state."""
        with cls._lock:
            cls._instance = None

    @staticmethod
    def normalize_query(query: str) -> str:
        """Canonicalize user natural language query for deterministic caching."""
        if not query:
            return ""
        # Lowercase, collapse consecutive whitespaces, strip leading/trailing spaces
        return re.sub(r"\s+", " ", query.strip().lower())

    @classmethod
    def generate_key(
        cls,
        tenant_id: str,
        kb_id: str,
        schema_version: str,
        user_query: str,
        top_k_tables: int = 5,
        top_k_columns: int = 25,
    ) -> str:
        """
        Generate cryptographic cache key strictly isolating tenant, knowledgebase,
        and schema version fingerprint.
        """
        norm_q = cls.normalize_query(user_query)
        payload = f"tenant:{str(tenant_id)}|kb:{str(kb_id)}|ver:{str(schema_version)}|t:{top_k_tables}|c:{top_k_columns}|q:{norm_q}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[SchemaRetrievalResult]:
        """
        Retrieve sub-schema outcome from cache if present and unexpired.
        Moves accessed item to most-recently-used position.
        """
        with self._entry_lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            now = datetime.now(timezone.utc).timestamp()
            if now > entry.expires_at:
                # Expired entry
                del self._cache[key]
                self._misses += 1
                return None

            # Hit: refresh LRU ordering
            self._cache.move_to_end(key, last=True)
            self._hits += 1
            return entry.result

    def set(
        self,
        key: str,
        result: SchemaRetrievalResult,
        tenant_id: str,
        kb_id: str,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store sub-schema outcome in cache with LRU eviction and TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        expires_at = datetime.now(timezone.utc).timestamp() + ttl

        with self._entry_lock:
            if key in self._cache:
                self._cache.move_to_end(key, last=True)
            elif len(self._cache) >= self.max_capacity:
                # Evict least-recently-used item
                self._cache.popitem(last=False)
                self._evictions += 1

            self._cache[key] = CacheEntry(
                result=result,
                expires_at=expires_at,
                tenant_id=str(tenant_id),
                kb_id=str(kb_id),
            )

    def invalidate_kb(self, tenant_id: str, kb_id: str) -> int:
        """
        Invalidate all cached sub-schemas for a specific Knowledgebase
        (e.g., when schema introspection runs or tables change).
        """
        tid = str(tenant_id)
        kid = str(kb_id)
        count = 0
        with self._entry_lock:
            keys_to_delete = [
                k for k, entry in self._cache.items()
                if entry.tenant_id == tid and entry.kb_id == kid
            ]
            for k in keys_to_delete:
                del self._cache[k]
                count += 1
        return count

    def invalidate_tenant(self, tenant_id: str) -> int:
        """Invalidate all cached entries for an entire tenant."""
        tid = str(tenant_id)
        count = 0
        with self._entry_lock:
            keys_to_delete = [
                k for k, entry in self._cache.items()
                if entry.tenant_id == tid
            ]
            for k in keys_to_delete:
                del self._cache[k]
                count += 1
        return count

    def clear(self) -> None:
        """Flush the entire cache."""
        with self._entry_lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    def get_metrics(self) -> Dict[str, Any]:
        """Return cache health and telemetry statistics."""
        with self._entry_lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total) if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "max_capacity": self.max_capacity,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": round(hit_rate, 4),
            }
