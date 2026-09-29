import json
from pathlib import Path

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.integrations.openai import OpenAIAdapter
from causalmesh.policy.contract import Contract
from causalmesh.sdk.errors import UnknownAgentError

MINIMAL_CONTRACT_YAML = """
version: 1
roles:
  - agent_id: test-agent
    archetype: writer
    owns:
      - allowed/
  - agent_id: admin-agent
    archetype: admin
    owns:
      - forbidden/
policy:
  arm: C3
  contested:
    forbidden/: exclusive
evidence:
  sign: true
  verify_on_exit: false
"""


@pytest.fixture
def mesh(tmp_path: Path) -> CausalMesh:
    p = tmp_path / "causalmesh.yaml"
    p.write_text(MINIMAL_CONTRACT_YAML)
    contract = Contract.find(tmp_path)

    m = CausalMesh(
        agent_id="test-agent",
        contract=contract,
        seed=b"test-seed-00000000000000000000000",
    )
    called = []

    def write_handler(path: str, content: str = "") -> str:
        called.append(path)
        return f"written:{path}"

    async def async_write_handler(path: str, content: str = "") -> str:
        called.append(path)
        return f"async-written:{path}"

    m.register_tool(
        Tool(
            name="write_file",
            handler=write_handler,
            kind="filesystem",
            mutating=True,
            description="Write a file",
            resource_args=["path"],
        )
    )
    m.register_tool(
        Tool(
            name="async_write",
            handler=async_write_handler,
            kind="filesystem",
            mutating=True,
            description="Async write",
            resource_args=["path"],
        )
    )
    m._called = called
    return m


def test_openai_adapter_get_tools(mesh: CausalMesh) -> None:
    adapter = OpenAIAdapter(mesh)
    tools = adapter.get_tools()

    assert len(tools) == 2
    tool_1 = tools[1]
    assert tool_1["type"] == "function"
    assert tool_1["function"]["name"] == "write_file"
    assert tool_1["function"]["description"] == "Write a file"
    assert "properties" in tool_1["function"]["parameters"]
    assert "path" in tool_1["function"]["parameters"]["properties"]


def test_openai_adapter_handle_tool_call_allowed(mesh: CausalMesh) -> None:
    adapter = OpenAIAdapter(mesh)
    tool_call = {
        "id": "call_123",
        "type": "function",
        "function": {
            "name": "write_file",
            "arguments": json.dumps({"path": "allowed/file.txt", "content": "hello"}),
        },
    }

    result = adapter.handle_tool_call(tool_call)

    assert result["role"] == "tool"
    assert result["tool_call_id"] == "call_123"
    assert result["content"] == "written:allowed/file.txt"
    assert "allowed/file.txt" in mesh._called

    events = mesh.audit_events()
    assert len(events) == 1
    assert events[0]["event"]["event_type"] == "WRITE"
    assert events[0]["event"]["payload"]["tool"] == "write_file"


def test_openai_adapter_handle_tool_call_denied(mesh: CausalMesh) -> None:
    adapter = OpenAIAdapter(mesh)
    tool_call = {
        "id": "call_456",
        "type": "function",
        "function": {
            "name": "write_file",
            "arguments": json.dumps({"path": "forbidden/secret.txt"}),
        },
    }

    result = adapter.handle_tool_call(tool_call)

    assert result["role"] == "tool"
    assert result["tool_call_id"] == "call_456"
    assert "Action denied by policy" in result["content"]
    assert len(mesh._called) == 0

    events = mesh.audit_events()
    assert len(events) == 1
    assert events[0]["event"]["event_type"] == "FAILURE"


def test_openai_adapter_handle_tool_call_malformed_json(mesh: CausalMesh) -> None:
    adapter = OpenAIAdapter(mesh)
    tool_call = {
        "id": "call_bad",
        "type": "function",
        "function": {
            "name": "write_file",
            "arguments": "{bad json",
        },
    }

    result = adapter.handle_tool_call(tool_call)

    assert result["role"] == "tool"
    assert result["tool_call_id"] == "call_bad"
    assert "Malformed JSON arguments" in result["content"]
    assert len(mesh._called) == 0

    events = mesh.audit_events()
    assert len(events) == 0


def test_openai_adapter_handle_tool_call_unsupported_type(mesh: CausalMesh) -> None:
    adapter = OpenAIAdapter(mesh)
    tool_call = {
        "id": "call_unsupported",
        "type": "not_a_function",
    }

    result = adapter.handle_tool_call(tool_call)

    assert result["role"] == "tool"
    assert result["tool_call_id"] == "call_unsupported"
    assert "Unsupported tool_call type" in result["content"]


@pytest.mark.asyncio
async def test_openai_adapter_ahandle_tool_call(mesh: CausalMesh) -> None:
    adapter = OpenAIAdapter(mesh)
    tool_call = {
        "id": "call_async",
        "type": "function",
        "function": {
            "name": "async_write",
            "arguments": json.dumps({"path": "allowed/async.txt"}),
        },
    }

    result = await adapter.ahandle_tool_call(tool_call)

    assert result["role"] == "tool"
    assert result["tool_call_id"] == "call_async"
    assert result["content"] == "async-written:allowed/async.txt"

    events = mesh.audit_events()
    assert len(events) == 1
    assert events[0]["event"]["payload"]["tool"] == "async_write"


