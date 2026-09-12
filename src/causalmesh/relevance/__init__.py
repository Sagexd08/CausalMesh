"""Deterministic relevance scoring for the bounded metadata channel (spec §17).

Arithmetic rather than learned, so selection is reproducible from the seed
and any benefit C2 shows is attributable to information rather than to a
ranking function doing unmeasured work.
"""

from __future__ import annotations

from .scorer import (
    DEFAULT_WEIGHTS,
    MUTATING_EVENT_TYPES,
    AgentInterests,
    RelevanceScore,
    RelevanceScorer,
    RelevanceWeights,
)

__all__ = [
    "DEFAULT_WEIGHTS",
    "MUTATING_EVENT_TYPES",
    "AgentInterests",
    "RelevanceScore",
    "RelevanceScorer",
    "RelevanceWeights",
]
