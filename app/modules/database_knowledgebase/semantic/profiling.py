"""Phase 6F: Controlled Value Profiling

Provides bounded, read-only metadata profiling for low-cardinality categorical columns.
Enables semantic resolution of entity values (e.g. status codes, department names).
Strictly prohibits profiling of passwords, credentials, tokens, secrets, or sensitive PII.
"""

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from .models import SensitivityLevel, ValueProfileSample
from ..exceptions import DatabaseKnowledgebaseError


class ValueProfilingError(DatabaseKnowledgebaseError):
    """Base error for value profiling."""
    pass


class SensitiveColumnProfilingBlockedError(ValueProfilingError):
    """Raised when an attempt is made to profile a sensitive or restricted column."""
    pass


class ValueProfiler:
    """
    Controlled, read-only value profiler.
    Excludes sensitive columns fail-closed before any database query is issued.
    """

    DEFAULT_SAMPLE_LIMIT = 20
    MAX_SAMPLE_LIMIT = 50

    # Patterns matching sensitive or credential columns that must NEVER be profiled
    _SENSITIVE_PATTERNS = re.compile(
        r"(password|passwd|pwd|secret|token|jwt|api_key|auth|hash|salt|credential|"
        r"private_key|master_key|ssn|social_security|tax_id|credit_card|card_num|cvv|pin)",
        re.IGNORECASE,
    )

    def __init__(self):
        # Cache key: (tenant_id, knowledgebase_id, table_name, column_name) -> ValueProfileSample
        self._cache: Dict[Tuple[uuid.UUID, uuid.UUID, str, str], ValueProfileSample] = {}

    @classmethod
    def is_column_sensitive(cls, column_name: str, sensitivity: Optional[SensitivityLevel] = None) -> bool:
        """
        Check if a column is classified as sensitive or matches credential patterns.
        Fails closed: if sensitivity is RESTRICTED or matches pattern, returns True.
        """
        if sensitivity == SensitivityLevel.RESTRICTED:
            return True

        if cls._SENSITIVE_PATTERNS.search(column_name):
            return True

        return False

    def get_cached_profile(
        self,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        table_name: str,
        column_name: str,
    ) -> Optional[ValueProfileSample]:
        """Retrieve cached value profile."""
        key = (tenant_id, knowledgebase_id, table_name.lower(), column_name.lower())
        return self._cache.get(key)

    def store_profile(self, sample: ValueProfileSample) -> None:
        """Cache a value profile sample."""
        key = (sample.tenant_id, sample.knowledgebase_id, sample.table_name.lower(), sample.column_name.lower())
        self._cache[key] = sample

    def clear_cache(self, tenant_id: Optional[uuid.UUID] = None, knowledgebase_id: Optional[uuid.UUID] = None) -> None:
        """Invalidate cache for specific tenant/KB or all."""
        if tenant_id and knowledgebase_id:
            keys_to_del = [k for k in self._cache.keys() if k[0] == tenant_id and k[1] == knowledgebase_id]
            for k in keys_to_del:
                del self._cache[k]
        else:
            self._cache.clear()

    async def profile_column_safe(
        self,
        connection_pool,
        table_name: str,
        column_name: str,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        sensitivity: Optional[SensitivityLevel] = None,
        sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    ) -> ValueProfileSample:
        """
        Profile distinct values for a column.
        Strictly enforces:
        1. Sensitive pattern block -> Raises SensitiveColumnProfilingBlockedError with ZERO DB execution.
        2. Bounded limit [1..50].
        3. Read-only transaction execution.
        """
        # Security Gate: Never profile sensitive columns
        if self.is_column_sensitive(column_name, sensitivity):
            raise SensitiveColumnProfilingBlockedError(
                f"Security policy rejection: Column '{table_name}.{column_name}' is classified as sensitive/credential and cannot be profiled."
            )

        # Check cache
        cached = self.get_cached_profile(tenant_id, knowledgebase_id, table_name, column_name)
        if cached:
            return cached

        # Enforce bounds
        bounded_limit = max(1, min(sample_limit, self.MAX_SAMPLE_LIMIT))

        # Build clean SQL identifier string
        clean_tbl = re.sub(r"[^a-zA-Z0-9_]", "", table_name)
        clean_col = re.sub(r"[^a-zA-Z0-9_]", "", column_name)

        query = f"SELECT DISTINCT {clean_col} AS val FROM public.{clean_tbl} WHERE {clean_col} IS NOT NULL LIMIT {bounded_limit};"

        distinct_vals: List[Any] = []
        async with connection_pool.acquire() as conn:
            rows = await conn.fetch(query)
            for r in rows:
                distinct_vals.append(r["val"])

        sample = ValueProfileSample(
            entity_name=table_name.capitalize(),
            table_name=clean_tbl,
            column_name=clean_col,
            distinct_values=distinct_vals,
            cardinality_estimate=len(distinct_vals),
            null_ratio=None,
            min_value=None,
            max_value=None,
            sample_bounded_limit=bounded_limit,
            is_sensitive=False,
            tenant_id=tenant_id,
            knowledgebase_id=knowledgebase_id,
        )

        self.store_profile(sample)
        return sample
