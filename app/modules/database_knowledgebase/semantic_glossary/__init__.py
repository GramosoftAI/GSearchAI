"""Semantic Glossary Subsystem

Provides deterministic canonicality filtering, orphan foreign-key risk detection,
offline LLM enrichment, domain workspaces, and verified grounding feedback loops.
"""

from .canonicality import is_canonical_table
from .enrichment import GlossaryEnrichmentService
from .feedback_loop import GlossaryFeedbackLoop, TIER_PRIORITIES
from .workspace_partitioner import WorkspacePartitioner, DomainWorkspacePartitioner
from .drift_handler import (
    SchemaDriftHandler,
    compute_name_similarity,
    compute_rename_confidence,
    has_antonym_tokens,
    has_non_interchangeable_tokens,
    NON_INTERCHANGEABLE_SIBLING_TOKEN_PAIRS,
    NON_INTERCHANGEABLE_TOKEN_MAP,
    OPPOSITE_MEANING_TOKEN_PAIRS,
    OPPOSITE_TOKEN_MAP,
    AUTO_CARRY_CONFIDENCE_THRESHOLD,
    NAME_SIMILARITY_FLOOR,
)

__all__ = [
    "is_canonical_table",
    "GlossaryEnrichmentService",
    "GlossaryFeedbackLoop",
    "TIER_PRIORITIES",
    "WorkspacePartitioner",
    "DomainWorkspacePartitioner",
    "SchemaDriftHandler",
    "compute_name_similarity",
    "compute_rename_confidence",
    "has_antonym_tokens",
    "has_non_interchangeable_tokens",
    "NON_INTERCHANGEABLE_SIBLING_TOKEN_PAIRS",
    "NON_INTERCHANGEABLE_TOKEN_MAP",
    "OPPOSITE_MEANING_TOKEN_PAIRS",
    "OPPOSITE_TOKEN_MAP",
    "AUTO_CARRY_CONFIDENCE_THRESHOLD",
    "NAME_SIMILARITY_FLOOR",
]



