"""A model-backed coding agent (spec §8, §9).

Implements the same five-method `CodingAgent` lifecycle the scripted agent
does, so the scheduler, relay, gate, channels and chain are untouched by
which kind of agent is running. That is the point: if swapping the agent
required changing anything below it, the substrate would have been coupled
to determinism rather than merely tested with it.

Three properties are load-bearing.

**Tools are reached only through `ToolExecutor`.** The adapter never holds
a `Toolbox`. There is therefore no code path by which a model's output can
touch the filesystem without passing the gate and being recorded — not as a
matter of discipline, but because the object it would need is not reachable
from here.

**`observe` is the only route information takes in.** The channel decides
what the model sees, exactly as it does for the scripted agent. Under C0 it
raises rather than silently dropping, so a contaminated run fails loudly.

**Everything that could change the output is recorded.** Endpoint, model,
temperature, seed, token counts, and every protocol violation, so §43's
confound register has real values rather than "a model was used".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..agents.base import AgentContext, AgentIdentity, CodingAgent, TurnResult
from ..channels.base import CoordinationChannel
from ..hooks.lifecycle import ToolOutcome, ToolResult
from ..tools.executor import ToolExecutor
from .protocol import ParsedAction, ProtocolError, parse_action, system_prompt
from .transport import ChatMessage, ChatResponse, TransportError

__all__ = ["ModelAgent", "ModelSettings"]


@dataclass(frozen=True)
class ModelSettings:
    """Decoding parameters, held constant across arms (§3).

    Defaulted to the most deterministic settings a provider offers, because
    §40 asks for no hidden randomness. This does **not** make a model
    deterministic — temperature 0 is not a reproducibility guarantee on any
    hosted provider, and `docs/adapters.md` says so rather than implying
    otherwise. It removes the randomness that *can* be removed and records
    the rest.
    """

    model: str
    temperature: float = 0.0
    max_tokens: int = 2048
    top_p: float = 1.0
    # Honoured by some providers and ignored by others. Recorded either way,
    # so a run states what it asked for even where the request had no effect.
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_tokens": self.max_tokens,
            "model": self.model,
            "seed": self.seed,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }


@dataclass
class TurnRecord:
    """What happened in one model turn, for the run artifact."""

    turn: int
    action: dict[str, Any] | None = None
    protocol_failure: str | None = None
    transport_failure: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    outcome: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "completion_tokens": self.completion_tokens,
            "latency_ms": self.latency_ms,
            "outcome": self.outcome,
            "prompt_tokens": self.prompt_tokens,
            "protocol_failure": self.protocol_failure,
            "transport_failure": self.transport_failure,
            "turn": self.turn,
        }


class ModelAgent(CodingAgent):
    """A `CodingAgent` driven by a chat-completion endpoint.

    Provider-neutral: the differences between OpenAI, Anthropic and a local
    server live entirely in the client object handed in, which need only
    expose `complete(messages, settings) -> ChatResponse`.
    """

    def __init__(
        self,
        identity: AgentIdentity,
        *,
        client: Any,
        settings: ModelSettings,
        executor: ToolExecutor,
        channel: CoordinationChannel,
        role_description: str = "",
        owns: tuple[str, ...] = (),
        depends_on: tuple[str, ...] = (),
        max_protocol_failures: int = 3,
        tick_us: int = 1_000_000,
    ) -> None:
        super().__init__(identity)
        self.client = client
        self.settings = settings
        self.executor = executor
        self.channel = channel
        self.owns = owns
        self.depends_on = depends_on
        # Bounded: a model stuck emitting prose would otherwise burn the
        # whole turn budget and every token in it. The cap is recorded so
        # "gave up on a non-compliant model" is distinguishable from
        # "finished normally" (§52).
        self.max_protocol_failures = max_protocol_failures
        self.tick_us = tick_us

        self._system = system_prompt(
            agent_id=identity.agent_id,
            role_description=role_description,
            owns=list(owns),
            depends_on=list(depends_on),
        )
        self._history: list[ChatMessage] = []
        self._pending: ParsedAction | None = None
        self._protocol_failures = 0
        self._finished = False

        self.turns: list[TurnResult] = []
        self.turn_records: list[TurnRecord] = []
        self.tool_results: list[ToolResult] = []
        self.observations: list[tuple[int, tuple[str, ...]]] = []
        self.informed_paths: set[str] = set()

    # -- lifecycle --------------------------------------------------------

    async def initialize(self) -> None:
        """Seed the conversation. No model call is made here.

        Calling the model during initialization would spend tokens before
        the run's first turn and put them outside the per-turn accounting
        the coordination-cost measurement depends on (§45).
        """
        self._history = [ChatMessage(role="system", content=self._system)]

    async def observe(self, context: AgentContext) -> None:
        """Take delivered peer events through the channel.

        Identical in structure to the scripted agent's `observe`, and
        deliberately so: the two must receive information by the same route
        or the arms would not mean the same thing for both.
        """
        delivered = self.executor.observe(context.now_us)
        injection = self.channel.offer(delivered, turn=context.turn)
        context.injection = injection

        for event in delivered:
            if _was_injected(event.event_id, injection):
                self.informed_paths.update(event.paths)

        self.observations.append(
            (context.turn, tuple(event.event_id for event in delivered))
        )

        # The injected text is the *only* peer information the model sees.
        # Appending it as a user message keeps it inside the same token
        # accounting as everything else the model reads.
        if injection.text:
            self._history.append(
                ChatMessage(
                    role="user",
                    content=f"Coordination update from your peers:\n{injection.text}",
                )
            )

    async def plan(self, context: AgentContext) -> None:
        """Call the model and parse one action.

        This is where a model-backed agent does its real work, and why the
        interface separates `plan` from `act`: the token cost of deciding is
        attributable separately from the effect of doing (§45).
        """
        record = TurnRecord(turn=context.turn)
        self._pending = None

        self._history.append(
            ChatMessage(
                role="user",
                content=(
                    f"Turn {context.turn}. Emit one JSON action object."
                    if context.turn > 0
                    else "Begin. Emit one JSON action object."
                ),
            )
        )

        try:
            response: ChatResponse = self.client.complete(self._history, self.settings)
        except TransportError as exc:
            # The provider failing is a run event, not a crash: §81 wants
            # the evidence either way, and an unreachable endpoint must not
            # take the surrounding chain down with it.
            record.transport_failure = f"{type(exc).__name__}: {exc}"
            self.turn_records.append(record)
            self._finished = True
            return

        record.prompt_tokens = response.prompt_tokens
        record.completion_tokens = response.completion_tokens
        record.latency_ms = response.latency_ms
        self._history.append(ChatMessage(role="assistant", content=response.text))

        try:
            self._pending = parse_action(response.text)
        except ProtocolError as exc:
            self._protocol_failures += 1
            record.protocol_failure = f"{exc.kind}: {exc}"
            # Told what it did wrong, once, rather than silently re-prompted
            # forever. A model that cannot comply is a measurement, not a
            # thing to work around.
            self._history.append(
                ChatMessage(
                    role="user",
                    content=(
                        f"That reply could not be parsed ({exc.kind}). "
                        "Reply with exactly one JSON object and no other text."
                    ),
                )
            )
            if self._protocol_failures >= self.max_protocol_failures:
                self._finished = True

        self.turn_records.append(record)
        context.notes["planned_action"] = (
            self._pending.tool if self._pending else None
        )

    async def act(self, context: AgentContext) -> TurnResult:
        """Execute the parsed action through the tool boundary."""
        if self._finished or self._pending is None:
            result = TurnResult(
                turn=context.turn,
                finished=self._finished,
                stalled=self._pending is None and not self._finished,
            )
            self.turns.append(result)
            return result

        action = self._pending
        self._pending = None

        if action.done:
            self._finished = True
            result = TurnResult(turn=context.turn, finished=True)
            self.turns.append(result)
            return result

        tool_result = self.executor.call(
            action.tool,
            now_us=context.now_us,
            paths=action.paths,
            **action.arguments,
        )
        self.tool_results.append(tool_result)

        if self.turn_records:
            self.turn_records[-1].action = action.to_dict()
            self.turn_records[-1].outcome = str(tool_result.outcome)

        # A denial is fed back so the model can respond to enforcement
        # rather than repeating the same refused write. This is the C3
        # behaviour the arm exists to measure.
        if tool_result.outcome == ToolOutcome.DENIED:
            reason = tool_result.decision.reason if tool_result.decision else "denied"
            self._history.append(
                ChatMessage(role="user", content=f"That write was refused: {reason}")
            )
        elif tool_result.outcome == ToolOutcome.FAILED:
            self._history.append(
                ChatMessage(
                    role="user", content=f"That call failed: {tool_result.error}"
                )
            )
        elif action.tool == "read_file" and isinstance(tool_result.value, str):
            self._history.append(
                ChatMessage(
                    role="user",
                    content=f"Contents of {action.arguments.get('path')}:\n{tool_result.value}",
                )
            )

        result = TurnResult(turn=context.turn, actions=1)
        self.turns.append(result)
        return result

    async def finalize(self) -> dict[str, Any]:
        return self.summary()

    # -- reporting --------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Everything this agent did, for the run artifact.

        Shaped to match the scripted agent's summary where the fields mean
        the same thing, so downstream analysis does not branch on agent
        kind — and carrying the model-specific fields the confound register
        needs (§43).
        """
        return {
            "agent_id": self.agent_id,
            "coordination": self.channel.accounting.to_dict(),
            "completion_tokens": sum(r.completion_tokens for r in self.turn_records),
            "denied": sum(
                1 for r in self.tool_results if r.outcome == ToolOutcome.DENIED
            ),
            "failed": sum(
                1 for r in self.tool_results if r.outcome == ToolOutcome.FAILED
            ),
            "informed_paths": sorted(self.informed_paths),
            "model": self.settings.to_dict(),
            "observations": [
                {"events": list(events), "turn": turn}
                for turn, events in self.observations
            ],
            "prompt_tokens": sum(r.prompt_tokens for r in self.turn_records),
            "protocol_failures": sum(
                1 for r in self.turn_records if r.protocol_failure
            ),
            "transport_failures": sum(
                1 for r in self.turn_records if r.transport_failure
            ),
            "turn_records": [r.to_dict() for r in self.turn_records],
            "turns": len(self.turns),
        }


def _was_injected(event_id: str, injection: Any) -> bool:
    """Whether the channel placed this event in the agent's context.

    The same rule the scripted agent uses, and it must stay the same: an
    event delivered but dropped by the window (§18) never reached the
    model's context, and counting it as known would credit an arm with
    information it did not receive.
    """
    if injection.events_injected == 0:
        return False
    per_event = [r for r in injection.selection_reasons if "event_id" in r]
    if not per_event:
        return True
    return any(r["event_id"] == event_id for r in per_event)
