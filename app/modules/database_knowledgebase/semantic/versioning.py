"""Semantic Versioning and Schema Drift Engine

Tracks semantic model versions and schema fingerprints.
Detects schema drift and triggers deterministic cache invalidation
when client database schemas change.
"""

import hashlib
import json
from typing import Dict, Optional, Tuple
import uuid


class SemanticVersioningEngine:
    """
    Tracks and validates schema fingerprints and semantic versions.
    Enforces cache invalidation upon schema drift.
    """

    def __init__(self):
        # Key: (tenant_id, knowledgebase_id) -> (schema_fingerprint, semantic_version)
        self._versions: Dict[Tuple[uuid.UUID, uuid.UUID], Tuple[str, int]] = {}

    def get_version(self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID) -> Tuple[Optional[str], int]:
        """Returns (current_fingerprint, current_version)."""
        key = (tenant_id, knowledgebase_id)
        if key in self._versions:
            return self._versions[key]
        return (None, 1)

    def record_version(
        self,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        schema_fingerprint: str,
    ) -> int:
        """
        Records a new fingerprint. If the fingerprint changed, increments version.
        Returns the new semantic_version.
        """
        key = (tenant_id, knowledgebase_id)
        if key not in self._versions:
            self._versions[key] = (schema_fingerprint, 1)
            return 1

        old_fp, version = self._versions[key]
        if old_fp != schema_fingerprint:
            new_version = version + 1
            self._versions[key] = (schema_fingerprint, new_version)
            return new_version

        return version

    def has_drifted(
        self,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        current_fingerprint: str,
    ) -> bool:
        """Checks if the active schema fingerprint differs from recorded fingerprint."""
        key = (tenant_id, knowledgebase_id)
        if key not in self._versions:
            return False
        recorded_fp, _ = self._versions[key]
        return recorded_fp != current_fingerprint
