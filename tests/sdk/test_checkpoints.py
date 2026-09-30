"""Human checkpoints in the SDK: a handler can now be attached.

Before, the SDK installed no checkpoint handler, so every matched
``policy.checkpoints`` rule was refused by the gate's default and a person had
no way in. ``CausalMesh(checkpoint_handler=...)`` forwards one to the gate.

What the chain records is pinned as it is, not as it might be: a refused
checkpoint is a FAILURE event whose payload names the rule, and an approved
one leaves no record of its own (the call's WRITE event is all there is).
``docs/backlog.md`` ("SDK claims and a human checkpoint handler") lists that as a gap.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.policy import ScriptedHandler, TerminalCheckpointHandler

pytestmark = pytest.mark.unit

NOW = 1_000_000


def _contract(tmp_path: Path, *, arm: str = "C3") -> Path:
    path = tmp_path / "causalmesh.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "agent:",
                "  id: alice",
                "policy:",
                f"  arm: {arm}",
                "  checkpoints:",
                "    - on: path",
                "      require: human",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _mesh(tmp_path: Path, *, arm: str = "C3", **kwargs: Any) -> CausalMesh:
    mesh = CausalMesh.from_config(_contract(tmp_path, arm=arm), **kwargs)
    mesh.register_tool(Tool(name="write_file", handler=lambda path: "ok", resource_args=["path"]))
    return mesh


def _write(mesh: CausalMesh, path: str = "src/a.py") -> Any:
    return mesh.execute(tool="write_file", arguments={"path": path}, now_us=NOW)


def _terminal(answers: str) -> tuple[TerminalCheckpointHandler, io.StringIO]:
    out = io.StringIO()
    handler = TerminalCheckpointHandler(input_stream=io.StringIO(answers), output_stream=out)
    return handler, out


class TestDefaultStillRefuses:
    def test_no_handler_means_a_matched_checkpoint_is_refused(self, tmp_path: Path) -> None:
        result = _write(_mesh(tmp_path))
        assert result.denied
        assert result.rule == "checkpoint"
        assert "no checkpoint handler attached" in result.reason


class TestAHandlerIsForwardedToTheGate:
    def test_a_scripted_approval_lets_the_call_run(self, tmp_path: Path) -> None:
        result = _write(_mesh(tmp_path, checkpoint_handler=ScriptedHandler([True])))
        assert result.executed

    def test_a_scripted_refusal_denies_it(self, tmp_path: Path) -> None:
        result = _write(_mesh(tmp_path, checkpoint_handler=ScriptedHandler([False])))
        assert result.denied and result.rule == "checkpoint"

    def test_the_constructor_accepts_it_as_well_as_from_config(self, tmp_path: Path) -> None:
        from causalmesh.policy import Contract

        contract = Contract.load(_contract(tmp_path))
        mesh = CausalMesh(
            contract=contract, agent_id="alice", checkpoint_handler=ScriptedHandler([True])
        )
        mesh.register_tool(Tool(name="w", handler=lambda path: 1, resource_args=["path"]))
        assert mesh.execute(tool="w", arguments={"path": "x"}, now_us=NOW).executed


class TestTerminalHandlerThroughTheSdk:
    def test_yes_runs_the_handler_and_the_person_was_shown_the_resource(
        self, tmp_path: Path
    ) -> None:
        handler, out = _terminal("yes\n")
        mesh = _mesh(tmp_path, checkpoint_handler=handler)

        result = _write(mesh, "src/secret.py")

        assert result.executed
        assert "src/secret.py" in out.getvalue()
        assert [entry["approved"] for entry in handler.decisions()] == [True]

    def test_no_denies_with_the_reason_a_person_gave(self, tmp_path: Path) -> None:
        handler, _ = _terminal("no\n")
        result = _write(_mesh(tmp_path, checkpoint_handler=handler))
        assert result.denied
        assert result.rule == "checkpoint"
        assert "denied by a person" in result.reason

    def test_end_of_input_denies(self, tmp_path: Path) -> None:
        handler, _ = _terminal("")
        assert _write(_mesh(tmp_path, checkpoint_handler=handler)).denied

    def test_a_handler_is_consulted_once_per_call_not_per_question(self, tmp_path: Path) -> None:
        handler, _ = _terminal("yes\nno\n")
        mesh = _mesh(tmp_path, checkpoint_handler=handler)
        assert _write(mesh, "a.py").executed
        assert _write(mesh, "b.py").denied
        assert len(handler.decisions()) == 2

    def test_a_non_mutating_tool_is_never_put_to_a_person(self, tmp_path: Path) -> None:
        handler, out = _terminal("no\n")
        mesh = _mesh(tmp_path, checkpoint_handler=handler)
        mesh.register_tool(Tool(name="read", handler=lambda path: "x", mutating=False))
        result = mesh.execute(tool="read", arguments={"path": "a.py"}, now_us=NOW)
        assert result.executed
        assert out.getvalue() == ""

    @pytest.mark.adversarial
    def test_an_agent_cannot_repaint_the_question_through_the_sdk(self, tmp_path: Path) -> None:
        handler, out = _terminal("no\n")
        mesh = _mesh(tmp_path, checkpoint_handler=handler)
        _write(mesh, "src/a.py\x1b[2J\x1b[Hresource: README.md")
        shown = out.getvalue()
        assert "\x1b" not in shown
        assert sum(line.startswith("resource: ") for line in shown.splitlines()) == 1


class TestWhatTheChainRecords:
    def test_a_refused_checkpoint_is_a_failure_event_naming_the_rule(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path, checkpoint_handler=ScriptedHandler([False]))
        _write(mesh)
        event = mesh.audit_events()[-1]["event"]
        assert event["event_type"] == "FAILURE"
        assert event["payload"]["rule"] == "checkpoint"

    def test_an_approved_checkpoint_leaves_no_record_of_its_own(self, tmp_path: Path) -> None:
        """Pinned as a known gap, not as a design: see the fragment."""
        mesh = _mesh(tmp_path, checkpoint_handler=ScriptedHandler([True]))
        _write(mesh)
        types = [record["event"]["event_type"] for record in mesh.audit_events()]
        assert types == ["WRITE"]

    def test_the_reason_recorded_is_free_of_clock_and_host(self, tmp_path: Path) -> None:
        """Two sessions given the same answers sign the same payloads."""

        def payload() -> dict[str, Any]:
            handler, _ = _terminal("no\n")
            mesh = _mesh(tmp_path, checkpoint_handler=handler, seed=b"s" * 32)
            _write(mesh)
            return dict(mesh.audit_events()[-1]["event"]["payload"])

        assert payload() == payload()


class TestAnUnenforcedArm:
    def test_the_person_is_still_asked_and_a_no_is_reported_not_enforced(
        self, tmp_path: Path
    ) -> None:
        """The gate consults checkpoints on every arm. Said here so it is not a surprise."""
        handler, out = _terminal("no\n")
        mesh = _mesh(tmp_path, arm="C2", checkpoint_handler=handler)

        result = _write(mesh)

        assert result.executed
        assert result.would_refuse
        assert result.shadow_rule == "checkpoint"
        assert "src/a.py" in out.getvalue()


class TestTheYamlKeyOn:
    def test_an_unquoted_on_loads_as_the_on_key(self, tmp_path: Path) -> None:
        """YAML 1.1 reads a bare `on` as True; the file an operator writes must still load."""
        mesh = _mesh(tmp_path)
        assert mesh.contract.checkpoints[0].on == "path"

    def test_an_unknown_non_string_key_is_reported_not_a_traceback(self, tmp_path: Path) -> None:
        from causalmesh.policy import Contract, ContractError

        with pytest.raises(ContractError, match="unknown key"):
            Contract.from_dict({"version": 1, "policy": {"checkpoints": [{"on": "path", 5: "x"}]}})
