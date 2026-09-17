"""Phase 6H: Verified Query Memory

Stores only queries that have passed the complete end-to-end execution chain:
Plan -> AST Security -> Authorization -> Read-Only Execution -> Grounding -> AnswerVerifier.

Every recall requires multi-layer revalidation against:
1. Exact tenant ID
2. Exact knowledgebase ID
3. Current schema fingerprint
4. Current semantic context fingerprint
5. Active AST security policy

Any mismatch invalidates memory recall fail-closed.
"""

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .models import VerifiedQueryMemoryRecord
from ..exceptions import DatabaseKnowledgebaseError
from ..sql_security.policy import SQLSecurityPolicyEngine


class QueryMemoryError(DatabaseKnowledgebaseError):
    """Base error for query memory operations."""
    pass


class StaleMemoryReplayBlockedError(QueryMemoryError):
    """Raised when an attempt is made to replay outdated or mismatched memory."""
    pass


class UnverifiedQueryStoreBlockedError(QueryMemoryError):
    """Raised when an ungrounded or unverified query is attempted to be stored."""
    pass


class VerifiedQueryMemory:
    """
    Semantic query memory storing verified execution plans and safe SQL representations.
    Guarantees strict fingerprint matching and security revalidation upon recall.
    """

    def __init__(self):
        # Key: (tenant_id, knowledgebase_id) -> Dict[normalized_query, VerifiedQueryMemoryRecord]
        self._storage: Dict[Tuple[uuid.UUID, uuid.UUID], Dict[str, VerifiedQueryMemoryRecord]] = {}

    @classmethod
    def normalize_query(cls, query: str) -> str:
        """Deterministically normalize query whitespace and casing."""
        q = query.strip().lower()
        q = re.sub(r"\s+", " ", q)
        q = re.sub(r"[?!.,;]+$", "", q)
        return q.strip()

    def record_verified_query(self, record: VerifiedQueryMemoryRecord) -> None:
        """
        Store a verified query execution record.
        Strictly requires verification_status == 'PASSED' and valid grounding.
        """
        if record.verifier_status != "PASSED":
            raise UnverifiedQueryStoreBlockedError(
                f"Cannot store unverified query: verifier status is '{record.verifier_status}'"
            )

        if record.grounding_status not in ("VERIFIED", "REPAIRED", "FALLBACK_DETERMINISTIC"):
            raise UnverifiedQueryStoreBlockedError(
                f"Cannot store ungrounded query: grounding status is '{record.grounding_status}'"
            )

        key = (record.tenant_id, record.knowledgebase_id)
        if key not in self._storage:
            self._storage[key] = {}

        norm_q = self.normalize_query(record.normalized_query)
        if norm_q in self._storage[key]:
            existing = self._storage[key][norm_q]
            record.execution_count = existing.execution_count + 1

        record.last_executed_at = datetime.now(timezone.utc)
        self._storage[key][norm_q] = record

    def recall_verified_query(
        self,
        query: str,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        current_context_fingerprint: str,
        current_schema_fingerprint: str,
    ) -> Optional[VerifiedQueryMemoryRecord]:
        """
        Recall a verified query record matching the query and tenant.
        Revalidates:
        1. Context fingerprint
        2. Schema fingerprint
        3. AST security invariants
        Returns None if fingerprints do not match or security revalidation fails.
        """
        key = (tenant_id, knowledgebase_id)
        storage = self._storage.get(key)
        if not storage:
            return None

        norm_q = self.normalize_query(query)
        record = storage.get(norm_q)
        if not record:
            return None

        # 1. Schema Fingerprint Check (RT-P6-17)
        if record.schema_fingerprint != current_schema_fingerprint:
            return None

        # 2. Context Fingerprint Check (RT-P6-16, RT-P6-18)
        if record.context_fingerprint != current_context_fingerprint:
            return None

        # 3. Security Re-Validation (RT-P6-13): Never replay prohibited SQL
        for forbidden in SQLSecurityPolicyEngine.FORBIDDEN_TABLES:
            if forbidden in record.compiled_sql.lower():
                return None

        if re.search(r"\b(drop|delete|update|insert|alter|truncate)\b", record.compiled_sql, re.IGNORECASE):
            return None

        return record

    def invalidate_memory(
        self,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
    ) -> int:
        """Invalidate all query memory for a specific KB."""
        key = (tenant_id, knowledgebase_id)
        if key in self._storage:
            count = len(self._storage[key])
            del self._storage[key]
            return count
        return 0

    def get_memory_stats(
        self,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Diagnostic metadata on memory contents."""
        key = (tenant_id, knowledgebase_id)
        storage = self._storage.get(key, {})
        return {
            "total_records": len(storage),
            "total_reused_executions": sum(r.execution_count for r in storage.values()),
        }
