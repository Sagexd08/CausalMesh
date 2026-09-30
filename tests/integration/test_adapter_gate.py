"""The safety properties every framework adapter must share, stated once.

Each adapter is driven through the same session by a small driver that speaks
that framework's calling convention. What is asserted is the fact a caller
depends on, whichever framework is in front:

- an allowed call runs its handler once, is recorded, and went through the gate;
- a denied call never reaches the handler and is recorded as a refusal;
- a mistake the model can make comes back as an ``Action failed:`` answer and
  runs nothing, while an unknown *agent* raises before the gate or the handler;
- the same holds on the async path.

Adapters whose framework is not installed are skipped with the package named,
never passed silently. The CrewAI driver uses a faithful minimal fake of
``crewai.tools.BaseTool`` unless the real package is present.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from adapter_support import Session, build_session, make_fake_crewai_base

import causalmesh
from causalmesh.integrations import (
    AnthropicAdapter,
    CrewAIAdapter,
    GenericAdapter,
    LangChainAdapter,
    LangGraphAdapter,
    OpenAIAdapter,
)
from causalmesh.sdk.errors import UnknownAgentError

pytestmark = pytest.mark.integration

ALLOWED = "allowed/notes.txt"
FORBIDDEN = "forbidden/secret.txt"


# --- drivers: one per adapter, speaking that framework's convention ---------


class Driver:
    id = ""
    by_name = True  # can the caller name a tool that is not registered?
    model_facing = True  # does it answer a model, so its mistakes must be answers?

    def setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Skip (with a reason) or patch, before the adapter is built."""

    def build(self, session: Session, agent_id: str | None) -> Any:
        raise NotImplementedError

    def call(self, adapter: Any, tool: str, args: dict[str, Any]) -> str:
        raise NotImplementedError

    async def acall(self, adapter: Any, tool: str, args: dict[str, Any]) -> str:
        raise NotImplementedError


class GenericDriver(Driver):
    # The developer's own agent calls this one, not a model: a bad call raises.
    id = "generic"
    model_facing = False

    def build(self, session, agent_id):
        return GenericAdapter(session.mesh, agent_id=agent_id)

    def call(self, adapter, tool, args):
        return adapter.format_result(adapter.call_tool(tool, args))

    async def acall(self, adapter, tool, args):
        return adapter.format_result(await adapter.acall_tool(tool, args))


class OpenAIDriver(Driver):
    id = "openai"

    def build(self, session, agent_id):
        return OpenAIAdapter(session.mesh, agent_id=agent_id)

    @staticmethod
    def _call(tool, args):
        function = {"name": tool, "arguments": json.dumps(args)}
        return {"id": "c1", "type": "function", "function": function}

    def call(self, adapter, tool, args):
        return adapter.handle_tool_call(self._call(tool, args))["content"]

    async def acall(self, adapter, tool, args):
        return (await adapter.ahandle_tool_call(self._call(tool, args)))["content"]


class AnthropicDriver(Driver):
    id = "anthropic"

    def build(self, session, agent_id):
        return AnthropicAdapter(session.mesh, agent_id=agent_id)

    @staticmethod
    def _block(tool, args):
        return {"type": "tool_use", "id": "toolu_1", "name": tool, "input": args}

    def call(self, adapter, tool, args):
        return adapter.handle_tool_use(self._block(tool, args))["content"]

    async def acall(self, adapter, tool, args):
        return (await adapter.ahandle_tool_use(self._block(tool, args)))["content"]


class LangChainDriver(Driver):
    id = "langchain"
    by_name = False
    adapter_class: Any = LangChainAdapter
    package = "langchain_core"

    def setup(self, monkeypatch):
        pytest.importorskip(self.package, reason=f"{self.package} is not installed")

    def build(self, session, agent_id):
        return self.adapter_class(session.mesh, agent_id=agent_id)

    def call(self, adapter, tool, args):
        return {t.name: t for t in adapter.get_tools()}[tool].invoke(args)

    async def acall(self, adapter, tool, args):
        return await {t.name: t for t in adapter.get_tools()}[tool].ainvoke(args)


class LangGraphDriver(LangChainDriver):
    id = "langgraph"
    adapter_class = LangGraphAdapter
    package = "langgraph"


