"""Coordination cost as agent count grows (spec §86).

Aggregation only, like the rest of this package: the numbers here were
recorded during a run (the channels' injection accounting and the chain) and
are read out, not re-measured. What this module adds is the shape of the
curve: how a cost changes as N grows, and by what exponent.

The exponent is a least-squares slope of log(cost) on log(N). It is a
description of the measured points, not a fit of a model: with three agent
counts it is a coarse summary, and it is reported next to the points so a
reader can see how coarse. It is `None` when it cannot be computed (fewer
than two points, or a non-positive cost) rather than 0, because "no growth
rate" and "a growth rate of zero" are different claims.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ScalingRun",
    "ScalingSeries",
    "growth_exponent",
    "summarize_scaling",
]


@dataclass(frozen=True)
class ScalingRun:
    """One measured run of the scalability profile.

    `events_available` is what broadcast would have offered: every event an
    agent produced, to each of its N-1 peers. `events_delivered` is what the
    relay actually delivered to agents, as each agent drained them.
    `events_injected` is the number of distinct events a bounded channel
    placed in an agent's context, so `delivered - injected` is what was
    delivered but never seen (§18: "not delivered" and "delivered but not
    injected" are different facts). It is `None` for the transcript arm,
    whose injection counter is replay volume rather than distinct events.
    """

    n_agents: int
    arm: str
    delivery_mode: str
    topology: str
    group_size: int
    agent_events: int
    events_available: int
    events_delivered: int
    events_injected: int | None
    coordination_bytes: int
    per_agent_bytes: tuple[int, ...]
    per_agent_delivered: tuple[int, ...]
    succeeded: bool | None
    chain_valid: bool
    head_hash: str | None

    @property
    def delivery_ratio(self) -> float | None:
        """Delivered over available; None when nothing was available."""
        if self.events_available <= 0:
            return None
        return self.events_delivered / self.events_available

    @property
    def events_unseen(self) -> int | None:
        """Delivered but never placed in an agent's context; None if unknown."""
        if self.events_injected is None:
            return None
        return self.events_delivered - self.events_injected

    @property
    def mean_bytes_per_agent(self) -> float | None:
        if not self.per_agent_bytes:
            return None
        return sum(self.per_agent_bytes) / len(self.per_agent_bytes)

    @property
    def max_bytes_per_agent(self) -> int | None:
        return max(self.per_agent_bytes) if self.per_agent_bytes else None

    @property
    def mean_delivered_per_agent(self) -> float | None:
        if not self.per_agent_delivered:
            return None
        return sum(self.per_agent_delivered) / len(self.per_agent_delivered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_events": self.agent_events,
            "arm": self.arm,
            "chain_valid": self.chain_valid,
            "coordination_bytes": self.coordination_bytes,
            "delivery_mode": self.delivery_mode,
            "delivery_ratio": self.delivery_ratio,
            "events_available": self.events_available,
            "events_delivered": self.events_delivered,
            "events_injected": self.events_injected,
            "events_unseen": self.events_unseen,
            "group_size": self.group_size,
            "head_hash": self.head_hash,
            "max_bytes_per_agent": self.max_bytes_per_agent,
            "mean_bytes_per_agent": self.mean_bytes_per_agent,
            "mean_delivered_per_agent": self.mean_delivered_per_agent,
            "n_agents": self.n_agents,
            "per_agent_bytes": list(self.per_agent_bytes),
            "per_agent_delivered": list(self.per_agent_delivered),
            "succeeded": self.succeeded,
            "topology": self.topology,
        }


def growth_exponent(points: Iterable[tuple[float, float]]) -> float | None:
    """Least-squares slope of log(y) on log(x), or None if undefined.

    Exponent 1 is linear growth, 2 quadratic. Undefined with fewer than two
    distinct x values or any non-positive value, because a logarithm of zero
    is not a small number.
    """
    pairs = list(points)
    if len(pairs) < 2 or any(x <= 0 or y <= 0 for x, y in pairs):
        return None
    xs = [math.log(x) for x, _ in pairs]
    ys = [math.log(y) for _, y in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    if spread == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread


@dataclass
class ScalingSeries:
    """One (arm, delivery mode, topology) curve across agent counts."""

    arm: str
    delivery_mode: str
    topology: str
    runs: list[ScalingRun] = field(default_factory=list)

    def points(self, attribute: str) -> list[tuple[float, float]]:
        return [
            (float(run.n_agents), float(getattr(run, attribute)))
            for run in sorted(self.runs, key=lambda r: r.n_agents)
        ]

    def exponent(self, attribute: str) -> float | None:
        return growth_exponent(self.points(attribute))

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "delivery_mode": self.delivery_mode,
            "exponent_coordination_bytes": self.exponent("coordination_bytes"),
            "exponent_events_delivered": self.exponent("events_delivered"),
            "runs": [run.to_dict() for run in sorted(self.runs, key=lambda r: r.n_agents)],
            "topology": self.topology,
        }


def summarize_scaling(runs: Iterable[ScalingRun]) -> list[ScalingSeries]:
    """Group runs into curves, in a stable order."""
    grouped: dict[tuple[str, str, str], ScalingSeries] = {}
    for run in runs:
        key = (run.arm, run.topology, run.delivery_mode)
        series = grouped.setdefault(
            key,
            ScalingSeries(arm=run.arm, delivery_mode=run.delivery_mode, topology=run.topology),
        )
        series.runs.append(run)
    return [grouped[key] for key in sorted(grouped)]
