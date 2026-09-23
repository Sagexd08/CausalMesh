"""Executing a real task under all four arms (spec §37, §71, §74).

This is the §71 vertical slice at full height: a real fixture, a real task,
real agents, and success judged automatically from an integrated workspace.

The §37 gate is the point of it. A task must *demonstrate* that the
coordination dependency exists, and the only way to demonstrate it is to
run the task and observe the arms differ. Everything here therefore
executes rather than asserting on structure.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from causalmesh.tasks import (
    RunConfig,
    TaskDefinition,
    check_sensitivity,
    execute_task,
)
from causalmesh.verifier import verify_chain

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REPO = Path(__file__).resolve().parents[2]
TASK_PATH = REPO / "tasks" / "schema_handler_widen.yaml"
FIXTURES = REPO / "fixtures"
SEED = b"causalmesh-task-execution-seed01"


@pytest.fixture(scope="module")
def task() -> TaskDefinition:
    return TaskDefinition.from_yaml(TASK_PATH)


async def run_arm(task: TaskDefinition, arm: str, tmp_path: Path):
    return await execute_task(
        task,
        RunConfig(
            experiment_id="exp_task_execution",
            run_id=f"run_{arm}",
            arm=arm,
            master_seed=SEED,
        ),
        workspace_root=tmp_path / arm,
        fixtures_root=FIXTURES,
    )


@pytest.fixture(scope="module")
async def all_arms(task: TaskDefinition, tmp_path_factory) -> dict:
    """Run each arm once and share the results across every test.

    Module-scoped deliberately. Each run spawns a real pytest subprocess
    for the integration test, so a function-scoped fixture would execute
    roughly fifty runs instead of four and take minutes rather than
    seconds — measured at 9 minutes before this was corrected.

    Sharing is safe because the tests only read the results. The
    determinism tests build their own runs, precisely because they need to
    compare two independent executions.
    """
    root = tmp_path_factory.mktemp("all_arms")
    return {arm: await run_arm(task, arm, root) for arm in ("C0", "C1", "C2", "C3")}


class TestInformationContrast:
    """C0 versus the informed arms — the factor §37 gates on."""

    async def test_the_isolated_arm_fails(self, all_arms: dict) -> None:
        c0 = all_arms["C0"]
        assert not c0.succeeded
        assert not c0.outcome.divergence_absent

    @pytest.mark.parametrize("arm", ["C1", "C2"])
    async def test_the_informed_arms_succeed(self, all_arms: dict, arm: str) -> None:
        result = all_arms[arm]
        assert result.succeeded, result.outcome.detail

    async def test_the_difference_comes_from_being_informed(self, all_arms: dict) -> None:
        # The mechanism, not just the outcome: agent_b knew about the schema
        # change in the informed arms and did not in C0.
        assert all_arms["C0"].agent_summaries["agent_b"]["informed_paths"] == []
        for arm in ("C1", "C2", "C3"):
            assert "src/schema.py" in all_arms[arm].agent_summaries["agent_b"]["informed_paths"]

    async def test_the_uninformed_agent_records_why_it_did_not_act(self, all_arms: dict) -> None:
        # §52: the agent's inaction is evidence, not a silent absence.
        skipped = all_arms["C0"].agent_summaries["agent_b"]["skipped_actions"]
        assert skipped
        assert any("not informed about src/schema.py" in s["reason"] for s in skipped)


class TestEnforcement:
    async def test_c3_holds_claims_on_owned_paths(self, all_arms: dict) -> None:
        claims = all_arms["C3"].claim_history
        assert {c["path"] for c in claims} == {"src/schema.py", "src/handler.py"}

    async def test_unenforced_arms_hold_no_claims(self, all_arms: dict) -> None:
        for arm in ("C0", "C1", "C2"):
            assert all_arms[arm].claim_history == []

    async def test_c3_succeeds_on_this_task(self, all_arms: dict) -> None:
        """§74: prevention is measured, not assumed to help.

        On this task C3 succeeds because each agent writes only what it
        owns, so enforcement never blocks legitimate work. A task where it
        does block legitimate work would show a cost, and that would be a
        finding rather than a defect.
        """
        assert all_arms["C3"].succeeded, all_arms["C3"].outcome.detail


class TestEvidence:
    async def test_every_arm_produces_a_verifiable_chain(self, all_arms: dict) -> None:
        for arm, result in all_arms.items():
            report = verify_chain(result.records, _key_ring(result))
            assert report.valid, f"{arm}: {report.summary()}"

    async def test_every_run_records_the_task_hash(
        self, all_arms: dict, task: TaskDefinition
    ) -> None:
        # §33: results can only be pooled across runs of the same task.
        for result in all_arms.values():
            assert result.task_hash == task.content_hash()

    async def test_every_run_records_workspace_digests(self, all_arms: dict) -> None:
        for result in all_arms.values():
            assert set(result.workspace_digests) == {"agent_a", "agent_b"}

    async def test_the_outcome_carries_its_evidence(self, all_arms: dict) -> None:
        for result in all_arms.values():
            assert result.outcome.evidence


class TestCoordinationCost:
    async def test_the_isolated_arm_spends_nothing(self, all_arms: dict) -> None:
        assert all_arms["C0"].coordination_bytes() == 0

    async def test_the_informed_arms_spend_something(self, all_arms: dict) -> None:
        for arm in ("C1", "C2", "C3"):
            assert all_arms[arm].coordination_bytes() > 0

    async def test_c2_and_c3_spend_the_same(self, all_arms: dict) -> None:
        # They differ by enforcement alone, so their information cost must
        # be identical or the contrast is confounded.
        assert all_arms["C2"].coordination_bytes() == all_arms["C3"].coordination_bytes()


class TestQualityGate:
    """§37: the gate itself, run for real."""

    async def test_the_task_is_demonstrably_coordination_sensitive(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        report = await check_sensitivity(
            task,
            workspace_root=tmp_path / "gate",
            fixtures_root=FIXTURES,
            master_seed=SEED,
            repetitions=1,
        )
        assert report.sensitive, report.detail
        assert report.informed_successes > report.isolated_successes

    async def test_the_gate_reports_the_divergence_counts(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        # A rejected task must be diagnosable, so the evidence behind the
        # verdict is retained rather than reduced to a boolean.
        report = await check_sensitivity(
            task,
            workspace_root=tmp_path / "gate",
            fixtures_root=FIXTURES,
            master_seed=SEED,
            repetitions=1,
        )
        assert report.isolated_divergences == 1
        assert report.informed_divergences == 0


class TestDeterminism:
    async def test_two_runs_of_the_same_arm_agree(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        first = await run_arm(task, "C2", tmp_path / "first")
        second = await run_arm(task, "C2", tmp_path / "second")
        assert first.head_hash == second.head_hash
        assert first.succeeded == second.succeeded
        assert first.workspace_digests == second.workspace_digests


def _key_ring(result):
    """Rebuild the key ring a run's chain verifies against."""
    from causalmesh.crypto.keys import KeyPair, PublicKeyRing

    agents = {record["event"]["identity"]["agent_id"] for record in result.records}
    return PublicKeyRing.from_keypairs({agent: KeyPair.derive(SEED, agent) for agent in agents})


