"""The C0 channel: no information, and proof of it (spec §14).

§14 requires C0 to *actively reject* peer events, transcripts, structured
metadata, the claim registry and coordination fan-out — not merely to have
none wired up. The difference matters: an arm that received nothing because
someone forgot to connect it looks identical, in the data, to one that
received nothing by design.

`NullChannel` therefore does two things. It raises if anything is ever
offered to it, so a misconfiguration fails loudly at the moment it happens.
And it reports a permanent zero through the same accounting interface every
other channel uses, so the C0 claim is checked by arithmetic rather than
inferred from absence.
"""

from __future__ import annotations

from ..events.schema import Event
from .base import ChannelError, Injection, InjectionAccounting

__all__ = ["NullChannel"]

# Every C0 turn injects this, and its digest is therefore constant. Recording
# it explicitly means a C0 run has a positive audit trail — "these are the
# bytes that entered" — rather than an empty one that proves nothing.
_EMPTY_INJECTION = Injection(
    text="",
    events_available=0,
    events_selected=0,
    events_injected=0,
    events_dropped=0,
)


class NullChannel:
    """Rejects all coordination information."""

    def __init__(self, agent_id: str) -> None:
        self._accounting = InjectionAccounting(agent_id=agent_id)

    @property
    def arm(self) -> str:
        return "C0"

    @property
    def accounting(self) -> InjectionAccounting:
        return self._accounting

    def offer(self, events: tuple[Event, ...], *, turn: int) -> Injection:
        """Refuse any offered events; record a zero turn otherwise.

        Being handed events at all means the relay's `NullDelivery` policy was
        bypassed — the isolation is already broken upstream, and continuing
        would produce a run that looked valid while being silently
        contaminated.
        """
        if events:
            raise ChannelError(
                f"C0 agent {self._accounting.agent_id!r} was offered "
                f"{len(events)} peer event(s) on turn {turn}; C0 must receive none. "
                "This means the relay's delivery policy was bypassed, and the run "
                "is contaminated rather than merely misconfigured."
            )

        self._accounting.record(_EMPTY_INJECTION)
        return _EMPTY_INJECTION
