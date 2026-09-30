"""The Anthropic adapter's block shapes, on top of the shared gate properties.

``test_adapter_gate.py`` proves a denied call never reaches a handler and an
unknown agent raises; this file pins the Messages API content-block shapes.
No hosted model produced any block here: they are written by hand from the
public documentation, so they show the adapter reads and writes that shape and
say nothing about how Claude actually behaves.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from adapter_support import Session, build_session

from causalmesh.integrations import AnthropicAdapter

pytestmark = pytest.mark.integration


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return build_session(tmp_path)


def _use(name: str, args: Any, block_id: str = "toolu_01") -> dict[str, Any]:
    return {"type": "tool_use", "id": block_id, "name": name, "input": args}


# --- tool definitions --------------------------------------------------------


def test_tool_definitions_have_the_messages_api_shape(session: Session) -> None:
    tools = AnthropicAdapter(session.mesh).get_tools()

    assert [t["name"] for t in tools] == sorted(t["name"] for t in tools)
    by_name = {t["name"]: t for t in tools}
    write = by_name["write_file"]
    assert set(write) == {"name", "description", "input_schema"}
    assert write["description"] == "Write a file"
    assert write["input_schema"]["type"] == "object"
    assert write["input_schema"]["required"] == ["path"]
    assert set(write["input_schema"]["properties"]) == {"path", "content"}
    # Not the OpenAI wrapper.
    assert "function" not in write
    assert "type" not in write


def test_input_schema_follows_the_handler_signature(session: Session) -> None:
    schema = {t["name"]: t for t in AnthropicAdapter(session.mesh).get_tools()}["lookup"][
        "input_schema"
    ]

    assert schema["properties"] == {"key": {"type": "string"}, "limit": {"type": "integer"}}
    assert schema["required"] == ["key"]


def test_definitions_are_json_serialisable(session: Session) -> None:
    json.dumps(AnthropicAdapter(session.mesh).get_tools())


# --- tool_result blocks ------------------------------------------------------


def test_an_allowed_call_returns_a_tool_result_for_the_same_id(session: Session) -> None:
    adapter = AnthropicAdapter(session.mesh, agent_id="test-agent")

    result = adapter.handle_tool_use(_use("write_file", {"path": "allowed/a.txt"}, "toolu_A"))

    assert result == {
        "type": "tool_result",
        "tool_use_id": "toolu_A",
        "content": "written:allowed/a.txt",
        "is_error": False,
    }
    assert session.called == ["allowed/a.txt"]


def test_a_denial_is_an_error_result_and_never_runs(session: Session) -> None:
    adapter = AnthropicAdapter(session.mesh, agent_id="test-agent")

    result = adapter.handle_tool_use(_use("write_file", {"path": "forbidden/x"}, "toolu_D"))

    assert result["tool_use_id"] == "toolu_D"
    assert result["is_error"] is True
    assert result["content"].startswith("Action denied by policy")
    assert session.called == []


def test_a_warning_on_an_unenforced_arm_is_not_an_error(tmp_path: Path) -> None:
    session = build_session(tmp_path, arm="C0")
    adapter = AnthropicAdapter(session.mesh, agent_id="test-agent")

    result = adapter.handle_tool_use(_use("write_file", {"path": "forbidden/x"}))

    assert result["is_error"] is False
    assert "would refuse under strict policy" in result["content"]


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        pytest.param(_use("write_file", ["allowed/x"]), "must be a JSON object", id="list-input"),
        pytest.param(_use("write_file", "allowed/x"), "must be a JSON object", id="string-input"),
        pytest.param(_use("", {}), "no tool name", id="empty-name"),
        pytest.param({"type": "tool_use", "id": "t", "input": {}}, "no tool name", id="no-name"),
        pytest.param(_use(7, {}), "no tool name", id="non-string-name"),
        pytest.param(
            {"type": "text", "id": "t", "text": "hi"}, "Unsupported block type", id="wrong-type"
        ),
        pytest.param(_use("nope", {}), "not registered", id="unknown-tool"),
        pytest.param(_use("write_optional", {}), "Action failed", id="missing-resource"),
    ],
)
def test_a_bad_block_is_an_error_result_and_nothing_runs(
    session: Session, block: dict[str, Any], expected: str
) -> None:
    result = AnthropicAdapter(session.mesh, agent_id="test-agent").handle_tool_use(block)

    assert result["type"] == "tool_result"
    assert result["is_error"] is True
    assert result["content"].startswith("Action failed:")
    assert expected in result["content"]
    assert session.called == []
    assert session.mesh.audit_events() == []


def test_a_missing_input_is_an_empty_object_not_a_crash(session: Session) -> None:
    block = {"type": "tool_use", "id": "t", "name": "write_optional"}

    result = AnthropicAdapter(session.mesh, agent_id="test-agent").handle_tool_use(block)

    assert result["content"].startswith("Action failed:")
    assert session.called == []


def test_a_missing_id_is_an_empty_string_so_the_result_is_still_valid_json(
    session: Session,
) -> None:
    block = {"type": "tool_use", "name": "lookup", "input": {"key": "k"}}

    result = AnthropicAdapter(session.mesh, agent_id="test-agent").handle_tool_use(block)

    assert result["tool_use_id"] == ""
    json.dumps(result)


def test_sdk_block_objects_are_accepted_by_attribute_and_by_model_dump(session: Session) -> None:
    adapter = AnthropicAdapter(session.mesh, agent_id="test-agent")
    by_attribute = SimpleNamespace(type="tool_use", id="toolu_S", name="lookup", input={"key": "a"})

    class Dumpable:
        def model_dump(self) -> dict[str, Any]:
            return _use("lookup", {"key": "b"}, "toolu_M")

    first = adapter.handle_tool_use(by_attribute)
    second = adapter.handle_tool_use(Dumpable())

    assert (first["tool_use_id"], first["content"]) == ("toolu_S", "found:a:3")
    assert (second["tool_use_id"], second["content"]) == ("toolu_M", "found:b:3")


# --- whole messages ----------------------------------------------------------


def test_a_message_gets_one_user_message_with_a_result_per_tool_use_in_order(
    session: Session,
) -> None:
    adapter = AnthropicAdapter(session.mesh, agent_id="test-agent")
    assistant = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Writing two files."},
            _use("write_file", {"path": "allowed/1.txt"}, "toolu_1"),
            {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {}},
            _use("write_file", {"path": "forbidden/2.txt"}, "toolu_2"),
            _use("write_file", {"path": "allowed/3.txt"}, "toolu_3"),
        ],
    }

    reply = adapter.handle_message(assistant)

    assert reply is not None
    assert reply["role"] == "user"
    assert [b["tool_use_id"] for b in reply["content"]] == ["toolu_1", "toolu_2", "toolu_3"]
    assert [b["is_error"] for b in reply["content"]] == [False, True, False]
    assert session.called == ["allowed/1.txt", "allowed/3.txt"]
    assert [e["event"]["event_type"] for e in session.mesh.audit_events()] == [
        "WRITE",
        "FAILURE",
        "WRITE",
    ]


@pytest.mark.parametrize(
    "message",
    [
        pytest.param({"role": "assistant", "content": "All done."}, id="string-content"),
        pytest.param(
            {"role": "assistant", "content": [{"type": "text", "text": "done"}]}, id="text-only"
        ),
        pytest.param({"role": "assistant", "content": []}, id="empty"),
        pytest.param({"role": "assistant"}, id="no-content"),
        pytest.param(SimpleNamespace(content=None), id="none-content"),
    ],
)
def test_a_message_without_tool_use_needs_no_reply(session: Session, message: Any) -> None:
    assert AnthropicAdapter(session.mesh, agent_id="test-agent").handle_message(message) is None
    assert session.mesh.audit_events() == []


def test_a_message_object_and_a_bare_block_list_are_both_accepted(session: Session) -> None:
    adapter = AnthropicAdapter(session.mesh, agent_id="test-agent")
    blocks = [_use("lookup", {"key": "k"}, "toolu_L")]

    from_object = adapter.handle_message(SimpleNamespace(content=blocks))
    from_list = adapter.handle_message(blocks)

    assert from_object == from_list
    assert from_list is not None
    assert from_list["content"][0]["content"] == "found:k:3"


async def test_the_async_message_path_matches_the_sync_one(session: Session) -> None:
    adapter = AnthropicAdapter(session.mesh, agent_id="test-agent")
    assistant = {
        "role": "assistant",
        "content": [
            _use("async_write", {"path": "allowed/a.txt"}, "toolu_a"),
            _use("write_file", {"path": "forbidden/b.txt"}, "toolu_b"),
        ],
    }

    reply = await adapter.ahandle_message(assistant)

    assert reply is not None
    assert reply["content"][0]["content"] == "async-written:allowed/a.txt"
    assert reply["content"][1]["is_error"] is True
    assert session.called == ["allowed/a.txt"]
    assert await adapter.ahandle_message({"content": "text"}) is None


def test_a_scripted_conversation_round_trips_as_valid_messages_api_json(
    session: Session,
) -> None:
    # A two-turn exchange as a client would build it: the assistant turn is
    # echoed back unchanged, followed by the adapter's user turn.
    adapter = AnthropicAdapter(session.mesh, agent_id="test-agent")
    messages: list[dict[str, Any]] = [{"role": "user", "content": "save my note"}]
    assistant = {
        "role": "assistant",
        "content": [_use("write_file", {"path": "allowed/note.txt", "content": "hi"}, "toolu_N")],
    }

    reply = adapter.handle_message(assistant)
    assert reply is not None
    messages += [assistant, reply]

    wire = json.loads(json.dumps(messages))
    assert [m["role"] for m in wire] == ["user", "assistant", "user"]
    tool_use = wire[1]["content"][0]
    tool_result = wire[2]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == tool_use["id"]
    assert session.called == ["allowed/note.txt"]


def test_an_argument_the_handler_cannot_bind_fails_inside_the_gate_and_is_recorded(
    session: Session,
) -> None:
    # Unlike a missing resource, this reaches the boundary: the gate allowed a
    # call the handler then rejected, so the handler never ran and a failure
    # is on the record.
    adapter = AnthropicAdapter(session.mesh, agent_id="test-agent")

    result = adapter.handle_tool_use(_use("write_file", {"path": "allowed/a", "bogus": 1}))

    assert result["is_error"] is True
    assert result["content"].startswith("Action failed:")
    assert "bogus" in result["content"]
    assert session.called == []
    assert session.gate_entries == ["write_file"]
