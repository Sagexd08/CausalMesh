"""The lifecycle boundary every tool call passes through (spec §13).

The required order is:

    Agent
     -> PreTool hook
     -> information injection
     -> policy / claim gate
     -> tool execution
     -> PostTool hook
     -> event generation
     -> relay
     -> persistence
     -> peer fan-out

Two properties of that ordering carry the experiment:

**The gate runs before execution.** §20 requires that a denied write never
modifies the artifact. Checking afterwards, or checking after opening the
file, would already have truncated it. The boundary therefore refuses before
the tool function is called at all.

**Every call is recorded, including the refused ones.** A denial that leaves
no event is invisible to the analysis, and the enforcement cost of C3 would
be understated. Denied calls emit an event just as executed calls do; they
simply record that nothing happened.

The boundary knows nothing about arms. It is given a gate and a channel, and
the harness decides what those are — the same separation the relay uses, for
the same reason: C0's guarantee should be a property of what was installed,
not of a branch that could be reached by mistake.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from ..events.schema import EventType

__all__ = [
    "Gate",
    "GateDecision",
    "HookContext",
    "LifecycleBoundary",
    "ToolCall",
    "ToolOutcome",
    "ToolResult",
]


class ToolOutcome(StrEnum):
    """How a tool call ended.

    `DENIED` and `FAILED` are distinct: a denial is the coordination
    mechanism working as designed, while a failure is the tool breaking.
    Collapsing them would make enforcement look like unreliability in the
    metrics (§44).
    """

    EXECUTED = "executed"
    DENIED = "denied"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One request from an agent to act on its workspace."""

    tool: str
    agent_id: str
    paths: tuple[str, ...] = ()
    arguments: dict[str, Any] = field(default_factory=dict)

    @property
    def is_mutating(self) -> bool:
        """Whether this call can change the workspace.

        Only mutating calls consult the claim gate. Gating reads would make
        C3 differ from C2 in more than enforcement of *writes*, which is the
        factor the specification defines (§20).
        """
        return self.tool in MUTATING_TOOLS


# The subset of the §12 tool API that can change the workspace.
MUTATING_TOOLS = frozenset(
    {"write_file", "create_file", "modify_file", "delete_file", "rename_file"}
)

# How each tool is recorded in the event log (§16).
TOOL_EVENT_TYPES: dict[str, EventType] = {
    "read_file": EventType.READ,
    "write_file": EventType.WRITE,
    "create_file": EventType.CREATE,
    "modify_file": EventType.MODIFY,
    "delete_file": EventType.DELETE,
    "rename_file": EventType.RENAME,
    "list_files": EventType.READ,
    "run_command": EventType.TEST,
    "run_tests": EventType.TEST,
    "git_status": EventType.READ,
    "git_diff": EventType.READ,
}


@dataclass(frozen=True, slots=True)
class GateDecision:
    """A gate's verdict on one call, with the reason recorded either way."""

    allowed: bool
    reason: str
    holder_agent: str | None = None
    blocked_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blocked_path": self.blocked_path,
            "holder_agent": self.holder_agent,
            "reason": self.reason,
        }


class Gate(Protocol):
    """Decides whether a mutating call may proceed.

    A protocol, so the arm's enforcement behaviour is an installed object
    rather than a conditional inside the boundary.
    """

    def check(self, call: ToolCall, now_us: int) -> GateDecision:
        ...


@dataclass(frozen=True, slots=True)
class AllowAllGate:
    """Permit every call — the C0, C1 and C2 gate.

    The reason states that no enforcement is installed, so an unenforced arm
    is visible in the record rather than merely implied by an absent
    component.
    """

    def check(self, call: ToolCall, now_us: int) -> GateDecision:
        return GateDecision(allowed=True, reason="no enforcement installed for this arm")


@dataclass(frozen=True, slots=True)
class ToolResult:
    """The complete record of one tool call.

    Carries everything the metrics layer needs, so accounting never has to
    re-derive what happened from side effects: what was asked, whether it ran,
    why not if it did not, how long it took, and what the hooks observed.
    """

    call: ToolCall
    outcome: ToolOutcome
    value: Any = None
    error: str | None = None
    decision: GateDecision | None = None
    duration_us: int = 0
    hook_overhead_us: int = 0
    injected_events: int = 0
    injected_bytes: int = 0

    @property
    def executed(self) -> bool:
        return self.outcome == ToolOutcome.EXECUTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.call.agent_id,
            "decision": self.decision.to_dict() if self.decision else None,
            "duration_us": self.duration_us,
            "error": self.error,
            "hook_overhead_us": self.hook_overhead_us,
            "injected_bytes": self.injected_bytes,
            "injected_events": self.injected_events,
            "outcome": str(self.outcome),
            "paths": list(self.call.paths),
            "tool": self.call.tool,
        }


