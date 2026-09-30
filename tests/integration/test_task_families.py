"""The two remaining §35 task families, executed (spec §35, §37, §38).

`interface_consumer` and `shared_utility_refactor` were the two families
`docs/backlog.md` recorded as unbuilt. Each is a *dependency* task in the
sense `docs/tasks.md` uses: no path is contested, and one agent's write
invalidates another agent's work.

They differ from `schema_handler_widen` in the mechanism, not the structure:

- `interface_consumer`: a consumer calls a function whose signature changed,
  so a stale consumer fails with `TypeError` when it runs;
- `shared_utility_refactor`: one refactor removes a name that two consumers
  owned by two different agents import, so a stale consumer fails with
  `ImportError` when its module loads.

Every assertion here reads what the run did. The sensitivity gate is run for
real; nothing in this file states a verdict the run did not produce.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from causalmesh.cli.main import app
from causalmesh.crypto.keys import KeyPair, PublicKeyRing
from causalmesh.tasks import (
    RunConfig,
    TaskDefinition,
    TaskFamily,
    check_sensitivity,
    execute_task,
    load_tasks,
    validate_structure,
)
from causalmesh.verifier import verify_chain

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "tasks"
FIXTURES = REPO / "fixtures"
SEED = b"causalmesh-task-families-seed001"
ARMS = ("C0", "C1", "C2", "C3")


@dataclass(frozen=True)
class Spec:
    """What is specific to one task; every test below is generic over it."""

    task_id: str
    family: str
    agents: frozenset[str]
    dependents: frozenset[str]
    written_by_producer: str
    # A file only a stale consumer can contain.
    stale_file: str
    stale_marker: str
    # A file only a consumer that followed the change can contain.
    fresh_file: str
    fresh_marker: str
    # What a stale consumer raises when the integration test runs.
    stale_error: str


SPECS = {
    "interface_consumer": Spec(
        task_id="interface_consumer",
        family=TaskFamily.INTERFACE_CONSUMER,
        agents=frozenset({"agent_a", "agent_b"}),
        dependents=frozenset({"agent_b"}),
        written_by_producer="src/pricing.py",
        stale_file="src/checkout.py",
        stale_marker="# call written against the pre-change signature",
        fresh_file="src/checkout.py",
        fresh_marker="format_price(cents, currency)",
        stale_error="TypeError",
    ),
    "shared_utility_refactor": Spec(
        task_id="shared_utility_refactor",
        family=TaskFamily.SHARED_UTILITY_REFACTOR,
        agents=frozenset({"agent_a", "agent_b", "agent_c"}),
        dependents=frozenset({"agent_b", "agent_c"}),
        written_by_producer="src/textutil.py",
        stale_file="src/exporter.py",
        stale_marker="from textutil import clean",
        fresh_file="src/exporter.py",
        fresh_marker="from textutil import normalize_text",
        stale_error="ImportError",
    ),
}


@pytest.fixture(scope="module", params=sorted(SPECS))
def spec(request) -> Spec:
    return SPECS[request.param]


@pytest.fixture(scope="module")
def task(spec: Spec) -> TaskDefinition:
    return TaskDefinition.from_yaml(TASKS / f"{spec.task_id}.yaml")


@pytest.fixture(scope="module")
async def all_arms(spec: Spec, task: TaskDefinition, tmp_path_factory) -> dict:
    """One run per arm, shared by every read-only test for this task.

    Module-scoped because each run spawns a real pytest subprocess.
    """
    root = tmp_path_factory.mktemp(spec.task_id)
    results: dict = {"_root": root}
    for arm in ARMS:
        results[arm] = await execute_task(
            task,
            RunConfig(
                experiment_id=f"exp_{spec.task_id}",
                run_id=f"run_{arm}",
                arm=arm,
                master_seed=SEED,
            ),
            workspace_root=root / arm,
            fixtures_root=FIXTURES,
        )
    return results


def integrated(all_arms: dict, arm: str) -> Path:
    return all_arms["_root"] / arm / f"run_{arm}_integrated"


def read_integrated(all_arms: dict, arm: str, relative: str) -> str:
    return (integrated(all_arms, arm) / relative).read_text(encoding="utf-8")


class TestTheTaskIsDefinedByConstruction:
    def test_it_belongs_to_its_family(self, spec: Spec, task: TaskDefinition) -> None:
        assert task.family == spec.family
        assert task.family in TaskFamily.ALL

    def test_it_validates_against_its_fixture(self, task: TaskDefinition) -> None:
        report = validate_structure(task, fixtures_root=FIXTURES)
        assert report.valid, [issue.to_dict() for issue in report.issues]
        assert not report.warnings, [issue.to_dict() for issue in report.warnings]

    def test_it_has_the_agents_the_design_calls_for(self, spec: Spec, task: TaskDefinition) -> None:
        assert set(task.agent_ids) == spec.agents

    def test_no_path_is_contested(self, task: TaskDefinition) -> None:
        # These are dependency tasks. Declaring contention would be a claim
        # the validator checks against the scenario, and there is none.
        assert task.contested_paths == frozenset()

    def test_every_dependent_depends_on_a_path_the_producer_writes(
        self, spec: Spec, task: TaskDefinition
    ) -> None:
        for agent_id in spec.dependents:
            assert spec.written_by_producer in task.role_for(agent_id).depends_on
        producer_writes = {
            action["write"]["path"]
            for action in task.scenario["agent_a"]["actions"]
            if isinstance(action, dict) and "write" in action
        }
        assert producer_writes == {spec.written_by_producer}

    def test_ownership_is_disjoint(self, task: TaskDefinition) -> None:
        owned = [path for role in task.roles for path in role.owns]
        assert len(owned) == len(set(owned))

    def test_the_divergence_marker_is_the_stale_form(
        self, spec: Spec, task: TaskDefinition
    ) -> None:
        assert task.success.divergence_marker == spec.stale_marker
        consumers_write = {
            action["write"]["path"]
            for agent_id in spec.dependents
            for action in task.scenario[agent_id]["actions"]
            if isinstance(action, dict) and "write" in action
        }
        assert task.success.divergence_file in consumers_write

    def test_it_is_held_out_of_experiment_profiles(self, task: TaskDefinition) -> None:
        assert task.in_design is False

    def test_it_is_listed_with_the_suite(self, spec: Spec) -> None:
        suite = {t.task_id: t for t in load_tasks(TASKS)}
        assert spec.task_id in suite

    def test_the_hash_is_stable_across_loads(self, spec: Spec, task: TaskDefinition) -> None:
        reloaded = TaskDefinition.from_yaml(TASKS / f"{spec.task_id}.yaml")
        assert reloaded.content_hash() == task.content_hash()


class TestTheFixtureStartsConsistent:
    """The failure must be induced by the scenario, not present at baseline."""

    def test_the_untouched_fixture_passes_its_own_integration_test(
        self, task: TaskDefinition
    ) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/"],
            cwd=FIXTURES / task.fixture,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env={"PYTHONDONTWRITEBYTECODE": "1", **_inherited_env()},
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


def _inherited_env() -> dict[str, str]:
    import os

    return {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME", "TEMP")
        if name in os.environ
    }


class TestTheArmsSeparate:
    async def test_the_isolated_arm_fails(self, all_arms: dict) -> None:
        c0 = all_arms["C0"]
        assert not c0.succeeded
        assert not c0.outcome.divergence_absent

    @pytest.mark.parametrize("arm", ["C1", "C2", "C3"])
    async def test_every_informed_arm_succeeds(self, all_arms: dict, arm: str) -> None:
        assert all_arms[arm].succeeded, all_arms[arm].outcome.detail
        assert all_arms[arm].outcome.divergence_absent

    async def test_no_arm_records_a_denial(self, all_arms: dict) -> None:
        # Ownership is disjoint, so enforcement has nothing to refuse. A
        # denial here would mean the task had grown a contested path.
        for arm in ARMS:
            assert all_arms[arm].denials == []

    async def test_the_isolated_arm_spends_nothing_on_coordination(self, all_arms: dict) -> None:
        assert all_arms["C0"].coordination_bytes() == 0
        for arm in ("C1", "C2", "C3"):
            assert all_arms[arm].coordination_bytes() > 0

    async def test_c2_and_c3_spend_the_same_coordination(self, all_arms: dict) -> None:
        # They differ by enforcement alone; any information difference would
        # confound the contrast.
        assert all_arms["C2"].coordination_bytes() == all_arms["C3"].coordination_bytes()

    async def test_no_run_errored(self, all_arms: dict) -> None:
        for arm in ARMS:
            assert all_arms[arm].error is None


class TestTheMechanism:
    """The right outcome for the right reason, read from the merged files."""

    async def test_the_producer_change_lands_in_every_arm(
        self, spec: Spec, task: TaskDefinition, all_arms: dict
    ) -> None:
        original = (FIXTURES / task.fixture / spec.written_by_producer).read_text(encoding="utf-8")
        changed = {arm: read_integrated(all_arms, arm, spec.written_by_producer) for arm in ARMS}
        assert len(set(changed.values())) == 1, "the producer's file differed between arms"
        assert changed["C0"] != original, "the producer never changed the shared interface"

    async def test_the_isolated_arm_keeps_the_stale_form(self, spec: Spec, all_arms: dict) -> None:
        assert spec.stale_marker in read_integrated(all_arms, "C0", spec.stale_file)
        assert spec.fresh_marker not in read_integrated(all_arms, "C0", spec.fresh_file)

    @pytest.mark.parametrize("arm", ["C1", "C2", "C3"])
    async def test_the_informed_arms_follow_the_change(
        self, spec: Spec, all_arms: dict, arm: str
    ) -> None:
        assert spec.fresh_marker in read_integrated(all_arms, arm, spec.fresh_file)
        assert spec.stale_marker not in read_integrated(all_arms, arm, spec.stale_file)

    async def test_the_stale_consumer_fails_for_the_designed_reason(
        self, spec: Spec, all_arms: dict
    ) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/"],
            cwd=integrated(all_arms, "C0"),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env={"PYTHONDONTWRITEBYTECODE": "1", **_inherited_env()},
        )
        assert completed.returncode != 0
        assert spec.stale_error in completed.stdout, completed.stdout[-600:]

    async def test_the_difference_comes_from_being_informed(
        self, spec: Spec, all_arms: dict
    ) -> None:
        # The mechanism, not just the outcome: each dependent knew about the
        # producer's change in the informed arms and did not in C0.
        for agent_id in spec.dependents:
            assert all_arms["C0"].agent_summaries[agent_id]["informed_paths"] == []
            for arm in ("C1", "C2", "C3"):
                informed = all_arms[arm].agent_summaries[agent_id]["informed_paths"]
                assert spec.written_by_producer in informed, f"{arm}: {agent_id} was never told"

    async def test_the_uninformed_agents_record_why_they_did_not_follow(
        self, spec: Spec, all_arms: dict
    ) -> None:
        # §52: inaction is evidence. Each dependent skipped exactly the
        # informed branch of its write, and the reason is on the record.
        for agent_id in spec.dependents:
            skipped = all_arms["C0"].agent_summaries[agent_id]["skipped_actions"]
            assert any(
                f"not informed about {spec.written_by_producer}" in s["reason"] for s in skipped
            ), f"{agent_id}: {skipped}"


class TestEvidence:
    async def test_every_arm_produces_a_verifiable_chain(self, spec: Spec, all_arms: dict) -> None:
        for arm in ARMS:
            result = all_arms[arm]
            agents = {r["event"]["identity"]["agent_id"] for r in result.records}
            ring = PublicKeyRing.from_keypairs({a: KeyPair.derive(SEED, a) for a in agents})
            report = verify_chain(result.records, ring)
            assert report.valid, f"{arm}: {report.summary()}"
            assert result.head_hash

    async def test_every_agent_appears_on_the_chain(self, spec: Spec, all_arms: dict) -> None:
        for arm in ARMS:
            on_chain = {r["event"]["identity"]["agent_id"] for r in all_arms[arm].records}
            assert spec.agents <= on_chain, f"{arm}: {sorted(spec.agents - on_chain)} never acted"

    async def test_every_run_records_the_task_hash(
        self, task: TaskDefinition, all_arms: dict
    ) -> None:
        for arm in ARMS:
            assert all_arms[arm].task_hash == task.content_hash()

    async def test_the_acceptance_decision_tracks_the_outcome(self, all_arms: dict) -> None:
        for arm in ARMS:
            result = all_arms[arm]
            expected = "ACCEPT" if result.outcome.succeeded else "REJECT"
            assert result.decision.verdict == expected
        assert all_arms["C0"].decision.verdict == "REJECT"
        assert all_arms["C2"].decision.verdict == "ACCEPT"

    async def test_c3_holds_a_lease_on_every_owned_path_and_refuses_none(
        self, task: TaskDefinition, all_arms: dict
    ) -> None:
        held = {c["path"] for c in all_arms["C3"].claim_history}
        assert held == {path for role in task.roles for path in role.owns}
        assert all_arms["C3"].denials == []


class TestQualityGate:
    async def test_the_task_is_demonstrably_coordination_sensitive(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        """§37, run for real: C0 versus C2, information alone."""
        report = await check_sensitivity(
            task,
            workspace_root=tmp_path / "gate",
            fixtures_root=FIXTURES,
            master_seed=SEED,
            repetitions=1,
        )
        assert report.sensitive, report.detail
        assert report.isolated_successes == 0
        assert report.informed_successes == 1
        assert report.isolated_divergences == 1
        assert report.informed_divergences == 0


class TestProfilesAreUnchanged:
    """Adding these tasks must not silently resize an existing collection."""

    runner = CliRunner()

    def _plan(self, profile: str) -> dict:
        import json

        result = self.runner.invoke(
            app, ["experiment", "plan", "--profile", profile, "--root", str(REPO), "--json"]
        )
        assert result.exit_code == 0, result.stdout
        return json.loads(result.stdout)

    @pytest.mark.parametrize("profile", ["smoke", "pilot", "small", "medium"])
    def test_no_profile_schedules_a_held_out_task(self, profile: str) -> None:
        planned = set(self._plan(profile)["tasks"])
        assert planned.isdisjoint(SPECS), planned

    def test_the_pilot_still_schedules_the_two_authored_tasks(self) -> None:
        plan = self._plan("pilot")
        assert set(plan["tasks"]) == {"concurrent_edit_collision", "schema_handler_widen"}
        assert plan["runs"] == 2 * 4 * 3

    def test_the_listing_says_which_tasks_are_held_out(self) -> None:
        import json

        result = self.runner.invoke(app, ["task", "list", "--root", str(REPO), "--json"])
        assert result.exit_code == 0, result.stdout
        listed = {entry["task_id"]: entry for entry in json.loads(result.stdout)}
        for task_id in SPECS:
            assert listed[task_id]["in_design"] is False
        assert listed["schema_handler_widen"]["in_design"] is True
