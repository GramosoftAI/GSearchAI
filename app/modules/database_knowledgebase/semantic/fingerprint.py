"""Phase 6I: Unified Context & Version Fingerprinting

Computes a deterministic, cryptographic fingerprint bundle representing:
- Physical schema snapshot fingerprint
- Semantic entity registry fingerprint
- Metric registry fingerprint
- Approved relationship graph fingerprint
- Business rules registry fingerprint
- Security policy version

Guarantees that any structural or semantic update cleanly invalidates caches and query memories.
"""

import hashlib
import json
from typing import Optional
import uuid

from .models import ContextFingerprint
from .registry import SemanticModelRegistry
from .metrics import CanonicalMetricRegistry
from .relationships import SemanticRelationshipGraph
from .business_rules import BusinessRuleRegistry


class ContextFingerprinter:
    """
    Computes a unified, reproducible SHA-256 fingerprint for a knowledgebase's complete semantic context.
    """

    DEFAULT_SECURITY_VERSION = "v1.0"

    @classmethod
    def compute(
        cls,
        tenant_id: uuid.UUID,
        knowledgebase_id: uuid.UUID,
        schema_version: str,
        semantic_registry: Optional[SemanticModelRegistry] = None,
        metric_registry: Optional[CanonicalMetricRegistry] = None,
        relationship_graph: Optional[SemanticRelationshipGraph] = None,
        business_rules: Optional[BusinessRuleRegistry] = None,
        security_policy_version: str = DEFAULT_SECURITY_VERSION,
    ) -> ContextFingerprint:
        """
        Compute the deterministic ContextFingerprint bundle.
        """
        sem_fp = semantic_registry.compute_fingerprint(tenant_id, knowledgebase_id) if semantic_registry else "empty"
        met_fp = metric_registry.compute_fingerprint(tenant_id, knowledgebase_id) if metric_registry else "empty"
        rel_fp = relationship_graph.compute_fingerprint(tenant_id, knowledgebase_id) if relationship_graph else "empty"
        rul_fp = business_rules.compute_fingerprint(tenant_id, knowledgebase_id) if business_rules else "empty"

        components = {
            "schema_version": schema_version,
            "semantic_registry": sem_fp,
            "metric_registry": met_fp,
            "relationship_graph": rel_fp,
            "business_rules": rul_fp,
            "security_policy": security_policy_version,
        }

        canonical_json = json.dumps(components, sort_keys=True, separators=(",", ":"))
        combined_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        return ContextFingerprint(
            schema_version=schema_version,
            semantic_registry_version=sem_fp,
            metric_registry_version=met_fp,
            relationship_graph_version=rel_fp,
            business_rules_version=rul_fp,
            security_policy_version=security_policy_version,
            combined_fingerprint=combined_hash,
        )
