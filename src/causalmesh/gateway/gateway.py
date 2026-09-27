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
    """

    def __init__(
        self,
        *,
        boundary: LifecycleBoundary,
        relay: Relay,
        agent_id: str = "sdk-agent",
        identity_factory: Any | None = None,
    ) -> None:
        self._boundary = boundary
        self._relay = relay
        self._agent_id = agent_id
        self._identity_factory = identity_factory
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
        """
        from causalmesh.sdk.errors import ToolNotFoundError

        if tool_name not in self._tools:
            raise ToolNotFoundError(
                f"tool {tool_name!r} is not registered. "
                f"Known tools: {self.registered_tools() or ['(none)']}"
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

        internal_result = self._boundary.invoke(aware_call, executor, now_us=ts)

        event_id = self._emit_event(internal_result, agent_id=agent_id, ts=ts)
        return GatewayResult(internal_result, event_id=event_id)

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

    def _emit_event(self, result: InternalToolResult, *, agent_id: str, ts: int) -> str | None:
        """Emit one event to the relay for this result.

        Mirrors the pattern in ``tools/executor.py:ToolExecutor._emit``.
        Executed calls emit as WRITE or READ depending on mutability;
        denied and failed calls emit as FAILURE.
        """
        event_id = self._next_event_id(agent_id)
        identity = self._identity_for(agent_id)

        if result.outcome == ToolOutcome.EXECUTED:
            event_type = _MUTATING_EVENT_TYPE if result.call.paths else _READ_EVENT_TYPE
            payload: dict[str, Any] = {
                "tool": result.call.tool,
                "outcome": "executed",
            }
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
            if not ingested.accepted:
                # Relay refusal is non-fatal for the SDK — we log but
                # do not raise; the call outcome stands.
                return None
            return event_id
        except Exception:  # noqa: BLE001 — relay errors must not mask tool results
            return None


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
