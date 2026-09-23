"""Checkpoint evaluation: `policy.checkpoints`, made real.

A checkpoint fires when a resource's kind matches `on` and its `when`
clause matches. The decision is delegated to a `CheckpointHandler`, a
synchronous callback, so the gate stays synchronous end to end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from causalmesh.policy.contract import Checkpoint
from causalmesh.policy.resource import Resource

__all__ = [
    "AutoDenyHandler",
    "CheckpointDecision",
    "CheckpointHandler",
    "ScriptedHandler",
    "evaluate_checkpoints",
]

_COMPARISON = re.compile(r"^(==|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)$")


@dataclass(frozen=True, slots=True)
class CheckpointDecision:
    """The outcome of one matched checkpoint."""

    approved: bool
    checkpoint: Checkpoint
    resource: Resource
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "checkpoint": self.checkpoint.to_dict(),
            "reason": self.reason,
            "resource": self.resource.to_dict(),
        }


class CheckpointHandler(Protocol):
    """Decides a matched checkpoint. Synchronous, so evaluation never blocks

    on I/O the gate cannot model.
    """

    def decide(
        self, *, agent_id: str, resource: Resource, checkpoint: Checkpoint, now_us: int
    ) -> tuple[bool, str]: ...


@dataclass(frozen=True, slots=True)
class AutoDenyHandler:
    """The default: refuse every matched checkpoint.

    A run with no attached human cannot honor `require: human`, and treating
    that as approval would make an unattended run silently skip the
    safeguard it declared.
    """

    def decide(
        self, *, agent_id: str, resource: Resource, checkpoint: Checkpoint, now_us: int
    ) -> tuple[bool, str]:
        return False, f"no checkpoint handler attached; refusing by default ({checkpoint.require})"


@dataclass(slots=True)
class ScriptedHandler:
    """A deterministic sequence of answers, for tests and reproducible runs."""

    answers: list[bool]
    _index: int = 0

    def decide(
        self, *, agent_id: str, resource: Resource, checkpoint: Checkpoint, now_us: int
    ) -> tuple[bool, str]:
        if self._index >= len(self.answers):
            raise RuntimeError(
                f"ScriptedHandler exhausted its {len(self.answers)} scripted answer(s) "
                f"on a checkpoint for {agent_id!r}"
            )
        answer = self.answers[self._index]
        self._index += 1
        return answer, f"scripted answer #{self._index}: {'approved' if answer else 'denied'}"


def evaluate_checkpoints(
    checkpoints: tuple[Checkpoint, ...],
    *,
    agent_id: str,
    resource: Resource,
    handler: CheckpointHandler,
    now_us: int,
) -> CheckpointDecision | None:
    """The first checkpoint that matches this resource, decided by `handler`.

    `None` when nothing matches — a resource with no declared checkpoint is
    not gated by this rule at all, the same "declare the parts you care
    about" default `Contract` uses elsewhere.
    """
    for checkpoint in checkpoints:
        if checkpoint.on != resource.kind.value:
            continue
        if not _when_matches(checkpoint.when, resource):
            continue
        approved, reason = handler.decide(
            agent_id=agent_id, resource=resource, checkpoint=checkpoint, now_us=now_us
        )
        return CheckpointDecision(
            approved=approved, checkpoint=checkpoint, resource=resource, reason=reason
        )
    return None


def _when_matches(when: dict[str, str], resource: Resource) -> bool:
    """Every clause in `when` must match. Only `usd` (against `resource.amount`)

    is understood today.
    """
    for key, expression in when.items():
        if key != "usd":
            raise ValueError(f"unknown checkpoint `when` key: {key!r}; only 'usd' is understood")
        if not _usd_matches(expression, resource.amount):
            return False
    return True


def _usd_matches(expression: str, amount: Decimal | None) -> bool:
    match = _COMPARISON.match(expression.strip())
    if match is None:
        raise ValueError(f"checkpoint `when.usd` must look like '>0.50', got {expression!r}")
    operator, threshold_text = match.groups()
    try:
        threshold = Decimal(threshold_text)
    except InvalidOperation as exc:
        raise ValueError(
            f"checkpoint `when.usd` threshold is not a number: {threshold_text!r}"
        ) from exc
    if amount is None:
        return False
    comparisons = {
        "==": amount.__eq__,
        ">=": amount.__ge__,
        "<=": amount.__le__,
        ">": amount.__gt__,
        "<": amount.__lt__,
    }
    return bool(comparisons[operator](threshold))
