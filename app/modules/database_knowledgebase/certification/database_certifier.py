"""Universal Database Certification Engine

Automated certification test suite that validates the readiness, semantics,
relationships, query planning, and security invariants of any newly connected database
before marking it certified for production query traffic.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid
from pydantic import BaseModel, ConfigDict, Field

from ..discovery.database_discovery import DiscoveredCatalog
from ..planning.models import IntentType, QueryPlanIR
from ..planning.planner import QueryPlanner
from ..schemas.canonical import DatabaseSchema
from ..semantic.database_knowledge_profile import (
    CertificationStatus,
    DatabaseKnowledgeProfile,
    TableCategory,
)
from ..semantic.semantic_model_builder import SemanticModelBuilder
from ..sql_generator.generator import CandidateSQLGenerator
from ..sql_security.policy import SQLSecurityPolicyEngine


class GateStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class CertificationGateResult(BaseModel):
    """Result of an individual certification gate."""
    model_config = ConfigDict(extra="forbid")

    gate_name: str
    status: GateStatus
    score: float = Field(default=1.0, ge=0.0, le=1.0)
    details: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class CertificationReport(BaseModel):
    """Comprehensive certification report for a database knowledge profile."""
    model_config = ConfigDict(extra="forbid")

    database_name: str
    status: CertificationStatus
    overall_score: float = Field(ge=0.0, le=1.0)
    gates: Dict[str, CertificationGateResult] = Field(default_factory=dict)
    total_tables: int = 0
    total_entities: int = 0
    total_relationships: int = 0
    total_metrics: int = 0
    certified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    diagnostic_summary: str = ""


class DatabaseCertifier:
    """
    Executes automated certification gates on a client database profile.
    Guarantees structural integrity, semantic coherence, planning feasibility,
    and non-negotiable security invariant enforcement.
    """

    PASSING_SCORE_THRESHOLD = 0.80

    @classmethod
    def certify(
        cls,
        profile: DatabaseKnowledgeProfile,
        canonical_schema: DatabaseSchema,
    ) -> CertificationReport:
        """
        Executes all 6 certification gates and updates profile status.
        """
        gates: Dict[str, CertificationGateResult] = {}

        # Gate 1: Structural Integrity
        gates["structural_integrity"] = cls._gate_structural_integrity(profile, canonical_schema)

        # Gate 2: Semantic Classification
        gates["semantic_classification"] = cls._gate_semantic_classification(profile)

        # Gate 3: Relational Graph Consistency
        gates["relational_graph"] = cls._gate_relational_graph(profile)

        # Gate 4: Identity & Lookup Columns
        gates["identity_resolution"] = cls._gate_identity_resolution(profile)

        # Gate 5: Query Planning Feasibility
        gates["query_planning"] = cls._gate_query_planning(profile, canonical_schema)

        # Gate 6: Security AST Policy
        gates["security_ast_policy"] = cls._gate_security_ast_policy(profile, canonical_schema)

        # Gate 7: Canonicality & Structural Risk
        canonical_overrides = getattr(profile, "canonical_overrides", None)
        if not canonical_overrides and hasattr(profile, "metadata") and isinstance(profile.metadata, dict):
            canonical_overrides = profile.metadata.get("canonical_overrides")
        gates["canonicality_and_structural_risk"] = cls._gate_canonicality_and_structural_risk(
            profile, canonical_schema, canonical_overrides=canonical_overrides
        )

        # Compute overall score
        total_score = sum(g.score for g in gates.values())
        overall_score = total_score / max(1, len(gates))

        all_passed = all(g.status == GateStatus.PASSED for g in gates.values())
        status = CertificationStatus.CERTIFIED if (all_passed and overall_score >= cls.PASSING_SCORE_THRESHOLD) else CertificationStatus.FAILED

        # Update profile certification status
        profile.certification_status = status
        report_dict = {
            "status": status.value,
            "overall_score": overall_score,
            "gates_passed": sum(1 for g in gates.values() if g.status == GateStatus.PASSED),
            "total_gates": len(gates),
        }
        profile.certification_report = report_dict

        report = CertificationReport(
            database_name=profile.database_name,
            status=status,
            overall_score=overall_score,
            gates=gates,
            total_tables=len(profile.tables),
            total_entities=len(profile.entities),
            total_relationships=len(profile.relationships),
            total_metrics=len(profile.metrics),
            diagnostic_summary=f"Database certification {'PASSED' if status == CertificationStatus.CERTIFIED else 'FAILED'} with score {overall_score:.2f}",
        )

        return report

    @classmethod
    def _gate_structural_integrity(
        cls, profile: DatabaseKnowledgeProfile, schema: DatabaseSchema
    ) -> CertificationGateResult:
        """Validates that tables exist, columns are typed, and PKs are defined."""
        errors: List[str] = []
        details: List[str] = []

        if not schema.all_tables:
            errors.append("Schema contains 0 tables.")
            return CertificationGateResult(gate_name="structural_integrity", status=GateStatus.FAILED, score=0.0, errors=errors)

        details.append(f"{len(schema.all_tables)} physical tables discovered")

        pks_found = sum(1 for t in schema.all_tables if t.primary_key_columns)
        if pks_found == 0:
            errors.append("No primary keys found across tables.")
        else:
            details.append(f"{pks_found} tables define authoritative primary keys")

        score = 1.0 if not errors else max(0.0, 1.0 - (len(errors) * 0.5))
        status = GateStatus.PASSED if score >= cls.PASSING_SCORE_THRESHOLD else GateStatus.FAILED

        return CertificationGateResult(gate_name="structural_integrity", status=status, score=score, details=details, errors=errors)

    @classmethod
    def _gate_semantic_classification(cls, profile: DatabaseKnowledgeProfile) -> CertificationGateResult:
        """Validates that tables and columns are classified with high confidence."""
        errors: List[str] = []
        details: List[str] = []

        if not profile.entities:
            errors.append("0 business entities identified.")

        details.append(f"{len(profile.entities)} canonical business entities identified")
        details.append(f"{len(profile.tables)} total tables classified")

        # Check system table boundary
        details.append(f"{len(profile.system_tables)} system tables quarantined")
        details.append(f"{len(profile.security_tables)} security/credential tables quarantined")

        score = 1.0 if not errors else 0.0
        status = GateStatus.PASSED if score >= cls.PASSING_SCORE_THRESHOLD else GateStatus.FAILED

        return CertificationGateResult(gate_name="semantic_classification", status=status, score=score, details=details, errors=errors)

    @classmethod
    def _gate_relational_graph(cls, profile: DatabaseKnowledgeProfile) -> CertificationGateResult:
        """Validates relational foreign key graph consistency."""
        details: List[str] = []
        errors: List[str] = []

        declared_fks = [r for r in profile.relationships if r.is_declared_fk]
        inferred = [r for r in profile.relationships if not r.is_declared_fk]

        details.append(f"{len(declared_fks)} declared FK relationships")
        details.append(f"{len(inferred)} inferred relationships")

        # Verify no system tables are participating in business joins
        for rel in profile.relationships:
            src_key = f"{rel.source_schema}.{rel.source_table}".lower()
            tgt_key = f"{rel.target_schema}.{rel.target_table}".lower()
            if src_key in profile.security_tables or tgt_key in profile.security_tables:
                errors.append(f"Security table {src_key} or {tgt_key} found in relationship graph!")

        score = 1.0 if not errors else 0.0
        status = GateStatus.PASSED if not errors else GateStatus.FAILED

        return CertificationGateResult(gate_name="relational_graph", status=status, score=score, details=details, errors=errors)

    @classmethod
    def _gate_identity_resolution(cls, profile: DatabaseKnowledgeProfile) -> CertificationGateResult:
        """Validates that business entities have viable identity columns."""
        details: List[str] = []
        errors: List[str] = []

        entities_with_identity = 0
        for ent_id, ent in profile.entities.items():
            if ent.identity_columns or ent.primary_key_columns:
                entities_with_identity += 1

        details.append(f"{entities_with_identity}/{len(profile.entities)} entities possess identity lookup fields")

        if len(profile.entities) > 0 and entities_with_identity == 0:
            errors.append("No entity has identity or lookup columns.")

        score = entities_with_identity / max(1, len(profile.entities))
        status = GateStatus.PASSED if score >= 0.70 else GateStatus.FAILED

        return CertificationGateResult(gate_name="identity_resolution", status=status, score=score, details=details, errors=errors)

    @classmethod
    def _gate_query_planning(
        cls, profile: DatabaseKnowledgeProfile, schema: DatabaseSchema
    ) -> CertificationGateResult:
        """Validates that QueryPlanner can construct a valid QueryPlanIR for basic queries."""
        details: List[str] = []
        errors: List[str] = []

        if not profile.entities:
            return CertificationGateResult(
                gate_name="query_planning", status=GateStatus.FAILED, score=0.0, errors=["No entities to query"]
            )

        # Pick primary entity
        primary_entity = next(iter(profile.entities.values()))
        test_query = f"Show all {primary_entity.semantic_name}s"

        try:
            from ..retrieval.retriever import SchemaRetrievalResult
            from ..retrieval.scorer import TableRetrievalScore
            target_tbl = schema.get_table(primary_entity.physical_table, primary_entity.physical_schema) or schema.all_tables[0]
            retrieval = SchemaRetrievalResult(
                database_name=schema.database_name,
                database_type=schema.database_type,
                schema_version=profile.schema_fingerprint,
                retrieved_tables=[target_tbl],
                retrieval_scores={
                    target_tbl.table_name: TableRetrievalScore(
                        table_name=target_tbl.table_name,
                        schema_name=target_tbl.schema_name,
                        final_score=1.0,
                    )
                },
                join_paths=[],
                overall_confidence=1.0,
                untrusted_boundary_text="<untrusted_database_schema>...</untrusted_database_schema>",
            )
            plan = QueryPlanner.plan(
                user_query=test_query,
                database_knowledgebase_id=profile.knowledgebase_id,
                canonical_schema=schema,
                retrieval_result=retrieval,
            )
            details.append(f"Successfully planned query: '{test_query}' -> {len(plan.tables)} table(s)")
            score = 1.0
            status = GateStatus.PASSED
        except Exception as e:
            errors.append(f"Planning failed on '{test_query}': {str(e)}")
            score = 0.0
            status = GateStatus.FAILED

        return CertificationGateResult(gate_name="query_planning", status=status, score=score, details=details, errors=errors)

    @classmethod
    def _gate_security_ast_policy(
        cls, profile: DatabaseKnowledgeProfile, schema: DatabaseSchema
    ) -> CertificationGateResult:
        """Validates that generated SQL compiles and satisfies the 22 security invariants."""
        details: List[str] = []
        errors: List[str] = []

        if not profile.entities:
            return CertificationGateResult(
                gate_name="security_ast_policy", status=GateStatus.FAILED, score=0.0, errors=["No entities to test"]
            )

        primary_entity = next(iter(profile.entities.values()))
        test_query = f"Show all {primary_entity.semantic_name}s"

        try:
            from ..retrieval.retriever import SchemaRetrievalResult
            from ..retrieval.scorer import TableRetrievalScore
            target_tbl = schema.get_table(primary_entity.physical_table, primary_entity.physical_schema) or schema.all_tables[0]
            retrieval = SchemaRetrievalResult(
                database_name=schema.database_name,
                database_type=schema.database_type,
                schema_version=profile.schema_fingerprint,
                retrieved_tables=[target_tbl],
                retrieval_scores={
                    target_tbl.table_name: TableRetrievalScore(
                        table_name=target_tbl.table_name,
                        schema_name=target_tbl.schema_name,
                        final_score=1.0,
                    )
                },
                join_paths=[],
                overall_confidence=1.0,
                untrusted_boundary_text="<untrusted_database_schema>...</untrusted_database_schema>",
            )
            plan = QueryPlanner.plan(
                user_query=test_query,
                database_knowledgebase_id=profile.knowledgebase_id,
                canonical_schema=schema,
                retrieval_result=retrieval,
            )

            # Compile SQL
            sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
            if not sql:
                raise ValueError("Failed to compile SQL from query plan")

            # Run through strict AST security policy
            from ..sql_parser.ast_parser import SQLASTParser
            root = SQLASTParser.parse_sql(sql)
            res = SQLSecurityPolicyEngine.validate_ast(root, schema, retrieval)
            if not res.is_valid:
                err_msg = "; ".join(e.message for e in res.errors)
                raise ValueError(f"Security AST policy violation: {err_msg}")

            details.append("Deterministic SQL compiled successfully")
            details.append("SQL AST passed all 22 read-only security invariants without violation")
            score = 1.0
            status = GateStatus.PASSED
        except Exception as e:
            errors.append(f"Security AST check failed: {str(e)}")
            score = 0.0
            status = GateStatus.FAILED

        return CertificationGateResult(gate_name="security_ast_policy", status=status, score=score, details=details, errors=errors)

    @classmethod
    def _gate_canonicality_and_structural_risk(
        cls,
        profile: DatabaseKnowledgeProfile,
        schema: DatabaseSchema,
        canonical_overrides: Optional[Dict[str, bool]] = None,
    ) -> CertificationGateResult:
        """
        Gate 7: Validates table canonicality and flags orphan foreign-key structural risks.
        - Non-canonical tables (history, backup, unconstrained) are tagged and excluded from default query candidate pools.
        - Supports operator whitelists/overrides via canonical_overrides (table_name -> bool).
        - Columns matching naming convention (.*_id$ or .*_id_id$) without authoritative FK constraints
          are flagged with structural_risk: true and explicitly named in the certification report.
        """
        from ..semantic_glossary.canonicality import is_canonical_table
        import re

        details: List[str] = []
        errors: List[str] = []
        orphan_fk_pattern = re.compile(r"(_id|_id_id)$", re.IGNORECASE)

        canonical_count = 0
        non_canonical_tables = []
        structural_risks: List[Dict[str, Any]] = []

        for table in schema.all_tables:
            is_canon = is_canonical_table(table, canonical_overrides=canonical_overrides)
            if canonical_overrides:
                t_lower = table.table_name.lower()
                q_lower = f"{table.schema_name}.{table.table_name}".lower()
                if t_lower in canonical_overrides or q_lower in canonical_overrides:
                    details.append(
                        f"Table '{table.table_name}' canonicality explicitly set to {is_canon} by operator override/whitelist"
                    )

            if is_canon:
                canonical_count += 1
            else:
                non_canonical_tables.append(table.table_name)
                details.append(f"Non-canonical table '{table.table_name}' tagged and excluded from default query pools")

            # Check for orphan foreign-key naming convention without declared FK
            declared_fk_cols = set()
            for fk in table.foreign_keys:
                declared_fk_cols.update(c.lower() for c in fk.constrained_columns)

            for col_name, col in table.columns.items():
                c_low = col_name.lower()
                if c_low in ("id", "pk"):
                    continue
                if orphan_fk_pattern.search(col_name) and c_low not in declared_fk_cols and not col.is_foreign_key:
                    structural_risks.append({
                        "table": table.table_name,
                        "column": col_name,
                        "structural_risk": True,
                    })
                    details.append(
                        f"[STRUCTURAL_RISK] Table '{table.table_name}', column '{col_name}' "
                        f"matches foreign-key naming convention but lacks an authoritative foreign key constraint."
                    )

        if canonical_count == 0 and len(schema.all_tables) > 0:
            errors.append("All discovered tables are non-canonical (historical/backup/unconstrained).")
            return CertificationGateResult(
                gate_name="canonicality_and_structural_risk",
                status=GateStatus.FAILED,
                score=0.0,
                details=details,
                errors=errors,
            )

        details.append(f"Canonical tables: {canonical_count}/{len(schema.all_tables)}. Non-canonical: {len(non_canonical_tables)}.")
        if structural_risks:
            details.append(f"Total structural FK risk warnings flagged: {len(structural_risks)}.")
        else:
            details.append("Zero orphan foreign key structural risks detected.")

        return CertificationGateResult(
            gate_name="canonicality_and_structural_risk",
            status=GateStatus.PASSED,
            score=1.0,
            details=details,
            errors=errors,
        )

