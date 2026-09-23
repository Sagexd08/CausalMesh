"""Coordination channels: the single point where information enters an agent.

Spec §14, §15, §16, §18. This module is layer **L3** of the isolation model in
`docs/security.md`, and it is what makes §96's first question answerable:

    Can we prove C0 received no coordination information?

The proof is arithmetic, not architectural. Every channel counts the bytes it
injects into an agent's context, and `NullChannel` both raises on any
injection attempt and reports a permanent zero. A C0 run whose counter is
non-zero is invalid and the harness fails it, rather than the isolation
resting on the belief that nothing was wired up.

Channels differ in **representation**, which is the C1→C2 contrast:

    C1  TranscriptChannel   unbounded prose; grows without limit
    C2  MetadataChannel     bounded typed events, at most `w` per turn
    C3  MetadataChannel     identical to C2 — C3 differs by enforcement only

C3 sharing C2's channel is deliberate. If C3 also changed representation, the
C2→C3 contrast would confound enforcement with a second factor.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..events.schema import Event

__all__ = [
    "ChannelError",
    "CoordinationChannel",
    "Injection",
    "InjectionAccounting",
]


class ChannelError(RuntimeError):
    """Raised when a channel is asked to do something its arm forbids."""


@dataclass(frozen=True, slots=True)
class Injection:
    """One turn's worth of information handed to an agent.

    Carries both the rendered text and the accounting, so a caller cannot use
    the content without the measurement being available — the two travel
    together by construction.
    """

    text: str
    events_available: int
    events_selected: int
    events_injected: int
    events_dropped: int
    selection_reasons: tuple[dict[str, Any], ...] = ()
    tokens: int = 0

    @property
    def bytes_injected(self) -> int:
        return len(self.text.encode("utf-8"))

    def digest(self) -> str:
        """SHA-256 of the injected bytes.

        Recorded per turn so a later audit can confirm exactly what entered
        an agent's context — and, for C0, that the digest is the digest of
        the empty string.
        """
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "bytes_injected": self.bytes_injected,
            "digest": self.digest(),
            "events_available": self.events_available,
            "events_dropped": self.events_dropped,
            "events_injected": self.events_injected,
            "events_selected": self.events_selected,
            "selection_reasons": list(self.selection_reasons),
            "tokens": self.tokens,
        }


@dataclass
class InjectionAccounting:
    """Running totals for one agent's coordination cost (§18, §45).

    §18 requires availability and injection to stay distinguishable: an event
    that was delivered but not selected is a different fact from one that was
    never delivered. Both are tracked.
    """

    agent_id: str
    turns: int = 0
    total_bytes: int = 0
    total_tokens: int = 0
    events_available: int = 0
    events_selected: int = 0
    events_injected: int = 0
    events_dropped: int = 0
    digests: list[str] = field(default_factory=list)

    def record(self, injection: Injection) -> None:
        self.turns += 1
        self.total_bytes += injection.bytes_injected
        self.total_tokens += injection.tokens
        self.events_available += injection.events_available
        self.events_selected += injection.events_selected
        self.events_injected += injection.events_injected
        self.events_dropped += injection.events_dropped
        self.digests.append(injection.digest())

    @property
    def received_no_coordination(self) -> bool:
        """The C0 assertion, as a checkable property.

        True only when nothing was available, nothing was injected and not a
        single byte crossed the boundary. Checking bytes alone would pass for
        an empty-but-attempted injection; checking availability alone would
        miss a channel that injected something it invented itself.
        """
        return self.total_bytes == 0 and self.events_injected == 0 and self.events_available == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "coordination_bytes": self.total_bytes,
            "coordination_tokens": self.total_tokens,
            "events_available": self.events_available,
            "events_dropped": self.events_dropped,
            "events_injected": self.events_injected,
            "events_selected": self.events_selected,
            "received_no_coordination": self.received_no_coordination,
            "turns": self.turns,
            "turn_digests": list(self.digests),
        }


class CoordinationChannel(Protocol):
    """What every arm's channel must provide.

    A protocol, so the arm's information behaviour is an installed object
    rather than a branch inside the runtime — the same reasoning as the
    relay's delivery policy and the boundary's gate.
    """

    @property
    def arm(self) -> str: ...

    @property
    def accounting(self) -> InjectionAccounting: ...

    def offer(self, events: tuple[Event, ...], *, turn: int) -> Injection:
        """Render delivered peer events into an agent's context for one turn."""
        ...
