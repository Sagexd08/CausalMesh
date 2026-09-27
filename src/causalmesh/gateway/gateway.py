"""The ToolGateway: routes tool calls through the existing lifecycle boundary.

``ToolGateway`` is the bridge between the developer-facing SDK and the
existing CausalMesh enforcement infrastructure:

    Developer
        ↓  gateway.execute(agent_id, tool_name, arguments)
    ToolGateway
        ↓  ToolCall(tool, agent_id, paths, arguments)
    LifecycleBoundary.invoke
        ↓  gate.check(call, now_us)
    ContractGate / PolicyGate
        ↓  ALLOW or DENY
    handler(**arguments)  ← only reached when allowed
        ↓
    GatewayResult

**Security invariant**: the handler is called *only* inside
``LifecycleBoundary.invoke``, which checks the gate before calling the
executor.  ``ToolGateway`` never calls the handler directly.

**Evidence**: every call (allowed *and* denied) is recorded via the
relay supplied to ``ToolGateway``.  Denied calls appear as FAILURE
events, exactly as the existing ``ToolExecutor`` in ``tools/executor.py``
does — the gateway reuses the same pattern without duplicating the
event-emission logic by delegating to the relay directly.
"""

from __future__ import annotations

from typing import Any

from causalmesh.events.schema import EventIdentity, EventType, utc_now_micros
from causalmesh.hooks.lifecycle import (
    LifecycleBoundary,
    ToolCall,
    ToolOutcome,
    ToolResult as InternalToolResult,
)
from causalmesh.hooks.policy_gate import ContractGate
from causalmesh.policy.gate import Verdict
from causalmesh.relay import Relay

from .result import GatewayResult
from .tool import Tool

__all__ = ["ToolGateway"]

# SDK event types for gateway-registered tools
_MUTATING_EVENT_TYPE = EventType.WRITE
_READ_EVENT_TYPE = EventType.READ
_FAILURE_EVENT_TYPE = EventType.FAILURE


