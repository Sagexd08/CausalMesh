"""Binding the tool API to the lifecycle boundary (spec §12, §13).

`ToolExecutor` is the only way an agent acts. It takes a named tool and
arguments, routes them through `LifecycleBoundary.invoke`, and — when the
call is allowed and succeeds — emits the corresponding event to the relay.

Keeping this in one place is what makes two guarantees structural rather
than habitual:

- no tool runs without passing the gate;
- no tool call goes unrecorded, denials and failures included.

The event is emitted *after* execution, carrying the real outcome. Emitting
beforehand would record intentions as if they were facts, and a denied write
would appear in the log as a write that happened.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..events.schema import Event, EventIdentity, EventType
from ..hooks.lifecycle import (
    TOOL_EVENT_TYPES,
    LifecycleBoundary,
    ToolCall,
    ToolOutcome,
    ToolResult,
)
from ..relay import Relay
from .api import CommandResult, Toolbox

__all__ = ["ToolExecutor"]


class ToolExecutor:
    """Runs an agent's tool calls through the boundary and into the record."""

    def __init__(
        self,
        *,
        agent_id: str,
        identity: EventIdentity,
        toolbox: Toolbox,
        boundary: LifecycleBoundary,
        relay: Relay,
        event_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.identity = identity
        self.toolbox = toolbox
        self.boundary = boundary
        self.relay = relay
        self._event_counter = 0
        self._event_id_factory = event_id_factory or self._default_event_id
        # The last peer event this agent consumed, recorded as the causal
        # parent of what it does next. This is what makes "what did the agent
        # know before it acted" answerable from the chain (§57).
        self.last_observed_event_id: str | None = None

    def _default_event_id(self) -> str:
        self._event_counter += 1
        return f"evt_{self.agent_id}_{self._event_counter:04d}"

    def call(
        self,
        tool: str,
        *,
        now_us: int,
        paths: tuple[str, ...] = (),
        **arguments: Any,
    ) -> ToolResult:
        """Invoke one tool and record what happened."""
        if not hasattr(self.toolbox, tool) or tool not in TOOL_EVENT_TYPES:
            raise ValueError(
                f"unknown tool {tool!r}; the controlled API is {sorted(TOOL_EVENT_TYPES)}"
            )

        request = ToolCall(
            tool=tool, agent_id=self.agent_id, paths=paths, arguments=dict(arguments)
        )
        result = self.boundary.invoke(
            request, lambda c: getattr(self.toolbox, c.tool)(**c.arguments), now_us=now_us
        )
        self._emit(result, now_us)
        return result

    def _emit(self, result: ToolResult, now_us: int) -> None:
        """Record the call in the event chain, whatever its outcome.

        A denial is emitted as a FAILURE event rather than as the write it
        was refused: the log must say what happened, not what was attempted.
        Without this the enforcement cost of C3 would be invisible to the
        analysis (§20, §44).
        """
        if result.outcome == ToolOutcome.EXECUTED:
            event_type = TOOL_EVENT_TYPES[result.call.tool]
            payload: dict[str, Any] = {"tool": result.call.tool, "outcome": "executed"}
            if isinstance(result.value, CommandResult):
                # to_event_payload, not to_dict: command output is not
                # reproducible and must not enter the signed chain.
                payload.update(result.value.to_event_payload())
            elif isinstance(result.value, int):
                payload["bytes_written"] = result.value
        else:
            event_type = EventType.FAILURE
            payload = {
                "tool": result.call.tool,
                "outcome": str(result.outcome),
                "reason": (
                    result.decision.reason
                    if result.outcome == ToolOutcome.DENIED and result.decision
                    else result.error or ""
                ),
            }
            if result.outcome == ToolOutcome.DENIED and result.decision:
                payload["holder_agent"] = result.decision.holder_agent
                payload["blocked_path"] = result.decision.blocked_path
                # Which rule refused, as a key rather than as prose. The
                # reason is already here and is what a person reads; this is
                # what analysis groups by, so rewording an error message
                # cannot silently change what a measurement counts.
                #
                # Reproducible: the rule is a fixed identifier chosen by the
                # gate, not a timestamp, a path or anything the machine
                # supplies.
                if result.decision.rule:
                    payload["rule"] = result.decision.rule

        # Wall-clock duration is deliberately NOT written into the payload.
        # It varies between runs, and the payload is inside the signed hash
        # chain, so including it would make two identical runs produce
        # different chains and §84's reproducibility requirement
        # unsatisfiable. Timing is still measured — the lifecycle boundary
        # records it, and the metrics layer reads it from there (§85) — but
        # a performance measurement must not contaminate the integrity
        # record.

        ingested = self.relay.ingest(
            event_id=self._event_id_factory(),
            agent_id=self.agent_id,
            event_type=event_type,
            identity=self.identity,
            timestamp_us=now_us,
            paths=result.call.paths,
            parent_id=self.last_observed_event_id,
            payload=payload,
        )
        if not ingested.accepted:
            # The relay refusing an event means the record would be
            # incomplete, which invalidates the run's evidence. Better to
            # fail loudly here than to finish a run whose log has holes.
            raise RuntimeError(f"relay refused an event for {result.call.tool}: {ingested.reason}")

    def observe(self, now_us: int) -> tuple[Event, ...]:
        """Drain delivered peer events and record the causal parent.

        Returns the events themselves rather than their ids: the caller must
        hand them to its coordination channel, and ids alone would not be
        enough to render them. Draining twice is not an option — the second
        drain returns nothing — so this method is the single point at which
        delivered information becomes available.

        Under C0 the result is always empty, which is the isolation
        guarantee showing up at the point where information would otherwise
        enter.
        """
        delivered = self.relay.drain(self.agent_id)
        if delivered:
            self.last_observed_event_id = delivered[-1].event_id
        return delivered