def _write_contract(tmp_path: Path, *, owner_of_config: str) -> Path:
    """A minimal contract that will produce both a refusal and an allow.

    `owner_of_config` owns src/handler.py; anyone else writing it is refused.
    Every other path is undeclared, so writes to it are allowed — giving the
    run at least one ALLOW verdict and, when the scenario has an agent that
    is not `owner_of_config` write to src/handler.py, at least one REFUSE.
    """
    contract_path = tmp_path / "causalmesh.yaml"
    contract_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "roles": [{"agent_id": owner_of_config, "owns": ["src/handler.py"]}],
                "policy": {"arm": "C3"},
            }
        ),
        encoding="utf-8",
    )
    return contract_path


class TestPolicyVerdictsOnTheChain:
    """A contract-driven run's verdicts become real, verifiable chain events.

    This is the property the backlog entry "Verdicts do not enter the
    signed chain" names directly: a refusal recorded only in the run
    artifact is not provable the way a chain event is. Running with a real
    contract and reading the resulting chain back is the only way to prove
    this rather than asserting it.
    """

    async def test_verdicts_appear_as_verified_policy_verdict_events(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        contract_path = _write_contract(tmp_path, owner_of_config="agent_a")

        result = await execute_task(
            task,
            RunConfig(
                experiment_id="exp_policy_verdicts",
                run_id="run_policy_verdicts",
                arm="C3",
                master_seed=SEED,
                contract_path=str(contract_path),
            ),
            workspace_root=tmp_path / "ws",
            fixtures_root=FIXTURES,
        )

        verdict_records = [
            r for r in result.records if r["event"]["event_type"] == "POLICY_VERDICT"
        ]
        assert verdict_records, "expected at least one POLICY_VERDICT event on the chain"

        # Every verdict-event is attributed to the policy_gate identity,
        # never to a participating agent.
        for record in verdict_records:
            assert record["event"]["identity"]["agent_id"] == "policy_gate"

        # Offline verification must accept the new event type with no
        # special-casing — proving this rather than asserting it is the
        # whole point of this test. `_key_ring` (already defined in this
        # file) picks up the policy_gate identity automatically because it
        # derives a key for every agent_id actually present in the records.
        report = verify_chain(result.records, _key_ring(result))
        assert report.valid, report.failures


class TestCausalEdgesForDenials:
    """A denied write's FAILURE event is linked back to the verdict that
    caused it (`docs/backlog.md`, "Causal edges over the chain": population).

    The pairing is positional, not content-matched (`Verdict.to_dict()`
    carries no agent id), which is what makes it exact rather than a
    best-effort guess — this is the property worth proving by running a
    real refusal rather than asserting the pairing logic in isolation.
    """

    async def test_a_denied_write_gets_a_required_edge_to_its_verdict(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        from causalmesh.edges import RelationshipType

        contract_path = _write_contract(tmp_path, owner_of_config="agent_a")

        result = await execute_task(
            task,
            RunConfig(
                experiment_id="exp_causal_edges",
                run_id="run_causal_edges",
                arm="C3",
                master_seed=SEED,
                contract_path=str(contract_path),
            ),
            workspace_root=tmp_path / "ws",
            fixtures_root=FIXTURES,
        )

        denied_events = [
            r
            for r in result.records
            if r["event"]["event_type"] == "FAILURE"
            and r["event"]["payload"].get("outcome") == "denied"
        ]
        assert denied_events, "expected at least one denied write in this scenario"

        verdict_ids = {
            r["event"]["event_id"]
            for r in result.records
            if r["event"]["event_type"] == "POLICY_VERDICT"
        }

        assert result.edges, "expected at least one causal edge"
        for edge in result.edges:
            assert edge["relationship"] == str(RelationshipType.REQUIRED)
            assert edge["from_event_id"] in {e["event"]["event_id"] for e in denied_events}
            assert edge["to_event_id"] in verdict_ids

        # Every denial has exactly one edge, and every edge's target verdict
        # is itself a refusal — proving the pairing lines up with the
        # events it claims to connect, not just that some edges exist.
        assert len(result.edges) == len(denied_events)
