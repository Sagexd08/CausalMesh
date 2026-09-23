"""The C2/C3 channel: bounded structured metadata (spec §16, §17, §18).

Where C1 replays prose without limit, C2 injects **at most `w` typed events
per turn**, chosen by an explainable relevance score. The structured channel
describes *what changed*, never arbitrary conversation (§16).

The window is what makes C2's cost linear rather than quadratic — §46
predicts `C_md(T) ≤ νwT` — so `w` is the parameter the C1→C2 contrast turns
on. It is configurable, defaults to 8 (§18), and is recorded in the manifest.

Three counts are kept apart on every turn, because §18 requires it:

    events_available   delivered by the relay
    events_selected    scored and ranked
    events_injected    actually placed in context (at most w)
    events_dropped     available but excluded by the window

Collapsing these would make "the agent was never told" indistinguishable
from "the agent was told but the window cut it" — and those two support very
different conclusions about why an arm underperformed.

C3 uses this same channel unchanged. If C3 also altered representation, the
C2→C3 contrast would confound enforcement with a second factor.
"""

from __future__ import annotations

from typing import Any

from ..events.schema import Event
from ..relevance import AgentInterests, RelevanceScorer
from .base import Injection, InjectionAccounting
from .tokens import estimate_tokens

__all__ = ["DEFAULT_WINDOW", "MetadataChannel"]


DEFAULT_WINDOW = 8


def render_event(event: Event) -> str:
    """Render one event as a compact structured line.

    Fixed field order and no prose. This is the representational contrast
    with C1: the same underlying fact, carried as typed fields rather than a
    sentence.
    """
    paths = ",".join(event.paths) if event.paths else "-"
    parts = [
        f"seq={event.sequence}",
        f"actor={event.identity.agent_id}",
        f"type={event.event_type}",
        f"paths={paths}",
    ]
    if event.parent_id:
        parts.append(f"parent={event.parent_id}")
    return " ".join(parts)


class MetadataChannel:
    """Injects at most `window` relevance-ranked events per turn."""

    def __init__(
        self,
        agent_id: str,
        *,
        arm: str = "C2",
        window: int = DEFAULT_WINDOW,
        scorer: RelevanceScorer | None = None,
        interests: AgentInterests | None = None,
    ) -> None:
        if window < 0:
            raise ValueError(f"window must be non-negative, got {window}")
        self.agent_id = agent_id
        self._arm = arm
        self.window = window
        self.scorer = scorer or RelevanceScorer()
        self.interests = interests or AgentInterests(agent_id=agent_id)
        self._accounting = InjectionAccounting(agent_id=agent_id)
        self._known_event_ids: set[str] = set()
        self._pending: list[tuple[Event, int]] = []

    @property
    def arm(self) -> str:
        return self._arm

    @property
    def accounting(self) -> InjectionAccounting:
        return self._accounting

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def offer(self, events: tuple[Event, ...], *, turn: int) -> Injection:
        """Rank everything outstanding and inject the top `window`."""
        for event in events:
            self._pending.append((event, turn))

        available = len(self._pending)
        ranked = self.scorer.rank(
            self._pending,
            interests=self.interests,
            current_turn=turn,
            causal_parents=frozenset(self._known_event_ids),
        )

        chosen = ranked[: self.window]
        chosen_ids = {score.event_id for score in chosen}
        by_id = {event.event_id: event for event, _ in self._pending}

        lines = [render_event(by_id[score.event_id]) for score in chosen]
        text = "\n".join(lines)

        for score in chosen:
            self._known_event_ids.add(score.event_id)
            self.interests.record_touch(by_id[score.event_id].paths)

        self._pending = [
            (event, event_turn)
            for event, event_turn in self._pending
            if event.event_id not in chosen_ids
        ]

        injection = Injection(
            text=text,
            events_available=available,
            events_selected=len(ranked),
            events_injected=len(chosen),
            events_dropped=available - len(chosen),
            selection_reasons=tuple(score.to_dict() for score in chosen),
            tokens=estimate_tokens(text),
        )
        self._accounting.record(injection)
        return injection

    def to_dict(self) -> dict[str, Any]:
        """Channel configuration, for the run manifest (§32)."""
        return {
            "agent_id": self.agent_id,
            "arm": self._arm,
            "pending": len(self._pending),
            "weights": {
                "causal_distance": self.scorer.weights.causal_distance,
                "dependency_overlap": self.scorer.weights.dependency_overlap,
                "path_overlap": self.scorer.weights.path_overlap,
                "priority": self.scorer.weights.priority,
                "recency": self.scorer.weights.recency,
            },
            "window": self.window,
        }
