"""Answer Verifier for Phase 2D Grounded Synthesis

Coordinates numerical verification, entity grounding, truncation compliance,
and empty-result checks. Produces a comprehensive GroundingReport.
"""

from typing import List, Optional
from .grounding import (
    EmptyResultValidator,
    EntityGroundingValidator,
    NumericalVerifier,
    TruncationValidator,
)
from .models import EvidenceModel, GroundingReport, VerificationStatus


class AnswerVerifier:
    """Evaluates candidate answers against database evidence to prevent hallucinations."""

    @classmethod
    def verify(
        cls,
        answer_text: str,
        evidence: EvidenceModel,
        user_query: str = "",
    ) -> GroundingReport:
        """
        Verify candidate answer against all grounding gates.
        Returns a detailed GroundingReport with actionable repair feedback if failed.
        """
        warnings: List[str] = []
        unsupported_claims: List[str] = []

        # 0. Empty Answer Check
        if not answer_text or not answer_text.strip():
            return GroundingReport(
                is_grounded=False,
                verification_status=VerificationStatus.FAILED,
                unsupported_claims=["Answer text is empty."],
                repair_feedback="Generate a non-empty, factual answer based on the database result.",
            )

        # 1. Numerical Verification
        num_ok, bad_numbers = NumericalVerifier.verify(answer_text, evidence, user_query)

        # 2. Entity Grounding
        ent_ok, bad_entities = EntityGroundingValidator.verify(answer_text, evidence, user_query)

        # 3. Truncation Compliance
        trunc_ok, trunc_warnings = TruncationValidator.verify(answer_text, evidence)
        warnings.extend(trunc_warnings)
        if not trunc_ok:
            unsupported_claims.append("Claimed completeness on truncated result")

        # 4. Empty Result Compliance
        empty_ok, empty_warnings = EmptyResultValidator.verify(answer_text, evidence)
        warnings.extend(empty_warnings)
        if not empty_ok:
            unsupported_claims.append("Asserted entities on 0-row empty result")

        is_grounded = num_ok and ent_ok and trunc_ok and empty_ok
        status = VerificationStatus.PASSED if is_grounded else VerificationStatus.FAILED

        # Build repair feedback if not grounded
        repair_feedback: Optional[str] = None
        if not is_grounded:
            feedback_points = []
            if bad_numbers:
                feedback_points.append(f"Remove or correct unsupported numbers: {', '.join(bad_numbers)}.")
            if bad_entities:
                feedback_points.append(f"Remove hallucinated entities: {', '.join(bad_entities)}.")
            if not trunc_ok:
                feedback_points.append("Add a note that the result was truncated at the maximum limit.")
            if not empty_ok:
                feedback_points.append("Acknowledge that no matching records were found in the database.")
            repair_feedback = " ".join(feedback_points)

        return GroundingReport(
            is_grounded=is_grounded,
            verification_status=status,
            unsupported_numbers=bad_numbers,
            unsupported_entities=bad_entities,
            unsupported_claims=unsupported_claims,
            warnings=warnings,
            repair_feedback=repair_feedback,
        )