def test_openai_adapter_handle_tool_calls_multiple(mesh: CausalMesh) -> None:
    adapter = OpenAIAdapter(mesh)
    calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": "allowed/1.txt"}),
            },
        },
        {
            "id": "call_2",
            "type": "function",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": "allowed/2.txt"}),
            },
        },
    ]

    results = adapter.handle_tool_calls(calls)

    assert len(results) == 2
    assert results[0]["tool_call_id"] == "call_1"
    assert results[0]["content"] == "written:allowed/1.txt"
    assert results[1]["tool_call_id"] == "call_2"
    assert results[1]["content"] == "written:allowed/2.txt"

    assert len(mesh._called) == 2
    events = mesh.audit_events()
    assert len(events) == 2


@pytest.mark.asyncio
async def test_openai_adapter_ahandle_tool_calls_multiple(mesh: CausalMesh) -> None:
    adapter = OpenAIAdapter(mesh)
    calls = [
        {
            "id": "c1",
            "type": "function",
            "function": {
                "name": "async_write",
                "arguments": json.dumps({"path": "allowed/c1.txt"}),
            },
        },
        {
            "id": "c2",
            "type": "function",
            "function": {
                "name": "write_file",  # Sync handler used in async context
                "arguments": json.dumps({"path": "forbidden/c2.txt"}),
            },
        },
    ]

    results = await adapter.ahandle_tool_calls(calls)

    assert len(results) == 2
    assert results[0]["tool_call_id"] == "c1"
    assert "async-written" in results[0]["content"]

    assert results[1]["tool_call_id"] == "c2"
    assert "Action denied by policy" in results[1]["content"]

    assert len(mesh._called) == 1  # Only the allowed one ran
    events = mesh.audit_events()
    assert len(events) == 2
    assert events[0]["event"]["event_type"] == "WRITE"
    assert events[1]["event"]["event_type"] == "FAILURE"


# --- what the model can get wrong is an answer, not an exception ------------

_ERRORS = [
    pytest.param("nope", "{}", "not registered", id="unknown-tool"),
    pytest.param("write_file", "{}", "argument 'path' was not provided", id="missing-resource"),
    pytest.param("write_file", "[1]", "must be a JSON object", id="args-are-a-list"),
    pytest.param("write_file", "null", "must be a JSON object", id="args-are-null"),
    pytest.param("write_file", '"text"', "must be a JSON object", id="args-are-a-string"),
]


def _call(name: str, arguments: str) -> dict:
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": arguments}}


@pytest.mark.parametrize(("name", "arguments", "expected"), _ERRORS)
def test_a_bad_model_call_becomes_a_tool_message_and_nothing_runs(
    mesh: CausalMesh, name: str, arguments: str, expected: str
) -> None:
    # Unknown tool, missing resource and non-object arguments used to raise
    # out of the caller's loop, though malformed JSON was already translated.
    message = OpenAIAdapter(mesh).handle_tool_call(_call(name, arguments))

    assert message["role"] == "tool"
    assert message["tool_call_id"] == "c1"
    assert message["content"].startswith("Action failed:")
    assert expected in message["content"]
    assert mesh._called == []
    assert mesh.audit_events() == []


@pytest.mark.parametrize(("name", "arguments", "expected"), _ERRORS)
async def test_a_bad_model_call_becomes_a_tool_message_on_the_async_path(
    mesh: CausalMesh, name: str, arguments: str, expected: str
) -> None:
    message = await OpenAIAdapter(mesh).ahandle_tool_call(_call(name, arguments))

    assert message["content"].startswith("Action failed:")
    assert expected in message["content"]
    assert mesh._called == []
    assert mesh.audit_events() == []


def test_an_unknown_agent_still_raises_because_the_developer_chose_it(mesh: CausalMesh) -> None:
    # The agent id is configuration, not model output: hiding a misspelled one
    # inside a tool message would leave every call failing with no error.
    call = _call("write_file", json.dumps({"path": "allowed/x.txt"}))
    with pytest.raises(UnknownAgentError):
        OpenAIAdapter(mesh).handle_tool_call(call, agent_id="imposter")
    assert mesh._called == []


async def test_an_unknown_agent_is_refused_on_the_async_path_and_nothing_runs(
    mesh: CausalMesh,
) -> None:
    # Both tools, because `write_file` is synchronous and takes the async path
    # through a different branch than `async_write`.
    for tool in ("write_file", "async_write"):
        call = _call(tool, json.dumps({"path": "unowned/x.txt"}))
        with pytest.raises(UnknownAgentError):
            await OpenAIAdapter(mesh).ahandle_tool_call(call, agent_id="imposter")
    assert mesh._called == []
    assert mesh.audit_events() == []
