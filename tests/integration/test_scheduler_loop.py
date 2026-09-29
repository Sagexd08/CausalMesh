"""The experiment loop, executed for real (spec §79, §80, §81).

Every test here runs actual runs: real workspaces, real agents, real
pytest subprocesses, real artifacts on disk. §91 requires a step to be
exercised rather than asserted, and a scheduler is precisely the kind of
component that looks correct while quietly losing work.

The smoke profile is used throughout — one task, four arms, one repetition
— because that is the smallest collection that still contains every arm.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from causalmesh.experiments import plan_experiment, profile
from causalmesh.scheduler import ExperimentRunner, RunEnvironment, RunState
from causalmesh.storage import RunIndex
from causalmesh.tasks import TaskDefinition
from causalmesh.verifier import verify_chain

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REPO = Path(__file__).resolve().parents[2]
TASK_PATH = REPO / "tasks" / "schema_handler_widen.yaml"
FIXTURES = REPO / "fixtures"
SEED = b"causalmesh-scheduler-loop-seed01"


@pytest.fixture(scope="module")
def task() -> TaskDefinition:
    return TaskDefinition.from_yaml(TASK_PATH)


def build_runner(task: TaskDefinition, root: Path, *, experiment_id: str = "exp_loop"):
    plan = plan_experiment(
        experiment_id=experiment_id,
        profile=profile("smoke"),
        task_ids=[task.task_id],
        master_seed=SEED,
        task_hashes={task.task_id: task.content_hash()},
    )
    environment = RunEnvironment(
        fixtures_root=FIXTURES,
        raw_root=root / "raw",
        workspace_root=root / "work",
        index_path=root / "raw" / "index.db",
    )
    return (
        ExperimentRunner(
            plan=plan,
            tasks={task.task_id: task},
            environment=environment,
            master_seed=SEED,
        ),
        plan,
        environment,
    )


@pytest.fixture(scope="module")
async def executed(task: TaskDefinition, tmp_path_factory):
    """One full smoke collection, shared across the read-only tests.

    Module-scoped for the same reason as `test_task_execution.py`: each run
    spawns a real pytest subprocess, so a function-scoped fixture would
    execute the collection once per test. Tests that need their own
    collection (resume, idempotency) build one.
    """
    root = tmp_path_factory.mktemp("loop")
    runner, plan, environment = build_runner(task, root)
    runner.prepare()
    report = await runner.run()
    yield {
        "environment": environment,
        "plan": plan,
        "report": report,
        "root": root,
        "runner": runner,
    }
    runner.close()


class TestExecution:
    async def test_every_planned_run_executes(self, executed: dict) -> None:
        report = executed["report"]
        assert report.planned == 4  # 1 task x 4 arms x 1 repetition
        assert report.executed == 4
        assert report.is_complete

    async def test_every_run_reaches_a_terminal_state(self, executed: dict) -> None:
        """§81: no run may be silently skipped.

        A collection that quietly ran fewer runs than it planned would
        produce a smaller denominator with nothing recording the gap.
        """
        index = executed["runner"].index
        counts = index.counts("exp_loop")
        assert counts[RunState.COMPLETED] == 4
        assert counts[RunState.PLANNED] == 0
        assert counts[RunState.RUNNING] == 0
        assert index.is_complete("exp_loop")

    async def test_all_four_arms_ran(self, executed: dict) -> None:
        records = executed["runner"].index.runs("exp_loop")
        assert sorted(r.arm for r in records) == ["C0", "C1", "C2", "C3"]

    async def test_the_arms_separate_as_the_task_predicts(self, executed: dict) -> None:
        """The experiment actually measuring something, through the loop.

        Not a duplicate of the task-level test: this asserts the scheduler
        preserved the arm assignment end to end. A loop that mislabelled
        runs would produce a perfectly balanced, entirely wrong dataset.
        """
        by_arm = {r.arm: r for r in executed["runner"].index.runs("exp_loop")}
        assert by_arm["C0"].succeeded is False
        for arm in ("C1", "C2", "C3"):
            assert by_arm[arm].succeeded is True, f"{arm} failed unexpectedly"


class TestEvidence:
    async def test_every_run_writes_an_artifact(self, executed: dict) -> None:
        raw = executed["environment"].raw_root
        for record in executed["runner"].index.runs("exp_loop"):
            artifact = raw / record.run_id / "run.json"
            assert artifact.is_file(), f"no artifact for {record.run_id}"

    async def test_the_artifact_carries_the_whole_chain(self, executed: dict) -> None:
        # An artifact that summarised the chain would leave the verifier
        # nothing to verify.
        raw = executed["environment"].raw_root
        record = executed["runner"].index.runs("exp_loop")[0]
        payload = json.loads((raw / record.run_id / "run.json").read_text(encoding="utf-8"))
        assert payload["chain"]
        assert payload["result"]["outcome"]
        assert payload["arm"] == record.arm

    async def test_every_chain_verifies_offline_from_its_artifact(self, executed: dict) -> None:
        """§26: the evidence must stand on its own, read back from disk.

        Verifying the in-memory result would prove only that the relay
        agrees with itself. This reads the persisted JSON and rebuilds the
        key ring from the run's derived seed, which is what an external
        auditor would have to do.
        """
        from causalmesh.crypto.keys import KeyPair, PublicKeyRing
        from causalmesh.experiments import derive_run_seed

        raw = executed["environment"].raw_root
        for record in executed["runner"].index.runs("exp_loop"):
            payload = json.loads((raw / record.run_id / "run.json").read_text(encoding="utf-8"))
            chain = payload["chain"]
            if not chain:
                continue
            run_seed = derive_run_seed(SEED, record.run_id)
            agents = {r["event"]["identity"]["agent_id"] for r in chain}
            ring = PublicKeyRing.from_keypairs(
                {agent: KeyPair.derive(run_seed, agent) for agent in agents}
            )
            report = verify_chain(chain, ring)
            assert report.valid, f"{record.run_id}: {report.summary()}"

    async def test_the_index_records_the_task_hash(self, executed: dict, task) -> None:
        # §33: results can only be pooled across runs of the same task.
        for record in executed["runner"].index.runs("exp_loop"):
            assert record.task_hash == task.content_hash()

    async def test_an_existing_artifact_is_never_overwritten(self, executed: dict) -> None:
        """§31: raw evidence is immutable.

        A second execution under the same run id must fail loudly rather
        than replace the first run's evidence, leaving no trace that two
        executions ever happened.
        """
        runner = executed["runner"]
        record = runner.index.runs("exp_loop")[0]
        with pytest.raises(FileExistsError, match="immutable"):
            runner._write_artifact(executed["environment"].raw_root / record.run_id, {"x": 1})


class TestIdempotency:
    async def test_rerunning_a_finished_collection_executes_nothing(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        """§42. The second call must be a no-op, not a re-collection."""
        runner, _, _ = build_runner(task, tmp_path, experiment_id="exp_idem")
        runner.prepare()
        first = await runner.run()
        assert first.executed == 4

        second = await runner.run()
        assert second.executed == 0
        assert second.already_done == 4
        assert second.is_complete
        runner.close()

    async def test_repreparing_does_not_reset_progress(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        runner, _, _ = build_runner(task, tmp_path, experiment_id="exp_reprep")
        runner.prepare()
        await runner.run(limit=1)
        completed_before = runner.index.counts("exp_reprep")[RunState.COMPLETED]

        assert runner.prepare() == 0
        assert runner.index.counts("exp_reprep")[RunState.COMPLETED] == completed_before
        runner.close()


class TestResume:
    async def test_a_partial_collection_finishes_on_a_second_call(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        runner, _, _ = build_runner(task, tmp_path, experiment_id="exp_partial")
        runner.prepare()
        first = await runner.run(limit=2)
        assert first.executed == 2
        assert not first.is_complete

        second = await runner.run()
        assert second.executed == 2
        assert runner.index.is_complete("exp_partial")
        runner.close()

    @pytest.mark.failure
    async def test_a_crashed_run_is_recovered_and_re_executed(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        """The crash-recovery path, simulated honestly.

        A killed process leaves a run RUNNING with no verdict. Since
        `claim_next` skips RUNNING, without recovery that run would be
        stranded and the collection could never complete. The run is left
        RUNNING here exactly as a kill would leave it, and a fresh runner
        — a new process, in effect — must pick it up.
        """
        runner, _plan, _environment = build_runner(task, tmp_path, experiment_id="exp_crash")
        runner.prepare()
        await runner.run(limit=2)
        stranded = runner.index.claim_next("exp_crash", now_us=1)
        assert stranded is not None
        assert stranded.state == RunState.RUNNING
        runner.close()

        # A new process opens the same index.
        resumed, _, _ = build_runner(task, tmp_path, experiment_id="exp_crash")
        resumed.prepare()
        assert resumed.index.get(stranded.run_id).state == RunState.ABANDONED

        report = await resumed.run()
        assert report.resumed >= 1
        assert resumed.index.is_complete("exp_crash")
        assert resumed.index.get(stranded.run_id).state == RunState.COMPLETED
        resumed.close()

    @pytest.mark.failure
    async def test_a_resumed_run_is_visible_as_resumed(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        # §80: a resumed run must not be indistinguishable from a clean one.
        runner, _, _ = build_runner(task, tmp_path, experiment_id="exp_visible")
        runner.prepare()
        await runner.run(limit=1)
        stranded = runner.index.claim_next("exp_visible", now_us=1)
        runner.close()

        resumed, _, _ = build_runner(task, tmp_path, experiment_id="exp_visible")
        resumed.prepare()
        await resumed.run()
        transitions = resumed.index.transitions(stranded.run_id)
        assert any(t["to_state"] == RunState.ABANDONED for t in transitions)
        assert resumed.index.get(stranded.run_id).attempts == 2
        resumed.close()


class TestFailureHandling:
    @pytest.mark.failure
    async def test_a_harness_crash_becomes_a_recorded_failure(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        """§81: a failed run is evidence, not garbage.

        The crash is injected into `execute_task` so the failure is a real
        exception escaping the runner, not a mocked return value.
        """
        import causalmesh.scheduler.loop as loop_module

        async def explode(*args, **kwargs):
            raise RuntimeError("injected harness failure")

        runner, _, _environment = build_runner(task, tmp_path, experiment_id="exp_boom")
        monkeypatch.setattr(loop_module, "execute_task", explode)
        runner.prepare()
        report = await runner.run()

        assert report.executed == 4
        assert report.failed == 4
        assert report.completed == 0
        assert runner.index.counts("exp_boom")[RunState.FAILED] == 4
        runner.close()

    @pytest.mark.failure
    async def test_a_failed_run_still_writes_an_artifact(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        import causalmesh.scheduler.loop as loop_module

        async def explode(*args, **kwargs):
            raise RuntimeError("injected harness failure")

        runner, _, environment = build_runner(task, tmp_path, experiment_id="exp_eviden")
        monkeypatch.setattr(loop_module, "execute_task", explode)
        runner.prepare()
        await runner.run()

        for record in runner.index.runs("exp_eviden"):
            artifact = environment.raw_root / record.run_id / "run.json"
            assert artifact.is_file()
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            # The traceback, so the failure is diagnosable rather than
            # reduced to a class name.
            assert "injected harness failure" in payload["traceback"]
            assert payload["state"] == RunState.FAILED
        runner.close()

    @pytest.mark.failure
    async def test_a_failed_run_is_not_retried(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        """Retrying until a run passes would select on the outcome."""
        import causalmesh.scheduler.loop as loop_module

        async def explode(*args, **kwargs):
            raise RuntimeError("injected harness failure")

        runner, _, _ = build_runner(task, tmp_path, experiment_id="exp_noretry")
        monkeypatch.setattr(loop_module, "execute_task", explode)
        runner.prepare()
        await runner.run()

        # A second pass, now with the crash removed: a scheduler that
        # retried failures would happily re-execute all four.
        monkeypatch.undo()
        again = await runner.run()
        assert again.executed == 0
        assert runner.index.counts("exp_noretry")[RunState.FAILED] == 4
        runner.close()

    @pytest.mark.failure
    async def test_a_failure_leaves_no_run_stranded(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        import causalmesh.scheduler.loop as loop_module

        async def explode(*args, **kwargs):
            raise RuntimeError("injected harness failure")

        runner, _, _ = build_runner(task, tmp_path, experiment_id="exp_strand")
        monkeypatch.setattr(loop_module, "execute_task", explode)
        runner.prepare()
        await runner.run()
        assert runner.index.counts("exp_strand")[RunState.RUNNING] == 0
        assert runner.index.is_complete("exp_strand")
        runner.close()


class TestGuards:
    async def test_a_plan_naming_a_missing_task_is_refused(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        """A missing task would produce an unbalanced design silently."""
        plan = plan_experiment(
            experiment_id="exp_missing",
            profile=profile("smoke"),
            task_ids=["not_a_real_task"],
            master_seed=SEED,
        )
        with pytest.raises(ValueError, match="not supplied"):
            ExperimentRunner(
                plan=plan,
                tasks={task.task_id: task},
                environment=RunEnvironment.under(tmp_path, experiment_id="exp_missing"),
                master_seed=SEED,
            )

    async def test_status_is_read_from_the_index_not_remembered(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        """An in-memory cursor would be lost in the crash it must survive."""
        runner, _, _ = build_runner(task, tmp_path, experiment_id="exp_status")
        runner.prepare()
        await runner.run(limit=1)
        runner.close()

        fresh, _, _ = build_runner(task, tmp_path, experiment_id="exp_status")
        status = fresh.status()
        assert status["counts"][RunState.COMPLETED] == 1
        assert not status["complete"]
        fresh.close()

    async def test_each_run_gets_its_own_derived_seed(self, executed: dict) -> None:
        """§40: a run must be re-executable on its own.

        Sharing one seed across the collection would make two runs of the
        same task under the same arm byte-identical by construction,
        hiding any nondeterminism the harness had introduced.
        """
        from causalmesh.experiments import derive_run_seed

        seeds = {
            record.run_id: derive_run_seed(SEED, record.run_id)
            for record in executed["runner"].index.runs("exp_loop")
        }
        assert len(set(seeds.values())) == len(seeds)


class TestDeterminism:
    async def test_two_collections_with_the_same_seed_agree(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        """§84: same seed, same config, structurally equivalent chains.

        Head hashes are compared per run id rather than as a set, so a
        collection that produced the right hashes attached to the wrong
        runs would still fail.
        """
        first, _, _ = build_runner(task, tmp_path / "a", experiment_id="exp_det")
        first.prepare()
        await first.run()
        first_heads = {r.run_id: r.head_hash for r in first.index.runs("exp_det")}
        first.close()

        second, _, _ = build_runner(task, tmp_path / "b", experiment_id="exp_det")
        second.prepare()
        await second.run()
        second_heads = {r.run_id: r.head_hash for r in second.index.runs("exp_det")}
        second.close()

        assert first_heads == second_heads

    async def test_the_plan_hash_is_stable_across_processes(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        runner, plan, _ = build_runner(task, tmp_path, experiment_id="exp_hash")
        runner.prepare()
        stored = runner.index.plan_hash("exp_hash")
        runner.close()

        with RunIndex(tmp_path / "raw" / "index.db") as reopened:
            assert reopened.plan_hash("exp_hash") == stored == plan.content_hash()


class TestWorkspaceLayout:
    """Where a run's files go, which decides whether a checkout can hold them.

    `execute_task` already namespaces everything by run id (`<run_id>/<agent>`,
    `<run_id>_integrated`, `<run_id>_claims.db`). The scheduler used to hand it a
    base that already ended in the run id, so the id was in the path twice and a
    checkout at an ordinary Windows location overflowed MAX_PATH.
    """

    async def test_each_run_is_one_directory_of_agents_not_a_directory_of_itself(
        self, executed: dict
    ) -> None:
        work = executed["environment"].workspace_root
        for record in executed["runner"].index.runs("exp_loop"):
            run_dir = work / record.run_id
            assert (run_dir / "agent_a").is_dir()
            assert not (run_dir / record.run_id).exists(), "the run id is nested twice"

    async def test_no_path_in_the_workspace_tree_repeats_a_run_id(self, executed: dict) -> None:
        work = executed["environment"].workspace_root
        for path in work.rglob("*"):
            parts = path.relative_to(work).parts
            named = [part for part in parts if part.startswith("exp_loop__")]
            assert len(named) == len(set(named)) <= 1, path

    async def test_the_run_siblings_sit_beside_the_workspaces(self, executed: dict) -> None:
        work = executed["environment"].workspace_root
        for record in executed["runner"].index.runs("exp_loop"):
            assert (work / f"{record.run_id}_integrated").is_dir()


@pytest.mark.skipif(sys.platform != "win32", reason="MAX_PATH is a Windows limit")
class TestADeepCheckout:
    async def test_a_checkout_deep_enough_to_have_broken_the_old_layout_still_runs(
        self, task: TaskDefinition, executed: dict, tmp_path_factory
    ) -> None:
        """The regression: the same collection, run where the old layout overflowed.

        The root is padded so the deepest path the new layout makes is about 235
        characters, which is under MAX_PATH and over what a run id nested a
        second time would need. That arithmetic is asserted, so this cannot pass
        by being shallow.
        """
        work = executed["environment"].workspace_root
        # The padding below is sized from this collection's deepest path, so the
        # collection must have the right layout first. Sized from one that nests
        # the run id twice, the padding shrinks to match and the test would pass
        # on the very regression it exists to catch.
        for record in executed["runner"].index.runs("exp_loop"):
            assert not (work / record.run_id / record.run_id).exists(), "the run id is nested twice"
        deepest_relative = max(len(p.relative_to(work).as_posix()) for p in work.rglob("*"))
        run_id_length = max(len(r.run_id) for r in executed["runner"].index.runs("exp_loop"))

        base = tmp_path_factory.mktemp("deep")
        target = 235
        padding = target - (len(str(base)) + len("/x/work/") + deepest_relative)
        assert padding > 0, "the temp directory is already too deep to build this test"
        root = base / ("x" * padding)
        runner, _, environment = build_runner(task, root)
        try:
            runner.prepare()
            report = await runner.run()
            assert report.is_complete and report.executed == 4
            states = [r.state for r in runner.index.runs("exp_loop")]
            assert states == [RunState.COMPLETED] * 4, states

            deepest = max(len(str(p)) for p in environment.workspace_root.rglob("*"))
            assert 215 <= deepest <= 259, deepest
            assert deepest + run_id_length + 1 > 259, (
                "the old layout would have fitted here as well, so this proves nothing"
            )
            for run_dir in environment.raw_root.glob("exp_loop__*"):
                document = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
                assert document["chain"], "a completed run must carry its chain"
        finally:
            runner.close()
