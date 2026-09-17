"""Phase 2D: Grounded Database Answer Synthesis Package

Provides enterprise grounded natural language answer synthesis from Phase 2C
CanonicalQueryResult with zero-hallucination guarantees, prompt injection defense,
deterministic fast-paths, and fail-closed repair loops.
"""

from .calculator import DecimalCalculator
from .errors import (
    AnswerRepairExhausted,
    AnswerSynthesisError,
    GroundingViolationError,
    NumericalMismatchError,
    PromptInjectionDetected,
)
from .evidence import EvidenceExtractor
from .formatter import DeterministicFormatter
from .generator import AnswerGenerator
from .grounding import (
    EmptyResultValidator,
    EntityGroundingValidator,
    NumericalVerifier,
    TruncationValidator,
)
from .models import (
    AnswerType,
    EvidenceModel,
    GroundedDatabaseAnswer,
    GroundingReport,
    GroundingStatus,
    VerificationStatus,
)
from .prompt import GroundedAnswerPromptBuilder
from .service import DatabaseAnswerSynthesisService
from .verifier import AnswerVerifier

__all__ = [
    "AnswerType",
    "GroundingStatus",
    "VerificationStatus",
    "EvidenceModel",
    "GroundingReport",
    "GroundedDatabaseAnswer",
    "AnswerSynthesisError",
    "GroundingViolationError",
    "NumericalMismatchError",
    "PromptInjectionDetected",
    "AnswerRepairExhausted",
    "DecimalCalculator",
    "EvidenceExtractor",
    "DeterministicFormatter",
    "GroundedAnswerPromptBuilder",
    "AnswerGenerator",
    "NumericalVerifier",
    "EntityGroundingValidator",
    "TruncationValidator",
    "EmptyResultValidator",
    "AnswerVerifier",
    "DatabaseAnswerSynthesisService",
]
