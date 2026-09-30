"""Claims in the SDK: opt-in exclusive leases, enforced by the one gate.

The SDK used to build its gate with ``registry=None``, so a lease could not
apply to an SDK session at all. These tests pin the behaviour of passing a
``ClaimRegistry``:

- off by default, and saying so when a lease is asked for without one
- a path one agent holds is refused to another, as data, and the refusal is
  counted in ``denials()`` exactly once
- the lease and the gate share a run id, or the lease would protect nothing
- an unenforced arm reports the same call as ``would_refuse`` and runs it,
  and records no denial because nothing was blocked
- a refusal, an unknown agent and a bad path are each handled as the
  registry handles them: outcomes are returned, misuse raises
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.claims import ClaimError, ClaimRegistry
from causalmesh.sdk.errors import ConfigurationError, UnknownAgentError

pytestmark = pytest.mark.unit

NOW = 1_000_000
LEASE = 60_000_000


def _contract(tmp_path: Path, *, arm: str = "C3") -> Path:
    path = tmp_path / "causalmesh.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "agent:",
                "  id: alice",
                "roles:",
                "  - agent_id: alice",
                "    archetype: writer",
                "  - agent_id: bob",
                "    archetype: writer",
                "policy:",
                f"  arm: {arm}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[ClaimRegistry]:
    with ClaimRegistry(tmp_path / "claims.db") as reg:
        yield reg


def _mesh(
    tmp_path: Path, registry: ClaimRegistry | None, *, arm: str = "C3", **kwargs: Any
) -> CausalMesh:
    mesh = CausalMesh.from_config(_contract(tmp_path, arm=arm), claims=registry, **kwargs)
    mesh.register_tool(Tool(name="write_file", handler=lambda path, content="": "ok"))
    mesh.register_tool(Tool(name="read_file", handler=lambda path: "data", mutating=False))
    return mesh


def _write(mesh: CausalMesh, agent: str, path: str = "src/a.py", now_us: int = NOW + 1) -> Any:
    return mesh.execute(agent_id=agent, tool="write_file", arguments={"path": path}, now_us=now_us)


class TestOffByDefault:
    def test_without_a_registry_contested_paths_behave_as_before(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path, None)
        assert _write(mesh, "alice").executed
        assert _write(mesh, "bob").executed
        assert mesh.claim_registry is None

    def test_asking_for_a_lease_without_a_registry_is_a_configuration_error(
        self, tmp_path: Path
    ) -> None:
        mesh = _mesh(tmp_path, None)
        with pytest.raises(ConfigurationError, match="claim registry"):
            mesh.claim(path="src/a.py", duration_us=LEASE, now_us=NOW)
        with pytest.raises(ConfigurationError, match="claim registry"):
            mesh.release(claim_id="x", now_us=NOW)

    def test_denials_is_empty_not_an_error_without_a_registry(self, tmp_path: Path) -> None:
        assert _mesh(tmp_path, None).denials() == []

    def test_a_registry_with_no_lease_blocks_nobody(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        assert _write(mesh, "alice").executed
        assert _write(mesh, "bob").executed
        assert mesh.denials() == []


class TestTwoAgentsContendingForOnePath:
    def test_the_holder_is_allowed_and_the_other_agent_is_denied(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        outcome = mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)
        assert outcome.granted
        assert outcome.claim is not None and outcome.claim.agent_id == "alice"

        held = _write(mesh, "alice")
        blocked = _write(mesh, "bob")

        assert held.executed and not held.would_refuse
        assert blocked.denied
        assert blocked.rule == "claim"
        assert blocked.holder == "alice"
        assert blocked.blocked_path == "src/a.py"
        assert "alice" in blocked.reason

    def test_the_denial_is_recorded_once_and_visible_in_denials(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)

        _write(mesh, "alice")
        assert mesh.denials() == []

        _write(mesh, "bob")
        rows = mesh.denials()
        assert len(rows) == 1
        assert rows[0]["requesting_agent"] == "bob"
        assert rows[0]["holder_agent"] == "alice"
        assert rows[0]["path"] == "path:src/a.py"
        assert rows[0]["run_id"] == mesh.run_id
        assert registry.denials(run_id=mesh.run_id) == rows

    def test_a_denied_call_never_reaches_the_handler_and_is_on_the_chain(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        ran: list[str] = []
        mesh.register_tool(Tool(name="put", handler=lambda path: ran.append(path)))
        mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)

        result = mesh.execute(
            agent_id="bob", tool="put", arguments={"path": "src/a.py"}, now_us=NOW + 1
        )

        assert result.denied and ran == []
        assert result.recorded
        event = mesh.audit_events()[-1]["event"]
        assert event["event_type"] == "FAILURE"
        assert event["payload"]["rule"] == "claim"
        assert event["payload"]["holder_agent"] == "alice"

    def test_another_path_is_not_blocked_by_the_lease(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)
        assert _write(mesh, "bob", "src/b.py").executed
        assert mesh.denials() == []

    def test_spellings_of_one_path_are_one_lease(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        mesh.claim(agent_id="alice", path="src\\a.py", duration_us=LEASE, now_us=NOW)
        assert _write(mesh, "bob", "./src/../src/a.py").denied

    def test_a_reading_call_is_not_gated(self, tmp_path: Path, registry: ClaimRegistry) -> None:
        mesh = _mesh(tmp_path, registry)
        mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)
        result = mesh.execute(
            agent_id="bob", tool="read_file", arguments={"path": "src/a.py"}, now_us=NOW + 1
        )
        assert result.executed
        assert mesh.denials() == []

    @pytest.mark.asyncio
    async def test_the_async_path_is_gated_the_same_way(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)
        result = await mesh.execute_async(
            agent_id="bob", tool="write_file", arguments={"path": "src/a.py"}, now_us=NOW + 1
        )
        assert result.denied and result.rule == "claim"
        assert len(mesh.denials()) == 1


class TestAnUnenforcedArmReportsAndRuns:
    @pytest.mark.parametrize("arm", ["C0", "C1", "C2"])
    def test_the_contested_call_runs_and_says_c3_would_refuse_it(
        self, tmp_path: Path, registry: ClaimRegistry, arm: str
    ) -> None:
        mesh = _mesh(tmp_path, registry, arm=arm)
        assert not mesh.enforcing
        mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)

        held = _write(mesh, "alice")
        contested = _write(mesh, "bob")

        assert held.executed and not held.would_refuse
        assert contested.executed
        assert contested.would_refuse
        assert contested.shadow_rule == "claim"
        assert contested.shadow_reason is not None and "alice" in contested.shadow_reason
        event = mesh.audit_events()[-1]["event"]
        assert event["payload"]["would_refuse"] is True
        assert event["payload"]["shadow_rule"] == "claim"

    def test_nothing_was_blocked_so_no_denial_is_recorded(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry, arm="C2")
        mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)
        _write(mesh, "bob")
        assert mesh.denials() == []


class TestTheLeaseAndTheGateShareARunId:
    def test_a_custom_run_id_namespaces_both(self, tmp_path: Path, registry: ClaimRegistry) -> None:
        mesh = _mesh(tmp_path, registry, run_id="run-7")
        outcome = mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)
        assert outcome.claim is not None and outcome.claim.run_id == "run-7"

        assert _write(mesh, "bob").denied
        assert [row["run_id"] for row in registry.denials(run_id="run-7")] == ["run-7"]
        assert registry.denials(run_id="sdk") == []

    def test_the_default_run_id_is_the_sdk_constant(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        outcome = mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)
        assert outcome.claim is not None and outcome.claim.run_id == "sdk"

    def test_a_lease_in_another_runs_namespace_blocks_nobody(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        first = _mesh(tmp_path, registry, run_id="run-1")
        second = _mesh(tmp_path, registry, run_id="run-2")
        first.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)
        assert _write(second, "bob").executed
        assert _write(first, "bob").denied


class TestClaimOutcomesAreData:
    def test_a_contested_claim_is_refused_as_data_and_counted(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)

        outcome = mesh.claim(agent_id="bob", path="src/a.py", duration_us=LEASE, now_us=NOW + 1)

        assert not outcome.granted
        assert outcome.claim is None
        assert outcome.holder is not None and outcome.holder.agent_id == "alice"
        assert [row["requesting_agent"] for row in mesh.denials()] == ["bob"]

    def test_reclaiming_a_path_you_hold_renews_it(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        first = mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)
        again = mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW + 10)
        assert again.granted
        assert first.claim is not None and again.claim is not None
        assert again.claim.claim_id == first.claim.claim_id
        assert again.claim.renewals == 1

    def test_release_frees_the_path(self, tmp_path: Path, registry: ClaimRegistry) -> None:
        mesh = _mesh(tmp_path, registry)
        outcome = mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)
        assert outcome.claim is not None
        assert _write(mesh, "bob").denied

        released = mesh.release(claim_id=outcome.claim.claim_id, agent_id="alice", now_us=NOW + 2)
        assert released.granted
        assert _write(mesh, "bob", now_us=NOW + 3).executed

    def test_releasing_someone_elses_lease_is_refused_as_data(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        outcome = mesh.claim(agent_id="alice", path="src/a.py", duration_us=LEASE, now_us=NOW)
        assert outcome.claim is not None

        refused = mesh.release(claim_id=outcome.claim.claim_id, agent_id="bob", now_us=NOW + 1)

        assert not refused.granted
        assert _write(mesh, "bob").denied

    def test_a_lapsed_lease_stops_blocking(self, tmp_path: Path, registry: ClaimRegistry) -> None:
        mesh = _mesh(tmp_path, registry)
        mesh.claim(agent_id="alice", path="src/a.py", duration_us=100, now_us=NOW)
        assert _write(mesh, "bob", now_us=NOW + 50).denied
        assert _write(mesh, "bob", now_us=NOW + 100).executed

    def test_an_unusable_path_is_refused_as_data(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        outcome = _mesh(tmp_path, registry).claim(path="  ", duration_us=LEASE, now_us=NOW)
        assert not outcome.granted
        assert "not a usable resource" in outcome.reason

    def test_the_default_agent_holds_the_lease_when_none_is_named(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        outcome = mesh.claim(path="src/a.py", duration_us=LEASE, now_us=NOW)
        assert outcome.claim is not None and outcome.claim.agent_id == "alice"


class TestMisuseRaises:
    def test_an_agent_with_no_key_cannot_hold_a_lease(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        with pytest.raises(UnknownAgentError):
            mesh.claim(agent_id="mallory", path="src/a.py", duration_us=LEASE, now_us=NOW)
        assert registry.history(run_id=mesh.run_id) == []

    def test_a_lease_needs_a_positive_duration(
        self, tmp_path: Path, registry: ClaimRegistry
    ) -> None:
        mesh = _mesh(tmp_path, registry)
        with pytest.raises(ClaimError):
            mesh.claim(agent_id="alice", path="src/a.py", duration_us=0, now_us=NOW)