@dataclass
class HookContext:
    """State shared between the pre- and post-tool hooks for one call."""

    call: ToolCall
    now_us: int
    injected_events: int = 0
    injected_bytes: int = 0
    notes: dict[str, Any] = field(default_factory=dict)


class LifecycleBoundary:
    """Runs every tool call through the §13 control point.

    Nothing may reach a tool except through `invoke`. That single entry point
    is what makes "every tool call is recorded" a structural property rather
    than a discipline someone has to remember at each call site.
    """

    def __init__(
        self,
        *,
        gate: Gate | None = None,
        clock: Callable[[], int] | None = None,
        pre_hooks: list[Callable[[HookContext], None]] | None = None,
        post_hooks: list[Callable[[HookContext, ToolResult], None]] | None = None,
    ) -> None:
        self._gate: Gate = gate if gate is not None else AllowAllGate()
        self._clock = clock or _monotonic_micros
        self._pre_hooks = list(pre_hooks or [])
        self._post_hooks = list(post_hooks or [])
        self.results: list[ToolResult] = []

    def invoke(
        self, call: ToolCall, executor: Callable[[ToolCall], Any], *, now_us: int
    ) -> ToolResult:
        """Run one tool call through the full lifecycle.

        `executor` performs the actual work and is called only if the gate
        allows it — the refusal happens before the tool function runs, so a
        denied write cannot have touched the file.
        """
        hook_start = self._clock()
        context = HookContext(call=call, now_us=now_us)
        for hook in self._pre_hooks:
            hook(context)
        hook_overhead = self._clock() - hook_start

        # The gate sees only mutating calls: gating reads would make C3
        # differ from C2 in more than write enforcement.
        decision = (
            self._gate.check(call, now_us)
            if call.is_mutating
            else GateDecision(allowed=True, reason="non-mutating call; gate not consulted")
        )

        if not decision.allowed:
            result = ToolResult(
                call=call,
                outcome=ToolOutcome.DENIED,
                decision=decision,
                hook_overhead_us=max(0, hook_overhead),
                injected_events=context.injected_events,
                injected_bytes=context.injected_bytes,
            )
            return self._finish(context, result)

        started = self._clock()
        try:
            value = executor(call)
        except Exception as exc:
            # §81: a failure is evidence. The run continues and the failure is
            # recorded rather than propagating and losing the surrounding
            # context.
            result = ToolResult(
                call=call,
                outcome=ToolOutcome.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                decision=decision,
                duration_us=max(0, self._clock() - started),
                hook_overhead_us=max(0, hook_overhead),
                injected_events=context.injected_events,
                injected_bytes=context.injected_bytes,
            )
            return self._finish(context, result)

        result = ToolResult(
            call=call,
            outcome=ToolOutcome.EXECUTED,
            value=value,
            decision=decision,
            duration_us=max(0, self._clock() - started),
            hook_overhead_us=max(0, hook_overhead),
            injected_events=context.injected_events,
            injected_bytes=context.injected_bytes,
        )
        return self._finish(context, result)

    def _finish(self, context: HookContext, result: ToolResult) -> ToolResult:
        """Run post-hooks and record the result — for every outcome.

        Denied and failed calls are recorded exactly like executed ones. A
        denial that left no trace would be invisible to the analysis, and
        C3's enforcement cost would be understated.
        """
        post_start = self._clock()
        for hook in self._post_hooks:
            hook(context, result)
        overhead = result.hook_overhead_us + max(0, self._clock() - post_start)

        import dataclasses

        recorded = dataclasses.replace(result, hook_overhead_us=overhead)
        self.results.append(recorded)
        return recorded

    def summary(self) -> dict[str, Any]:
        """Per-outcome counts and hook latency, for the metrics layer (§44)."""
        overheads = sorted(r.hook_overhead_us for r in self.results)
        return {
            "calls": len(self.results),
            "denied": sum(1 for r in self.results if r.outcome == ToolOutcome.DENIED),
            "executed": sum(1 for r in self.results if r.outcome == ToolOutcome.EXECUTED),
            "failed": sum(1 for r in self.results if r.outcome == ToolOutcome.FAILED),
            "hook_latency_p50_us": _percentile(overheads, 50),
            "hook_latency_p99_us": _percentile(overheads, 99),
        }


def _percentile(sorted_values: list[int], percentile: int) -> int | None:
    if not sorted_values:
        return None
    rank = max(1, (percentile * len(sorted_values) + 99) // 100)
    return sorted_values[min(rank, len(sorted_values)) - 1]


def _monotonic_micros() -> int:
    import time

    return time.monotonic_ns() // 1_000
