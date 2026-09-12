"""The provider-neutral coding-agent interface (spec §8).

Five lifecycle methods, and nothing about any particular model provider:

    initialize -> observe -> plan -> act -> finalize

`observe`, `plan` and `act` repeat once per turn; `initialize` and `finalize`
bracket the run. The split matters for measurement rather than for tidiness:
`observe` is where coordination information enters, and keeping it separate
from `act` is what lets §45 report coordination cost apart from task
reasoning cost.

The interface is async because a real provider adapter will do network I/O
and because several agents run concurrently within a turn. The mock agent
implements it synchronously under the hood and simply does not await
anything — an interface that only fits one implementation would be a poor
abstraction, but an async one costs a mock nothing.

Adapters (§8): MockAgent is mandatory and implemented. LocalModelAgent,
OpenAIAdapter and AnthropicAdapter are deferred, tracked in `docs/backlog.md`
rather than stubbed here — §93 permits a placeholder only when it is marked,
documented and unused, and an unused stub with no consumer is worse than an
honest absence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..channels.base import Injection
from ..events.schema import EventIdentity

__all__ = ["AgentContext", "AgentIdentity", "CodingAgent", "TurnResult"]


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """Immutable identity for one agent execution (spec §10).

    Every field is supplied explicitly. §10 forbids deriving identity from
    filenames, because a path can be moved, copied or renamed while the
    evidence it contains must stay attributable.
    """

    experiment_id: str
    task_id: str
    run_id: str
    agent_id: str
    arm: str
    operator_id: str
    machine_id: str
    model_id: str
    model_version: str
    seed: int
    git_commit: str

    def to_event_identity(self) -> EventIdentity:
        return EventIdentity(
            experiment_id=self.experiment_id,
            task_id=self.task_id,
            run_id=self.run_id,
            agent_id=self.agent_id,
            arm=self.arm,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "arm": self.arm,
            "experiment_id": self.experiment_id,
            "git_commit": self.git_commit,
            "machine_id": self.machine_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "operator_id": self.operator_id,
            "run_id": self.run_id,
            "seed": self.seed,
            "task_id": self.task_id,
        }


@dataclass
class AgentContext:
    """What an agent knows at the start of a turn.

    `injection` is the *only* route by which peer information arrives. Any
    other channel would be an unmeasured side path, and the C0 accounting
    would no longer be a complete account of what entered the agent.
    """

    turn: int
    now_us: int
    injection: Injection | None = None
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnResult:
    """What an agent did in one turn.

    `finished` lets an agent stop before the turn budget is exhausted, and
    `stalled` records a turn in which it deliberately did nothing — the two
    are distinct, and collapsing them would hide a stall as an early finish.
    """

    turn: int
    actions: int = 0
    finished: bool = False
    stalled: bool = False
    crashed: bool = False
    error: str | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": self.actions,
            "crashed": self.crashed,
            "error": self.error,
            "finished": self.finished,
            "notes": dict(self.notes),
            "stalled": self.stalled,
            "turn": self.turn,
        }


class CodingAgent(ABC):
    """The interface every adapter implements (spec §8)."""

    def __init__(self, identity: AgentIdentity) -> None:
        self.identity = identity

    @property
    def agent_id(self) -> str:
        return self.identity.agent_id

    @abstractmethod
    async def initialize(self) -> None:
        """Prepare for the run. Called once, before any turn."""

    @abstractmethod
    async def observe(self, context: AgentContext) -> None:
        """Take in coordination information for this turn.

        Separate from `act` so that coordination cost is attributable
        (§45). An agent that folded observation into acting would make the
        two indistinguishable in the accounting.
        """

    @abstractmethod
    async def plan(self, context: AgentContext) -> None:
        """Decide what to do this turn."""

    @abstractmethod
    async def act(self, context: AgentContext) -> TurnResult:
        """Perform this turn's tool calls."""

    @abstractmethod
    async def finalize(self) -> dict[str, Any]:
        """Clean up and return a summary. Called once, after the last turn."""