class LangGraphToolNodeDriver(LangGraphDriver):
    """The real ``ToolNode`` in front of the tools, as a graph would run them."""

    id = "langgraph-toolnode"

    @staticmethod
    def _state(tool, args):
        from langchain_core.messages import AIMessage

        call = {"name": tool, "args": args, "id": "call_1", "type": "tool_call"}
        return {"messages": [AIMessage(content="", tool_calls=[call])]}

    @staticmethod
    def _graph(adapter):
        # A ToolNode needs the runtime a graph provides; one node is enough.
        from langgraph.graph import END, START, MessagesState, StateGraph

        graph = StateGraph(MessagesState)
        graph.add_node("tools", adapter.tool_node())
        graph.add_edge(START, "tools")
        graph.add_edge("tools", END)
        return graph.compile()

    def call(self, adapter, tool, args):
        out = self._graph(adapter).invoke(self._state(tool, args))
        return out["messages"][-1].content

    async def acall(self, adapter, tool, args):
        out = await self._graph(adapter).ainvoke(self._state(tool, args))
        return out["messages"][-1].content


class CrewAIDriver(Driver):
    id = "crewai"
    by_name = False

    def setup(self, monkeypatch):
        pytest.importorskip("pydantic", reason="pydantic is not installed")
        if importlib.util.find_spec("crewai") is None:
            import pydantic

            import causalmesh.integrations.crewai as module

            monkeypatch.setattr(module, "BaseTool", make_fake_crewai_base())
            monkeypatch.setattr(module, "BaseModel", pydantic.BaseModel)
            monkeypatch.setattr(module, "ConfigDict", pydantic.ConfigDict)
            monkeypatch.setattr(module, "create_model", pydantic.create_model)

    def build(self, session, agent_id):
        return CrewAIAdapter(session.mesh, agent_id=agent_id)

    def call(self, adapter, tool, args):
        return {t.name: t for t in adapter.get_tools()}[tool].run(**args)

    async def acall(self, adapter, tool, args):
        return await {t.name: t for t in adapter.get_tools()}[tool].arun(**args)


DRIVERS = [
    GenericDriver(),
    OpenAIDriver(),
    AnthropicDriver(),
    LangChainDriver(),
    LangGraphDriver(),
    LangGraphToolNodeDriver(),
    CrewAIDriver(),
]
MODEL_FACING = [d for d in DRIVERS if d.model_facing]
BY_NAME = [d for d in MODEL_FACING if d.by_name]


