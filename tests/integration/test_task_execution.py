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
