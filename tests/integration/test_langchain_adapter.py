"""Integration tests for the LangChain adapter."""

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.integrations import LangChainAdapter


@pytest.fixture
def mesh(tmp_path) -> CausalMesh:
    """A minimal configured mesh."""
    config_path = tmp_path / "causalmesh.yaml"
    config_path.write_text(
        """
version: 1
agent:
  id: "test-agent"
roles:
  - agent_id: "test-agent"
    archetype: "test"
    owns: ["src/"]
  - agent_id: "dba"
    archetype: "test"
    owns: ["production/"]
policy:
  arm: "C3"
tools:
  test_tool:
    mode: "auto"
  forbidden_tool:
    mode: "auto"
"""
    )
    m = CausalMesh.from_config(config_path)

    def dummy_handler(a: int, b: str) -> str:
        return f"{b}-{a}"

    m.register_tool(
        Tool(
            name="test_tool",
            handler=dummy_handler,
            description="A test tool that concatenates a string and an integer.",
            mutating=True,
        )
    )
    return m


def test_langchain_adapter_requires_core(mesh: CausalMesh, monkeypatch) -> None:
    """Adapter raises ImportError cleanly if langchain-core is missing."""
    import causalmesh.integrations.langchain as lc_module

    # Mock StructuredTool being None (like when langchain-core isn't installed)
    monkeypatch.setattr(lc_module, "StructuredTool", None)

    with pytest.raises(ImportError, match="langchain-core is required"):
        LangChainAdapter(mesh)


def test_langchain_tools_exposed_and_executable(mesh: CausalMesh) -> None:
    """The adapter exposes registered tools which execute through the boundary."""
    pytest.importorskip("langchain_core")

    adapter = LangChainAdapter(mesh, agent_id="test-agent")
    tools = adapter.get_tools()

    assert len(tools) == 1
    lc_tool = tools[0]

    # Langchain mapping
    assert lc_tool.name == "test_tool"
    assert "concatenates a string and an integer" in lc_tool.description

    # Execution should flow through CausalMesh
    result = lc_tool.invoke({"a": 42, "b": "src/hello"})

    # Value should be returned natively
    assert result == "src/hello-42"

    # Verify evidence was recorded by CausalMesh
    events = mesh.audit_events()
    assert len(events) == 1
    assert events[0]["event"]["payload"]["tool"] == "test_tool"


def test_langchain_denial_returns_safe_message(mesh: CausalMesh) -> None:
    """When CausalMesh denies an action, the LangChain tool safely returns a message."""
    pytest.importorskip("langchain_core")

    # Add a tool that the policy won't allow due to ownership
    def forbidden_handler(path: str) -> str:
        raise RuntimeError("Should never be called")

    mesh.register_tool(
        Tool(
            name="forbidden_tool",
            handler=forbidden_handler,
            mutating=True,
        )
    )

    adapter = LangChainAdapter(mesh, agent_id="test-agent")
    tools = {t.name: t for t in adapter.get_tools()}

    lc_tool = tools["forbidden_tool"]

    # Invoke it. The gate should deny it, returning a string message instead of crashing
    result = lc_tool.invoke({"path": "production/secret.txt"})

    assert isinstance(result, str)
    assert "Action denied by policy" in result

    events = mesh.audit_events()
    assert len(events) == 1
    assert events[0]["event"]["event_type"] == "FAILURE"


@pytest.mark.asyncio
async def test_langchain_adapter_supports_async_arun(mesh: CausalMesh) -> None:
    """The adapter supports asynchronous execution via _arun natively."""
    pytest.importorskip("langchain_core")

    adapter = LangChainAdapter(mesh, agent_id="test-agent")
    tools = adapter.get_tools()
    lc_tool = tools[0]

    # LangChain's ainvoke uses the _arun / coroutine handler we attached
    result = await lc_tool.ainvoke({"a": 99, "b": "async/path"})

    assert result == "async/path-99"

    events = mesh.audit_events()
    assert len(events) == 1
    assert events[0]["event"]["payload"]["tool"] == "test_tool"
