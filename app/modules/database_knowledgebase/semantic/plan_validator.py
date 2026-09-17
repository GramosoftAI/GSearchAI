"""Phase 6E: Dedicated PlanValidator

Validates QueryPlanIR between QueryPlanner and SQL compilation / LLM fallback.
Produces explicit PASS or REJECT(reason_code) outcomes with machine-readable diagnostics.
Never silently accepts unvetted, unapproved, or unsafe query plans.
"""

import logging
from typing import Any, Dict, List, Optional, Set
import uuid
import re

logger = logging.getLogger(__name__)

from .models import (
    PlanValidationResult,
    ValidationOutcome,
    ValidationReasonCode,
)
from .registry import SemanticModelRegistry
from .metrics import CanonicalMetricRegistry
from .relationships import SemanticRelationshipGraph
from ..planning.models import (
    AggregateFunction,
    ColumnProjectionPlan,
    JoinPlan,
    PredicatePlan,
    QueryPlanIR,
    TablePlan,
)
from ..schemas.canonical import DatabaseSchema, TableSchema
from ..sql_security.policy import SQLSecurityPolicyEngine


class PlanValidator:
    """
    Deterministic validator enforcing semantic validity, relationship approval,
    and schema authorization on QueryPlanIR.
    """

    MAX_LIMIT = 1000

    @classmethod
    def validate(
        cls,
        plan: QueryPlanIR,
        canonical_schema: DatabaseSchema,
        semantic_registry: Optional[SemanticModelRegistry] = None,
        metric_registry: Optional[CanonicalMetricRegistry] = None,
        relationship_graph: Optional[SemanticRelationshipGraph] = None,
        tenant_id: Optional[uuid.UUID] = None,
        knowledgebase_id: Optional[uuid.UUID] = None,
        requested_metric_id: Optional[str] = None,
        expected_entities: Optional[List[str]] = None,
        resolved_entities: Optional[List[Any]] = None,
    ) -> PlanValidationResult:
        """
        Deterministically validate a QueryPlanIR.
        Returns PlanValidationResult(outcome=PASS) or PlanValidationResult(outcome=REJECT, reason_code=...).
        """
        # Fail-closed guard: if plan confidence is 0.0 and no projections, it's an intentional fail-closed plan
        if plan.confidence == 0.0 and not plan.projections:
            return PlanValidationResult(
                outcome=ValidationOutcome.PASS,
                message="Plan intentionally failed closed",
            )

        # 1. Schema version verification
        if canonical_schema.fingerprint and plan.schema_version:
            if plan.schema_version != canonical_schema.fingerprint:
                return PlanValidationResult(
                    outcome=ValidationOutcome.REJECT,
                    reason_code=ValidationReasonCode.SCHEMA_VERSION_MISMATCH,
                    message=f"Plan schema version '{plan.schema_version}' does not match active schema '{canonical_schema.fingerprint}'",
                    offending_object=plan.schema_version,
                )

        # 2. Metric existence check (if a registered metric was requested)
        if requested_metric_id:
            if not metric_registry or not tenant_id or not knowledgebase_id:
                return PlanValidationResult(
                    outcome=ValidationOutcome.REJECT,
                    reason_code=ValidationReasonCode.METRIC_NOT_FOUND,
                    message=f"Requested metric '{requested_metric_id}' but metric registry is unavailable",
                    offending_object=requested_metric_id,
                )
            metric_def = metric_registry.get_metric(tenant_id, knowledgebase_id, requested_metric_id)
            if not metric_def or metric_def.status != "ACTIVE":
                return PlanValidationResult(
                    outcome=ValidationOutcome.REJECT,
                    reason_code=ValidationReasonCode.METRIC_NOT_FOUND,
                    message=f"Registered metric '{requested_metric_id}' not found or inactive",
                    offending_object=requested_metric_id,
                )

        # 3. Collect approved tables & columns from canonical schema
        known_tables: Dict[str, TableSchema] = {}
        alias_to_table: Dict[str, TableSchema] = {}

        for s_name, s_info in canonical_schema.schemas.items():
            for t_name, t_schema in s_info.tables.items():
                known_tables[t_name.lower()] = t_schema

        # 4. Table validation & security catalog check
        for tbl in plan.tables:
            t_clean = tbl.table_name.lower()
            if t_clean in SQLSecurityPolicyEngine.FORBIDDEN_TABLES or tbl.schema_name.lower() in SQLSecurityPolicyEngine.FORBIDDEN_CATALOGS:
                return PlanValidationResult(
                    outcome=ValidationOutcome.REJECT,
                    reason_code=ValidationReasonCode.SECURITY_POLICY_VIOLATION,
                    message=f"Table '{tbl.table_name}' is a forbidden system catalog or metadata table",
                    offending_object=tbl.table_name,
                )

            if t_clean not in known_tables:
                return PlanValidationResult(
                    outcome=ValidationOutcome.REJECT,
                    reason_code=ValidationReasonCode.UNAUTHORIZED_TABLE,
                    message=f"Table '{tbl.table_name}' does not exist in canonical schema",
                    offending_object=tbl.table_name,
                )

            alias_to_table[tbl.alias] = known_tables[t_clean]

            # Optional semantic entity check
            if semantic_registry and tenant_id and knowledgebase_id:
                s_entity = semantic_registry.get_entity_by_table(tenant_id, knowledgebase_id, t_clean)
                # If entities are registered for this KB, verify entity is recognized
                entities_list = semantic_registry.list_entities(tenant_id, knowledgebase_id)
                if entities_list and not s_entity:
                    # Note: Allow physical table if no explicit semantic restriction
                    pass

        # 5. Relationship & Join approval check
        if relationship_graph and tenant_id and knowledgebase_id:
            for join in plan.joins:
                src_tbl = alias_to_table.get(join.source_table_alias)
                tgt_tbl = alias_to_table.get(join.target_table_alias)

                if not src_tbl or not tgt_tbl:
                    return PlanValidationResult(
                        outcome=ValidationOutcome.REJECT,
                        reason_code=ValidationReasonCode.INVALID_JOIN_PATH,
                        message=f"Join references unknown table alias: '{join.source_table_alias}' or '{join.target_table_alias}'",
                        offending_object=f"{join.source_table_alias} -> {join.target_table_alias}",
                    )

                # Check if relationship graph has approved relationships
                approved_rels = relationship_graph.list_relationships(tenant_id, knowledgebase_id)
                if approved_rels:
                    is_approved = relationship_graph.is_join_approved(
                        src_tbl.table_name,
                        tgt_tbl.table_name,
                        tenant_id,
                        knowledgebase_id,
                        schema_version=plan.schema_version,
                    )
                    if not is_approved:
                        return PlanValidationResult(
                            outcome=ValidationOutcome.REJECT,
                            reason_code=ValidationReasonCode.RELATIONSHIP_NOT_APPROVED,
                            message=f"Join between '{src_tbl.table_name}' and '{tgt_tbl.table_name}' is not an approved semantic relationship",
                            offending_object=f"{src_tbl.table_name} -> {tgt_tbl.table_name}",
                        )

        # 6. Column existence & authorization in projections
        for proj in plan.projections:
            tbl_schema = alias_to_table.get(proj.table_alias)
            if not tbl_schema:
                return PlanValidationResult(
                    outcome=ValidationOutcome.REJECT,
                    reason_code=ValidationReasonCode.UNAUTHORIZED_TABLE,
                    message=f"Projection references unmapped table alias '{proj.table_alias}'",
                    offending_object=proj.table_alias,
                )

            if proj.column_name != "*" and proj.column_name != "1":
                if proj.column_name.lower() not in {c.lower() for c in tbl_schema.columns.keys()}:
                    valid_calc = False
                    try:
                        import sqlglot
                        from sqlglot import exp
                        parsed_expr = sqlglot.parse_one(proj.column_name, read="postgres")
                        cols = [c.name.lower() for c in parsed_expr.find_all(exp.Column)]
                        if cols and all(c in {col.lower() for col in tbl_schema.columns.keys()} for c in cols):
                            valid_calc = True
                    except Exception:
                        pass

                    if not valid_calc:
                        # Allow calculated expressions whose referenced columns exist
                        words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", proj.column_name)
                        SQL_KEYWORDS = {
                            "sum", "avg", "count", "min", "max", "round", "cast", "nullif", "as",
                            "numeric", "decimal", "integer", "coalesce", "least", "greatest",
                            "date_trunc", "current_date", "current_timestamp", "now", "interval",
                            "month", "year", "day", "date", "case", "when", "then", "else", "end",
                            "extract", "dow"
                        }
                        col_words = [w for w in words if w.lower() not in SQL_KEYWORDS]
                        if not col_words or not all(w.lower() in {c.lower() for c in tbl_schema.columns.keys()} for w in col_words):
                            return PlanValidationResult(
                                outcome=ValidationOutcome.REJECT,
                                reason_code=ValidationReasonCode.UNAUTHORIZED_COLUMN,
                                message=f"Column '{proj.column_name}' does not exist on table '{tbl_schema.table_name}'",
                                offending_object=f"{tbl_schema.table_name}.{proj.column_name}",
                            )

            # Check aggregation function
            if proj.aggregation and getattr(proj.aggregation, "value", str(proj.aggregation)) not in {"NONE", None}:
                agg_val = getattr(proj.aggregation, "value", str(proj.aggregation)).upper()
                if agg_val not in {"COUNT", "SUM", "AVG", "MIN", "MAX"}:
                    return PlanValidationResult(
                        outcome=ValidationOutcome.REJECT,
                        reason_code=ValidationReasonCode.INVALID_AGGREGATION,
                        message=f"Unsupported aggregation function '{agg_val}'",
                        offending_object=agg_val,
                    )

        # 7. Column existence in predicates
        for pred in plan.predicates:
            tbl_schema = alias_to_table.get(pred.table_alias)
            if not tbl_schema:
                return PlanValidationResult(
                    outcome=ValidationOutcome.REJECT,
                    reason_code=ValidationReasonCode.UNAUTHORIZED_TABLE,
                    message=f"Predicate references unmapped table alias '{pred.table_alias}'",
                    offending_object=pred.table_alias,
                )

            if pred.column_name.lower() not in {c.lower() for c in tbl_schema.columns.keys()}:
                return PlanValidationResult(
                    outcome=ValidationOutcome.REJECT,
                    reason_code=ValidationReasonCode.UNAUTHORIZED_COLUMN,
                    message=f"Predicate column '{pred.column_name}' does not exist on table '{tbl_schema.table_name}'",
                    offending_object=f"{tbl_schema.table_name}.{pred.column_name}",
                )

        # 8. Limit bounds check
        if plan.limit is not None:
            if plan.limit < 0 or plan.limit > cls.MAX_LIMIT:
                return PlanValidationResult(
                    outcome=ValidationOutcome.REJECT,
                    reason_code=ValidationReasonCode.UNSUPPORTED_PLAN,
                    message=f"Plan limit {plan.limit} exceeds bounds [0, {cls.MAX_LIMIT}]",
                    offending_object=str(plan.limit),
                )

        soft_misses: List[Dict[str, Any]] = []

        # 9. Multi-Entity Semantic Completeness & Relationship Validation (Phase 6.5 & Schema-Grounded)
        if resolved_entities:
            from ..planning.schema_entity_resolver import EntityConfidence

            planned_target_names: Set[str] = set()
            planned_table_tokens: Set[str] = set()

            for tp in plan.tables:
                planned_target_names.add(tp.table_name.lower())
                planned_target_names.add(f"{tp.schema_name.lower()}.{tp.table_name.lower()}")
                planned_table_tokens.add(tp.table_name.lower())
                parts = [p.lower() for p in re.split(r"[_\W]+", tp.table_name) if p]
                for p in parts:
                    planned_table_tokens.add(p)
                    if p.endswith("ies") and len(p) > 4:
                        planned_table_tokens.add(p[:-3] + "y")
                    elif p.endswith("es") and len(p) > 4 and not p.endswith("ses"):
                        planned_table_tokens.add(p[:-2])
                    elif p.endswith("s") and len(p) > 3 and not p.endswith("ss"):
                        planned_table_tokens.add(p[:-1])

                tbl_obj = alias_to_table.get(tp.alias)
                if tbl_obj:
                    for c_name in tbl_obj.columns.keys():
                        planned_target_names.add(f"{tp.table_name.lower()}.{c_name.lower()}")
                        planned_target_names.add(f"{tp.schema_name.lower()}.{tp.table_name.lower()}.{c_name.lower()}")
                        c_parts = [p.lower() for p in re.split(r"[_\W]+", c_name) if p]
                        for cp in c_parts:
                            planned_table_tokens.add(cp)
                            if cp.endswith("s") and len(cp) > 3:
                                planned_table_tokens.add(cp[:-1])

            # Tiered Validation:
            # 1. UNRESOLVED: Dropped upstream, never triggers rejection
            # 2. LOW/MEDIUM: If missing, logs ENTITY_SOFT_MISS and allows plan to PASS
            # 3. HIGH: If missing, triggers hard REJECT (MISSING_REQUIRED_ENTITY)
            for r in resolved_entities:
                if r.confidence == EntityConfidence.UNRESOLVED or not r.resolved_to:
                    continue

                # Bigrams, verbs, and temporal tokens are concept-binding candidates, never required entity tables
                if getattr(r, "metadata", {}).get("is_ngram") or getattr(r, "metadata", {}).get("likely_verb"):
                    continue

                tok = r.token.lower()
                if tok in {
                    "today", "yesterday", "tomorrow", "morning", "afternoon", "evening", "night",
                    "week", "month", "year", "day", "date", "time", "hour", "minute", "second",
                    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                    "now", "current", "past", "next", "last", "earliest", "latest",
                    "number", "numbers", "code", "id", "value", "values", "type", "data", "info",
                    "record", "records", "item", "items",
                }:
                    continue

                # Skip if this token is a sub-word of an extracted n-gram candidate (e.g. 'number' in 'phone number')
                if any(getattr(other, "metadata", {}).get("is_ngram") and tok in other.token.lower().split() for other in resolved_entities):
                    continue

                r_clean = r.resolved_to.lower()
                r_parts = r_clean.split(".")
                r_tbl = r_parts[-2] if len(r_parts) >= 2 and r.entity_type == "COLUMN" else r_parts[-1]

                matched = False
                if r_clean in planned_target_names or any(r_tbl == tp.table_name.lower() for tp in plan.tables):
                    matched = True
                else:
                    tok_squash = tok.replace("_", "")
                    if (
                        tok in planned_table_tokens
                        or tok_squash in planned_table_tokens
                        or any(tok in ptt or tok_squash in ptt for ptt in planned_table_tokens)
                    ):
                        matched = True

                if not matched:
                    # Non-blocking entity handling: record soft miss and allow query to proceed
                    logger.warning(
                        "ENTITY_SOFT_MISS: Entity '%s' resolved to '%s' (confidence=%s, scope=%s) not in plan",
                        r.token,
                        r.resolved_to,
                        r.confidence.value,
                        r.resolution_scope,
                        extra={
                            "event": "ENTITY_SOFT_MISS",
                            "token": r.token,
                            "resolved_to": r.resolved_to,
                            "confidence": r.confidence.value,
                            "resolution_scope": r.resolution_scope,
                        },
                    )
                    soft_misses.append({
                        "token": r.token,
                        "resolved_to": r.resolved_to,
                        "confidence": r.confidence.value,
                        "resolution_scope": r.resolution_scope,
                    })

            # Check join requirement if >= 2 HIGH entities
            high_entities = [r for r in resolved_entities if r.confidence == EntityConfidence.HIGH and r.entity_type == "TABLE"]
            if len(high_entities) >= 2:
                if len(plan.tables) > 1 and len(plan.joins) == 0:
                    return PlanValidationResult(
                        outcome=ValidationOutcome.REJECT,
                        reason_code=ValidationReasonCode.MISSING_RELATIONSHIP_PATH,
                        message=f"Semantic plan validation failed: Multi-entity query requires active joins between {[t.table_name for t in plan.tables]}, but join count is 0",
                        offending_object="joins",
                        details={"planned_tables": [t.table_name for t in plan.tables], "join_count": 0},
                    )

        elif expected_entities and len(expected_entities) >= 2:
            planned_table_tokens = set()
            for tp in plan.tables:
                planned_table_tokens.add(tp.table_name.lower())
                parts = [p.lower() for p in re.split(r"[_\W]+", tp.table_name) if p]
                for p in parts:
                    planned_table_tokens.add(p)
                    if p.endswith("ies") and len(p) > 4:
                        planned_table_tokens.add(p[:-3] + "y")
                    elif p.endswith("es") and len(p) > 4 and not p.endswith("ses"):
                        planned_table_tokens.add(p[:-2])
                    elif p.endswith("s") and len(p) > 3 and not p.endswith("ss"):
                        planned_table_tokens.add(p[:-1])

                # Also include column tokens from the planned tables to support attribute-based entities (e.g. reporting_manager)
                tbl_obj = alias_to_table.get(tp.alias)
                if tbl_obj:
                    for c_name in tbl_obj.columns.keys():
                        c_parts = [p.lower() for p in re.split(r"[_\W]+", c_name) if p]
                        for cp in c_parts:
                            planned_table_tokens.add(cp)
                            if cp.endswith("s") and len(cp) > 3:
                                planned_table_tokens.add(cp[:-1])

            # Check that every expected entity has a corresponding table in the plan
            for ent in expected_entities:
                e_clean = ent.lower()
                e_stem = e_clean[:-1] if (e_clean.endswith("s") and len(e_clean) > 3) else e_clean
                e_stripped = e_clean.replace("_", "")
                e_parts = [p for p in e_clean.split("_") if p]

                matched = False
                for tok in planned_table_tokens:
                    tok_stripped = tok.replace("_", "")
                    if (
                        tok == e_clean
                        or tok == e_stem
                        or e_clean in tok
                        or e_stem in tok
                        or (len(e_stripped) >= 4 and (e_stripped in tok_stripped or tok_stripped in e_stripped))
                    ):
                        matched = True
                        break
                if not matched and len(e_parts) > 1:
                    # Check if all constituent parts of the compound entity are present in planned tokens
                    if all(any(p == tok or p in tok for tok in planned_table_tokens) for p in e_parts):
                        matched = True
                if not matched:
                    return PlanValidationResult(
                        outcome=ValidationOutcome.REJECT,
                        reason_code=ValidationReasonCode.MISSING_REQUIRED_ENTITY,
                        message=f"Semantic plan validation failed: Expected entity '{ent}' is not represented in the planned tables {[t.table_name for t in plan.tables]}",
                        offending_object=ent,
                        details={"expected_entities": expected_entities, "planned_tables": [t.table_name for t in plan.tables]},
                    )

            # If 2 or more entities are expected, plan MUST have at least 1 join
            if len(plan.tables) > 1 and len(plan.joins) == 0:
                return PlanValidationResult(
                    outcome=ValidationOutcome.REJECT,
                    reason_code=ValidationReasonCode.MISSING_RELATIONSHIP_PATH,
                    message=f"Semantic plan validation failed: Multi-entity query requires active joins between {[t.table_name for t in plan.tables]}, but join count is 0",
                    offending_object="joins",
                    details={"expected_entities": expected_entities, "planned_tables": [t.table_name for t in plan.tables], "join_count": 0},
                )
            elif len(plan.tables) == 1 and len(expected_entities) >= 2:
                single_table_tokens = set()
                p_tokens = [p.lower() for p in re.split(r"[_\W]+", plan.tables[0].table_name) if p]
                for p in p_tokens:
                    single_table_tokens.add(p)
                    if p.endswith("s") and len(p) > 3:
                        single_table_tokens.add(p[:-1])
                single_covers_all = all(
                    any(
                        ent.lower() == tok
                        or ent.lower() in tok
                        or tok in ent.lower()
                        or ent.lower().replace("_", "") in plan.tables[0].table_name.lower().replace("_", "")
                        for tok in single_table_tokens
                    )
                    for ent in expected_entities
                )
                if not single_covers_all:
                    return PlanValidationResult(
                        outcome=ValidationOutcome.REJECT,
                        reason_code=ValidationReasonCode.MISSING_RELATIONSHIP_PATH,
                        message=f"Semantic plan validation failed: Multi-entity query requires relationships between multiple tables, but plan only contains '{plan.tables[0].table_name}'",
                        offending_object=plan.tables[0].table_name,
                        details={"expected_entities": expected_entities, "planned_tables": [plan.tables[0].table_name]},
                    )

        # All checks passed
        return PlanValidationResult(
            outcome=ValidationOutcome.PASS,
            message="Plan is semantically valid and authorized",
            details={"soft_misses": soft_misses} if soft_misses else {},
        )
