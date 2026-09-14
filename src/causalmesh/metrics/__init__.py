"""Coordination-cost accounting and measured contrasts (spec §44, §45, §46).

Aggregation only: every cost reported here was recorded by the channel at
injection time and persisted in the run artifact. Nothing in this package
re-derives a measurement from event payloads, because a second derivation
of the same quantity is a second answer waiting to disagree with the first.

Staleness estimation (λ̂, δ̂, Δ̂) is **not** here. See `docs/backlog.md`.
"""

from __future__ import annotations

from .accounting import (
    ArmMetrics,
    CollectionMetrics,
    MetricsError,
    RunMetrics,
    collect,
)
from .contrasts import ContrastResult, measure

__all__ = [
    "ArmMetrics",
    "CollectionMetrics",
    "ContrastResult",
    "MetricsError",
    "RunMetrics",
    "collect",
    "measure",
]
