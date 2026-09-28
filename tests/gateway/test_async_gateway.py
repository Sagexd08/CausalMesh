"""Async gateway security invariant tests.

Authorization ordering contract
--------------------------------
Both sync and async execution paths must follow the same sequence:

    1. resolve_resource   – extract declared resource strings
    2. gate.check         – ALLOW or DENY decision (synchronous in both paths)
    3. handler invoked    – ONLY if allowed (never before, never speculatively)
    4. evidence emitted   – always (allowed AND denied calls are recorded)

Tests below verify these invariants explicitly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from causalmesh.gateway.gateway import ToolGateway
from causalmesh.gateway.tool import Tool
from causalmesh.hooks.lifecycle import Gate, GateDecision, LifecycleBoundary
from causalmesh.relay import Relay

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deny_all_boundary() -> LifecycleBoundary:
    class DenyAllGate(Gate):
        def check(self, call: Any, now_us: int) -> GateDecision:
            return GateDecision(allowed=False, reason="always denied")

    return LifecycleBoundary(gate=DenyAllGate())


def _recording_deny_boundary() -> tuple[LifecycleBoundary, list[str]]:
    """Returns a boundary that records calls in `order` before denying."""
    order: list[str] = []

    class OrderTrackingGate(Gate):
        def check(self, call: Any, now_us: int) -> GateDecision:
            order.append("gate_check")
            return GateDecision(allowed=False, reason="denied")

    return LifecycleBoundary(gate=OrderTrackingGate()), order


def _recording_allow_boundary() -> tuple[LifecycleBoundary, list[str]]:
    """Returns an allow-all boundary that records the gate check."""
    order: list[str] = []

    class RecordingAllowGate(Gate):
        def check(self, call: Any, now_us: int) -> GateDecision:
            order.append("gate_check")
            return GateDecision(allowed=True, reason="allowed")

    return LifecycleBoundary(gate=RecordingAllowGate()), order


def _make_gateway(boundary: LifecycleBoundary) -> ToolGateway:
    return ToolGateway(boundary=boundary, relay=Mock(spec=Relay))


# ---------------------------------------------------------------------------
# Sync: allowed path
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_gateway() -> ToolGateway:
    return _make_gateway(LifecycleBoundary())


def test_allowed_sync_tool_executes(empty_gateway: ToolGateway) -> None:
    executed = False

    def handler() -> int:
        nonlocal executed
        executed = True
        return 42

    tool = Tool(name="read_file", handler=handler, mutating=False)
    empty_gateway.register(tool)

    result = empty_gateway.execute(agent_id="test-agent", tool_name="read_file", arguments={})

    assert result.executed
    assert not result.denied
    assert executed


def test_denied_sync_tool_never_executes() -> None:
    executed = False

    def handler() -> int:
        nonlocal executed
        executed = True
        return 42

    boundary = _deny_all_boundary()
    gateway = _make_gateway(boundary)
    tool = Tool(name="sync_action", handler=handler, mutating=True)
    gateway.register(tool)

    result = gateway.execute(agent_id="test-agent", tool_name="sync_action", arguments={})

    assert result.denied
    assert not result.executed
    assert not executed


def test_sync_execution_with_async_handler_raises_error(empty_gateway: ToolGateway) -> None:
    async def async_handler() -> None:
        pass

    tool = Tool(name="async_action", handler=async_handler)
    empty_gateway.register(tool)

    with pytest.raises(TypeError, match="has an asynchronous handler"):
        empty_gateway.execute(agent_id="test", tool_name="async_action")


# ---------------------------------------------------------------------------
# Async: allowed path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowed_async_tool_executes(empty_gateway: ToolGateway) -> None:
    executed = False

    async def handler() -> int:
        nonlocal executed
        executed = True
        return 42

    tool = Tool(name="async_action", handler=handler, mutating=False)
    empty_gateway.register(tool)

    result = await empty_gateway.execute_async(
        agent_id="test-agent", tool="async_action", arguments={}
    )

    assert result.executed
    assert not result.denied
    assert executed


@pytest.mark.asyncio
async def test_denied_async_tool_never_executes() -> None:
    executed = False

    async def handler() -> int:
        nonlocal executed
        executed = True
        return 42

    boundary = _deny_all_boundary()
    gateway = _make_gateway(boundary)
    tool = Tool(name="async_action", handler=handler, mutating=True)
    gateway.register(tool)

    result = await gateway.execute_async(agent_id="test-agent", tool="async_action", arguments={})

    assert result.denied
    assert not result.executed
    assert not executed
    assert result.reason == "always denied"


@pytest.mark.asyncio
async def test_async_execution_with_sync_handler_executes(empty_gateway: ToolGateway) -> None:
    def sync_handler() -> int:
        return 123

    tool = Tool(name="sync_action", handler=sync_handler)
    empty_gateway.register(tool)

    result = await empty_gateway.execute_async(agent_id="test", tool="sync_action")

    assert result.executed


# ---------------------------------------------------------------------------
# Authorization ordering: gate must fire before handler in BOTH paths
# ---------------------------------------------------------------------------


def test_sync_ordering_gate_before_handler() -> None:
    """Gate check is recorded before handler runs (sync path)."""
    order: list[str] = []

    class RecordGate(Gate):
        def check(self, call: Any, now_us: int) -> GateDecision:
            order.append("gate")
            return GateDecision(allowed=True, reason="ok")

    def handler() -> None:
        order.append("handler")

    boundary = LifecycleBoundary(gate=RecordGate())
    gateway = _make_gateway(boundary)
    gateway.register(Tool(name="t", handler=handler, mutating=True))
    gateway.execute(agent_id="a", tool_name="t", arguments={})

    assert order == ["gate", "handler"], f"unexpected order: {order}"


@pytest.mark.asyncio
async def test_async_ordering_gate_before_handler() -> None:
    """Gate check is recorded before handler is awaited (async path)."""
    order: list[str] = []

    class RecordGate(Gate):
        def check(self, call: Any, now_us: int) -> GateDecision:
            order.append("gate")
            return GateDecision(allowed=True, reason="ok")

    async def handler() -> None:
        order.append("handler")

    boundary = LifecycleBoundary(gate=RecordGate())
    gateway = _make_gateway(boundary)
    gateway.register(Tool(name="t", handler=handler, mutating=True))
    await gateway.execute_async(agent_id="a", tool="t", arguments={})

    assert order == ["gate", "handler"], f"unexpected order: {order}"


def test_sync_deny_gate_handler_never_called() -> None:
    """When gate denies, handler order list is empty."""
    order: list[str] = []

    class RecordGate(Gate):
        def check(self, call: Any, now_us: int) -> GateDecision:
            order.append("gate")
            return GateDecision(allowed=False, reason="denied")

    def handler() -> None:
        order.append("handler")

    boundary = LifecycleBoundary(gate=RecordGate())
    gateway = _make_gateway(boundary)
    gateway.register(Tool(name="t", handler=handler, mutating=True))
    result = gateway.execute(agent_id="a", tool_name="t", arguments={})

    assert result.denied
    assert order == ["gate"], f"unexpected order: {order}"


@pytest.mark.asyncio
async def test_async_deny_gate_handler_never_awaited() -> None:
    """When gate denies, async handler is never awaited."""
    order: list[str] = []

    class RecordGate(Gate):
        def check(self, call: Any, now_us: int) -> GateDecision:
            order.append("gate")
            return GateDecision(allowed=False, reason="denied")

    async def handler() -> None:
        order.append("handler")

    boundary = LifecycleBoundary(gate=RecordGate())
    gateway = _make_gateway(boundary)
    gateway.register(Tool(name="t", handler=handler, mutating=True))
    result = await gateway.execute_async(agent_id="a", tool="t", arguments={})

    assert result.denied
    assert order == ["gate"], f"unexpected order: {order}"


# ---------------------------------------------------------------------------
# Evidence: relay.ingest called for both allowed and denied (both paths)
# ---------------------------------------------------------------------------


def test_sync_evidence_emitted_on_allow() -> None:
    relay = Mock(spec=Relay)
    relay.ingest = Mock(return_value=Mock(accepted=True, sequence=1))
    boundary = LifecycleBoundary()
    gateway = ToolGateway(boundary=boundary, relay=relay)
    gateway.register(Tool(name="t", handler=lambda: None, mutating=False))

    result = gateway.execute(agent_id="a", tool_name="t")

    assert result.executed
    relay.ingest.assert_called_once()


def test_sync_evidence_emitted_on_deny() -> None:
    relay = Mock(spec=Relay)
    relay.ingest = Mock(return_value=Mock(accepted=True, sequence=1))
    boundary = _deny_all_boundary()
    gateway = ToolGateway(boundary=boundary, relay=relay)
    gateway.register(Tool(name="t", handler=lambda: None, mutating=True))

    result = gateway.execute(agent_id="a", tool_name="t")

    assert result.denied
    relay.ingest.assert_called_once()


@pytest.mark.asyncio
async def test_async_evidence_emitted_on_allow() -> None:
    relay = Mock(spec=Relay)
    relay.ingest = Mock(return_value=Mock(accepted=True, sequence=1))
    boundary = LifecycleBoundary()
    gateway = ToolGateway(boundary=boundary, relay=relay)

    async def handler() -> None:
        pass

    gateway.register(Tool(name="t", handler=handler, mutating=False))
    result = await gateway.execute_async(agent_id="a", tool="t")

    assert result.executed
    relay.ingest.assert_called_once()


@pytest.mark.asyncio
async def test_async_evidence_emitted_on_deny() -> None:
    relay = Mock(spec=Relay)
    relay.ingest = Mock(return_value=Mock(accepted=True, sequence=1))
    boundary = _deny_all_boundary()
    gateway = ToolGateway(boundary=boundary, relay=relay)

    async def handler() -> None:
        pass

    gateway.register(Tool(name="t", handler=handler, mutating=True))
    result = await gateway.execute_async(agent_id="a", tool="t")

    assert result.denied
    relay.ingest.assert_called_once()
