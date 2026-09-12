"""Deterministic relevance scoring for structured events (spec §17).

C2 gives an agent *bounded* structured metadata. Something must therefore
decide which events make it into a bounded window, and §17 requires that
decision to be **explainable**: every injected event stores why it was
selected.

The scorer is deliberately arithmetic rather than learned. Three reasons:

- **Reproducibility (§40, §84).** The same events, the same agent state and
  the same configuration must yield the same selection on every run. A model
  would introduce a second source of variation on top of the manipulated
  factors.
- **Attribution.** If C2 outperforms C0, the benefit must be attributable to
  *information*, not to a clever ranking function that is itself doing work
  the experiment did not intend to measure.
- **Inspectability.** A reviewer can recompute any score by hand from the
  recorded components.

The components are recorded individually, not just the total. A single number
would say an event scored 0.71 without saying whether that came from path
overlap or from recency, and the two mean very different things when
interpreting a result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..events.schema import Event, EventType

__all__ = [
    "DEFAULT_WEIGHTS",
    "MUTATING_EVENT_TYPES",
    "RelevanceScore",
    "RelevanceScorer",
    "RelevanceWeights",
]


# Event classes that describe a change to the shared repository. A peer's
# READ tells an agent almost nothing about what it must react to; a WRITE
# may invalidate work in progress.
MUTATING_EVENT_TYPES = frozenset(
    {
        EventType.WRITE,
        EventType.CREATE,
        EventType.MODIFY,
        EventType.DELETE,
        EventType.RENAME,
    }
)


@dataclass(frozen=True, slots=True)
class RelevanceWeights:
    """How much each component contributes to the total.

    Configurable rather than hard-coded (§18), and recorded in the run
    manifest so a result can never be reproduced against different weights
    than the ones that produced it.
    """

    path_overlap: float = 0.40
    dependency_overlap: float = 0.25
    causal_distance: float = 0.15
    recency: float = 0.10
    priority: float = 0.10

    def total(self) -> float:
        return (
            self.path_overlap
            + self.dependency_overlap
            + self.causal_distance
            + self.recency
            + self.priority
        )


DEFAULT_WEIGHTS = RelevanceWeights()


@dataclass(frozen=True, slots=True)
class RelevanceScore:
    """A score with its components and a human-readable justification.

    §17 requires that every injected event store *why* it was selected. The
    components are the machine-readable form of that; `reason` is the form a
    reviewer reads.
    """

    event_id: str
    total: float
    path_overlap: float
    dependency_overlap: float
    causal_distance: float
    recency: float
    priority: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "causal_distance": round(self.causal_distance, 6),
            "dependency_overlap": round(self.dependency_overlap, 6),
            "event_id": self.event_id,
            "path_overlap": round(self.path_overlap, 6),
            "priority": round(self.priority, 6),
            "reason": self.reason,
            "recency": round(self.recency, 6),
            "total": round(self.total, 6),
        }


@dataclass
class AgentInterests:
    """What an agent is working on, as declared by the task (§35).

    Declared rather than inferred. Inferring interests from an agent's own
    behaviour would make the information it receives depend on what it has
    already done, coupling the manipulation to the outcome.
    """

    agent_id: str
    owned_paths: frozenset[str] = frozenset()
    dependency_paths: frozenset[str] = frozenset()
    touched_paths: set[str] = field(default_factory=set)

    def record_touch(self, paths: tuple[str, ...]) -> None:
        """Note a path this agent has actually worked on."""
        self.touched_paths.update(paths)

    def all_relevant_paths(self) -> frozenset[str]:
        return frozenset(self.owned_paths | self.dependency_paths | self.touched_paths)


class RelevanceScorer:
    """Scores peer events for one agent, deterministically.

    Every score is a pure function of the event, the agent's declared
    interests and the current turn number — no clocks, no randomness, no
    hidden state that could vary between runs.
    """

    def __init__(self, weights: RelevanceWeights | None = None) -> None:
        self.weights = weights or DEFAULT_WEIGHTS

    def score(
        self,
        event: Event,
        *,
        interests: AgentInterests,
        current_turn: int,
        event_turn: int,
        causal_parents: frozenset[str] = frozenset(),
    ) -> RelevanceScore:
        """Score one event's relevance to one agent."""
        weights = self.weights
        reasons: list[str] = []

        path_overlap = self._path_overlap(event, interests, reasons)
        dependency_overlap = self._dependency_overlap(event, interests, reasons)
        causal_distance = self._causal_distance(event, causal_parents, reasons)
        recency = self._recency(current_turn, event_turn, reasons)
        priority = self._priority(event, reasons)

        total = (
            weights.path_overlap * path_overlap
            + weights.dependency_overlap * dependency_overlap
            + weights.causal_distance * causal_distance
            + weights.recency * recency
            + weights.priority * priority
        )

        return RelevanceScore(
            event_id=event.event_id,
            total=total,
            path_overlap=path_overlap,
            dependency_overlap=dependency_overlap,
            causal_distance=causal_distance,
            recency=recency,
            priority=priority,
            reason="; ".join(reasons) if reasons else "no relevance signal matched",
        )

    def _path_overlap(
        self, event: Event, interests: AgentInterests, reasons: list[str]
    ) -> float:
        """Does this event touch a path the agent cares about?

        The strongest signal: a peer writing a file this agent owns or has
        already edited is the collision the coordination channel exists to
        surface.
        """
        if not event.paths:
            return 0.0
        touched = set(event.paths)

        owned = touched & interests.owned_paths
        if owned:
            reasons.append(f"touches owned path(s) {sorted(owned)}")
            return 1.0

        worked = touched & interests.touched_paths
        if worked:
            reasons.append(f"touches path(s) this agent has edited {sorted(worked)}")
            return 1.0

        return 0.0

    def _dependency_overlap(
        self, event: Event, interests: AgentInterests, reasons: list[str]
    ) -> float:
        """Does this event touch something the agent's work depends on?

        Weaker than owning the path, but this is exactly the stale-dependency
        case (§23): agent B read a schema, agent A changed it, and B's write
        is now built on something that no longer holds.
        """
        if not event.paths:
            return 0.0
        overlap = set(event.paths) & interests.dependency_paths
        if overlap:
            reasons.append(f"touches declared dependency {sorted(overlap)}")
            return 1.0
        return 0.0

    def _causal_distance(
        self, event: Event, causal_parents: frozenset[str], reasons: list[str]
    ) -> float:
        """Is this event causally connected to what the agent already knows?"""
        if event.event_id in causal_parents:
            reasons.append("directly follows an event this agent has already seen")
            return 1.0
        if event.parent_id and event.parent_id in causal_parents:
            reasons.append("descends from an event this agent has already seen")
            return 0.5
        return 0.0

    def _recency(self, current_turn: int, event_turn: int, reasons: list[str]) -> float:
        """How recent is this event, in turns?

        Decays as `1 / (1 + age)`, so the current turn scores 1.0, the
        previous 0.5, and so on. Chosen for being trivially recomputable by
        hand rather than for any modelling reason — an exponential would fit
        no better and would be harder to audit.
        """
        age = max(0, current_turn - event_turn)
        value = 1.0 / (1.0 + age)
        if age == 0:
            reasons.append("emitted this turn")
        elif age <= 2:
            reasons.append(f"recent ({age} turn(s) ago)")
        return value

    def _priority(self, event: Event, reasons: list[str]) -> float:
        """Does this event class describe a change, or merely an observation?"""
        if event.event_type in MUTATING_EVENT_TYPES:
            reasons.append(f"{event.event_type} changes the repository")
            return 1.0
        if event.event_type == EventType.FAILURE:
            reasons.append("reports a failure")
            return 0.75
        if event.event_type in {EventType.CLAIM, EventType.RELEASE}:
            reasons.append("changes claim state")
            return 0.5
        return 0.0

    def rank(
        self,
        events: list[tuple[Event, int]],
        *,
        interests: AgentInterests,
        current_turn: int,
        causal_parents: frozenset[str] = frozenset(),
    ) -> list[RelevanceScore]:
        """Score and order events, most relevant first.

        Ties break on `event_id`, not on list position. Input order can vary
        with delivery timing, and a selection that depended on it would not
        be reproducible from the seed alone (§40).
        """
        scores = [
            self.score(
                event,
                interests=interests,
                current_turn=current_turn,
                event_turn=turn,
                causal_parents=causal_parents,
            )
            for event, turn in events
        ]
        return sorted(scores, key=lambda s: (-s.total, s.event_id))