class ToolGateway:
    """Registry and execution router for developer-registered tools.

    One instance serves one agent (or all agents in single-agent setups).
    The gateway maintains a registry of ``Tool`` objects and routes every
    call through the provided ``LifecycleBoundary``.

    Args:
        boundary:   The lifecycle boundary that owns gate + recording.
        relay:      The event relay for audit recording.
        agent_id:   Default agent id (can be overridden per call).
        identity_factory: Callable ``(agent_id) -> EventIdentity`` for
                    building event identity when emitting.
        gate:       The ``ContractGate`` behind ``boundary``, when there is
                    one.  Supplying it lets a result report the refusal an
                    unenforced arm recorded but did not act on.
    """

    def __init__(
        self,
        *,
        boundary: LifecycleBoundary,
        relay: Relay,
        agent_id: str = "sdk-agent",
        identity_factory: Any | None = None,
        gate: ContractGate | None = None,
    ) -> None:
        self._boundary = boundary
        self._relay = relay
        self._agent_id = agent_id
        self._identity_factory = identity_factory
        self._gate = gate
        self._tools: dict[str, Tool] = {}
        self._event_counter = 0

    # ------------------------------------------------------------------ #
    # Registration                                                        #
    # ------------------------------------------------------------------ #

    def register(self, tool: Tool) -> None:
        """Add a tool to the registry.

        Overwrites silently when the same name is registered twice so
        that hot-reload patterns work without errors.
        """
        if not isinstance(tool, Tool):
            raise TypeError(f"expected Tool, got {type(tool).__name__}")
        self._tools[tool.name] = tool

    def registered_tools(self) -> list[str]:
        """Names of all registered tools, sorted."""
        return sorted(self._tools)

    # ------------------------------------------------------------------ #
    # Execution                                                           #
    # ------------------------------------------------------------------ #

    def execute(
        self,
        agent_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        paths: tuple[str, ...] | None = None,
        now_us: int | None = None,
    ) -> GatewayResult:
        """Route one tool call through the boundary and return the result.

        The handler is **never** called before the gate allows it.
        Denied calls are recorded in the relay and returned as a
        ``GatewayResult`` with ``denied=True``.

        Args:
            agent_id:   The agent making the call.
            tool_name:  Name of a registered tool.
            arguments:  Keyword arguments forwarded to the handler.
            paths:      Paths the call touches (for gate + event).
                        When omitted, extracted from ``arguments`` if
                        a ``"path"`` key is present.
            now_us:     Timestamp override (for deterministic tests).

        Raises:
            ToolNotFoundError: When ``tool_name`` is not registered.
            UnknownAgentError: When the relay holds no key for ``agent_id``.
                Checked before the gate, so the handler never runs for a
                call that could not be recorded.
        """
        from causalmesh.sdk.errors import ToolNotFoundError, UnknownAgentError

        if tool_name not in self._tools:
            raise ToolNotFoundError(
                f"tool {tool_name!r} is not registered. "
                f"Known tools: {self.registered_tools() or ['(none)']}"
            )
        if not self._relay.has_key(agent_id):
            raise UnknownAgentError(
                f"agent {agent_id!r} has no signing key in this session, so its "
                f"calls cannot be recorded. Known agents: {list(self._relay.actors)}. "
                "Declare it under `roles` in causalmesh.yaml or pass it in `agents=`."
            )

        tool = self._tools[tool_name]
        args = dict(arguments or {})
        ts = now_us if now_us is not None else utc_now_micros()

        # Determine paths for the gate.  When the caller does not provide
        # explicit paths, look for a "path" argument — the common case for
        # filesystem tools.
        if paths is None:
            path_arg = args.get("path")
            paths = (str(path_arg),) if path_arg else ()

        # Override is_mutating based on the Tool's own declaration.
        # LifecycleBoundary only gates calls whose .is_mutating is True,
        # which uses the MUTATING_TOOLS frozenset.  For SDK tools we need
        # to honour the Tool.mutating flag instead.
        # Wrap the tool call so the boundary respects the Tool's mutating flag.
        aware_call: ToolCall = _MutatingAwareCall(  # type: ignore[assignment]
            tool=tool_name,
            agent_id=agent_id,
            paths=paths,
            arguments=args,
            _mutating=tool.mutating,
        )

        def executor(c: ToolCall) -> Any:
            return tool.handler(**c.arguments)

        checks_before = len(self._gate.verdicts) if self._gate is not None else 0
        internal_result = self._boundary.invoke(aware_call, executor, now_us=ts)
        shadow = self._shadow_refusal(checks_before)

        event_id, audit_error = self._emit_event(
            internal_result,
            agent_id=agent_id,
            ts=ts,
            mutating=tool.mutating,
            shadow=shadow,
        )
        return GatewayResult(
            internal_result, event_id=event_id, audit_error=audit_error, shadow=shadow
        )

    def _shadow_refusal(self, checks_before: int) -> Verdict | None:
        """The first refusal this call's checks recorded but did not enforce."""
        if self._gate is None:
            return None
        for verdict in self._gate.verdicts[checks_before:]:
            if verdict.detail.get("would_refuse") is True:
                return verdict
        return None

    # ------------------------------------------------------------------ #
    # Event emission (mirrors tools/executor.py pattern)                  #
    # ------------------------------------------------------------------ #

    def _next_event_id(self, agent_id: str) -> str:
        self._event_counter += 1
        return f"sdk_{agent_id}_{self._event_counter:06d}"

    def _identity_for(self, agent_id: str) -> EventIdentity:
        if self._identity_factory is not None:
            result = self._identity_factory(agent_id)
            return result  # type: ignore[return-value,no-any-return]
        # Fallback: minimal valid identity
        return EventIdentity(
            experiment_id="sdk-run",
            task_id="sdk-task",
            run_id="sdk-run-001",
            agent_id=agent_id,
            arm="C3",
        )

    def _emit_event(
        self,
        result: InternalToolResult,
        *,
        agent_id: str,
        ts: int,
        mutating: bool,
        shadow: Verdict | None = None,
    ) -> tuple[str | None, str | None]:
        """Emit one event to the relay for this result.

        Mirrors the pattern in ``tools/executor.py:ToolExecutor._emit``.
        Executed calls emit as WRITE or READ according to the tool's own
        ``mutating`` declaration; denied and failed calls emit as FAILURE.

        Returns ``(event_id, None)`` when recorded and ``(None, reason)``
        when not, so a missing record is reported rather than silent.
        """
        event_id = self._next_event_id(agent_id)
        identity = self._identity_for(agent_id)

        if result.outcome == ToolOutcome.EXECUTED:
            event_type = _MUTATING_EVENT_TYPE if mutating else _READ_EVENT_TYPE
            payload: dict[str, Any] = {
                "tool": result.call.tool,
                "outcome": "executed",
            }
            if shadow is not None:
                payload["would_refuse"] = True
                payload["shadow_rule"] = shadow.rule
                payload["shadow_reason"] = shadow.reason
        else:
            event_type = _FAILURE_EVENT_TYPE
            payload = {
                "tool": result.call.tool,
                "outcome": str(result.outcome),
                "reason": (
                    result.decision.reason
                    if result.outcome == ToolOutcome.DENIED and result.decision
                    else (result.error or "")
                ),
            }
            if result.outcome == ToolOutcome.DENIED and result.decision:
                payload["holder_agent"] = result.decision.holder_agent
                payload["blocked_path"] = result.decision.blocked_path
                if result.decision.rule:
                    payload["rule"] = result.decision.rule

        try:
            ingested = self._relay.ingest(
                event_id=event_id,
                agent_id=agent_id,
                event_type=event_type,
                identity=identity,
                timestamp_us=ts,
                paths=result.call.paths,
                parent_id=None,
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001 — relay errors must not mask tool results
            return None, f"{type(exc).__name__}: {exc}"
        if not ingested.accepted:
            # The call outcome stands; the missing record is reported on
            # the result instead of raised, so it cannot mask the outcome.
            return None, ingested.reason or "the relay refused the event"
        return event_id, None


class _MutatingAwareCall:
    """A ToolCall-compatible object that honours Tool.mutating.

    ``ToolCall`` uses ``slots=True`` + ``frozen=True`` which makes subclassing
    unreliable across Python implementations.  This duck-typed stand-in satisfies
    the same interface ``LifecycleBoundary.invoke`` needs without inheriting.
    """

    __slots__ = ("_mutating", "agent_id", "arguments", "paths", "tool")

    def __init__(
        self,
        *,
        tool: str,
        agent_id: str,
        paths: tuple[str, ...] = (),
        arguments: dict[str, Any] | None = None,
        _mutating: bool = False,
    ) -> None:
        self.tool = tool
        self.agent_id = agent_id
        self.paths = paths
        self.arguments = arguments or {}
        self._mutating = _mutating

    @property
    def is_mutating(self) -> bool:
        return self._mutating
