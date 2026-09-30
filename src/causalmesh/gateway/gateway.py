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

from collections.abc import Mapping
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
from causalmesh.policy.ledger import Ledger
from causalmesh.policy.resource import Resource, ResourceKind
from causalmesh.relay import Relay

from .resolver import ResourceResolver
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
        ledger:     Where consumption is recorded once a spend or budget call
                    has run.  Without one, a declared total cannot be enforced
                    and the gate refuses the call (see ``Gate(require_ledger)``).
    """

    def __init__(
        self,
        *,
        boundary: LifecycleBoundary,
        relay: Relay,
        agent_id: str = "sdk-agent",
        identity_factory: Any | None = None,
        gate: ContractGate | None = None,
        ledger: Ledger | None = None,
    ) -> None:
        self._ledger = ledger
        self._boundary = boundary
        self._relay = relay
        self._agent_id = agent_id
        self._identity_factory = identity_factory
        self._gate = gate
        self._tools: dict[str, Tool] = {}
        self._event_counter = 0
        self._resolver = ResourceResolver()

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

    def get_tool(self, name: str) -> Tool:
        """Fetch a registered tool by name.

        Raises:
            ToolNotFoundError: When the tool is not registered.
        """
        from causalmesh.sdk.errors import ToolNotFoundError

        if name not in self._tools:
            raise ToolNotFoundError(
                f"tool {name!r} is not registered. "
                f"Known tools: {self.registered_tools() or ['(none)']}"
            )
        return self._tools[name]

    def _require_known_agent(self, agent_id: str) -> None:
        """Refuse a call the relay holds no signing key for, before anything runs.

        Shared by ``execute`` and ``execute_async`` so the two cannot drift:
        an agent that cannot be recorded must not reach the gate or the
        handler on either path.
        """
        from causalmesh.sdk.errors import UnknownAgentError

        if not self._relay.has_key(agent_id):
            raise UnknownAgentError(
                f"agent {agent_id!r} has no signing key in this session, so its "
                f"calls cannot be recorded. Known agents: {list(self._relay.actors)}. "
                "Declare it under `roles` in causalmesh.yaml or pass it in `agents=`."
            )

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
        annotations: Mapping[str, str] | None = None,
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
            annotations: Extra string fields recorded on the call's event, for
                        the transport to say how the call arrived (the HTTP
                        server records ``identity_source``).  They are
                        signed into the chain, so they must be reproducible:
                        no clock, host or random value.  A key the gateway
                        already writes (``tool``, ``outcome``, ...) is never
                        overridden.

        Raises:
            ToolNotFoundError: When ``tool_name`` is not registered.
            UnknownAgentError: When the relay holds no key for ``agent_id``.
                Checked before the gate, so the handler never runs for a
                call that could not be recorded.
        """
        from causalmesh.sdk.errors import ToolNotFoundError

        if tool_name not in self._tools:
            raise ToolNotFoundError(
                f"tool {tool_name!r} is not registered. "
                f"Known tools: {self.registered_tools() or ['(none)']}"
            )
        self._require_known_agent(agent_id)

        tool = self._tools[tool_name]
        args = dict(arguments or {})
        ts = now_us if now_us is not None else utc_now_micros()

        # Extract paths using ResourceResolver instead of guessing "path".
        if paths is None:
            paths = self._resolver.resolve(tool, args)
        resources = self._resolver.resolve_resources(tool, args)

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
            resources=resources,
            _mutating=tool.mutating,
        )

        import inspect

        if inspect.iscoroutinefunction(tool.handler):
            raise TypeError(
                f"Tool {tool_name!r} has an asynchronous handler. "
                f"Use execute_async() instead of execute()."
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
            annotations=annotations,
        )
        audit_error = self._record_consumption(
            internal_result, resources, agent_id, ts, event_id, audit_error
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

    async def execute_async(
        self,
        *,
        agent_id: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
        paths: tuple[str, ...] | None = None,
        now_us: int | None = None,
        annotations: Mapping[str, str] | None = None,
    ) -> GatewayResult:
        """Route an async tool call through the policy boundary.

        Raises the same ``ToolNotFoundError`` and ``UnknownAgentError`` as
        ``execute()``, before the gate or the handler is reached.
        """
        from causalmesh.sdk.errors import ToolNotFoundError

        if tool not in self._tools:
            raise ToolNotFoundError(
                f"tool {tool!r} is not registered. "
                f"Known tools: {self.registered_tools() or ['(none)']}"
            )
        self._require_known_agent(agent_id)

        tool_obj = self._tools[tool]
        args = dict(arguments or {})
        ts = now_us if now_us is not None else utc_now_micros()

        if paths is None:
            paths = self._resolver.resolve(tool_obj, args)
        resources = self._resolver.resolve_resources(tool_obj, args)

        aware_call: ToolCall = _MutatingAwareCall(  # type: ignore[assignment]
            tool=tool,
            agent_id=agent_id,
            paths=paths,
            arguments=args,
            resources=resources,
            _mutating=tool_obj.mutating,
        )

        import inspect

        async def async_executor(c: ToolCall) -> Any:
            # Optionally support synchronous handlers in execute_async
            if inspect.iscoroutinefunction(tool_obj.handler):
                return await tool_obj.handler(**c.arguments)
            else:
                return tool_obj.handler(**c.arguments)

        checks_before = len(self._gate.verdicts) if self._gate is not None else 0
        internal_result = await self._boundary.invoke_async(aware_call, async_executor, now_us=ts)
        shadow = self._shadow_refusal(checks_before)

        event_id, audit_error = self._emit_event(
            internal_result,
            agent_id=agent_id,
            ts=ts,
            mutating=tool_obj.mutating,
            shadow=shadow,
            annotations=annotations,
        )
        audit_error = self._record_consumption(
            internal_result, resources, agent_id, ts, event_id, audit_error
        )
        return GatewayResult(
            internal_result, event_id=event_id, audit_error=audit_error, shadow=shadow
        )

    def _record_consumption(
        self,
        result: InternalToolResult,
        resources: tuple[Resource, ...],
        agent_id: str,
        ts: int,
        event_id: str | None,
        audit_error: str | None,
    ) -> str | None:
        """Write what a completed spend or budget call consumed to the ledger.

        Only a call that ran is recorded, and only after it ran: a refused
        call spent nothing, and recording on intent would count a refusal
        against the allowance it never touched. A handler that raised is not
        recorded either, which under-counts if it failed after the money left;
        the handler is the only thing that knows, and `docs/backlog.md` says
        so. A ledger that cannot be written is reported on the result rather
        than raised, so it cannot mask the outcome.
        """
        if self._ledger is None or result.outcome != ToolOutcome.EXECUTED:
            return audit_error
        for resource in resources:
            if resource.kind not in (ResourceKind.SPEND, ResourceKind.BUDGET):
                continue
            try:
                self._ledger.record(
                    agent_id=agent_id, resource=resource, now_us=ts, reference=event_id
                )
            except Exception as exc:  # noqa: BLE001 - see docstring
                note = f"ledger: {type(exc).__name__}: {exc}"
                audit_error = note if audit_error is None else f"{audit_error}; {note}"
        return audit_error

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
        annotations: Mapping[str, str] | None = None,
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
        resources: tuple[Resource, ...] = getattr(result.call, "resources", ())

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
            if resources:
                payload["resources"] = [resource.to_dict() for resource in resources]
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
            if resources:
                payload["resources"] = [resource.to_dict() for resource in resources]

        for key, value in (annotations or {}).items():
            payload.setdefault(key, value)

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

    __slots__ = ("_mutating", "agent_id", "arguments", "paths", "resources", "tool")

    def __init__(
        self,
        *,
        tool: str,
        agent_id: str,
        paths: tuple[str, ...] = (),
        arguments: dict[str, Any] | None = None,
        resources: tuple[Resource, ...] = (),
        _mutating: bool = False,
    ) -> None:
        self.tool = tool
        self.agent_id = agent_id
        self.paths = paths
        self.arguments = arguments or {}
        self.resources = resources
        self._mutating = _mutating

    @property
    def is_mutating(self) -> bool:
        return self._mutating
