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

C1 and C2 share a fan-out policy on purpose. They differ in *representation*
— an unbounded transcript versus bounded typed metadata — which is handled by
the channel layer, not by who receives what. Conflating the two would make
the C1→C2 contrast measure delivery differences instead of the
representational difference it is designed to isolate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..events.schema import Event, EventType

__all__ = [
    "BroadcastDelivery",
    "NullDelivery",
    "PathScopedDelivery",
    "policy_for_arm",
]

from .core import NullDelivery  # re-exported: C0's policy lives with the protocol


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

    Not used by the four primary arms. It exists for the scalability profile
    (§86), where broadcast fan-out grows quadratically with agent count; the
    interest map is supplied by the harness rather than inferred, so the
    reduction is explicit and recorded.
    """

    interests: dict[str, frozenset[str]]

    def recipients(self, event: Event, participants: Iterable[str]) -> tuple[str, ...]:
        # Events that name no path (INTENT, FAILURE) carry run-level meaning
        # and go to everyone; scoping them by path would silently hide them.
        if not event.paths:
            return tuple(participants)
        touched = set(event.paths)
        return tuple(
            agent for agent in participants if touched & self.interests.get(agent, frozenset())
        )


# Event classes that describe a change to the shared repository. Retained for
# the channel layer's relevance scoring; the relay itself does not filter.
MUTATING_EVENT_TYPES = frozenset(
    {
        EventType.WRITE,
        EventType.CREATE,
        EventType.MODIFY,
        EventType.DELETE,
        EventType.RENAME,
    }
)


def policy_for_arm(arm: str) -> NullDelivery | BroadcastDelivery:
    """Return the fan-out policy for an experimental arm.

    Raises on an unknown arm rather than defaulting. A silent default here
    could hand C0 a broadcast policy and destroy the isolation the whole
    experiment rests on, so an unrecognised arm must fail loudly.
    """
    normalized = arm.strip().upper()
    if normalized == "C0":
        return NullDelivery()
    if normalized in {"C1", "C2", "C3"}:
        return BroadcastDelivery()
    raise ValueError(
        f"unknown arm {arm!r}: expected one of C0, C1, C2, C3. "
        "Refusing to guess, because the wrong policy would invalidate the run."
    )
