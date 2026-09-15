"""Unit tests for the model adapters (spec §8, §12, §43).

The parser is the security-relevant part: it turns untrusted model output
into tool calls. A permissive parser would let a model reach an operation
it did not name, so most of these tests are rejections.
"""

from __future__ import annotations

import json

import pytest

from causalmesh.adapters import (
    AnthropicClient,
    ChatMessage,
    ModelSettings,
    OpenAIClient,
    ProtocolError,
    client_from_environment,
    parse_action,
    system_prompt,
)
from causalmesh.adapters.protocol import PATH_ARGUMENTS, REQUIRED_ARGUMENTS
from causalmesh.tools import TOOL_NAMES

pytestmark = pytest.mark.unit


class TestParserAcceptsValidActions:
    def test_a_bare_json_object(self) -> None:
        action = parse_action('{"tool": "read_file", "arguments": {"path": "a.py"}}')
        assert action.tool == "read_file"
        assert action.arguments == {"path": "a.py"}

    def test_a_fenced_json_object(self) -> None:
        # Models wrap JSON in fences regardless of instructions.
        reply = 'Sure:\n```json\n{"tool": "git_status", "arguments": {}}\n```\n'
        assert parse_action(reply).tool == "git_status"

    def test_json_surrounded_by_prose(self) -> None:
        reply = 'I will read it.\n{"tool": "read_file", "arguments": {"path": "a.py"}}\nDone.'
        assert parse_action(reply).tool == "read_file"

    def test_nested_objects_do_not_truncate_the_match(self) -> None:
        # Brace-balanced scanning, not a naive search for the first "}".
        reply = '{"tool": "write_file", "arguments": {"path": "a.py", "content": "x"}}'
        action = parse_action(reply)
        assert action.arguments["content"] == "x"

    def test_braces_inside_strings_do_not_confuse_the_scanner(self) -> None:
        reply = json.dumps(
            {"tool": "write_file", "arguments": {"path": "a.py", "content": "def f(): return {}"}}
        )
        assert parse_action(reply).arguments["content"] == "def f(): return {}"

    def test_done_without_a_tool_is_valid(self) -> None:
        action = parse_action('{"done": true, "reasoning": "finished"}')
        assert action.done
        assert action.tool == ""

    def test_paths_are_extracted_for_the_gate(self) -> None:
        # The executor needs these separately: the claim gate checks them
        # before the call runs, and events record what a call touched.
        action = parse_action(
            '{"tool": "rename_file", "arguments": {"source": "a.py", "destination": "b.py"}}'
        )
        assert action.paths == ("a.py", "b.py")

    def test_non_path_tools_declare_no_paths(self) -> None:
        assert parse_action('{"tool": "run_tests", "arguments": {}}').paths == ()


class TestParserRejectsInvalidActions:
    """Every rejection carries a kind, so non-compliance is countable."""

    def test_prose_with_no_json(self) -> None:
        with pytest.raises(ProtocolError) as info:
            parse_action("I think I should read the schema file first.")
        assert info.value.kind == "no_json"

    def test_malformed_json(self) -> None:
        with pytest.raises(ProtocolError) as info:
            parse_action('{"tool": "read_file", "arguments":}')
        assert info.value.kind == "malformed_json"

    def test_an_unterminated_object(self) -> None:
        with pytest.raises(ProtocolError) as info:
            parse_action('{"tool": "read_file", "arguments": {"path": "a.py"')
        assert info.value.kind == "malformed_json"

    def test_a_json_array(self) -> None:
        with pytest.raises(ProtocolError) as info:
            parse_action("[1, 2, 3]")
        assert info.value.kind == "no_json"

    def test_a_missing_tool_field(self) -> None:
        with pytest.raises(ProtocolError) as info:
            parse_action('{"arguments": {"path": "a.py"}}')
        assert info.value.kind == "missing_tool"

    def test_an_unknown_tool(self) -> None:
        """The containment property.

        A model naming an operation outside the controlled API must be
        refused here. If the parser passed it through, the executor would
        raise — but the refusal would be an internal error rather than a
        recorded protocol violation attributable to the model.
        """
        with pytest.raises(ProtocolError) as info:
            parse_action('{"tool": "exec_shell", "arguments": {"cmd": "rm -rf /"}}')
        assert info.value.kind == "unknown_tool"

    def test_no_shell_tool_is_reachable(self) -> None:
        for name in ("shell", "exec", "system", "eval", "subprocess", "bash"):
            with pytest.raises(ProtocolError):
                parse_action(json.dumps({"tool": name, "arguments": {}}))

    def test_arguments_that_are_not_an_object(self) -> None:
        with pytest.raises(ProtocolError) as info:
            parse_action('{"tool": "read_file", "arguments": "a.py"}')
        assert info.value.kind == "bad_arguments"

    def test_a_missing_required_argument(self) -> None:
        # Caught here rather than as a TypeError inside the toolbox, which
        # would look like a harness bug rather than model non-compliance.
        with pytest.raises(ProtocolError) as info:
            parse_action('{"tool": "write_file", "arguments": {"path": "a.py"}}')
        assert info.value.kind == "bad_arguments"
        assert "content" in str(info.value)


