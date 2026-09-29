"""Evidence guarantees of the SDK.

Every call that runs must either reach the signed chain or say that it did
not, and the chain must describe the call accurately. Each class below pins
one defect found in the first Phase 1 SDK drop:

- a second agent's calls ran but were silently not recorded
- read-only tools were recorded as WRITE events
- a tool registered without ``mutating=`` skipped the gate
- unenforced arms gave no sign that C3 would have refused a call
- keys came from a public, hard-coded seed
- a random run id made the signed chain irreproducible
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.sdk.errors import ConfigurationError, UnknownAgentError

pytestmark = pytest.mark.unit

NOW = 1_000_000


def _contract(tmp_path: Path, *, arm: str = "C3", extra: list[str] | None = None) -> Path:
    p = tmp_path / "causalmesh.yaml"
    lines = [
        "version: 1",
        "agent:",
        "  id: coding-agent",
        "roles:",
        "  - agent_id: coding-agent",
        "    archetype: writer",
        "    owns:",
        '      - "src/"',
        "  - agent_id: dba-agent",
        "    archetype: writer",
        "    owns:",
        '      - "production/"',
        "policy:",
        f"  arm: {arm}",
        *(extra or []),
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _mesh(tmp_path: Path, **kwargs: Any) -> CausalMesh:
    arm = kwargs.pop("arm", "C3")
    mesh = CausalMesh.from_config(_contract(tmp_path, arm=arm), **kwargs)
    mesh.register_tool(Tool(name="write_file", handler=lambda path, content="": "ok"))
    mesh.register_tool(Tool(name="read_file", handler=lambda path: "data", mutating=False))
    return mesh


def _event(mesh: CausalMesh, index: int = -1) -> dict[str, Any]:
    event: dict[str, Any] = mesh.audit_events()[index]["event"]
    return event


class TestEveryDeclaredAgentIsRecorded:
    def test_a_role_other_than_the_default_agent_is_recorded(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        result = mesh.execute(
            agent_id="dba-agent", tool="write_file", arguments={"path": "production/x.sql"}
        )
        assert result.executed
        assert result.recorded
        assert _event(mesh)["identity"]["agent_id"] == "dba-agent"

    def test_agents_passed_explicitly_are_recorded(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path, agents=["reviewer"])
        result = mesh.execute(agent_id="reviewer", tool="read_file", arguments={"path": "a"})
        assert result.recorded
        assert "reviewer" in mesh.agents

    def test_an_undeclared_agent_is_refused_before_the_handler_runs(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_contract(tmp_path))
        calls: list[str] = []
        mesh.register_tool(Tool(name="write_file", handler=lambda path: calls.append(path)))
        with pytest.raises(UnknownAgentError, match="stranger"):
            mesh.execute(agent_id="stranger", tool="write_file", arguments={"path": "src/a.py"})
        assert calls == []
        assert mesh.audit_events() == []

    @pytest.mark.parametrize("async_handler", [True, False])
    async def test_the_async_path_refuses_an_undeclared_agent_too(
        self, tmp_path: Path, async_handler: bool
    ) -> None:
        """`execute_async` once skipped the check `execute` makes.

        The handler ran for an agent with no key, unrecorded, and the result
        said only `recorded is False`. The path is one nobody owns, so the
        gate has nothing to refuse it on: the key check is the only thing
        standing between the stranger and the handler.
        """
        mesh = CausalMesh.from_config(_contract(tmp_path))
        calls: list[str] = []

        async def async_handler_fn(path: str) -> None:
            calls.append(path)

        def sync_handler_fn(path: str) -> None:
            calls.append(path)

        mesh.register_tool(
            Tool(
                name="write_file",
                handler=async_handler_fn if async_handler else sync_handler_fn,
                resource_args=["path"],
            )
        )
        with pytest.raises(UnknownAgentError, match="stranger"):
            await mesh.execute_async(
                agent_id="stranger", tool="write_file", arguments={"path": "unowned/a.py"}
            )
        assert calls == []
        assert mesh.audit_events() == []


class TestAMissingRecordIsReported:
    def test_a_relay_failure_leaves_the_outcome_and_reports_the_gap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mesh = _mesh(tmp_path)

        def broken_ingest(**_: Any) -> Any:
            raise OSError("disk full")

        monkeypatch.setattr(mesh._relay, "ingest", broken_ingest)
        result = mesh.execute(tool="write_file", arguments={"path": "src/a.py"})
        assert result.executed
        assert result.recorded is False
        assert result.event_id is None
        assert result.audit_error is not None
        assert "disk full" in result.audit_error


class TestEventTypeFollowsTheToolDeclaration:
    def test_a_read_only_tool_with_a_path_is_recorded_as_read(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        mesh.execute(tool="read_file", arguments={"path": "src/a.py"})
        assert _event(mesh)["event_type"] == "READ"

    def test_a_mutating_tool_is_recorded_as_write(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        mesh.execute(tool="write_file", arguments={"path": "src/a.py"})
        assert _event(mesh)["event_type"] == "WRITE"


class TestToolsAreGatedByDefault:
    def test_a_tool_registered_without_mutating_is_gated(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_contract(tmp_path))
        calls: list[str] = []
        mesh.register_tool(Tool(name="exec_sql", handler=lambda path: calls.append(path)))
        result = mesh.execute(tool="exec_sql", arguments={"path": "production/db.sql"})
        assert result.denied
        assert calls == []


class TestUnenforcedArmsReportTheShadowRefusal:
    def test_c2_allows_the_call_and_says_c3_would_refuse_it(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path, arm="C2")
        assert mesh.enforcing is False
        result = mesh.execute(tool="write_file", arguments={"path": "production/db.sql"})
        assert result.executed
        assert result.would_refuse
        assert result.shadow_rule
        assert "C3 would refuse" in result.describe()

    def test_the_shadow_refusal_reaches_the_signed_record(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path, arm="C2")
        mesh.execute(tool="write_file", arguments={"path": "production/db.sql"})
        assert _event(mesh)["payload"]["would_refuse"] is True

    def test_a_permitted_call_on_c2_is_not_a_shadow_refusal(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path, arm="C2")
        result = mesh.execute(tool="write_file", arguments={"path": "src/a.py"})
        assert result.would_refuse is False

    def test_c3_denies_instead_of_shadowing(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path, arm="C3")
        assert mesh.enforcing is True
        result = mesh.execute(tool="write_file", arguments={"path": "production/db.sql"})
        assert result.denied
        assert result.would_refuse is False


class TestKeysAndReproducibility:
    def _chain(self, tmp_path: Path, **kwargs: Any) -> list[dict[str, Any]]:
        mesh = _mesh(tmp_path, **kwargs)
        mesh.execute(tool="write_file", arguments={"path": "src/a.py"}, now_us=NOW)
        mesh.execute(tool="read_file", arguments={"path": "src/a.py"}, now_us=NOW + 1)
        return mesh.audit_events()

    def test_the_same_seed_reproduces_the_signed_chain(self, tmp_path: Path) -> None:
        seed = b"a-recorded-seed-of-32-bytes-long"
        assert self._chain(tmp_path, seed=seed) == self._chain(tmp_path, seed=seed)

    def test_without_a_seed_payloads_match_and_keys_do_not(self, tmp_path: Path) -> None:
        first, second = self._chain(tmp_path), self._chain(tmp_path)
        assert [r["chain_hash"] for r in first] == [r["chain_hash"] for r in second]
        assert first[0]["actor_public_key"] != second[0]["actor_public_key"]

    def test_identity_keys_missing_a_declared_agent_is_a_configuration_error(
        self, tmp_path: Path
    ) -> None:
        keys = tmp_path / "keys"
        keys.mkdir()
        (keys / "coding-agent.key").write_bytes(b"\x01" * 32)
        p = _contract(tmp_path, extra=["identity:", f"  keys: {keys.as_posix()}"])
        with pytest.raises(ConfigurationError, match="dba-agent"):
            CausalMesh.from_config(p)

    def test_identity_keys_are_used_when_complete(self, tmp_path: Path) -> None:
        keys = tmp_path / "keys"
        keys.mkdir()
        for agent in ("coding-agent", "dba-agent"):
            (keys / f"{agent}.key").write_bytes(b"\x02" * 32)
        p = _contract(tmp_path, extra=["identity:", f"  keys: {keys.as_posix()}"])
        first, second = CausalMesh.from_config(p), CausalMesh.from_config(p)
        for mesh in (first, second):
            mesh.register_tool(Tool(name="write_file", handler=lambda path: None))
            mesh.execute(tool="write_file", arguments={"path": "src/a.py"}, now_us=NOW)
        assert first.audit_events() == second.audit_events()
