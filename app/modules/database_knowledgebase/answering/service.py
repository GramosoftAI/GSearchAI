"""Database Answer Synthesis Service for Phase 2D

Orchestrates evidence extraction, deterministic routing, LLM generation,
grounding verification, and fail-closed repair loops to produce GroundedDatabaseAnswer.
"""

import logging
import time
from typing import Any, Dict, Optional
import uuid

from ..execution.models import CanonicalQueryResult
from .calculator import DecimalCalculator
from .errors import AnswerSynthesisError
from .evidence import EvidenceExtractor
from .formatter import DeterministicFormatter
from .generator import AnswerGenerator
from .models import (
    AnswerType,
    EvidenceModel,
    GroundedDatabaseAnswer,
    GroundingReport,
    GroundingStatus,
    VerificationStatus,
)
from .verifier import AnswerVerifier

logger = logging.getLogger(__name__)


class DatabaseAnswerSynthesisService:
    """Orchestrates end-to-end grounded database answer generation with deterministic fast path."""

    MAX_FAST_PATH_ROWS = 15

    AMBIGUOUS_KEYWORDS = {
        "why", "explain", "how come", "reason", "reasons", "cause", "causes",
        "analyze", "trend", "trends", "recommend", "recommendation", "predict",
        "prediction", "opinion", "interpret", "interpretation", "summarize why",
        "better", "worse", "should we", "what does this mean", "elaborate",
    }

    def __init__(
        self,
        generator: Optional[AnswerGenerator] = None,
        max_fast_path_rows: Optional[int] = None,
    ):
        self._has_custom_generator = generator is not None
        self.generator = generator or AnswerGenerator()
        self.max_fast_path_rows = max_fast_path_rows if max_fast_path_rows is not None else self.MAX_FAST_PATH_ROWS

    def _validate_canonical_result(self, result: Any) -> None:
        """Validate structural integrity of CanonicalQueryResult."""
        if not isinstance(result, CanonicalQueryResult):
            raise AnswerSynthesisError(
                detail="Malformed or invalid CanonicalQueryResult provided.",
                error_code="INVALID_CANONICAL_RESULT",
            )
        if result.rows is None or result.columns is None or result.row_count is None:
            raise AnswerSynthesisError(
                detail="CanonicalQueryResult has missing or null structural fields.",
                error_code="MALFORMED_CANONICAL_RESULT",
            )
        if not isinstance(result.rows, list) or not isinstance(result.columns, list):
            raise AnswerSynthesisError(
                detail="CanonicalQueryResult rows or columns must be list instances.",
                error_code="MALFORMED_CANONICAL_RESULT",
            )

    def _is_ambiguous_query(self, user_query: str) -> bool:
        """
        Detect whether a natural language query is ambiguous, explanatory,
        or requires subjective reasoning/analysis beyond factual database presentation.
        """
        q_lower = user_query.lower()
        import re
        tokens = set(re.findall(r"\b\w+\b", q_lower))
        if any(phrase in q_lower for phrase in ["how come", "summarize why", "what does this mean", "should we"]):
            return True
        for kw in self.AMBIGUOUS_KEYWORDS:
            if kw in tokens or kw in q_lower:
                return True
        return False

    async def synthesize_answer(
        self,
        result: CanonicalQueryResult,
        user_query: str,
        use_llm: bool = True,
    ) -> GroundedDatabaseAnswer:
        """
        Transform CanonicalQueryResult into a verified GroundedDatabaseAnswer.
        Uses deterministic fast-paths for zero LLM risk where applicable,
        and strictly verifies LLM synthesis against database evidence.
        """
        t0 = time.perf_counter()

        # 0. Canonical Result Validation
        self._validate_canonical_result(result)

        # 1. Extract Lossless Evidence
        evidence = EvidenceExtractor.extract(result, user_query=user_query)

        # 2. Deterministic Fast-Path Decision Gate (Eligible -> Formatter -> Verifier -> Fast-Path Answer)
        # Skipped if an explicit custom generator was injected for specialized test or workflow evaluation
        if not self._has_custom_generator:
            fast_path_answer = self._try_deterministic_fast_path(user_query, evidence)
            if fast_path_answer is not None:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                fast_path_answer.generation_metadata["total_synthesis_time_ms"] = round(elapsed_ms, 2)
                fast_path_answer.raw_result = result
                return fast_path_answer

        # If LLM is disabled by request, format deterministically as table/summary
        if not use_llm:
            fallback_text = DeterministicFormatter.format_table(user_query, evidence)
            fallback_text = DeterministicFormatter.apply_truncation_disclaimer(fallback_text, evidence.truncated)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return GroundedDatabaseAnswer(
                query_id=evidence.query_id,
                database_knowledgebase_id=evidence.database_knowledgebase_id,
                schema_version=evidence.schema_version,
                answer_text=fallback_text,
                answer_type=AnswerType.MULTI_ROW,
                evidence=evidence,
                source_columns=evidence.columns,
                row_count=evidence.row_count,
                truncated=evidence.truncated,
                grounding_status=GroundingStatus.FALLBACK_DETERMINISTIC,
                verification_status=VerificationStatus.PASSED,
                warnings=result.warnings,
                generation_metadata={
                    "deterministic": True,
                    "fast_path": False,
                    "used_llm": False,
                    "total_synthesis_time_ms": round(elapsed_ms, 2),
                },
                rows=evidence.rows,
                columns=evidence.columns,
                raw_result=result,
            )

        # 3. LLM Synthesis Path with Verification & Repair Loop
        answer_text, telemetry = await self.generator.generate_answer(user_query, evidence)
        report: GroundingReport = AnswerVerifier.verify(answer_text, evidence, user_query)

        final_text = answer_text
        grounding_status = GroundingStatus.VERIFIED

        # Repair Attempt 1: If verification failed, regenerate with targeted feedback
        if not report.is_grounded:
            logger.warning(f"Answer failed initial grounding verification: {report.repair_feedback}. Attempting repair...")
            try:
                repaired_text, rep_telemetry = await self.generator.generate_answer(
                    user_query=user_query,
                    evidence=evidence,
                    repair_feedback=report.repair_feedback,
                )
                rep_report = AnswerVerifier.verify(repaired_text, evidence, user_query)
                if rep_report.is_grounded:
                    final_text = repaired_text
                    grounding_status = GroundingStatus.REPAIRED
                    report = rep_report
                    telemetry.update(rep_telemetry)
                else:
                    # Attempt 2 failed: FAIL CLOSED to deterministic evidence presentation
                    logger.warning("Answer repair attempt 2 failed grounding verification. Failing closed to deterministic presentation.")
                    final_text = DeterministicFormatter.format_table(user_query, evidence)
                    grounding_status = GroundingStatus.FALLBACK_DETERMINISTIC
                    report = GroundingReport(
                        is_grounded=True,
                        verification_status=VerificationStatus.PASSED,
                        warnings=["Answer fell back to deterministic summary following failed LLM verification."],
                    )
            except Exception as e:
                logger.error(f"Error during answer repair attempt: {e}. Failing closed.")
                final_text = DeterministicFormatter.format_table(user_query, evidence)
                grounding_status = GroundingStatus.FALLBACK_DETERMINISTIC
                report = GroundingReport(
                    is_grounded=True,
                    verification_status=VerificationStatus.PASSED,
                    warnings=[f"Answer repair encountered error: {e}"],
                )

        # Apply truncation notice if needed
        final_text = DeterministicFormatter.apply_truncation_disclaimer(final_text, evidence.truncated)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        telemetry["total_synthesis_time_ms"] = round(elapsed_ms, 2)
        telemetry["grounding_verified"] = report.is_grounded

        return GroundedDatabaseAnswer(
            query_id=evidence.query_id,
            database_knowledgebase_id=evidence.database_knowledgebase_id,
            schema_version=evidence.schema_version,
            answer_text=final_text,
            answer_type=self._classify_answer_type(user_query, evidence),
            evidence=evidence,
            source_columns=evidence.columns,
            row_count=evidence.row_count,
            truncated=evidence.truncated,
            grounding_status=grounding_status,
            verification_status=report.verification_status,
            warnings=result.warnings + report.warnings,
            generation_metadata=telemetry,
            rows=evidence.rows,
            columns=evidence.columns,
            raw_result=result,
        )

    def _try_deterministic_fast_path(
        self,
        user_query: str,
        evidence: EvidenceModel,
    ) -> Optional[GroundedDatabaseAnswer]:
        """
        Evaluate if query result satisfies strict criteria for deterministic formatting.
        Eliminates LLM latency and hallucination risks for high-confidence structural patterns.
        Flow: Eligibility Check -> DeterministicFormatter -> AnswerVerifier -> response / fallback.
        """
        # 1. Hard threshold: row count cap (> max_fast_path_rows must fall back to LLM)
        if evidence.row_count > self.max_fast_path_rows:
            logger.debug(
                f"Row count {evidence.row_count} exceeds fast-path threshold "
                f"({self.max_fast_path_rows}). Falling back to LLM."
            )
            return None

        # 2. Check query ambiguity / analytical intent (scalar numeric results remain factual and neutral)
        is_scalar = (evidence.row_count == 1 and len(evidence.columns) == 1)
        if self._is_ambiguous_query(user_query) and not is_scalar:
            logger.debug(f"Query '{user_query}' contains analytical/ambiguous terms. Falling back to LLM.")
            return None

        candidate_text: Optional[str] = None
        answer_type = AnswerType.MULTI_ROW
        fast_path_type = "UNKNOWN"

        q_lower = user_query.lower()

        # Pattern 1: Empty Results (row_count == 0)
        if evidence.row_count == 0:
            candidate_text = DeterministicFormatter.format_empty(user_query, evidence)
            answer_type = AnswerType.EMPTY
            fast_path_type = "EMPTY_RESULT"

        # Pattern 2: Single Scalar / Single Aggregate (COUNT, SUM, AVG, MIN, MAX)
        elif evidence.row_count == 1 and len(evidence.columns) == 1:
            raw_text = DeterministicFormatter.format_scalar(user_query, evidence)
            candidate_text = DeterministicFormatter.apply_truncation_disclaimer(raw_text, evidence.truncated)
            col_name = evidence.columns[0].lower()
            if "count" in col_name or any(k in q_lower for k in ["how many", "count"]):
                answer_type = AnswerType.COUNT
            elif any(k in col_name for k in ["sum", "total", "avg", "average", "min", "max"]) or any(k in q_lower for k in ["sum", "total", "average", "avg", "highest", "lowest", "min", "max"]):
                answer_type = AnswerType.AGGREGATION
            else:
                answer_type = AnswerType.SCALAR
            fast_path_type = "SINGLE_SCALAR"

        # Pattern 3: Simple Ranking List (e.g. "Top 5 ...")
        elif any(k in q_lower for k in ["top 5", "top 10", "ranking", "highest spending"]) and evidence.row_count <= 10:
            name_col = next((c for c in evidence.columns if any(k in c.lower() for k in ["name", "customer", "product", "employee"])), None)
            val_col = next((c for c in evidence.columns if any(k in c.lower() for k in ["amount", "spending", "total", "price", "revenue", "salary"])), None)
            if name_col and val_col:
                raw_text = DeterministicFormatter.format_ranking(user_query, evidence, label_col=name_col, value_col=val_col)
                candidate_text = DeterministicFormatter.apply_truncation_disclaimer(raw_text, evidence.truncated)
                answer_type = AnswerType.RANKING
                fast_path_type = "RANKING_LIST"

        # Pattern 4: Tabular / Entity Listing (1 <= row_count <= max_fast_path_rows)
        elif 1 <= evidence.row_count <= self.max_fast_path_rows:
            if evidence.row_count == 1 and len(evidence.columns) > 1:
                raw_text = DeterministicFormatter.format_single_row(user_query, evidence)
                candidate_text = DeterministicFormatter.apply_truncation_disclaimer(raw_text, evidence.truncated)
                answer_type = AnswerType.SINGLE_ROW
                fast_path_type = "SINGLE_ENTITY"
            else:
                raw_text = DeterministicFormatter.format_table(user_query, evidence, max_display_rows=50)
                candidate_text = DeterministicFormatter.apply_truncation_disclaimer(raw_text, evidence.truncated)
                answer_type = AnswerType.MULTI_ROW
                fast_path_type = "TABULAR_RESULT"

        if candidate_text is None:
            return None

        # 3. Mandatory AnswerVerifier Verification Gate
        report: GroundingReport = AnswerVerifier.verify(
            answer_text=candidate_text,
            evidence=evidence,
            user_query=user_query,
        )

        # If verification fails, do NOT fail closed; fall back smoothly to LLM synthesis!
        if not report.is_grounded:
            logger.warning(
                f"Deterministic candidate text failed AnswerVerifier: {report.repair_feedback}. "
                f"Falling back to LLM synthesis path."
            )
            return None

        # 4. Verified Grounded Answer Construction
        return GroundedDatabaseAnswer(
            query_id=evidence.query_id,
            database_knowledgebase_id=evidence.database_knowledgebase_id,
            schema_version=evidence.schema_version,
            answer_text=candidate_text,
            answer_type=answer_type,
            evidence=evidence,
            source_columns=evidence.columns,
            row_count=evidence.row_count,
            truncated=evidence.truncated,
            grounding_status=GroundingStatus.VERIFIED,
            verification_status=report.verification_status,
            warnings=report.warnings,
            generation_metadata={
                "deterministic": True,
                "fast_path": True,
                "fast_path_type": fast_path_type,
                "grounding_verified": True,
                "used_llm": False,
                "bypass_llm": True,
            },
            rows=evidence.rows,
            columns=evidence.columns,
        )

    def _classify_answer_type(self, user_query: str, evidence: EvidenceModel) -> AnswerType:
        """Classify answer format for telemetry and rendering."""
        q_lower = user_query.lower()
        if evidence.row_count == 0:
            return AnswerType.EMPTY
        if evidence.row_count == 1 and len(evidence.columns) == 1:
            return AnswerType.COUNT if "count" in q_lower else AnswerType.SCALAR
        if any(k in q_lower for k in ["top", "highest", "lowest", "rank"]):
            return AnswerType.RANKING
        if any(k in q_lower for k in ["total", "sum", "average", "avg"]):
            return AnswerType.AGGREGATION
        if evidence.row_count == 1:
            return AnswerType.SINGLE_ROW
        return AnswerType.MULTI_ROW
