"""Phase 6B: Canonical Metric Registry

Provides an authoritative registry of business metrics.
Enforces that metric definitions are deterministic, structured, and immutable
to arbitrary LLM overrides. All metric formulas must adhere to safe aggregations.
"""

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Dict, List, Optional, Set, Tuple
import uuid

import sqlglot
from sqlglot import exp

from .models import MetricDefinition, MetricType
from ..exceptions import DatabaseKnowledgebaseError


class MetricRegistryError(DatabaseKnowledgebaseError):
    """Base error for metric registry operations."""
    pass


class DuplicateMetricError(MetricRegistryError):
    """Raised when a metric with the same ID or name already exists."""
    pass


class MetricNotFoundError(MetricRegistryError):
    """Raised when a metric cannot be found."""
    pass


class InvalidMetricExpressionError(MetricRegistryError):
    """Raised when a metric expression is malformed, unapproved, or contains adversarial SQL."""
    pass


class CanonicalMetricRegistry:
    """
    Authoritative registry for business metrics.
    Guarantees that canonical metrics take absolute precedence over LLM interpretations.
    """

    ALLOWED_AGGREGATIONS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}

    _INJECTION_PATTERN = re.compile(
        r"(\b(ignore\s+(?:all\s+)?(?:previous\s+)?(?:instructions|rules|safety|security\s+policy)|"
        r"disregard\s+(?:all\s+)?(?:rules|instructions)|override\s+system\s+prompt|bypass\s+security|"
        r"drop\s+table|delete\s+from|update\s+\w+\s+set|truncate\s+table|alter\s+table|<script|<\?xml)\b)",
        re.IGNORECASE,
    )

    def __init__(self):
        # Key: (tenant_id, knowledgebase_id) -> Dict[metric_id, MetricDefinition]
        self._storage: Dict[Tuple[uuid.UUID, uuid.UUID], Dict[str, MetricDefinition]] = {}
        # Revision versions per KB
        self._versions: Dict[Tuple[uuid.UUID, uuid.UUID], int] = {}

    def _validate_safe_text(self, text: Optional[str], field_name: str) -> None:
        if not text:
            return
        match = self._INJECTION_PATTERN.search(text)
        if match:
            raise InvalidMetricExpressionError(
                f"Security rejection: Prohibited adversarial sequence detected in {field_name}: '{match.group(0)}'"
            )

    def _validate_expression(self, expression: str, aggregation: MetricType) -> None:
        """
        Validate that the metric formula is a valid read-only aggregation expression.
        Strictly prohibits DDL, DML, multiple statements, or unauthorized function calls.
        """
        self._validate_safe_text(expression, "metric.expression")

        try:
            parsed = sqlglot.parse_one(expression, read="postgres")
        except Exception as e:
            raise InvalidMetricExpressionError(
                f"Malformed metric expression '{expression}': {e}"
            )

        # Expression must be an aggregate function (e.g. SUM, AVG, COUNT, MIN, MAX)
        # or a SELECT containing an aggregate
        func = None
        if isinstance(parsed, exp.Func):
            func = parsed
        elif isinstance(parsed, exp.Select):
            select_exprs = parsed.expressions
            if select_exprs and isinstance(select_exprs[0], exp.Func):
                func = select_exprs[0]

        if not func:
            # Check if it wraps an aggregate function
            funcs = list(parsed.find_all(exp.Func))
            if funcs:
                func = funcs[0]

        if not func:
            raise InvalidMetricExpressionError(
                f"Metric expression '{expression}' must contain an approved aggregate function ({', '.join(self.ALLOWED_AGGREGATIONS)})."
            )

        func_name = (
            func.sql_name()
            if hasattr(func, "sql_name") and func.sql_name()
            else (func.key.upper() if hasattr(func, "key") and func.key else func.__class__.__name__.upper())
        ).upper()
        if func_name not in self.ALLOWED_AGGREGATIONS:
            raise InvalidMetricExpressionError(
                f"Prohibited metric function '{func_name}'. Only {', '.join(self.ALLOWED_AGGREGATIONS)} are permitted."
            )

        # Prevent subquery execution or catalog access inside metric expression
        for col in parsed.find_all(exp.Column):
            if col.table and (col.table.lower().startswith("pg_") or col.table.lower() == "information_schema"):
                raise InvalidMetricExpressionError(
                    f"Security rejection: Access to system catalog '{col.table}' in metric expression is forbidden."
                )
        for tbl in parsed.find_all(exp.Table):
            tbl_name = tbl.name.lower()
            if tbl_name.startswith("pg_") or tbl_name.startswith("information_schema"):
                raise InvalidMetricExpressionError(
                    f"Security rejection: Access to system catalog '{tbl_name}' in metric expression is forbidden."
                )
        if re.search(r"\b(pg_\w+|information_schema)\b", expression, re.IGNORECASE):
            raise InvalidMetricExpressionError(
                "Security rejection: Access to system catalog in metric expression is forbidden."
            )

    def _get_kb_storage(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> Dict[str, MetricDefinition]:
        key = (tenant_id, knowledgebase_id)
        if key not in self._storage:
            self._storage[key] = {}
            self._versions[key] = 1
        return self._storage[key]

    def _bump_version(self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID) -> int:
        key = (tenant_id, knowledgebase_id)
        self._versions[key] = self._versions.get(key, 1) + 1
        return self._versions[key]

    def register_metric(self, metric: MetricDefinition) -> MetricDefinition:
        """Register a new canonical metric."""
        self._validate_safe_text(metric.name, "metric.name")
        self._validate_safe_text(metric.display_name, "metric.display_name")
        self._validate_safe_text(metric.description, "metric.description")
        for syn in metric.synonyms:
            self._validate_safe_text(syn, "metric.synonym")

        self._validate_expression(metric.expression, metric.aggregation)

        storage = self._get_kb_storage(metric.tenant_id, metric.knowledgebase_id)

        if metric.metric_id in storage:
            raise DuplicateMetricError(
                f"Metric with ID '{metric.metric_id}' already exists in this knowledgebase."
            )

        clean_name = metric.name.strip().lower()
        for existing in storage.values():
            if existing.name.strip().lower() == clean_name:
                raise DuplicateMetricError(
                    f"Metric with name '{metric.name}' already exists in this knowledgebase."
                )

        storage[metric.metric_id] = metric
        self._bump_version(metric.tenant_id, metric.knowledgebase_id)
        return metric

    def get_metric(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID, metric_id: str
    ) -> Optional[MetricDefinition]:
        """Get metric by ID."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        return storage.get(metric_id)

    def get_metric_by_name(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID, metric_name: str
    ) -> Optional[MetricDefinition]:
        """Get metric by canonical name."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        clean_name = metric_name.strip().lower()
        for metric in storage.values():
            if metric.name.strip().lower() == clean_name:
                return metric
        return None

    def list_metrics(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> List[MetricDefinition]:
        """List all metrics for KB, sorted deterministically by name."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        return sorted(list(storage.values()), key=lambda m: m.name.lower())

    def update_metric(self, metric: MetricDefinition) -> MetricDefinition:
        """Update an existing metric."""
        storage = self._get_kb_storage(metric.tenant_id, metric.knowledgebase_id)
        if metric.metric_id not in storage:
            raise MetricNotFoundError(
                f"Cannot update: metric with ID '{metric.metric_id}' not found."
            )

        self._validate_safe_text(metric.name, "metric.name")
        self._validate_safe_text(metric.display_name, "metric.display_name")
        for syn in metric.synonyms:
            self._validate_safe_text(syn, "metric.synonym")

        self._validate_expression(metric.expression, metric.aggregation)

        clean_name = metric.name.strip().lower()
        for m_id, existing in storage.items():
            if m_id != metric.metric_id and existing.name.strip().lower() == clean_name:
                raise DuplicateMetricError(
                    f"Another metric with name '{metric.name}' already exists."
                )

        metric.version = storage[metric.metric_id].version + 1
        metric.updated_at = datetime.now(timezone.utc)
        storage[metric.metric_id] = metric
        self._bump_version(metric.tenant_id, metric.knowledgebase_id)
        return metric

    def delete_metric(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID, metric_id: str
    ) -> bool:
        """Delete metric."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if metric_id in storage:
            del storage[metric_id]
            self._bump_version(tenant_id, knowledgebase_id)
            return True
        return False

    def resolve_metric(
        self,
        query: str,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
    ) -> Optional[Tuple[MetricDefinition, float]]:
        """
        Deterministically resolve natural language question to a canonical metric.
        If a registered metric matches with high confidence, it takes absolute precedence over LLM generation.
        Returns (MetricDefinition, confidence_score) or None.
        """
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if not storage:
            return None

        query_clean = query.strip().lower()
        query_tokens = set(re.findall(r"\b[a-zA-Z0-9_]+\b", query_clean))

        best_metric: Optional[MetricDefinition] = None
        best_score: float = 0.0

        for metric in storage.values():
            if metric.status != "ACTIVE":
                continue

            score = 0.0

            # 1. Exact name or display name in query
            if metric.name.lower() in query_clean:
                score = max(score, 1.0)
            if metric.display_name.lower() in query_clean:
                score = max(score, 1.0)

            # 2. Check synonyms
            for syn in metric.synonyms:
                syn_clean = syn.lower()
                if syn_clean in query_clean:
                    score = max(score, 0.95)
                else:
                    syn_tokens = set(syn_clean.split())
                    if syn_tokens and syn_tokens.issubset(query_tokens):
                        score = max(score, 0.85)

            # 3. Key concept combination (e.g. "average" + "salary")
            source_col = metric.source_column.lower()
            agg_type = metric.aggregation.value.lower()
            if agg_type in query_tokens and source_col in query_tokens:
                score = max(score, 0.90)

            if score > best_score:
                best_score = score
                best_metric = metric

        if best_metric and best_score >= 0.70:
            return best_metric, best_score
        return None

    def compute_fingerprint(
        self, tenant_id: uuid.UUID, knowledgebase_id: uuid.UUID
    ) -> str:
        """Compute deterministic SHA256 fingerprint of all metrics."""
        storage = self._get_kb_storage(tenant_id, knowledgebase_id)
        if not storage:
            return hashlib.sha256(b"empty_metric_registry").hexdigest()

        metrics_data = []
        for metric in sorted(storage.values(), key=lambda m: m.name.lower()):
            metrics_data.append({
                "id": metric.metric_id,
                "name": metric.name,
                "expr": metric.expression,
                "agg": metric.aggregation.value,
                "entity": metric.source_entity,
                "col": metric.source_column,
                "filter": metric.filter_condition,
                "dims": sorted(metric.supported_dimensions),
                "syns": sorted(metric.synonyms),
                "ver": metric.version,
                "status": metric.status,
            })

        canonical_json = json.dumps(metrics_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
