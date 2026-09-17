"""SQL Repair Engine and Validated Candidate SQL Model

Coordinates Candidate SQL generation, AST Security Policy validation,
and diagnostic LLM repair loop with fail-closed semantics.
"""

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp

from ..exceptions import SQLValidationError
from ..planning.models import AggregateFunction, QueryPlanIR
from ..retrieval.retriever import SchemaRetrievalResult
from ..schemas.canonical import DatabaseSchema
from ..sql_parser.ast_parser import SQLASTParser
from ..sql_security.diagnostics import ValidationResult
from ..sql_security.parameterizer import ParameterizedSQL, SQLParameterizer
from ..sql_security.policy import SQLSecurityPolicyEngine
from .generator import CandidateSQLGenerator
from .prompt_templates import SQLPromptBuilder

logger = logging.getLogger(__name__)


class ValidatedCandidateSQL(BaseModel):
    """
    Certified, validated candidate SQL output.
    Represents the end boundary of Phase 2B.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    raw_sql: str = Field(..., description="Original raw SQL candidate")
    sanitized_sql: str = Field(..., description="Sanitized and validated SQL string")
    parameterized: ParameterizedSQL = Field(..., description="Parameterized SQL and parameter bindings")
    plan: QueryPlanIR = Field(..., description="Underlying validated QueryPlanIR")
    validation_report: ValidationResult = Field(..., description="Audit validation results and warnings")
    repair_attempts: int = Field(default=0, ge=0, le=2, description="Number of repair loops executed")
    sql_generation_mode: str = Field(default="llm", description="'deterministic' or 'llm'")
    deterministic_sql_compilation: bool = Field(default=False, description="Whether SQL was deterministically compiled")
    sql_llm_bypassed: bool = Field(default=False, description="Whether Phase 2B LLM generation was bypassed")


class SQLRepairEngine:
    """
    Orchestrates generation, security validation, and diagnostic repair.
    Supports conservative deterministic SQL compilation for unambiguous plans,
    bypassing external LLM calls with strict fail-closed security validation.
    """

    MAX_REPAIR_ATTEMPTS = 2

    @classmethod
    def can_compile_plan_deterministically(cls, plan: QueryPlanIR) -> bool:
        """
        Conservative eligibility gate for deterministic SQL compilation.
        Only plans whose semantics are fully and explicitly represented by QueryPlanIR
        are eligible.
        """
        if not plan or not plan.tables:
            return False

        # Reject plans with planner confidence below threshold
        if plan.confidence < 0.5:
            return False

        # Projections check: every projection must have supported aggregation
        for proj in plan.projections:
            agg_val = proj.aggregation.value if hasattr(proj.aggregation, "value") else str(proj.aggregation)
            if agg_val not in {"NONE", "COUNT", "COUNT_DISTINCT", "SUM", "AVG", "MIN", "MAX"}:
                return False

        # Predicates check: all operators must be standard supported operators
        supported_ops = {"=", "==", "!=", ">", "<", ">=", "<=", "LIKE", "ILIKE", "IS NULL", "IS NOT NULL"}
        for pred in plan.predicates:
            op = pred.operator.upper().strip()
            if op not in supported_ops:
                return False

        # Joins check: if multiple tables, joins must exist and connect tables
        if len(plan.tables) > 1:
            if not plan.joins:
                return False
            for j in plan.joins:
                join_kind = j.join_type.value if hasattr(j.join_type, "value") else str(j.join_type)
                if join_kind.upper() not in {"INNER", "LEFT"}:
                    return False

        return True

    @classmethod
    async def generate_and_validate(
        cls,
        user_query: str,
        plan: QueryPlanIR,
        canonical_schema: DatabaseSchema,
        retrieval_result: SchemaRetrievalResult,
        use_llm: bool = True,
    ) -> ValidatedCandidateSQL:
        """
        Generate candidate SQL and validate through security policy engine.
        Flow:
        1. Conservative Deterministic Gate: If plan is unambiguous and supported,
           compile directly via CandidateSQLGenerator.compile_plan_to_sql.
        2. AST Security Policy Gate: Validate compiled SQL. If security policy fails,
           FAIL CLOSED immediately (never use LLM as an escape hatch).
        3. Parameterization Gate: Parameterize SQL. If fails, FAIL CLOSED immediately.
        4. Fallback: If plan is unsupported or compiler throws an internal exception,
           route to existing Phase 2B LLM generation and diagnostic repair loop.
        """
        # =========================================================================
        # PATH A: Deterministic SQL Compilation Gate
        # =========================================================================
        if cls.can_compile_plan_deterministically(plan):
            logger.debug(f"Plan is eligible for deterministic compilation: intent={plan.intent}")
            compiled_sql: Optional[str] = None
            compiler_failed = False

            try:
                compiled_sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
            except Exception as compiler_exc:
                logger.warning(
                    f"Deterministic plan compiler raised exception: {compiler_exc}. "
                    f"Falling back safely to LLM SQL generation."
                )
                compiler_failed = True

            if not compiler_failed and compiled_sql is not None:
                # 1. AST Security Validation Gate (MANDATORY & FAIL-CLOSED)
                validation = SQLSecurityPolicyEngine.validate_sql(
                    sql_text=compiled_sql,
                    canonical_schema=canonical_schema,
                    retrieval_result=retrieval_result,
                )
                if not validation.is_valid:
                    # STRICT SECURITY INVARIANT:
                    # Never route an AST security violation to the LLM as an escape hatch!
                    error_msgs = "; ".join([e.message for e in validation.errors])
                    logger.error(
                        f"Deterministically compiled SQL failed security policy: {error_msgs}. FAILING CLOSED."
                    )
                    raise SQLValidationError(
                        f"Candidate SQL failed security validation: {error_msgs}"
                    )

                # 2. Parameterization Gate (MANDATORY & FAIL-CLOSED)
                try:
                    ast = SQLASTParser.parse_sql(validation.sanitized_sql)
                    parameterized = SQLParameterizer.parameterize(ast)
                except Exception as param_exc:
                    logger.error(f"Parameterization failed for compiled SQL: {param_exc}. FAILING CLOSED.")
                    raise SQLValidationError(f"SQL parameterization failed: {param_exc}")

                logger.info("Deterministic SQL compilation successfully validated and parameterized (LLM bypassed).")
                return ValidatedCandidateSQL(
                    raw_sql=compiled_sql,
                    sanitized_sql=validation.sanitized_sql,
                    parameterized=parameterized,
                    plan=plan,
                    validation_report=validation,
                    repair_attempts=0,
                    sql_generation_mode="deterministic",
                    deterministic_sql_compilation=True,
                    sql_llm_bypassed=True,
                )

        # =========================================================================
        # PATH B: LLM Candidate SQL Generation & Diagnostic Repair Loop
        # =========================================================================
        logger.info("Executing Phase 2B LLM Candidate SQL generation path...")
        current_sql = await CandidateSQLGenerator.generate_candidate_sql(
            user_query=user_query,
            plan=plan,
            retrieval_result=retrieval_result,
            use_llm=use_llm,
        )

        validation = SQLSecurityPolicyEngine.validate_sql(
            sql_text=current_sql,
            canonical_schema=canonical_schema,
            retrieval_result=retrieval_result,
        )

        repair_count = 0

        # Repair Loop (Maximum 2 attempts)
        while not validation.is_valid and repair_count < cls.MAX_REPAIR_ATTEMPTS:
            repair_count += 1
            logger.info(f"SQL validation failed (attempt {repair_count}/{cls.MAX_REPAIR_ATTEMPTS}). Triggering repair loop...")

            if use_llm:
                try:
                    from app.core.llm.deepinfra_llm import DeepInfraLLMClient

                    client = DeepInfraLLMClient()
                    repair_prompt = SQLPromptBuilder.build_repair_prompt(
                        user_query=user_query,
                        failed_sql=current_sql,
                        diagnostics=validation.errors,
                        retrieval_result=retrieval_result,
                    )

                    response_text = await client.generate_cloud(
                        prompt=repair_prompt,
                        system_prompt=SQLPromptBuilder.SYSTEM_PROMPT,
                        temperature=0.0,
                        max_tokens=1024,
                        enable_thinking=False,
                    )
                    if response_text:
                        repaired_candidate = CandidateSQLGenerator._extract_sql_from_response(response_text)
                        if repaired_candidate:
                            current_sql = repaired_candidate
                except Exception as e:
                    logger.warning(f"LLM repair attempt {repair_count} failed: {e}")
                    # Fallback to deterministic plan compilation
                    current_sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
            else:
                # Deterministic fallback
                current_sql = CandidateSQLGenerator.compile_plan_to_sql(plan)

            validation = SQLSecurityPolicyEngine.validate_sql(
                sql_text=current_sql,
                canonical_schema=canonical_schema,
                retrieval_result=retrieval_result,
            )

        # Fail-Closed if still invalid
        if not validation.is_valid:
            error_msgs = "; ".join([e.message for e in validation.errors])
            raise SQLValidationError(
                f"Candidate SQL failed security validation after {repair_count} repair attempts: {error_msgs}"
            )

        # Parameterize and construct ValidatedCandidateSQL
        ast = SQLASTParser.parse_sql(validation.sanitized_sql)
        parameterized = SQLParameterizer.parameterize(ast)

        return ValidatedCandidateSQL(
            raw_sql=current_sql,
            sanitized_sql=validation.sanitized_sql,
            parameterized=parameterized,
            plan=plan,
            validation_report=validation,
            repair_attempts=repair_count,
            sql_generation_mode="llm",
            deterministic_sql_compilation=False,
            sql_llm_bypassed=False,
        )
