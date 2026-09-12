"""The deterministic mock agent (spec §9).

§9 is explicit that this is not a throwaway test double. It is the
laboratory in which C0 through C3 are verified before any model inference is
paid for, so it must be able to produce every behaviour the experiment needs
to observe:

    reading, writing and modifying files      responding to coordination events
    running tests                             creating deliberate conflicts
    emitting intents                          simulating stale reads
    crashing, stalling, retrying              delayed deliberation

Determinism is the point. Given the same script, the same seed and the same
delivered events, the agent takes exactly the same actions — so a
difference between two runs is attributable to the manipulated factors and
nothing else.

The agent does not decide *whether* it may write. It asks, through the
lifecycle boundary, and records what came back. Putting the decision here
would move enforcement out of the layer the experiment manipulates.
"""

from __future__ import annotations

from typing import Any

from ..channels.base import CoordinationChannel
from ..hooks.lifecycle import ToolOutcome, ToolResult
from ..tools.executor import ToolExecutor
from .base import AgentContext, AgentIdentity, CodingAgent, TurnResult
from .script import Action, ActionKind, AgentScript

__all__ = ["MockAgent", "MockAgentCrashError"]


def _was_injected(event_id: str, injection: Any) -> bool:
    """Whether the channel placed this event in the agent's context.

    Only injected events count as known. An event the relay delivered but
    the window dropped (§18) never reached the agent's context, and
    treating it as known would credit an arm with information it did not
    receive.

    Channels describe their selection differently, so the discriminator is
    whether the reasons carry per-event ids at all:

    - C0 injects nothing, so this is always false — the isolation guarantee
      reaching the agent's decision-making.
    - C1 records a single policy entry with no event id, because an
      unbounded transcript selects nothing: everything delivered is
      injected.
    - C2 and C3 record one scored entry per injected event, so the id
      lookup is meaningful and a dropped event is correctly excluded.
    """
    if injection.events_injected == 0:
        return False

    per_event = [
        reason for reason in injection.selection_reasons if "event_id" in reason
    ]
    if not per_event:
        # No per-event selection was performed, so nothing was filtered out.
        return True
    return any(reason["event_id"] == event_id for reason in per_event)


class MockAgentCrashError(RuntimeError):
    """Raised by a scripted `crash` action.

    A distinct type so the harness can tell an *induced* crash — part of the
    experiment (§22) — from a genuine defect in the runtime. Treating the two
    alike would let a real bug hide inside a fault-injection scenario.
    """


