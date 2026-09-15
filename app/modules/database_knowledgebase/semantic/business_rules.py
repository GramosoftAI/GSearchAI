"""Phase 6D: Structured Business Rule Registry

Provides structured, deterministic business and operational rule definitions.
Governs default filters (e.g. active employees), exclusions, and operational constraints
prior to SQL generation. Strictly prohibits unvetted or executable SQL payloads.
"""

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Dict, List, Optional, Set, Tuple
import uuid

import sqlglot
from sqlglot import exp

from .models import BusinessRule, RuleScope
from ..exceptions import DatabaseKnowledgebaseError


class BusinessRuleError(DatabaseKnowledgebaseError):
    """Base error for business rule operations."""
    pass


class DuplicateRuleError(BusinessRuleError):
    """Raised when a business rule with the same ID or name already exists."""
    pass


class RuleNotFoundError(BusinessRuleError):
    """Raised when a business rule cannot be found."""
    pass


class InvalidBusinessRuleError(BusinessRuleError):
    """Raised when a rule condition is malformed, malicious, or unapproved."""
    pass


class ConflictingBusinessRuleError(BusinessRuleError):
    """Raised when two active business rules define contradictory constraints."""
    pass


class BusinessRuleRegistry:
    """
    Registry and deterministic evaluator for operational business rules.
    Injects required predicates into QueryPlanIR before SQL generation.
    """

    _INJECTION_PATTERN = re.compile(
        r"(\b(ignore\s+(?:all\s+)?(?:previous\s+)?(?:instructions|rules|safety|security\s+policy)|"
        r"disregard\s+(?:all\s+)?(?:rules|instructions)|override\s+system\s+prompt|bypass\s+security|"
        r"drop\s+table|delete\s+from|update\s+\w+\s+set|truncate\s+table|alter\s+table|<script|<\?xml)\b)",
        re.IGNORECASE,
    )

    def __init__(self):
        # Key: (tenant_id, knowledgebase_id) -> Dict[rule_id, BusinessRule]
        self._storage: Dict[Tuple[uuid.UUID, uuid.UUID], Dict[str, BusinessRule]] = {}
        # Version counter per KB
        self._versions: Dict[Tuple[uuid.UUID, uuid.UUID], int] = {}

    def _validate_safe_text(self, text: Optional[str], field_name: str) -> None:
        if not text:
            return
        match = self._INJECTION_PATTERN.search(text)
        if match:
            raise InvalidBusinessRuleError(
                f"Security rejection: Prohibited adversarial sequence detected in {field_name}: '{match.group(0)}'"
            )

    def _validate_condition(self, condition: str) -> None:
        """Validate that rule condition is a safe boolean predicate expression."""
        self._validate_safe_text(condition, "rule.condition_expression")

        try:
            parsed = sqlglot.parse_one(f"SELECT * WHERE {condition}", read="postgres")
        except Exception as e:
            raise InvalidBusinessRuleError(f"Malformed rule condition expression '{condition}': {e}")

        # Check for disallowed operations or statement types
        where_clause = parsed.find(exp.Where)
        if not where_clause:
            raise InvalidBusinessRuleError(
                f"Rule condition '{condition}' is not a valid boolean filter predicate."
            )

        # Ensure no DDL, DML, or catalogs inside condition
        for tbl in parsed.find_all(exp.Table):
            tbl_name = tbl.name.lower()
            if tbl_name.startswith("pg_") or tbl_name.startswith("information_schema"):
                raise InvalidBusinessRuleError(
                    f"Security rejection: Access to system catalog '{tbl_name}' in business rule is forbidden."
                )

        if re.search(r"\b(drop|delete|update|insert|alter|truncate|exec|execute)\b", condition, re.IGNORECASE):
            raise InvalidBusinessRuleError(
                f"Security rejection: Prohibited SQL command in rule condition: '{condition}'"
            )

    def _get_kb_storage(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> Dict[str, BusinessRule]:
        key = (tenant_id, knowledgebase_id)
        if key not in self._storage:
            self._storage[key] = {}
            self._versions[key] = 1
        return self._storage[key]

    def _bump_version(self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID) -> int:
        key = (tenant_id, knowledgebase_id)
        self._versions[key] = self._versions.get(key, 1) + 1
        return self._versions[key]

    def register_rule(self, rule: BusinessRule) -> BusinessRule:
        """Register a new business rule."""
        self._validate_safe_text(rule.rule_id, "rule.rule_id")
        self._validate_safe_text(rule.name, "rule.name")
        self._validate_safe_text(rule.description, "rule.description")
        self._validate_safe_text(rule.effect_description, "rule.effect_description")

        self._validate_condition(rule.condition_expression)

        storage = self._get_kb_storage(rule.tenant_id, rule.knowledgebase_id)

        if rule.rule_id in storage:
            raise DuplicateRuleError(f"Business rule with ID '{rule.rule_id}' already exists.")

        clean_name = rule.name.strip().lower()
        for existing in storage.values():
            if existing.name.strip().lower() == clean_name:
                raise DuplicateRuleError(f"Business rule with name '{rule.name}' already exists.")

        storage[rule.rule_id] = rule
        self._bump_version(rule.tenant_id, rule.knowledgebase_id)
        return rule

    def get_rule(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID, rule_id: str
    ) -> Optional[BusinessRule]:
        """Get rule by ID."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        return storage.get(rule_id)

    def list_rules(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> List[BusinessRule]:
        """List all rules for KB sorted deterministically by priority desc, name asc."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        return sorted(list(storage.values()), key=lambda r: (-r.priority, r.name.lower()))

    def update_rule(self, rule: BusinessRule) -> BusinessRule:
        """Update an existing rule."""
        storage = self._get_kb_storage(rule.tenant_id, rule.knowledgebase_id)
        if rule.rule_id not in storage:
            raise RuleNotFoundError(f"Cannot update: rule with ID '{rule.rule_id}' not found.")

        self._validate_safe_text(rule.name, "rule.name")
        self._validate_safe_text(rule.description, "rule.description")
        self._validate_condition(rule.condition_expression)

        clean_name = rule.name.strip().lower()
        for r_id, existing in storage.items():
            if r_id != rule.rule_id and existing.name.strip().lower() == clean_name:
                raise DuplicateRuleError(f"Another rule with name '{rule.name}' already exists.")

        rule.version = storage[rule.rule_id].version + 1
        rule.updated_at = datetime.now(timezone.utc)
        storage[rule.rule_id] = rule
        self._bump_version(rule.tenant_id, rule.knowledgebase_id)
        return rule

    def delete_rule(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID, rule_id: str
    ) -> bool:
        """Delete rule."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if rule_id in storage:
            del storage[rule_id]
            self._bump_version(tenant_id, knowledgebase_id)
            return True
        return False

    def get_applicable_rules(
        self,
        entities: List[str],
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        scope: Optional[RuleScope] = None,
    ) -> List[BusinessRule]:
        """
        Retrieve and order all active business rules applicable to the given entities.
        Detects and resolves rule conflicts.
        """
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if not storage:
            return []

        entity_set = {e.strip().lower() for e in entities}
        applicable: List[BusinessRule] = []

        for rule in storage.values():
            if rule.status != "ACTIVE":
                continue

            if scope and rule.scope != scope:
                continue

            rule_entities = {re_name.strip().lower() for re_name in rule.referenced_entities}
            # Rule applies if referenced entities intersect with query entities, or if rule is global (empty entities)
            if not rule_entities or rule_entities.intersection(entity_set):
                applicable.append(rule)

        # Sort by priority descending
        applicable.sort(key=lambda r: (-r.priority, r.name.lower()))

        # Check for contradictory column rules
        seen_column_conditions: Dict[str, BusinessRule] = {}
        for r in applicable:
            for col in r.referenced_columns:
                col_clean = col.strip().lower()
                if col_clean in seen_column_conditions:
                    prev_r = seen_column_conditions[col_clean]
                    if prev_r.priority == r.priority and prev_r.condition_expression != r.condition_expression:
                        raise ConflictingBusinessRuleError(
                            f"Conflicting business rules on column '{col}': '{prev_r.name}' vs '{r.name}' with equal priority {r.priority}"
                        )
                else:
                    seen_column_conditions[col_clean] = r

        return applicable

    def compute_fingerprint(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> str:
        """Compute deterministic SHA256 fingerprint of all business rules."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if not storage:
            return hashlib.sha256(b"empty_business_rules").hexdigest()

        rules_data = []
        for rule in sorted(storage.values(), key=lambda r: r.rule_id):
            rules_data.append({
                "id": rule.rule_id,
                "name": rule.name,
                "scope": rule.scope.value,
                "cond": rule.condition_expression,
                "entities": sorted(rule.referenced_entities),
                "cols": sorted(rule.referenced_columns),
                "prio": rule.priority,
                "status": rule.status,
                "ver": rule.version,
            })

        canonical_json = json.dumps(rules_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
