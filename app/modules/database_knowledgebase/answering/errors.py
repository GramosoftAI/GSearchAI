"""Typed Exceptions for Phase 2D: Grounded Database Answer Synthesis

All exceptions inherit from DatabaseKnowledgebaseError and sanitize internal messages,
guaranteeing zero leakage of connection DSNs, passwords, or system internals.
"""

from typing import Any, Dict, Optional
from ..exceptions.errors import DatabaseKnowledgebaseError


class AnswerSynthesisError(DatabaseKnowledgebaseError):
    """Base exception for all answer synthesis failures."""
    def __init__(
        self,
        detail: str = "Failed to synthesize grounded answer from query result.",
        error_code: str = "ANSWER_SYNTHESIS_ERROR",
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 500,
    ):
        super().__init__(detail=detail, status_code=status_code, error_code=error_code, details=details)


class GroundingViolationError(AnswerSynthesisError):
    """Raised when generated answer asserts facts or entities not present in database evidence."""
    def __init__(
        self,
        detail: str = "Answer failed grounding validation against database evidence.",
        error_code: str = "GROUNDING_VIOLATION",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(detail=detail, error_code=error_code, details=details, status_code=422)


class NumericalMismatchError(AnswerSynthesisError):
    """Raised when generated answer contains numerical values or arithmetic differing from database evidence."""
    def __init__(
        self,
        detail: str = "Answer numerical values diverge from exact database evidence.",
        error_code: str = "NUMERICAL_MISMATCH",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(detail=detail, error_code=error_code, details=details, status_code=422)


class PromptInjectionDetected(AnswerSynthesisError):
    """Raised when malicious prompt injection or system override is detected in input context."""
    def __init__(
        self,
        detail: str = "Untrusted input triggered prompt injection barrier.",
        error_code: str = "PROMPT_INJECTION_DETECTED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(detail=detail, error_code=error_code, details=details, status_code=403)


class AnswerRepairExhausted(AnswerSynthesisError):
    """Raised when maximum repair iterations fail to produce a verifiable answer."""
    def __init__(
        self,
        detail: str = "Maximum answer repair attempts exhausted without satisfying grounding constraints.",
        error_code: str = "ANSWER_REPAIR_EXHAUSTED",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(detail=detail, error_code=error_code, details=details, status_code=422)