class MockAgent(CodingAgent):
    """Executes a declarative script through the real tool path.

    Every action goes through `ToolExecutor`, so the mock exercises the same
    gate, hooks, events and relay a model-backed agent would. A mock that
    called the filesystem directly would validate nothing about the
    coordination infrastructure.
    """

    def __init__(
        self,
        identity: AgentIdentity,
        *,
        script: AgentScript,
        executor: ToolExecutor,
        channel: CoordinationChannel,
        clock_us: int = 0,
        tick_us: int = 1_000_000,
    ) -> None:
        super().__init__(identity)
        self.script = script
        self.executor = executor
        self.channel = channel
        self.clock_us = clock_us
        self.tick_us = tick_us

        self._cursor = 0
        self._initialized = False
        self._finalized = False
        self.turns: list[TurnResult] = []
        self.tool_results: list[ToolResult] = []
        # Peer events observed, per turn. The stale-read analysis (§23) needs
        # to know what an agent had seen at the moment it acted.
        self.observations: list[tuple[int, tuple[str, ...]]] = []
        # Paths this agent has been told a peer touched. Populated only from
        # events the channel actually injected, so it reflects what reached
        # the agent's context rather than what the relay delivered.
        self.informed_paths: set[str] = set()
        # Actions skipped because their guard was not satisfied. Retained so
        # a run's evidence shows the agent chose not to act, rather than the
        # action silently vanishing.
        self.skipped_actions: list[tuple[int, str]] = []

    # -- lifecycle --------------------------------------------------------

    async def initialize(self) -> None:
        self._initialized = True

    async def observe(self, context: AgentContext) -> None:
        """Take delivered peer events through the channel.

        The channel is the only route in. Under C0 it raises if anything is
        offered, so a contaminated run fails here rather than completing and
        looking valid.

        The inbox is drained exactly once per turn: a second drain would
        return nothing and the events would be lost, so the executor hands
        back the events themselves rather than only their ids.
        """
        delivered = self.executor.observe(context.now_us)
        injection = self.channel.offer(delivered, turn=context.turn)
        context.injection = injection

        # Record which paths this agent has actually been *told about*, so a
        # conditional action can depend on it. Only events the channel
        # injected count: an event that was delivered but dropped by the
        # window (§18) never reached the agent's context, and treating it as
        # known would credit C2 with information it did not receive.
        for event in delivered:
            if _was_injected(event.event_id, injection):
                self.informed_paths.update(event.paths)

        self.observations.append(
            (context.turn, tuple(event.event_id for event in delivered))
        )

    async def plan(self, context: AgentContext) -> None:
        """Decide this turn's action.

        The script already fixes the sequence, so planning is a no-op beyond
        recording that the phase happened. It stays in the interface because
        a model-backed adapter does real work here, and the harness measures
        the phases separately.
        """
        context.notes["planned_action"] = (
            str(self.script.actions[self._cursor].kind)
            if self._cursor < len(self.script.actions)
            else None
        )

    async def act(self, context: AgentContext) -> TurnResult:
        """Perform the next scripted action."""
        if self._cursor >= len(self.script.actions):
            result = TurnResult(turn=context.turn, finished=True)
            self.turns.append(result)
            return result

        action = self.script.actions[self._cursor]
        self._cursor += 1

        try:
            result = self._perform(action, context)
        except MockAgentCrashError as crash:
            # An induced crash is data: the run records it and stops this
            # agent, rather than the exception escaping and losing the
            # surrounding evidence (§81).
            result = TurnResult(
                turn=context.turn, crashed=True, finished=True, error=str(crash)
            )

        self.clock_us += self.tick_us
        self.turns.append(result)
        return result

    async def finalize(self) -> dict[str, Any]:
        self._finalized = True
        return self.summary()

    # -- action dispatch --------------------------------------------------

    def _perform(self, action: Action, context: AgentContext) -> TurnResult:
        now = context.now_us

        skip_reason = self._guard_blocks(action)
        if skip_reason is not None:
            # The agent deliberately does not act. Recorded rather than
            # silently dropped: "chose not to act because it was told" is a
            # finding, and it is the mechanism by which information changes
            # an outcome.
            self.skipped_actions.append((context.turn, skip_reason))
            return TurnResult(
                turn=context.turn, actions=0, notes={"skipped": skip_reason}
            )

        if action.kind is ActionKind.CRASH:
            raise MockAgentCrashError(action.note or "scripted crash")

        if action.kind in {ActionKind.WAIT, ActionKind.STALL}:
            # A wait advances the agent's clock without acting. This is how
            # §23's deliberation window is induced: the agent read something,
            # then took time before writing, during which a peer may have
            # invalidated it.
            self.clock_us += action.duration_us
            return TurnResult(
                turn=context.turn,
                stalled=action.kind is ActionKind.STALL,
                notes={"waited_us": action.duration_us},
            )

        if action.kind is ActionKind.INTENT:
            result = self.executor.call(
                "list_files", now_us=now, paths=(), subdirectory=None
            )
            self.tool_results.append(result)
            return TurnResult(turn=context.turn, actions=1, notes={"intent": action.note})

        return self._perform_tool_action(action, context)

    def _guard_blocks(self, action: Action) -> str | None:
        """Whether a conditional action should be skipped, and why.

        This is the only place an agent's behaviour depends on what it was
        told. Keeping it in one predicate means the dependence is auditable
        rather than scattered through the dispatch.
        """
        if action.if_informed_about and action.if_informed_about not in self.informed_paths:
            return f"not informed about {action.if_informed_about}"
        if action.if_uninformed_about and action.if_uninformed_about in self.informed_paths:
            return f"already informed about {action.if_uninformed_about}"
        return None

    def _perform_tool_action(self, action: Action, context: AgentContext) -> TurnResult:
        """Run a file or test action, honouring any scripted retries."""
        attempts = action.retries + 1
        result: ToolResult | None = None

        for attempt in range(attempts):
            result = self._invoke(action, context.now_us + attempt)
            self.tool_results.append(result)
            if result.outcome != ToolOutcome.DENIED:
                break
            # Retrying a denied write is realistic behaviour and is what
            # produces lease-wait time (§21). The retry itself is recorded,
            # so the wait is measured rather than inferred.

        assert result is not None
        return TurnResult(
            turn=context.turn,
            actions=1,
            notes={
                "attempts": attempt + 1,
                "outcome": str(result.outcome),
                "tool": result.call.tool,
            },
        )

    def _invoke(self, action: Action, now_us: int) -> ToolResult:
        """Translate one scripted action into a tool call."""
        path = action.path or ""

        if action.kind is ActionKind.READ:
            return self.executor.call("read_file", now_us=now_us, paths=(path,), path=path)

        if action.kind is ActionKind.WRITE:
            return self.executor.call(
                "write_file",
                now_us=now_us,
                paths=(path,),
                path=path,
                content=self._content_for(action),
            )

        if action.kind is ActionKind.CREATE:
            return self.executor.call(
                "create_file",
                now_us=now_us,
                paths=(path,),
                path=path,
                content=self._content_for(action),
            )

        if action.kind is ActionKind.MODIFY:
            return self.executor.call(
                "modify_file",
                now_us=now_us,
                paths=(path,),
                path=path,
                old=action.old,
                new=action.new,
            )

        if action.kind is ActionKind.DELETE:
            return self.executor.call("delete_file", now_us=now_us, paths=(path,), path=path)

        if action.kind is ActionKind.RENAME:
            destination = action.destination or ""
            return self.executor.call(
                "rename_file",
                now_us=now_us,
                paths=(path, destination),
                source=path,
                destination=destination,
            )

        if action.kind is ActionKind.LIST:
            return self.executor.call(
                "list_files", now_us=now_us, paths=(), subdirectory=action.path
            )

        if action.kind is ActionKind.TEST:
            return self.executor.call("run_tests", now_us=now_us, paths=(), target=action.path)

        raise ScriptDispatchError(
            f"action {action.kind} has no tool mapping; claims are taken by the "
            "harness, not by the agent"
        )

    def _content_for(self, action: Action) -> str:
        """The bytes a write action produces.

        Deterministic and self-describing: the content names the agent and
        the action index, so a file's final state says which agent's write
        survived a conflict without needing the event log.
        """
        if action.content is not None:
            return action.content
        return f"# written by {self.agent_id} (action {self._cursor})\n"

    # -- reporting --------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        denied = sum(1 for r in self.tool_results if r.outcome == ToolOutcome.DENIED)
        failed = sum(1 for r in self.tool_results if r.outcome == ToolOutcome.FAILED)
        return {
            "actions_executed": sum(
                1 for r in self.tool_results if r.outcome == ToolOutcome.EXECUTED
            ),
            "actions_scripted": len(self.script.actions),
            "agent_id": self.agent_id,
            "coordination": self.channel.accounting.to_dict(),
            "crashed": any(turn.crashed for turn in self.turns),
            "denied": denied,
            "failed": failed,
            "informed_paths": sorted(self.informed_paths),
            "observations": [
                {"turn": turn, "event_ids": list(ids)} for turn, ids in self.observations
            ],
            "skipped_actions": [
                {"reason": reason, "turn": turn} for turn, reason in self.skipped_actions
            ],
            "turns": len(self.turns),
        }


class ScriptDispatchError(RuntimeError):
    """Raised when a scripted action has no corresponding tool call."""
