"""Delivery policies: who sees what (spec §14, §15, §16, §55).

The experimental manipulation lives here rather than inside the relay. Each
arm installs a policy object, and the relay simply asks it who should receive
an event. That separation is what makes C0's isolation claim checkable: it is
a property of which object was installed, not of a conditional buried in the
ingestion path that could be reached by accident.

    C0  NullDelivery       nothing reaches anyone
    C1  BroadcastDelivery  every peer sees every event (transcript)
    C2  BroadcastDelivery  every peer sees every event (structured metadata)
    C3  BroadcastDelivery  as C2; the difference is the claim gate, not fan-out

The four primary arms always get the policies above. The scalability profile
(§86) additionally selects, per run, between `BroadcastDelivery` and
`PathScopedDelivery` for the informed arms through
`policy_for_arm(..., mode=...)`; C0 is `NullDelivery` whatever mode is
requested.

C1 and C2 share a fan-out policy on purpose. They differ in *representation*
— an unbounded transcript versus bounded typed metadata — which is handled by
the channel layer, not by who receives what. Conflating the two would make
the C1→C2 contrast measure delivery differences instead of the
representational difference it is designed to isolate.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..events.schema import Event, EventType

__all__ = [
    "BROADCAST",
    "DELIVERY_MODES",
    "PATH_SCOPED",
    "BroadcastDelivery",
    "NullDelivery",
    "PathScopedDelivery",
    "policy_for_arm",
]

from .core import NullDelivery

# Delivery modes selectable per run. Leaving the mode unset means "whatever
# the arm prescribes", which for C1, C2 and C3 is broadcast.
BROADCAST = "broadcast"
PATH_SCOPED = "path_scoped"
DELIVERY_MODES: tuple[str, ...] = (BROADCAST, PATH_SCOPED)


@dataclass(frozen=True, slots=True)
class BroadcastDelivery:
    """Every participant except the actor receives every event.

    Deliberately unfiltered. Relevance filtering and windowing (§17, §18)
    belong to the channel layer, which records *why* each event was selected;
    doing it here would silently drop events with no trace, and the
    difference between "not available" and "available but not injected" is
    exactly what §18 requires the measurement to preserve.
    """

    def recipients(self, event: Event, participants: Iterable[str]) -> tuple[str, ...]:
        return tuple(participants)


@dataclass(frozen=True, slots=True)
class PathScopedDelivery:
    """Deliver only to agents whose declared interests overlap the event.

    Selected per run through `policy_for_arm(arm, mode="path_scoped",
    interests=...)`, which `tasks.runner.execute_task` calls when a run is
    configured with `delivery_mode="path_scoped"` (the scalability profile,
    §86). The four primary arms never use it: their delivery is broadcast,
    and the C1, C2 and C3 contrasts depend on that.

    Broadcast fan-out grows quadratically with agent count (every event goes
    to N-1 peers, and the number of events itself grows with N). The
    interest map is supplied by the harness rather than inferred, so the
    reduction is explicit and recorded. An agent receives exactly the events
    whose paths intersect its declared interests, and no others.

    An event that carries no path (a directory listing, a test run, the
    acceptance record) cannot be scoped and is delivered to every
    participant, exactly as broadcast would. Dropping it would be a silent
    loss with no trace, which the delivery layer refuses to do.
    """

    interests: Mapping[str, frozenset[str]]

    def recipients(self, event: Event, participants: Iterable[str]) -> tuple[str, ...]:
        if not event.paths:
            return tuple(participants)
        touched = set(event.paths)
        return tuple(
            agent for agent in participants if touched & self.interests.get(agent, frozenset())
        )


MUTATING_EVENT_TYPES = frozenset(
    {
        EventType.WRITE,
        EventType.CREATE,
        EventType.MODIFY,
        EventType.DELETE,
        EventType.RENAME,
    }
)


def policy_for_arm(
    arm: str,
    *,
    mode: str | None = None,
    interests: Mapping[str, frozenset[str]] | None = None,
) -> NullDelivery | BroadcastDelivery | PathScopedDelivery:
    """Return the fan-out policy for an experimental arm.

    Raises on an unknown arm rather than defaulting. A silent default here
    could hand C0 a broadcast policy and destroy the isolation the whole
    experiment rests on, so an unrecognised arm must fail loudly.

    `mode` selects broadcast or path-scoped delivery for the informed arms
    (§86). Omitted, it is broadcast, so every existing caller behaves as it
    did. C0 is `NullDelivery` whatever `mode` says: the isolation guarantee
    is not something a delivery mode can relax. An unknown mode raises, and
    `path_scoped` without an interest map raises rather than falling back
    to broadcast, because a silent fallback would label a broadcast run as
    scoped.
    """
    normalized = arm.strip().upper()
    if mode is not None and mode not in DELIVERY_MODES:
        raise ValueError(f"unknown delivery mode {mode!r}: expected one of {list(DELIVERY_MODES)}")
    if normalized == "C0":
        return NullDelivery()
    if normalized in {"C1", "C2", "C3"}:
        if mode == PATH_SCOPED:
            if interests is None:
                raise ValueError(
                    "path_scoped delivery needs an interest map (agent id -> paths); "
                    "refusing to fall back to broadcast"
                )
            return PathScopedDelivery(interests=dict(interests))
        return BroadcastDelivery()
    raise ValueError(
        f"unknown arm {arm!r}: expected one of C0, C1, C2, C3. "
        "Refusing to guess, because the wrong policy would invalidate the run."
    )
