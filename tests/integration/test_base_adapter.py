from unittest.mock import MagicMock

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.gateway.result import GatewayResult
from causalmesh.integrations import BaseFrameworkAdapter

pytestmark = pytest.mark.integration


@pytest.fixture
def mesh(tmp_path) -> CausalMesh:
    """A minimal configured mesh for base adapter testing."""
    config_path = tmp_path / "causalmesh.yaml"
    config_path.write_text(
        """
version: 1
roles:
  - agent_id: "test-agent"
    archetype: "test"
    owns: ["src/"]
policy:
  arm: "C3"
"""
    )
    m = CausalMesh.from_config(config_path)

    def dummy_handler(path: str) -> str:
        return f"read {path}"

    async def dummy_async_handler(path: str) -> str:
        return f"async read {path}"

    m.register_tool(
        Tool(
            name="test_tool",
            handler=dummy_handler,
            mutating=True,
        )
    )

    m.register_tool(
        Tool(
            name="test_tool_async",
            handler=dummy_async_handler,
            mutating=True,
        )
    )
    return m


def test_call_tool_routes_to_mesh_execute(mesh: CausalMesh) -> None:
    adapter = BaseFrameworkAdapter(mesh, agent_id="test-agent")
    result = adapter.call_tool("test_tool", {"path": "src/file.txt"})

    assert isinstance(result, GatewayResult)
    assert result.allowed is True
    assert result.executed is True
    assert result.value == "read src/file.txt"

    events = mesh.audit_events()
    assert len(events) == 1
    assert events[0]["event"]["payload"]["tool"] == "test_tool"


@pytest.mark.asyncio
async def test_acall_tool_routes_to_mesh_execute_async(mesh: CausalMesh) -> None:
    adapter = BaseFrameworkAdapter(mesh, agent_id="test-agent")
    result = await adapter.acall_tool("test_tool_async", {"path": "src/file.txt"})

    assert isinstance(result, GatewayResult)
    assert result.allowed is True
    assert result.executed is True
    assert result.value == "async read src/file.txt"

    events = mesh.audit_events()
    assert len(events) == 1
    assert events[0]["event"]["payload"]["tool"] == "test_tool_async"


def test_format_result_handles_allowed() -> None:
    result = MagicMock(spec=GatewayResult)
    result.allowed = True
    result.executed = True
    result.denied = False
    result.failed = False
    result.value = "success!"
    result.would_refuse = False
    assert BaseFrameworkAdapter.format_result(result) == "success!"


def test_format_result_handles_denied() -> None:
    result = MagicMock(spec=GatewayResult)
    result.allowed = False
    result.executed = False
    result.denied = True
    result.failed = False
    result.reason = "ownership violation"
    result.value = None
    result.would_refuse = False
    formatted = BaseFrameworkAdapter.format_result(result)
    assert "Action denied by policy" in formatted
    assert "ownership violation" in formatted


def test_format_result_handles_failed() -> None:
    result = MagicMock(spec=GatewayResult)
    result.allowed = True
    result.executed = False
    result.denied = False
    result.failed = True
    result.reason = "ValueError: bad input"
    result.value = None
    result.would_refuse = False
    formatted = BaseFrameworkAdapter.format_result(result)
    assert "Action failed" in formatted
    assert "ValueError: bad input" in formatted


def test_format_result_includes_shadow_warnings() -> None:
    result = MagicMock(spec=GatewayResult)
    result.allowed = True
    result.executed = True
    result.denied = False
    result.failed = False
    result.reason = "allowed on C0"
    result.would_refuse = True
    result.value = "success!"
    formatted = BaseFrameworkAdapter.format_result(result)
    assert "WARNING - would refuse under strict policy" in formatted
    assert "allowed on C0" in formatted
    assert "success!" in formatted
