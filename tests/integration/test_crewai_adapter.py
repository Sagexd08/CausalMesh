"""The CrewAI adapter, against a fake ``BaseTool`` and, where present, the real one.

``crewai`` is heavy and is deliberately not installed on the machine these were
written on, so the ``BaseTool`` contract the adapter targets was written from
crewai's public interface and is checked here only against a minimal fake that
has those members (``adapter_support.make_fake_crewai_base``). The tests marked
``needs_crewai`` run against the real package and are skipped, with a reason,
when it is missing: they have never been run.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from adapter_support import Session, build_session, make_fake_crewai_base

from causalmesh import Tool
from causalmesh.integrations import CrewAIAdapter

pytestmark = pytest.mark.integration

needs_crewai = pytest.mark.skipif(
    importlib.util.find_spec("crewai") is None,
    reason="crewai is not installed (heavy, not installed on purpose): real-package tests skipped",
)


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return build_session(tmp_path)


@pytest.fixture
def fake_crewai(monkeypatch: pytest.MonkeyPatch) -> type:
    """Point the adapter at the fake ``BaseTool`` (and real pydantic)."""
    pydantic = pytest.importorskip("pydantic", reason="pydantic is not installed")
    import causalmesh.integrations.crewai as module

    base = make_fake_crewai_base()
    monkeypatch.setattr(module, "BaseTool", base)
    monkeypatch.setattr(module, "BaseModel", pydantic.BaseModel)
    monkeypatch.setattr(module, "ConfigDict", pydantic.ConfigDict)
    monkeypatch.setattr(module, "create_model", pydantic.create_model)
    return base


def _tools(session: Session, **kwargs):
    return {t.name: t for t in CrewAIAdapter(session.mesh, **kwargs).get_tools()}


# --- import guard --------------------------------------------------------------


def test_the_adapter_requires_crewai(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import causalmesh.integrations.crewai as module

    monkeypatch.setattr(module, "BaseTool", None)

    with pytest.raises(ImportError, match="crewai is required"):
        CrewAIAdapter(session.mesh)


# --- the tool objects ------------------------------------------------------------


def test_tools_are_base_tool_instances_with_name_description_and_schema(
    fake_crewai: type, session: Session
) -> None:
    tools = _tools(session, agent_id="test-agent")

    assert set(tools) == set(session.mesh.registered_tools())
    write = tools["write_file"]
    assert isinstance(write, fake_crewai)
    assert write.description == "Write a file"
    schema = write.args_schema.model_json_schema()
    assert set(schema["properties"]) == {"path", "content"}
    assert schema["required"] == ["path"]
    assert schema["properties"]["path"]["type"] == "string"
    lookup = tools["lookup"].args_schema.model_json_schema()
    assert lookup["properties"]["limit"]["type"] == "integer"
    assert lookup["required"] == ["key"]


def test_a_tool_without_a_description_gets_a_default_one(
    fake_crewai: type, session: Session
) -> None:
    session.mesh.register_tool(
        Tool(name="bare", handler=lambda path: path, resource_args=["path"], mutating=True)
    )

    assert _tools(session)["bare"].description == "Executes the bare action."


def test_get_tools_agent_id_overrides_the_default(fake_crewai: type, session: Session) -> None:
    adapter = CrewAIAdapter(session.mesh, agent_id="test-agent")
    tools = {t.name: t for t in adapter.get_tools(agent_id="admin-agent")}

    # admin-agent owns forbidden/, so the path test-agent is refused runs.
    assert tools["write_file"].run(path="forbidden/ok.txt") == "written:forbidden/ok.txt"
    assert session.mesh.audit_events()[0]["event"]["identity"]["agent_id"] == "admin-agent"


# --- calling conventions ---------------------------------------------------------


def test_defaults_are_applied_before_the_gate_sees_the_call(
    fake_crewai: type, session: Session
) -> None:
    tools = _tools(session, agent_id="test-agent")

    assert tools["lookup"].run(key="k") == "found:k:3"


def test_positional_arguments_map_onto_the_handler_signature(
    fake_crewai: type, session: Session
) -> None:
    tools = _tools(session, agent_id="test-agent")

    assert tools["write_file"].run("allowed/p.txt") == "written:allowed/p.txt"
    assert tools["write_file"].run("forbidden/p.txt").startswith("Action denied by policy")
    assert session.called == ["allowed/p.txt"]


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({}, id="missing-required"),
        pytest.param({"path": "allowed/x", "surprise": 1}, id="unexpected-argument"),
    ],
)
def test_a_call_the_signature_rejects_is_an_answer_and_nothing_runs(
    fake_crewai: type, session: Session, kwargs: dict
) -> None:
    text = _tools(session, agent_id="test-agent")["write_file"].run(**kwargs)

    assert text.startswith("Action failed: Invalid arguments")
    assert session.called == []
    assert session.gate_entries == []
    assert session.mesh.audit_events() == []


async def test_the_async_call_rejects_a_bad_signature_the_same_way(
    fake_crewai: type, session: Session
) -> None:
    text = await _tools(session, agent_id="test-agent")["write_file"].arun(surprise=1)

    assert text.startswith("Action failed: Invalid arguments")
    assert session.called == []


def test_var_keyword_handlers_are_flattened_and_out_of_the_schema(
    fake_crewai: type, session: Session
) -> None:
    seen: list[dict] = []

    def with_extras(path: str, **extra: str) -> str:
        seen.append(extra)
        return f"extras:{sorted(extra)}"

    session.mesh.register_tool(
        Tool(name="extras", handler=with_extras, resource_args=["path"], mutating=True)
    )
    tool = _tools(session, agent_id="test-agent")["extras"]

    assert set(tool.args_schema.model_json_schema()["properties"]) == {"path"}
    assert tool.run(path="allowed/x", tag="t") == "extras:['tag']"
    assert seen == [{"tag": "t"}]


# --- the real package (never run on the author's machine) ---------------------------


@needs_crewai
def test_real_tools_are_crewai_base_tools_and_run_through_the_gate(session: Session) -> None:
    from crewai.tools import BaseTool

    tools = _tools(session, agent_id="test-agent")

    assert all(isinstance(t, BaseTool) for t in tools.values())
    assert tools["write_file"].run(path="allowed/r.txt") == "written:allowed/r.txt"
    assert tools["write_file"].run(path="forbidden/r.txt").startswith("Action denied by policy")
    assert session.called == ["allowed/r.txt"]


@needs_crewai
async def test_real_tools_are_gated_on_the_async_path(session: Session) -> None:
    tools = _tools(session, agent_id="test-agent")

    text = await tools["async_write"].arun(path="forbidden/r.txt")

    assert text.startswith("Action denied by policy")
    assert session.called == []
