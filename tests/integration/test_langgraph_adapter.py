"""The LangGraph adapter: real ``ToolNode`` and prebuilt agent, scripted model.

Needs ``langgraph`` (and ``langchain-core``). Where it is not installed the
tests that need it are skipped with the package named, and the ones that need
nothing (the import guard) still run. No hosted model is involved: the agent
is driven by a scripted fake chat model, so these tests show the tools work
inside LangGraph, and say nothing about how a real model would use them.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from adapter_support import Session, build_session

import causalmesh
from causalmesh.integrations import LangChainAdapter, LangGraphAdapter
from causalmesh.sdk.errors import UnknownAgentError

pytestmark = pytest.mark.integration

needs_langgraph = pytest.mark.skipif(
    importlib.util.find_spec("langgraph") is None
    or importlib.util.find_spec("langchain_core") is None,
    reason="langgraph and langchain-core are not installed: tests against the real package skipped",
)


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return build_session(tmp_path)


# --- no package needed --------------------------------------------------------


def test_the_adapter_requires_langgraph(session: Session, monkeypatch) -> None:
    import causalmesh.integrations.langgraph as module

    monkeypatch.setattr(module, "ToolNode", None)

    with pytest.raises(ImportError, match="langgraph is required"):
        LangGraphAdapter(session.mesh)


def test_importing_the_integrations_package_works_without_any_framework() -> None:
    # `sys.modules[name] = None` makes `import name` raise ImportError, which is
    # what a machine without the package does, without uninstalling anything.
    src = Path(causalmesh.__file__).resolve().parents[1]
    code = (
        "import sys\n"
        "for name in ('langchain_core', 'langgraph', 'crewai', 'pydantic', 'openai', 'anthropic'):\n"
        "    sys.modules[name] = None\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import causalmesh.integrations as i\n"
        "print(sorted(i.__all__))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code, str(src)], capture_output=True, text=True, timeout=120
    )

    assert done.returncode == 0, done.stderr
    for name in ("AnthropicAdapter", "CrewAIAdapter", "LangChainAdapter", "LangGraphAdapter"):
        assert name in done.stdout


def test_constructing_without_the_framework_names_the_package_to_install() -> None:
    src = Path(causalmesh.__file__).resolve().parents[1]
    code = (
        "import sys\n"
        "for name in ('langchain_core', 'langgraph', 'crewai', 'pydantic'):\n"
        "    sys.modules[name] = None\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from causalmesh.integrations import LangChainAdapter, LangGraphAdapter, CrewAIAdapter\n"
        "for cls, needle in ((LangChainAdapter, 'langchain-core'), (LangGraphAdapter, 'langgraph'),"
        " (CrewAIAdapter, 'crewai')):\n"
        "    try:\n"
        "        cls(None)\n"
        "    except ImportError as exc:\n"
        "        assert needle in str(exc), str(exc)\n"
        "    else:\n"
        "        raise SystemExit(cls.__name__ + ' did not raise')\n"
        "print('ok')\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code, str(src)], capture_output=True, text=True, timeout=120
    )

    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout


# --- the real package ---------------------------------------------------------


@needs_langgraph
def test_it_reuses_the_langchain_tool_machinery(session: Session) -> None:
    adapter = LangGraphAdapter(session.mesh, agent_id="test-agent")

    assert isinstance(adapter, LangChainAdapter)
    tools = {t.name: t for t in adapter.get_tools()}
    assert set(tools) == set(session.mesh.registered_tools())
    assert tools["write_file"].description == "Write a file"
    assert set(tools["write_file"].args) == {"path", "content"}


@needs_langgraph
def test_tool_node_is_a_real_langgraph_tool_node(session: Session) -> None:
    from langgraph.prebuilt import ToolNode

    node = LangGraphAdapter(session.mesh, agent_id="test-agent").tool_node(name="cm_tools")

    assert isinstance(node, ToolNode)
    assert set(node.tools_by_name) == set(session.mesh.registered_tools())


@needs_langgraph
def test_tool_node_agent_id_overrides_the_default(session: Session) -> None:
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    adapter = LangGraphAdapter(session.mesh, agent_id="test-agent")
    graph = StateGraph(MessagesState)
    graph.add_node("tools", adapter.tool_node(agent_id="admin-agent"))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    call = {
        "name": "write_file",
        "args": {"path": "forbidden/ok.txt"},
        "id": "c",
        "type": "tool_call",
    }

    out = graph.compile().invoke({"messages": [AIMessage(content="", tool_calls=[call])]})

    # admin-agent owns forbidden/, so the same path that test-agent is refused runs.
    assert out["messages"][-1].content == "written:forbidden/ok.txt"


@needs_langgraph
def test_tool_node_reports_arguments_the_schema_rejects_as_a_message_and_runs_nothing(
    session: Session,
) -> None:
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    adapter = LangGraphAdapter(session.mesh, agent_id="test-agent")
    graph = StateGraph(MessagesState)
    graph.add_node("tools", adapter.tool_node())
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    call = {"name": "write_file", "args": {}, "id": "c", "type": "tool_call"}

    out = graph.compile().invoke({"messages": [AIMessage(content="", tool_calls=[call])]})

    assert out["messages"][-1].status == "error"
    assert session.called == []
    assert session.mesh.audit_events() == []


# --- a prebuilt agent, driven by a scripted model -----------------------------


def _agent(model: Any, tools: list[Any]) -> Any:
    try:
        from langchain.agents import create_agent

        return create_agent(model, tools)
    except ImportError:
        from langgraph.prebuilt import create_react_agent

        return create_react_agent(model, tools)


def _scripted_model(*tool_calls: dict[str, Any]) -> Any:
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    class ScriptedModel(GenericFakeChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    turns = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": c["name"], "args": c["args"], "id": f"call_{i}", "type": "tool_call"}
                for i, c in enumerate(tool_calls)
            ],
        ),
        AIMessage(content="finished"),
    ]
    return ScriptedModel(messages=iter(turns))


@needs_langgraph
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_a_prebuilt_agent_runs_an_allowed_and_a_denied_call_through_the_gate(
    session: Session,
) -> None:
    adapter = LangGraphAdapter(session.mesh, agent_id="test-agent")
    model = _scripted_model(
        {"name": "write_file", "args": {"path": "allowed/a.txt"}},
        {"name": "write_file", "args": {"path": "forbidden/b.txt"}},
    )

    out = _agent(model, adapter.get_tools()).invoke({"messages": [("user", "go")]})

    tool_messages = [m for m in out["messages"] if m.type == "tool"]
    assert [m.content.split(":")[0] for m in tool_messages] == [
        "written",
        "Action denied by policy",
    ]
    assert out["messages"][-1].content == "finished"
    assert session.called == ["allowed/a.txt"]
    assert [e["event"]["event_type"] for e in session.mesh.audit_events()] == ["WRITE", "FAILURE"]


@needs_langgraph
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
async def test_a_prebuilt_agent_on_the_async_path_is_gated_too(session: Session) -> None:
    adapter = LangGraphAdapter(session.mesh, agent_id="test-agent")
    model = _scripted_model(
        {"name": "async_write", "args": {"path": "allowed/a.txt"}},
        {"name": "async_write", "args": {"path": "forbidden/b.txt"}},
    )

    out = await _agent(model, adapter.get_tools()).ainvoke({"messages": [("user", "go")]})

    tool_messages = [m for m in out["messages"] if m.type == "tool"]
    assert tool_messages[0].content == "async-written:allowed/a.txt"
    assert tool_messages[1].content.startswith("Action denied by policy")
    assert session.called == ["allowed/a.txt"]


@needs_langgraph
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_an_unknown_agent_stops_a_prebuilt_agent_before_anything_runs(session: Session) -> None:
    adapter = LangGraphAdapter(session.mesh, agent_id="imposter")
    model = _scripted_model({"name": "write_file", "args": {"path": "allowed/a.txt"}})

    with pytest.raises(UnknownAgentError):
        _agent(model, adapter.get_tools()).invoke({"messages": [("user", "go")]})

    assert session.called == []
    assert session.gate_entries == []
    assert session.mesh.audit_events() == []
