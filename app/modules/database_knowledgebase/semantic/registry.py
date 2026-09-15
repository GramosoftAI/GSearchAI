"""Phase 6A: Semantic Model Registry

Provides a first-class, versioned, tenant-isolated registry for semantic entities
and their attributes. Maps business concepts to physical tables/columns without
compromising database schema isolation or security policies.
"""

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Dict, List, Optional, Set, Tuple
import uuid

from pydantic import ValidationError

from .models import (
    SemanticAttribute,
    SemanticEntity,
    SemanticOperation,
    SensitivityLevel,
)
from ..exceptions import DatabaseKnowledgebaseError


class SemanticRegistryError(DatabaseKnowledgebaseError):
    """Base error for semantic registry operations."""
    pass


class DuplicateEntityError(SemanticRegistryError):
    """Raised when an entity with the same name/ID already exists in the KB."""
    pass


class EntityNotFoundError(SemanticRegistryError):
    """Raised when an entity is not found in the registry."""
    pass


class InvalidSemanticPayloadError(SemanticRegistryError):
    """Raised when semantic entity or attribute payload fails validation or security checks."""
    pass


class SemanticModelRegistry:
    """
    In-memory / persistence registry for semantic entities and attributes.
    Enforces strict tenant isolation, KB isolation, versioning, and deterministic fingerprinting.
    """

    # Adversarial / injection regex for semantic metadata inputs
    _INJECTION_PATTERN = re.compile(
        r"(\b(ignore\s+(?:all\s+)?(?:previous\s+)?(?:instructions|rules|safety|security\s+policy)|"
        r"disregard\s+(?:all\s+)?(?:rules|instructions)|override\s+system\s+prompt|bypass\s+security|"
        r"drop\s+table|delete\s+from|update\s+\w+\s+set|truncate\s+table|alter\s+table|<script|<\?xml)\b)",
        re.IGNORECASE,
    )

    def __init__(self):
        # Key: (tenant_id, knowledgebase_id) -> Dict[entity_id, SemanticEntity]
        self._storage: Dict[Tuple[uuid.UUID, uuid.UUID], Dict[str, SemanticEntity]] = {}
        # Version counter per (tenant_id, knowledgebase_id)
        self._versions: Dict[Tuple[uuid.UUID, uuid.UUID], int] = {}

    def _validate_safe_text(self, text: Optional[str], field_name: str) -> None:
        """Ensure semantic names, descriptions, and synonyms do not contain injection attempts."""
        if not text:
            return
        match = self._INJECTION_PATTERN.search(text)
        if match:
            raise InvalidSemanticPayloadError(
                f"Security rejection: Prohibited adversarial sequence detected in {field_name}: '{match.group(0)}'"
            )

    def _get_kb_storage(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> Dict[str, SemanticEntity]:
        key = (tenant_id, knowledgebase_id)
        if key not in self._storage:
            self._storage[key] = {}
            self._versions[key] = 1
        return self._storage[key]

    def _bump_version(self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID) -> int:
        key = (tenant_id, knowledgebase_id)
        self._versions[key] = self._versions.get(key, 1) + 1
        return self._versions[key]

    def register_entity(self, entity: SemanticEntity) -> SemanticEntity:
        """
        Create a new semantic entity in the registry.
        Enforces uniqueness of entity_id and entity.name within tenant and KB.
        """
        # 1. Validate security of strings
        self._validate_safe_text(entity.name, "entity.name")
        self._validate_safe_text(entity.display_name, "entity.display_name")
        self._validate_safe_text(entity.description, "entity.description")
        for syn in entity.synonyms:
            self._validate_safe_text(syn, "entity.synonym")

        for attr in entity.attributes.values():
            self._validate_safe_text(attr.display_name, f"attribute.{attr.attribute_id}.display_name")
            self._validate_safe_text(attr.description, f"attribute.{attr.attribute_id}.description")
            for syn in attr.synonyms:
                self._validate_safe_text(syn, f"attribute.{attr.attribute_id}.synonym")

        storage = self._get_kb_storage(entity.tenant_id, entity.knowledgebase_id)

        # 2. Check duplicates
        if entity.entity_id in storage:
            raise DuplicateEntityError(
                f"Semantic entity with ID '{entity.entity_id}' already exists in this knowledgebase."
            )

        clean_name = entity.name.strip().lower()
        for existing in storage.values():
            if existing.name.strip().lower() == clean_name:
                raise DuplicateEntityError(
                    f"Semantic entity with name '{entity.name}' already exists in this knowledgebase."
                )

        # 3. Store entity
        storage[entity.entity_id] = entity
        self._bump_version(entity.tenant_id, entity.knowledgebase_id)
        return entity

    def get_entity(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID, entity_id: str
    ) -> Optional[SemanticEntity]:
        """Retrieve semantic entity by entity_id with strict tenant/KB boundary."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        return storage.get(entity_id)

    def get_entity_by_name(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID, entity_name: str
    ) -> Optional[SemanticEntity]:
        """Retrieve semantic entity by canonical business name (case-insensitive)."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        clean_name = entity_name.strip().lower()
        for entity in storage.values():
            if entity.name.strip().lower() == clean_name:
                return entity
        return None

    def get_entity_by_table(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID, table_name: str
    ) -> Optional[SemanticEntity]:
        """Retrieve semantic entity mapped to a physical table name."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        clean_table = table_name.strip().lower()
        for entity in storage.values():
            if entity.physical_table.strip().lower() == clean_table:
                return entity
        return None

    def list_entities(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> List[SemanticEntity]:
        """List all semantic entities for a given tenant and KB."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        # Return sorted deterministically by entity name
        return sorted(list(storage.values()), key=lambda e: e.name.lower())

    def update_entity(self, entity: SemanticEntity) -> SemanticEntity:
        """Update an existing semantic entity."""
        storage = self._get_kb_storage(entity.tenant_id, entity.knowledgebase_id)
        if entity.entity_id not in storage:
            raise EntityNotFoundError(
                f"Cannot update: entity with ID '{entity.entity_id}' does not exist."
            )

        # Validate security
        self._validate_safe_text(entity.name, "entity.name")
        self._validate_safe_text(entity.display_name, "entity.display_name")
        for syn in entity.synonyms:
            self._validate_safe_text(syn, "entity.synonym")

        clean_name = entity.name.strip().lower()
        for e_id, existing in storage.items():
            if e_id != entity.entity_id and existing.name.strip().lower() == clean_name:
                raise DuplicateEntityError(
                    f"Another semantic entity with name '{entity.name}' already exists."
                )

        entity.version = storage[entity.entity_id].version + 1
        entity.updated_at = datetime.now(timezone.utc)
        storage[entity.entity_id] = entity
        self._bump_version(entity.tenant_id, entity.knowledgebase_id)
        return entity

    def delete_entity(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID, entity_id: str
    ) -> bool:
        """Delete an entity from the registry."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if entity_id in storage:
            del storage[entity_id]
            self._bump_version(tenant_id, knowledgebase_id)
            return True
        return False

    def resolve_entities(
        self,
        query: str,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
    ) -> List[Tuple[SemanticEntity, float, List[str]]]:
        """
        Deterministically resolve natural language query terms against registered entities.
        Returns a list of (SemanticEntity, confidence_score, matched_tokens) sorted by confidence desc.
        """
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if not storage:
            return []

        tokens = set(re.findall(r"\b[a-zA-Z0-9_]+\b", query.lower()))
        matched_results: List[Tuple[SemanticEntity, float, List[str]]] = []

        for entity in storage.values():
            matched_tokens = []
            score = 0.0

            # 1. Exact entity name match
            clean_name = entity.name.lower()
            if clean_name in tokens or clean_name in query.lower():
                score += 1.0
                matched_tokens.append(entity.name)

            # 2. Physical table match
            clean_tbl = entity.physical_table.lower()
            if clean_tbl in tokens:
                score += 0.9
                matched_tokens.append(entity.physical_table)

            # 3. Synonym matches
            for syn in entity.synonyms:
                clean_syn = syn.lower()
                if clean_syn in tokens or clean_syn in query.lower():
                    score += 0.8
                    matched_tokens.append(syn)

            # 4. Attribute synonym / name matches
            for attr in entity.attributes.values():
                if attr.physical_column.lower() in tokens:
                    score += 0.5
                    matched_tokens.append(attr.physical_column)
                for syn in attr.synonyms:
                    if syn.lower() in tokens or syn.lower() in query.lower():
                        score += 0.4
                        matched_tokens.append(syn)

            if score > 0:
                normalized_confidence = min(1.0, score)
                matched_results.append((entity, normalized_confidence, list(set(matched_tokens))))

        # Sort by confidence descending, then by name for determinism
        matched_results.sort(key=lambda item: (-item[1], item[0].name))
        return matched_results

    def compute_fingerprint(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> str:
        """
        Compute deterministic SHA256 fingerprint of all entities in the registry.
        Changes to any entity name, table, column, or synonym automatically alters the fingerprint.
        """
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if not storage:
            return hashlib.sha256(b"empty_semantic_registry").hexdigest()

        # Build canonical ordered representation
        entities_data = []
        for entity in sorted(storage.values(), key=lambda e: e.name.lower()):
            attrs_data = []
            for attr in sorted(entity.attributes.values(), key=lambda a: a.attribute_id):
                attrs_data.append({
                    "id": attr.attribute_id,
                    "col": attr.physical_column,
                    "syns": sorted(attr.synonyms),
                    "is_dim": attr.is_dimension,
                    "is_meas": attr.is_measure,
                    "sens": attr.sensitivity.value,
                })

            entities_data.append({
                "id": entity.entity_id,
                "name": entity.name,
                "table": entity.physical_table,
                "schema": entity.physical_schema,
                "syns": sorted(entity.synonyms),
                "attrs": attrs_data,
                "ver": entity.version,
            })

        canonical_json = json.dumps(entities_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
