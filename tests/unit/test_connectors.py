"""Agent discovery and the process connector.

Discovery is tested against **this machine**, not a mock. The whole point
of the module is that a tool on `PATH` may not be a working tool, and a
fake `PATH` would test the fake rather than the discovery.

Nothing here invokes a real agent. Driving one costs money — a single
trivial Claude Code call during development cost $0.32 — so the process
connector is tested against a stub command instead, and the real
invocation is exercised by hand.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from causalmesh.connectors.discovery import (
    AGENT_SPECS,
    INFRA_SPECS,
    Availability,
    Probe,
    ToolSpec,
    available_agents,
    discover,
    probe,
)
from causalmesh.connectors.process import (
    SPECS,
    AgentInvocation,
    ConnectorError,
    ConnectorSpec,
    _read_json,
    invoke,
    spec_for,
)

pytestmark = [pytest.mark.unit]


class TestDiscovery:
    def test_python_is_found_because_it_is_running_this_test(self) -> None:
        """A probe that cannot find the running interpreter is broken."""
        spec = next(s for s in INFRA_SPECS if s.name == "python")
        found = probe(spec)
        assert found.availability is Availability.AVAILABLE
        assert found.version is not None
        assert found.path is not None

    def test_a_missing_tool_is_absent_rather_than_an_error(self) -> None:
        found = probe(ToolSpec("nope", "agent", "definitely-not-a-real-command-xyz"))
        assert found.availability is Availability.ABSENT
        assert found.usable is False
        assert found.path is None

    def test_a_tool_that_does_not_answer_is_degraded_not_absent(self, tmp_path: Path) -> None:
        """Degraded is the outcome that matters.

        Folding it into `absent` hides an installation the operator
        probably wants to fix; folding it into `available` produces a run
        that dies partway through. On the development machine the Copilot
        CLI was exactly this: installed, executable, and refusing to start
        because the Node runtime was too old.
        """
        # A real executable that exits non-zero with no version.
        script = tmp_path / "broken.py"
        script.write_text("import sys; sys.exit(3)", encoding="utf-8")
        spec = ToolSpec("broken", "agent", sys.executable, version_args=(str(script),))
        found = probe(spec)
        assert found.availability is Availability.DEGRADED
        assert found.usable is False
        # It was located, so the operator can go and look at it.
        assert found.path is not None

    def test_discovery_covers_every_known_tool(self) -> None:
        probes = discover()
        assert len(probes) == len(AGENT_SPECS) + len(INFRA_SPECS)
        assert {p.name for p in probes} == {s.name for s in (*AGENT_SPECS, *INFRA_SPECS)}

    def test_available_agents_excludes_degraded_and_absent(self) -> None:
        probes = [
            Probe("a", "agent", Availability.AVAILABLE, version="1.0"),
            Probe("b", "agent", Availability.DEGRADED),
            Probe("c", "agent", Availability.ABSENT),
            Probe("git", "infra", Availability.AVAILABLE, version="2.0"),
        ]
        assert [p.name for p in available_agents(probes)] == ["a"]

    def test_a_probe_serialises(self) -> None:
        found = probe(next(s for s in INFRA_SPECS if s.name == "python"))
        data = found.to_dict()
        assert data["usable"] is True
        assert set(data) == {
            "availability",
            "detail",
            "kind",
            "name",
            "path",
            "usable",
            "version",
        }


class TestReadJson:
    def test_it_finds_the_last_complete_object(self) -> None:
        """Agent CLIs print progress around their structured output."""
        stream = '{"type":"progress"}\n{"type":"result","result":"done"}'
        assert _read_json(stream)["result"] == "done"

    def test_it_tolerates_surrounding_noise(self) -> None:
        stream = 'warning: something\n{"result":"ok"}\n'
        assert _read_json(stream)["result"] == "ok"

    def test_it_returns_none_for_no_json(self) -> None:
        assert _read_json("just some text") is None

    def test_a_bare_object_still_parses(self) -> None:
        assert _read_json('{"result": "x"}')["result"] == "x"


class TestConnectorSpec:
    def test_the_prompt_is_substituted_into_argv(self) -> None:
        spec = SPECS["claude"]
        argv = spec.build("hello world")
        assert "hello world" in argv
        assert "{prompt}" not in " ".join(argv)

    def test_only_exercised_agents_are_listed_as_drivable(self) -> None:
        """An entry in SPECS is a claim this build can drive it.

        Listing an agent whose headless interface was never exercised is
        exactly the "complete because it compiles" the standing commitments
        forbid.
        """
        assert set(SPECS) == {"claude", "codex"}

    def test_an_unknown_agent_is_refused_with_the_list(self) -> None:
        with pytest.raises(ConnectorError, match="claude"):
            spec_for("not-an-agent")


class TestInvoke:
    """Driven against a stub, because a real agent costs money per call."""

    @staticmethod
    def stub(tmp_path: Path, payload: dict) -> ConnectorSpec:
        script = tmp_path / "stub.py"
        script.write_text(
            f"import json; print(json.dumps({payload!r}))", encoding="utf-8"
        )
        return ConnectorSpec(
            argv=(str(script), "{prompt}"),
            command=sys.executable,
            cost_field="total_cost_usd",
            denials_field="permission_denials",
            name="stub",
            reply_field="result",
        )

    def test_a_reply_is_read_from_the_json_field(self, tmp_path: Path) -> None:
        spec = self.stub(tmp_path, {"result": "STUB_OK", "total_cost_usd": 0.01})
        result = asyncio.run(invoke(spec, "hi", workspace=tmp_path, timeout_s=60))
        assert result.ok
        assert result.reply == "STUB_OK"
        assert result.cost_usd == 0.01

    def test_denials_are_counted_from_a_list(self, tmp_path: Path) -> None:
        """Claude Code reports permission_denials as a list of objects."""
        spec = self.stub(
            tmp_path, {"result": "x", "permission_denials": [{"tool": "Write"}]}
        )
        result = asyncio.run(invoke(spec, "hi", workspace=tmp_path, timeout_s=60))
        assert result.permission_denials == 1

    def test_a_missing_workspace_is_refused(self, tmp_path: Path) -> None:
        spec = self.stub(tmp_path, {"result": "x"})
        with pytest.raises(ConnectorError, match="does not exist"):
            asyncio.run(invoke(spec, "hi", workspace=tmp_path / "nope"))

    def test_an_unresolvable_command_is_refused(self, tmp_path: Path) -> None:
        spec = ConnectorSpec(
            argv=("{prompt}",), command="definitely-not-a-real-command-xyz", name="x"
        )
        with pytest.raises(ConnectorError, match="not on PATH"):
            asyncio.run(invoke(spec, "hi", workspace=tmp_path))

    def test_a_hung_agent_is_killed_rather_than_waited_on(self, tmp_path: Path) -> None:
        """A hung agent is a failed turn, not a reason to wait longer."""
        script = tmp_path / "hang.py"
        script.write_text("import time; time.sleep(30)", encoding="utf-8")
        spec = ConnectorSpec(
            argv=(str(script), "{prompt}"), command=sys.executable, name="hang"
        )
        with pytest.raises(ConnectorError, match="did not finish"):
            asyncio.run(invoke(spec, "hi", workspace=tmp_path, timeout_s=2))

    def test_an_invocation_serialises_without_the_raw_payload(self, tmp_path: Path) -> None:
        """`raw` can be tens of kilobytes of provider telemetry."""
        spec = self.stub(tmp_path, {"result": "x", "usage": {"input_tokens": 5}})
        result = asyncio.run(invoke(spec, "hi", workspace=tmp_path, timeout_s=60))
        assert "raw" not in result.to_dict()
        assert result.input_tokens == 5


class TestAgentInvocation:
    def test_an_empty_reply_is_not_ok_even_at_exit_zero(self) -> None:
        """An agent that exits cleanly having said nothing did not work."""
        assert not AgentInvocation("a", "p", "", 0, 1.0).ok
        assert AgentInvocation("a", "p", "said something", 0, 1.0).ok

    def test_a_nonzero_exit_is_not_ok(self) -> None:
        assert not AgentInvocation("a", "p", "output", 1, 1.0).ok