@pytest.fixture(params=DRIVERS, ids=lambda d: d.id)
def driver(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Driver:
    request.param.setup(monkeypatch)
    return request.param


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return build_session(tmp_path)


def _events(session: Session) -> list[dict[str, Any]]:
    return session.mesh.audit_events()


# --- allowed: runs once, is recorded, went through the gate -----------------


def test_an_allowed_call_runs_once_through_the_gate_and_is_recorded(driver, session) -> None:
    adapter = driver.build(session, "test-agent")

    text = driver.call(adapter, "write_file", {"path": ALLOWED})

    assert text == f"written:{ALLOWED}"
    assert session.called == [ALLOWED]
    assert session.gate_entries == ["write_file"]
    events = _events(session)
    assert [e["event"]["event_type"] for e in events] == ["WRITE"]
    assert events[0]["event"]["payload"]["tool"] == "write_file"


@pytest.mark.parametrize("tool", ["write_file", "async_write"])
async def test_an_allowed_async_call_goes_through_the_gate(driver, session, tool) -> None:
    adapter = driver.build(session, "test-agent")

    text = await driver.acall(adapter, tool, {"path": ALLOWED})

    assert text.endswith(f"written:{ALLOWED}")
    assert session.called == [ALLOWED]
    assert session.gate_entries == [tool]
    assert [e["event"]["event_type"] for e in _events(session)] == ["WRITE"]


def test_a_read_only_tool_is_answered_and_still_recorded_by_the_boundary(driver, session) -> None:
    adapter = driver.build(session, "test-agent")

    text = driver.call(adapter, "lookup", {"key": "k"})

    assert text == "found:k:3"
    assert session.gate_entries == ["lookup"]


# --- denied: never reaches the handler --------------------------------------


def test_a_denied_call_never_reaches_the_handler(driver, session) -> None:
    adapter = driver.build(session, "test-agent")

    text = driver.call(adapter, "write_file", {"path": FORBIDDEN})

    assert text.startswith("Action denied by policy")
    assert session.called == []
    assert session.gate_entries == ["write_file"]
    events = _events(session)
    assert [e["event"]["event_type"] for e in events] == ["FAILURE"]


@pytest.mark.parametrize("tool", ["write_file", "async_write"])
async def test_a_denied_async_call_never_reaches_the_handler(driver, session, tool) -> None:
    # `write_file` is synchronous and takes the async path through a different
    # branch than `async_write`; both must be held.
    adapter = driver.build(session, "test-agent")

    text = await driver.acall(adapter, tool, {"path": FORBIDDEN})

    assert text.startswith("Action denied by policy")
    assert session.called == []
    assert session.gate_entries == [tool]
    assert [e["event"]["event_type"] for e in _events(session)] == ["FAILURE"]


def test_a_denial_is_not_swallowed_into_a_success_on_an_unenforced_arm(
    driver, tmp_path: Path
) -> None:
    # On C0 the same call runs, and the answer says C3 would have refused it.
    session = build_session(tmp_path, arm="C0")
    adapter = driver.build(session, "test-agent")

    text = driver.call(adapter, "write_file", {"path": FORBIDDEN})

    assert "would refuse under strict policy" in text
    assert session.called == [FORBIDDEN]


def test_a_handler_that_raises_is_an_answer_not_an_exception(driver, session) -> None:
    adapter = driver.build(session, "test-agent")

    text = driver.call(adapter, "explode", {"path": ALLOWED})

    assert text.startswith("Action failed:")
    assert "handler exploded" in text
    assert session.called == [ALLOWED]


# --- the model's mistakes are answers, the developer's are errors -----------


@pytest.mark.parametrize("driver", MODEL_FACING, ids=lambda d: d.id, indirect=True)
def test_a_missing_resource_is_an_answer_and_nothing_runs(driver, session) -> None:
    adapter = driver.build(session, "test-agent")

    text = driver.call(adapter, "write_optional", {})

    assert text.startswith("Action failed:")
    assert session.called == []
    assert session.gate_entries == []
    assert _events(session) == []


@pytest.mark.parametrize("driver", MODEL_FACING, ids=lambda d: d.id, indirect=True)
async def test_a_missing_resource_is_an_answer_on_the_async_path(driver, session) -> None:
    adapter = driver.build(session, "test-agent")

    text = await driver.acall(adapter, "write_optional", {})

    assert text.startswith("Action failed:")
    assert session.called == []
    assert _events(session) == []


@pytest.mark.parametrize("driver", BY_NAME, ids=lambda d: d.id, indirect=True)
def test_an_unknown_tool_is_an_answer_and_nothing_runs(driver, session) -> None:
    adapter = driver.build(session, "test-agent")

    text = driver.call(adapter, "nope", {"path": ALLOWED})

    assert text.startswith("Action failed:")
    assert "not registered" in text
    assert session.called == []
    assert session.gate_entries == []
    assert _events(session) == []


@pytest.mark.parametrize("driver", BY_NAME, ids=lambda d: d.id, indirect=True)
async def test_an_unknown_tool_is_an_answer_on_the_async_path(driver, session) -> None:
    adapter = driver.build(session, "test-agent")

    text = await driver.acall(adapter, "nope", {"path": ALLOWED})

    assert text.startswith("Action failed:")
    assert session.called == []
    assert session.gate_entries == []


def test_an_unknown_agent_raises_before_the_gate_or_the_handler(driver, session) -> None:
    # The agent id is configuration, not model output: hiding a misspelled one
    # inside a tool message would leave every call failing with no error.
    adapter = driver.build(session, "imposter")

    with pytest.raises(UnknownAgentError):
        driver.call(adapter, "write_file", {"path": ALLOWED})

    assert session.called == []
    assert session.gate_entries == []
    assert _events(session) == []


@pytest.mark.parametrize("tool", ["write_file", "async_write"])
async def test_an_unknown_agent_raises_before_the_gate_on_the_async_path(
    driver, session, tool
) -> None:
    adapter = driver.build(session, "imposter")

    with pytest.raises(UnknownAgentError):
        await driver.acall(adapter, tool, {"path": ALLOWED})

    assert session.called == []
    assert session.gate_entries == []
    assert _events(session) == []


def test_an_unknown_agent_raises_even_for_a_call_the_gate_would_deny(driver, session) -> None:
    # The forbidden path would be denied for a known agent. For an unknown one
    # the gate must not even be asked: there is no key to record a refusal with.
    adapter = driver.build(session, "imposter")

    with pytest.raises(UnknownAgentError):
        driver.call(adapter, "write_file", {"path": FORBIDDEN})

    assert session.gate_entries == []
    assert _events(session) == []


# --- structure: no adapter module can call a handler itself -----------------


def _integration_modules() -> list[Path]:
    package = Path(causalmesh.__file__).parent / "integrations"
    return sorted(package.glob("*.py"))


@pytest.mark.parametrize("path", _integration_modules(), ids=lambda p: p.name)
def test_no_adapter_module_calls_a_handler_directly(path: Path) -> None:
    # Reading `tool.handler` for its signature is fine. Calling it, or calling
    # a Tool object (`Tool.__call__` invokes the handler), skips the gate.
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            (isinstance(func, ast.Attribute) and func.attr == "handler")
            or (isinstance(func, ast.Call) and getattr(func.func, "attr", "") == "get_tool")
            or (isinstance(func, ast.Name) and func.id in {"tool", "tool_obj"})
        ):
            offenders.append(node.lineno)
    assert offenders == [], f"{path.name} calls a tool handler directly at lines {offenders}"
