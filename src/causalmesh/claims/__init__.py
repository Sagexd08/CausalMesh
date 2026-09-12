"""Write claims and leases — the enforcement half of the experiment (§19, §20 and §21).

C3 differs from C2 by exactly one thing: writes must pass the claim gate.
This package therefore has no notion of arms or experiments itself; it
enforces exclusivity and records denials, and the harness decides which arm
consults it.
"""

from __future__ import annotations

from .registry import (
    Claim,
    ClaimDeniedError,
    ClaimError,
    ClaimOutcome,
    ClaimRegistry,
    ClaimStatus,
)

__all__ = [
    "Claim",
    "ClaimDeniedError",
    "ClaimError",
    "ClaimOutcome",
    "ClaimRegistry",
    "ClaimStatus",
]
