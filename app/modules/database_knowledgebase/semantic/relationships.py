"""Phase 6C: Approved Semantic Relationship Graph

Provides an approved semantic relationship graph that governs table join paths.
Enforces that only vetted, semantically approved join paths are ever used in query planning.
Prevents unneeded candidate joins and cartesian expansions.
"""

from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Dict, List, Optional, Set, Tuple
import uuid

from .models import ApprovedRelationship, RelationshipCardinality
from ..exceptions import DatabaseKnowledgebaseError


class RelationshipGraphError(DatabaseKnowledgebaseError):
    """Base error for relationship graph operations."""
    pass


class DuplicateRelationshipError(RelationshipGraphError):
    """Raised when an approved relationship already exists."""
    pass


class RelationshipNotFoundError(RelationshipGraphError):
    """Raised when a relationship cannot be found."""
    pass


class UnauthorizedRelationshipError(RelationshipGraphError):
    """Raised when an unapproved join is attempted."""
    pass


class InvalidRelationshipPayloadError(RelationshipGraphError):
    """Raised when relationship metadata contains prohibited content."""
    pass


class SemanticRelationshipGraph:
    """
    Registry and pathfinder for approved semantic relationships.
    Governs table joins deterministically: only approved paths can be joined in QueryPlanner.
    """

    _INJECTION_PATTERN = re.compile(
        r"(\b(ignore\s+(?:all\s+)?(?:previous\s+)?(?:instructions|rules|safety|security\s+policy)|"
        r"disregard\s+(?:all\s+)?(?:rules|instructions)|override\s+system\s+prompt|bypass\s+security|"
        r"drop\s+table|delete\s+from|update\s+\w+\s+set|truncate\s+table|alter\s+table|<script|<\?xml)\b)",
        re.IGNORECASE,
    )

    def __init__(self):
        # Key: (tenant_id, knowledgebase_id) -> Dict[relationship_id, ApprovedRelationship]
        self._storage: Dict[Tuple[uuid.UUID, uuid.UUID], Dict[str, ApprovedRelationship]] = {}
        # Version counter per KB
        self._versions: Dict[Tuple[uuid.UUID, uuid.UUID], int] = {}

    def _validate_safe_text(self, text: Optional[str], field_name: str) -> None:
        if not text:
            return
        match = self._INJECTION_PATTERN.search(text)
        if match:
            raise InvalidRelationshipPayloadError(
                f"Security rejection: Prohibited adversarial sequence detected in {field_name}: '{match.group(0)}'"
            )

    def _get_kb_storage(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> Dict[str, ApprovedRelationship]:
        key = (tenant_id, knowledgebase_id)
        if key not in self._storage:
            self._storage[key] = {}
            self._versions[key] = 1
        return self._storage[key]

    def _bump_version(self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID) -> int:
        key = (tenant_id, knowledgebase_id)
        self._versions[key] = self._versions.get(key, 1) + 1
        return self._versions[key]

    def register_relationship(self, rel: ApprovedRelationship) -> ApprovedRelationship:
        """Register an approved semantic relationship."""
        self._validate_safe_text(rel.relationship_id, "relationship.id")
        self._validate_safe_text(rel.business_description, "relationship.description")
        for app in rel.approved_for:
            self._validate_safe_text(app, "relationship.approved_for")

        storage = self._get_kb_storage(rel.tenant_id, rel.knowledgebase_id)

        if rel.relationship_id in storage:
            raise DuplicateRelationshipError(
                f"Relationship with ID '{rel.relationship_id}' already exists."
            )

        storage[rel.relationship_id] = rel
        self._bump_version(rel.tenant_id, rel.knowledgebase_id)
        return rel

    def get_relationship(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID, rel_id: str
    ) -> Optional[ApprovedRelationship]:
        """Get relationship by ID."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        return storage.get(rel_id)

    def list_relationships(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> List[ApprovedRelationship]:
        """List all relationships for KB sorted deterministically."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        return sorted(list(storage.values()), key=lambda r: r.relationship_id)

    def delete_relationship(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID, rel_id: str
    ) -> bool:
        """Delete relationship."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if rel_id in storage:
            del storage[rel_id]
            self._bump_version(tenant_id, knowledgebase_id)
            return True
        return False

    def is_join_approved(
        self,
        source_table: str,
        target_table: str,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        purpose: Optional[str] = None,
        schema_version: Optional[str] = None,
    ) -> bool:
        """Verify whether a direct join between two tables is approved."""
        path = self.find_approved_join_path(
            source_table=source_table,
            target_table=target_table,
            tenant_id=tenant_id,
            knowledgebase_id=knowledgebase_id,
            purpose=purpose,
            schema_version=schema_version,
            max_hops=1,
        )
        return path is not None and len(path) == 1

    def find_approved_join_path(
        self,
        source_table: str,
        target_table: str,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        purpose: Optional[str] = None,
        schema_version: Optional[str] = None,
        max_hops: int = 3,
    ) -> Optional[List[ApprovedRelationship]]:
        """
        Find shortest approved join path between source_table and target_table using BFS.
        Ensures tenant boundary, schema version compatibility, and approved business scope.
        """
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if not storage:
            return None

        src_clean = source_table.strip().lower()
        tgt_clean = target_table.strip().lower()

        if src_clean == tgt_clean:
            return []

        # Build adjacency graph of approved edges
        # Table -> List of (neighbor_table, relationship_obj)
        adj: Dict[str, List[Tuple[str, ApprovedRelationship]]] = {}

        for rel in storage.values():
            # Check schema version compatibility if supplied
            if schema_version and rel.schema_version and rel.schema_version != schema_version:
                continue

            # Check purpose filtering if requested
            if purpose and rel.approved_for:
                purpose_clean = purpose.strip().lower()
                matches_purpose = any(purpose_clean in app.lower() for app in rel.approved_for)
                if not matches_purpose:
                    continue

            s_tbl = rel.source_table.strip().lower()
            t_tbl = rel.target_table.strip().lower()

            if s_tbl not in adj:
                adj[s_tbl] = []
            if t_tbl not in adj:
                adj[t_tbl] = []

            # Add forward and reverse traversals
            adj[s_tbl].append((t_tbl, rel))
            adj[t_tbl].append((s_tbl, rel))

        # BFS shortest path
        queue = deque([(src_clean, [])])
        visited: Set[str] = {src_clean}

        while queue:
            current_tbl, current_path = queue.popleft()

            if len(current_path) >= max_hops:
                continue

            for neighbor, rel in adj.get(current_tbl, []):
                if neighbor == tgt_clean:
                    return current_path + [rel]

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, current_path + [rel]))

        return None

    def compute_fingerprint(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> str:
        """Compute deterministic SHA256 fingerprint of all relationships."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if not storage:
            return hashlib.sha256(b"empty_relationship_graph").hexdigest()

        rels_data = []
        for rel in sorted(storage.values(), key=lambda r: r.relationship_id):
            rels_data.append({
                "id": rel.relationship_id,
                "src_entity": rel.source_entity,
                "tgt_entity": rel.target_entity,
                "src_tbl": rel.source_table,
                "tgt_tbl": rel.target_table,
                "src_cols": sorted(rel.source_columns),
                "tgt_cols": sorted(rel.target_columns),
                "card": rel.cardinality.value,
                "app": sorted(rel.approved_for),
                "conf": rel.confidence,
                "ver": rel.version,
            })

        canonical_json = json.dumps(rels_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
