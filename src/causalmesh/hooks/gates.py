"""Gates that decide whether a mutating tool call may proceed (spec §13, §20).

A gate is the enforcement factor made concrete. C0, C1 and C2 install
`AllowAllGate`; C3 installs `ClaimGate`. Nothing else about the runtime
differs, which is what lets the C2→C3 contrast be read as enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..claims import ClaimRegistry
from .lifecycle import AllowAllGate, Gate, GateDecision, ToolCall

__all__ = ["AllowAllGate", "ClaimGate", "gate_for_arm"]


@dataclass(frozen=True, slots=True)
class ClaimGate:
    """Refuse a mutating call when a peer holds a live claim on the path.

    Every path in the call is checked, and the first refusal stops the call.
    A partially-applied multi-path operation would leave the workspace in a
    state no event described.
    """

    registry: ClaimRegistry
    run_id: str

    def check(self, call: ToolCall, now_us: int) -> GateDecision:
        for path in call.paths:
            outcome = self.registry.may_write(
                path=path, agent_id=call.agent_id, run_id=self.run_id, now_us=now_us
            )
            if not outcome.granted:
                return GateDecision(
                    allowed=False,
                    reason=outcome.reason,
                    holder_agent=outcome.holder.agent_id if outcome.holder else None,
                    blocked_path=path,
                )
        return GateDecision(allowed=True, reason="no conflicting claim on any path")


def gate_for_arm(arm: str, *, registry: ClaimRegistry | None, run_id: str) -> Gate:
    """Return the gate an arm installs.

    Raises on an unknown arm, and on C3 without a registry. Both would
    silently produce an unenforced C3 run that looked like a valid one — the
    C2→C3 contrast would then measure nothing, with no error to reveal it.
    """
    normalized = arm.strip().upper()
    if normalized in {"C0", "C1", "C2"}:
        return AllowAllGate()
    if normalized == "C3":
        if registry is None:
            raise ValueError(
                "arm C3 requires a claim registry; without one the run would be "
                "indistinguishable from C2 while claiming to be enforced"
            )
        return ClaimGate(registry=registry, run_id=run_id)
    raise ValueError(f"unknown arm {arm!r}: expected one of C0, C1, C2, C3")
