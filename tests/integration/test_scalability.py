"""The scalability profile, run for real on scripted mock agents (spec §86).

These drive the whole stack (generated task, isolated workspaces, relay,
channels, mock agents, offline verification) at N = 4, 8 and 16. Every
number asserted here is a property of the scripted task on this machine; none
says anything about how a real agent would coordinate.

What they establish:

- delivery correctness: under path-scoped delivery an agent receives exactly
  the events other agents produced on paths it declared interest in;
- the chain verifies at every size and under both modes;
- the same seed gives the same head hash, and a different seed does not;
- broadcast fan-out grows about quadratically with N in the measured runs
  while path-scoped delivery grows about linearly under localized contention;
- under dense contention path-scoped delivery removes a constant share, not
  a growth order, which is the honest limit of the technique.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from causalmesh.cli.main import app
from causalmesh.experiments.scalability import (
    SCALABILITY_PROFILES,
    ScalabilityProfile,
    scalability_profile,
)
from causalmesh.metrics import ScalingRun, summarize_scaling
from causalmesh.relay import BROADCAST, PATH_SCOPED
from causalmesh.tasks import RunConfig, execute_task
from causalmesh.tasks.scalability import (
    measure_run,
    render_scalability,
    run_scalability,
    spec_for,
)
from causalmesh.tasks.scaled import ScaledSpec, generate_scaled_task, write_scaled_fixture

pytestmark = pytest.mark.integration

SEED = b"causalmesh-scalability-test-seed"

GROWTH_PROFILE = ScalabilityProfile(
    name="growth_check",
    agent_counts=(4, 8, 16),
    arms=("C2",),
    topologies=("localized",),
)


def run_one(
    tmp_path: Path, *, n: int, arm: str, mode: str, seed: bytes = SEED, group_size: int = 4
):
    spec = ScaledSpec(n_agents=n, group_size=min(group_size, n))
    task = generate_scaled_task(spec)
    write_scaled_fixture(spec, tmp_path / "fx")
    result = asyncio.run(
        execute_task(
            task,
            RunConfig(
                experiment_id="exp_scal",
                run_id=f"r_{n}_{arm}_{mode}",
                arm=arm,
                master_seed=seed,
                delivery_mode=mode,
            ),
            workspace_root=tmp_path / "ws",
            fixtures_root=tmp_path / "fx",
        )
    )
    return task, spec, result


@pytest.fixture(scope="module")
def growth_runs(tmp_path_factory) -> dict[tuple[int, str], ScalingRun]:
    root = tmp_path_factory.mktemp("growth")
    report = asyncio.run(run_scalability(GROWTH_PROFILE, workspace_root=root, seed=SEED))
    return {(run.n_agents, run.delivery_mode): run for run in report.runs}


class TestDeliveryCorrectnessEndToEnd:
    @pytest.mark.parametrize("arm", ["C1", "C2", "C3"])
    def test_a_path_scoped_agent_receives_exactly_the_events_on_its_declared_paths(
        self, tmp_path: Path, arm: str
    ) -> None:
        task, _, result = run_one(tmp_path, n=8, arm=arm, mode=PATH_SCOPED)
        assert result.error is None, result.error

        interests = {role.agent_id: role.owns | role.depends_on for role in task.roles}
        events = [r["event"] for r in result.records]
        agent_events = [e for e in events if e["identity"]["agent_id"] in interests]

        for agent, declared in interests.items():
            expected = {
                e["event_id"]
                for e in agent_events
                if e["identity"]["agent_id"] != agent and set(e["paths"]) & declared
            }
            observed = {
                event_id
                for observation in result.agent_summaries[agent]["observations"]
                for event_id in observation["event_ids"]
            }
            assert observed == expected, agent
            assert expected, "the task must give every agent something to hear"

    def test_broadcast_delivers_every_peer_event_to_every_agent(self, tmp_path: Path) -> None:
        task, _, result = run_one(tmp_path, n=8, arm="C2", mode=BROADCAST)
        agents = set(task.agent_ids)
        agent_event_ids = [
            r["event"]["event_id"]
            for r in result.records
            if r["event"]["identity"]["agent_id"] in agents
        ]
        for agent in agents:
            observed = {
                event_id
                for observation in result.agent_summaries[agent]["observations"]
                for event_id in observation["event_ids"]
            }
            own = {
                r["event"]["event_id"]
                for r in result.records
                if r["event"]["identity"]["agent_id"] == agent
            }
            assert observed == set(agent_event_ids) - own

    @pytest.mark.parametrize("mode", [None, BROADCAST, PATH_SCOPED])
    def test_c0_stays_isolated_at_sixteen_agents_in_every_mode(
        self, tmp_path: Path, mode: str | None
    ) -> None:
        _, _, result = run_one(tmp_path, n=16, arm="C0", mode=mode)
        assert result.error is None, result.error
        for summary in result.agent_summaries.values():
            assert summary["coordination"]["received_no_coordination"] is True
        assert result.coordination_bytes() == 0

    def test_path_scoped_agents_are_still_informed_and_the_task_succeeds(
        self, tmp_path: Path
    ) -> None:
        # Scoping removes events an agent did not declare; it must not remove
        # the ones its work depends on, or "cheaper" would mean "blind".
        for n in (4, 8):
            _, _, scoped = run_one(tmp_path / f"s{n}", n=n, arm="C2", mode=PATH_SCOPED)
            _, _, broadcast = run_one(tmp_path / f"b{n}", n=n, arm="C2", mode=BROADCAST)
            assert scoped.succeeded and broadcast.succeeded
            assert scoped.outcome.divergence_absent


class TestChainAndDeterminism:
    @pytest.mark.parametrize("mode", [BROADCAST, PATH_SCOPED])
    @pytest.mark.parametrize("n", [4, 8, 16])
    def test_the_chain_verifies_at_every_size(self, tmp_path: Path, n: int, mode: str) -> None:
        _, spec, result = run_one(tmp_path, n=n, arm="C2", mode=mode)
        measured = measure_run(
            result, spec=spec, topology="localized", delivery_mode=mode, master_seed=SEED
        )
        assert measured.chain_valid
        assert result.head_hash is not None

    @pytest.mark.parametrize("mode", [BROADCAST, PATH_SCOPED])
    def test_the_same_seed_gives_the_same_head_hash(self, tmp_path: Path, mode: str) -> None:
        _, _, first = run_one(tmp_path / "a", n=8, arm="C2", mode=mode)
        _, _, second = run_one(tmp_path / "b", n=8, arm="C2", mode=mode)
        assert first.head_hash == second.head_hash
        assert [r["chain_hash"] for r in first.records] == [r["chain_hash"] for r in second.records]

    def test_the_same_seed_gives_the_same_signatures_and_a_different_seed_does_not(
        self, tmp_path: Path
    ) -> None:
        # The seed derives the signing keys. The chain hash covers event
        # content, not the signature, so the head hash is seed independent by
        # design; what a seed changes is who signed, and that must differ.
        _, _, first = run_one(tmp_path / "a", n=8, arm="C2", mode=BROADCAST, seed=SEED)
        _, _, again = run_one(tmp_path / "b", n=8, arm="C2", mode=BROADCAST, seed=SEED)
        _, _, other = run_one(tmp_path / "c", n=8, arm="C2", mode=BROADCAST, seed=b"z" * 32)

        def signatures(result) -> list[str]:
            return [r["signature"] for r in result.records]

        assert signatures(first) == signatures(again)
        assert signatures(first) != signatures(other)
        assert (
            first.relay_summary["key_ring_fingerprint"]
            != (other.relay_summary["key_ring_fingerprint"])
        )

    def test_causal_parents_in_the_chain_reflect_what_delivery_let_an_agent_see(
        self, tmp_path: Path
    ) -> None:
        # An event's `parent_id` is the last peer event its agent observed, so
        # the delivery mode is visible in the signed record (the two heads
        # differ), and under path-scoped delivery every parent lies on a path
        # the child's agent declared interest in.
        task, _, broadcast = run_one(tmp_path / "a", n=8, arm="C2", mode=BROADCAST)
        _, _, scoped = run_one(tmp_path / "b", n=8, arm="C2", mode=PATH_SCOPED)
        assert broadcast.head_hash != scoped.head_hash

        interests = {role.agent_id: role.owns | role.depends_on for role in task.roles}
        by_id = {r["event"]["event_id"]: r["event"] for r in scoped.records}
        checked = 0
        for record in scoped.records:
            event = record["event"]
            agent = event["identity"]["agent_id"]
            if agent in interests and event["parent_id"] is not None:
                parent = by_id[event["parent_id"]]
                assert parent["identity"]["agent_id"] != agent
                assert set(parent["paths"]) & interests[agent]
                checked += 1
        assert checked > 0


class TestMeasuredGrowth:
    def test_broadcast_fan_out_is_n_times_n_minus_one_times_events_per_agent(
        self, growth_runs
    ) -> None:
        # 6 events per agent (2 files x read+write, then read+write of the shared registry).
        for n in (4, 8, 16):
            run = growth_runs[(n, BROADCAST)]
            assert run.agent_events == 6 * n
            assert run.events_available == 6 * n * (n - 1)
            assert run.events_delivered == run.events_available

    def test_path_scoped_delivery_is_linear_with_localized_contention(self, growth_runs) -> None:
        # Each shared-path event goes to the other three members of its group:
        # 2 events per agent x 3 recipients = 6 deliveries per agent.
        for n in (4, 8, 16):
            assert growth_runs[(n, PATH_SCOPED)].events_delivered == 6 * n

    def test_doubling_agents_more_than_quadruples_broadcast_but_only_doubles_scoped(
        self, growth_runs
    ) -> None:
        for small, large in ((4, 8), (8, 16)):
            broadcast = growth_runs[(large, BROADCAST)].events_delivered / (
                growth_runs[(small, BROADCAST)].events_delivered
            )
            scoped = growth_runs[(large, PATH_SCOPED)].events_delivered / (
                growth_runs[(small, PATH_SCOPED)].events_delivered
            )
            assert broadcast > 4.0
            assert scoped == pytest.approx(2.0)

    def test_the_fitted_exponents_separate_the_two_policies(self, growth_runs) -> None:
        series = {s.delivery_mode: s for s in summarize_scaling(growth_runs.values())}
        broadcast = series[BROADCAST].exponent("events_delivered")
        scoped = series[PATH_SCOPED].exponent("events_delivered")
        assert broadcast is not None and scoped is not None
        assert broadcast > 2.0  # N(N-1) over N=4..16 fits a little above 2
        assert scoped == pytest.approx(1.0, abs=0.05)
        assert scoped < broadcast - 1.0

    def test_scoped_coordination_bytes_grow_slower_than_broadcast_bytes(self, growth_runs) -> None:
        series = {s.delivery_mode: s for s in summarize_scaling(growth_runs.values())}
        assert series[PATH_SCOPED].exponent("coordination_bytes") < (
            series[BROADCAST].exponent("coordination_bytes")
        )
        for n in (8, 16):
            assert (
                growth_runs[(n, PATH_SCOPED)].coordination_bytes
                < growth_runs[(n, BROADCAST)].coordination_bytes
            )

    def test_at_four_agents_the_saving_is_only_the_events_on_private_files(
        self, growth_runs
    ) -> None:
        # One contention group holds all four agents, so only own-directory
        # events (4 of 6 per agent) are scoped away: a third is delivered.
        run = growth_runs[(4, PATH_SCOPED)]
        assert run.delivery_ratio == pytest.approx(1 / 3)

    def test_every_measured_run_has_a_valid_chain_and_a_known_outcome(self, growth_runs) -> None:
        for run in growth_runs.values():
            assert run.chain_valid
            assert run.succeeded is True

    def test_dense_contention_removes_a_constant_share_not_a_growth_order(
        self, tmp_path: Path
    ) -> None:
        profile = ScalabilityProfile(
            name="dense_check", agent_counts=(4, 8, 16), arms=("C2",), topologies=("dense",)
        )
        report = asyncio.run(run_scalability(profile, workspace_root=tmp_path, seed=SEED))
        series = {s.delivery_mode: s for s in report.series}
        scoped = series[PATH_SCOPED].exponent("events_delivered")
        broadcast = series[BROADCAST].exponent("events_delivered")
        assert scoped == pytest.approx(broadcast, abs=0.01)
        for run in report.runs:
            if run.delivery_mode == PATH_SCOPED:
                assert run.delivery_ratio == pytest.approx(1 / 3)


class TestTheProfileEntryPoints:
    def test_spec_for_maps_topology_to_group_size(self) -> None:
        found = scalability_profile("scalability")
        assert spec_for(found, n_agents=16, topology="localized").group_size == 4
        assert spec_for(found, n_agents=16, topology="dense").group_size == 16
        assert spec_for(found, n_agents=4, topology="localized").group_size == 4

    def test_the_smoke_profile_runs_and_renders_ascii(self, tmp_path: Path) -> None:
        found = SCALABILITY_PROFILES["scalability_smoke"]
        report = asyncio.run(run_scalability(found, workspace_root=tmp_path, seed=SEED))
        assert len(report.runs) == found.run_count()
        text = render_scalability(report)
        text.encode("ascii")
        assert "mock agents" in text
        payload = report.to_dict()
        assert payload["profile"]["gated"] is False
        assert "not evidence about real agent behaviour" in payload["note"].lower()

    def test_the_cli_runs_the_smoke_profile_and_emits_json(self) -> None:
        result = CliRunner().invoke(
            app, ["experiment", "scalability", "--profile", "scalability_smoke", "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout[result.stdout.index("{") :])
        assert len(payload["runs"]) == 4
        assert all(run["chain_valid"] for run in payload["runs"])

    def test_the_cli_refuses_an_unknown_profile(self) -> None:
        result = CliRunner().invoke(app, ["experiment", "scalability", "--profile", "nonsense"])
        assert result.exit_code != 0


@pytest.mark.slow
def test_the_full_scalability_profile_runs_every_cell(tmp_path: Path) -> None:
    found = scalability_profile("scalability")
    report = asyncio.run(run_scalability(found, workspace_root=tmp_path, seed=SEED))
    assert len(report.runs) == found.run_count() == 24
    assert all(run.chain_valid for run in report.runs)
    for run in report.runs:
        if run.delivery_mode == BROADCAST:
            assert run.events_delivered == run.events_available
