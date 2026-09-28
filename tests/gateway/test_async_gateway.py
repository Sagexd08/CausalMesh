from unittest.mock import Mock

import pytest

from causalmesh.gateway.gateway import ToolGateway
from causalmesh.gateway.tool import Tool
from causalmesh.hooks.lifecycle import LifecycleBoundary
from causalmesh.relay import Relay


@pytest.fixture
def empty_gateway():
    boundary = LifecycleBoundary()
    relay = Mock(spec=Relay)
    return ToolGateway(boundary=boundary, relay=relay)


@pytest.mark.asyncio
async def test_allowed_async_tool_executes(empty_gateway):
    executed = False

    async def handler():
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
async def test_denied_async_tool_never_executes(empty_gateway):
    executed = False

    async def handler():
        nonlocal executed
        executed = True
        return 42

    # Gate expects paths to make decisions if mutating is True.
    # But since it's mutating=True and we provide no paths and the AllowAllGate might allow it,
    # let's mock the boundary or configure a gate that denies everything.
    from causalmesh.hooks.lifecycle import Gate, GateDecision

    class DenyAllGate(Gate):
        def check(self, call, now_us):
            return GateDecision(allowed=False, reason="always denied")

    denying_boundary = LifecycleBoundary(gate=DenyAllGate())
    relay = Mock(spec=Relay)
    gateway = ToolGateway(boundary=denying_boundary, relay=relay)

    tool = Tool(name="async_action", handler=handler, mutating=True)
    gateway.register(tool)

    result = await gateway.execute_async(agent_id="test-agent", tool="async_action", arguments={})

    assert result.denied
    assert not result.executed
    assert not executed
    assert result.reason == "always denied"


def test_denied_sync_tool_never_executes():
    executed = False

    def handler():
        nonlocal executed
        executed = True
        return 42

    from causalmesh.hooks.lifecycle import Gate, GateDecision, LifecycleBoundary

    class DenyAllGate(Gate):
        def check(self, call, now_us):
            return GateDecision(allowed=False, reason="always denied")

    denying_boundary = LifecycleBoundary(gate=DenyAllGate())
    relay = Mock(spec=Relay)
    from causalmesh.gateway.gateway import ToolGateway

    gateway = ToolGateway(boundary=denying_boundary, relay=relay)

    tool = Tool(name="sync_action", handler=handler, mutating=True)
    gateway.register(tool)

    result = gateway.execute(agent_id="test-agent", tool_name="sync_action", arguments={})

    assert result.denied
    assert not result.executed
    assert not executed


def test_sync_execution_with_async_handler_raises_error(empty_gateway):
    async def async_handler():
        pass

    tool = Tool(name="async_action", handler=async_handler)
    empty_gateway.register(tool)

    with pytest.raises(TypeError, match="has an asynchronous handler"):
        empty_gateway.execute(agent_id="test", tool_name="async_action")


@pytest.mark.asyncio
async def test_async_execution_with_sync_handler_executes(empty_gateway):
    def sync_handler():
        return 123

    tool = Tool(name="sync_action", handler=sync_handler)
    empty_gateway.register(tool)

    result = await empty_gateway.execute_async(agent_id="test", tool="sync_action")

    assert result.executed