class TestProtocolTables:
    def test_every_tool_has_a_required_argument_entry(self) -> None:
        # A tool missing from the table would raise KeyError mid-run.
        assert set(REQUIRED_ARGUMENTS) == set(TOOL_NAMES)

    def test_every_tool_has_a_path_argument_entry(self) -> None:
        assert set(PATH_ARGUMENTS) == set(TOOL_NAMES)

    def test_path_arguments_are_a_subset_of_required_or_optional(self) -> None:
        # A path argument the parser looks for but no tool accepts would
        # silently never populate `paths`, so the gate would see nothing.
        for tool, paths in PATH_ARGUMENTS.items():
            for name in paths:
                assert name in REQUIRED_ARGUMENTS[tool] or tool == "list_files"


class TestSystemPrompt:
    def test_it_names_the_agent_and_its_role(self) -> None:
        prompt = system_prompt(
            agent_id="agent_a",
            role_description="Widen the schema",
            owns=["src/schema.py"],
            depends_on=[],
        )
        assert "agent_a" in prompt
        assert "Widen the schema" in prompt
        assert "src/schema.py" in prompt

    def test_it_lists_every_available_tool(self) -> None:
        prompt = system_prompt(agent_id="a", role_description="", owns=[], depends_on=[])
        for name in TOOL_NAMES:
            assert name in prompt

    def test_it_is_identical_across_arms(self) -> None:
        """§3: only the manipulated factors may differ between arms.

        The system prompt takes no arm parameter, so it cannot differ. If
        it could, the C0/C2 contrast would confound information with
        instruction. This test pins the absence of that parameter.
        """
        import inspect

        assert "arm" not in inspect.signature(system_prompt).parameters


class TestClientConstruction:
    def test_openai_refuses_to_run_without_a_key(self, monkeypatch) -> None:
        # Never falls back to an unauthenticated request: a run that
        # silently hit a different endpoint would be attributed to the
        # wrong model (§43).
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            OpenAIClient()

    def test_anthropic_refuses_to_run_without_a_key(self, monkeypatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            AnthropicClient()

    def test_a_local_client_needs_no_key(self) -> None:
        from causalmesh.adapters import LocalClient

        assert LocalClient(base_url="http://localhost:9999/v1").provider == "local"

    def test_an_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown provider"):
            client_from_environment("gpt5-turbo-max")

    def test_local_aliases_all_resolve(self) -> None:
        for alias in ("local", "ollama", "vllm", "lmstudio", "llamacpp"):
            client = client_from_environment(alias, base_url="http://localhost:9999/v1")
            assert client.provider == "local"

    def test_the_anthropic_version_is_pinned(self) -> None:
        # A floating API version means a stored run cannot be replayed
        # against the semantics it ran under.
        from causalmesh.adapters.clients import ANTHROPIC_VERSION

        assert ANTHROPIC_VERSION == "2023-06-01"


class TestSettings:
    def test_defaults_are_the_most_deterministic_available(self) -> None:
        settings = ModelSettings(model="m")
        assert settings.temperature == 0.0
        assert settings.top_p == 1.0

    def test_settings_are_fully_recorded(self) -> None:
        # §43: every parameter that could change the output is a confound
        # and must appear in the run record.
        recorded = ModelSettings(model="m", seed=7).to_dict()
        assert set(recorded) == {"max_tokens", "model", "seed", "temperature", "top_p"}


class TestChatMessage:
    def test_it_serializes_to_the_wire_shape(self) -> None:
        assert ChatMessage(role="user", content="hi").to_dict() == {
            "content": "hi",
            "role": "user",
        }
