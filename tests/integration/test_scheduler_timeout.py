"""The whole-run watchdog, against a deliberately hung mock agent.

A real run, real workspaces, a real pytest subprocess for the integration
check, and an agent that stops answering partway through. The claims under
test are the ones the backlog item ("Timeout as a distinct run state") made:
the run reaches TIMED_OUT, its partial evidence survives, the chain still
verifies, no wall-clock value reaches the signed chain, and the run is never
retried.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from causalmesh.agents import AgentContext, MockAgent
from causalmesh.cli._output import Exit
from causalmesh.cli.main import app
from causalmesh.crypto.keys import KeyPair, PublicKeyRing
from causalmesh.experiments import derive_run_seed, plan_experiment, profile
from causalmesh.scheduler import ExperimentRunner, RunEnvironment, RunState
from causalmesh.tasks import TaskDefinition
from causalmesh.tasks.runner import DEFAULT_MAX_TURNS, DEFAULT_TICK_US, RunConfig
from causalmesh.verifier import verify_chain

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REPO = Path(__file__).resolve().parents[2]
TASK_PATH = REPO / "tasks" / "schema_handler_widen.yaml"
FIXTURES = REPO / "fixtures"
SEED = b"causalmesh-scheduler-timeout-001"
HANG_FROM_TURN = 1


class HungAgent(MockAgent):
    """A mock agent that stops answering after its first turn.

    It hangs at a fixed turn, so where the run is cut is the same every time
    and the partial chain is reproducible, which is what lets one test
    compare two timed-out runs byte for byte.
    """

    async def act(self, context: AgentContext):
        if context.turn >= HANG_FROM_TURN:
            await asyncio.sleep(3600)
        return await super().act(context)


@pytest.fixture(scope="module")
def task() -> TaskDefinition:
    return TaskDefinition.from_yaml(TASK_PATH)


@pytest.fixture
def hung(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("causalmesh.tasks.runner.MockAgent", HungAgent)


def build_runner(task: TaskDefinition, root: Path, **kwargs) -> ExperimentRunner:
    plan = plan_experiment(
        experiment_id="exp_timeout",
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
    return ExperimentRunner(
        plan=plan,
        tasks={task.task_id: task},
        environment=environment,
        master_seed=SEED,
        **kwargs,
    )


async def run_one_hung(task: TaskDefinition, root: Path, **kwargs):
    runner = build_runner(task, root, run_timeout_s=1.0, **kwargs)
    runner.prepare()
    report = await runner.run(limit=1)
    record = next(r for r in runner.index.runs("exp_timeout") if r.state == RunState.TIMED_OUT)
    artifact = json.loads(
        (runner.environment.raw_root / record.run_id / "run.json").read_text(encoding="utf-8")
    )
    return runner, report, record, artifact


def verify_artifact(artifact: dict, run_id: str):
    chain = artifact["chain"]
    run_seed = derive_run_seed(SEED, run_id)
    agents = {r["event"]["identity"]["agent_id"] for r in chain}
    ring = PublicKeyRing.from_keypairs({agent: KeyPair.derive(run_seed, agent) for agent in agents})
    return verify_chain(chain, ring)


@pytest.fixture
async def timed_out(task: TaskDefinition, hung, tmp_path: Path):
    runner, report, record, artifact = await run_one_hung(task, tmp_path)
    yield {"runner": runner, "report": report, "record": record, "artifact": artifact}
    runner.close()


class TestTimedOutRun:
    async def test_a_hung_run_reaches_timed_out(self, timed_out: dict) -> None:
        assert timed_out["record"].state == RunState.TIMED_OUT
        assert timed_out["report"].timed_out == 1
        assert timed_out["report"].completed == 0
        assert timed_out["report"].failed == 0

    async def test_the_task_outcome_is_unknown_not_failed(self, timed_out: dict) -> None:
        # The agents never finished, so nobody measured whether they would
        # have succeeded. False would put a timeout in the failure column.
        assert timed_out["record"].succeeded is None
        result = timed_out["artifact"]["result"]
        assert result["outcome"] is None
        assert result["partial_outcome"] is not None
        assert result["interrupted"] is True

    async def test_the_index_says_why(self, timed_out: dict) -> None:
        assert "wall-clock budget" in (timed_out["record"].error or "")
        notes = [
            t["note"] for t in timed_out["runner"].index.transitions(timed_out["record"].run_id)
        ]
        assert any("partial evidence kept" in note for note in notes)

    async def test_the_timeout_is_reported_as_an_error_entry(self, timed_out: dict) -> None:
        assert [e["run_id"] for e in timed_out["report"].errors] == [timed_out["record"].run_id]

    async def test_the_artifact_is_marked_timed_out_and_not_reproducible(
        self, timed_out: dict
    ) -> None:
        artifact = timed_out["artifact"]
        assert artifact["state"] == RunState.TIMED_OUT
        assert artifact["reproducible"] is False

    async def test_a_timed_out_run_is_never_retried(self, timed_out: dict) -> None:
        """§81: retrying until a run fits the budget selects on the outcome."""
        index = timed_out["runner"].index
        run_id = timed_out["record"].run_id
        assert index.abandon_running("exp_timeout", now_us=1) == 0
        claimed = set()
        while (record := index.claim_next("exp_timeout", now_us=2)) is not None:
            claimed.add(record.run_id)
        assert run_id not in claimed
        assert index.get(run_id).state == RunState.TIMED_OUT
        assert index.get(run_id).attempts == 1

    async def test_a_resumed_collection_counts_it_as_done(
        self, task: TaskDefinition, timed_out: dict, tmp_path: Path
    ) -> None:
        runner = timed_out["runner"]
        before = runner.index.counts("exp_timeout")
        assert before[RunState.TIMED_OUT] == 1
        runner.prepare()
        assert runner.index.counts("exp_timeout")[RunState.TIMED_OUT] == 1


class TestPartialEvidence:
    async def test_the_partial_chain_is_preserved(self, timed_out: dict) -> None:
        artifact = timed_out["artifact"]
        assert artifact["chain"], "a timed-out run must keep the events it got through"
        # Turn 0 ran before the hang, so agents acted: more than the lone
        # acceptance event a run with no work would leave.
        assert len(artifact["chain"]) > 1
        assert artifact["result"]["events"] == len(artifact["chain"])
        assert artifact["result"]["head_hash"] == timed_out["record"].head_hash

    async def test_the_partial_chain_verifies_offline(self, timed_out: dict) -> None:
        report = verify_artifact(timed_out["artifact"], timed_out["record"].run_id)
        assert report.valid, report.summary()

    async def test_the_chain_records_that_the_run_was_not_accepted_and_why(
        self, timed_out: dict
    ) -> None:
        decisions = [
            r["event"]["payload"]
            for r in timed_out["artifact"]["chain"]
            if r["event"]["event_type"] == "ACCEPTANCE_DECIDED"
        ]
        assert len(decisions) == 1
        assert decisions[0]["verdict"] == "REJECT"
        assert "run_interrupted_before_completion" in decisions[0]["evidence"]

    async def test_the_agents_partial_workspaces_are_kept(self, timed_out: dict) -> None:
        digests = timed_out["artifact"]["result"]["workspace_digests"]
        assert digests
        assert all(files for files in digests.values())


class TestNothingNonReproducibleInTheChain:
    async def test_no_wall_clock_value_is_in_the_signed_chain(self, timed_out: dict) -> None:
        defaults = RunConfig(experiment_id="e", run_id="r", arm="C0", master_seed=SEED)
        low = defaults.base_time_us
        high = low + (DEFAULT_MAX_TURNS + 1) * DEFAULT_TICK_US
        for record in timed_out["artifact"]["chain"]:
            assert low <= record["event"]["timestamp_us"] <= high, (
                "an event timestamp outside the simulated clock's range means a real "
                "clock reached the signed chain"
            )

    async def test_the_budget_and_elapsed_time_live_in_the_envelope_only(
        self, timed_out: dict
    ) -> None:
        artifact = timed_out["artifact"]
        watchdog = artifact["envelope"]["watchdog"]
        assert watchdog["budget_s"] == 1.0
        assert watchdog["elapsed_s"] is not None
        assert watchdog["grace_expired"] is False
        chain_text = json.dumps(artifact["chain"])
        for name in ("budget_s", "elapsed_s", "watchdog", "timed_out", "TimeoutError"):
            assert name not in chain_text

    async def test_the_same_hang_leaves_the_same_chain(
        self, task: TaskDefinition, hung, timed_out: dict, tmp_path: Path
    ) -> None:
        """Two timeouts of the same run, on different machines' worth of clock.

        The hang is at a fixed turn, so the cut is deterministic here, and the
        only things that differ between the two runs are the wall-clock
        values that must not matter.
        """
        runner, _, record, artifact = await run_one_hung(task, tmp_path / "again")
        try:
            assert record.run_id == timed_out["record"].run_id
            assert artifact["result"]["head_hash"] == timed_out["artifact"]["result"]["head_hash"]
            assert [r["chain_hash"] for r in artifact["chain"]] == [
                r["chain_hash"] for r in timed_out["artifact"]["chain"]
            ]
        finally:
            runner.close()


class TestDefaultsAreUnchanged:
    async def test_no_timeout_is_configured_by_default(self, task: TaskDefinition, tmp_path: Path):
        with build_runner(task, tmp_path) as runner:
            assert runner.run_timeout_s is None

    async def test_a_hung_agent_without_a_budget_is_not_interrupted_by_the_scheduler(
        self, task: TaskDefinition, hung, tmp_path: Path
    ) -> None:
        """The watchdog is opt-in: with no budget nothing else cancels the run.

        Bounded here by the test's own timeout so the assertion is that the
        run is still in flight, not that it finished.
        """
        with build_runner(task, tmp_path) as runner:
            runner.prepare()
            running = asyncio.ensure_future(runner.run(limit=1))
            done, _ = await asyncio.wait({running}, timeout=3.0)
            assert not done, "a run with no budget must not be cut short"
            running.cancel()
            await asyncio.wait({running})
            assert runner.index.counts("exp_timeout")[RunState.TIMED_OUT] == 0


class TestUncooperativeRun:
    @pytest.mark.failure
    async def test_a_run_that_ignores_cancellation_is_timed_out_without_evidence(
        self, task: TaskDefinition, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        release = asyncio.Event()

        class StubbornAgent(MockAgent):
            async def act(self, context: AgentContext):
                if context.turn >= HANG_FROM_TURN:
                    while not release.is_set():
                        try:
                            await release.wait()
                        except asyncio.CancelledError:
                            continue
                    raise RuntimeError("released after the test")
                return await super().act(context)

        monkeypatch.setattr("causalmesh.tasks.runner.MockAgent", StubbornAgent)
        runner = build_runner(task, tmp_path, run_timeout_s=0.5, timeout_grace_s=0.5)
        try:
            runner.prepare()
            report = await runner.run(limit=1)
            record = next(r for r in runner.index.runs("exp_timeout") if r.is_terminal)
            assert record.state == RunState.TIMED_OUT
            assert report.timed_out == 1
            artifact = json.loads(
                (runner.environment.raw_root / record.run_id / "run.json").read_text(
                    encoding="utf-8"
                )
            )
            # No chain could be sealed, and the artifact says so rather than
            # carrying an empty one that would read as "a run with no events".
            assert "chain" not in artifact
            assert "none:" in artifact["evidence"]
            assert artifact["envelope"]["watchdog"]["grace_expired"] is True
            assert record.succeeded is None
            assert record.head_hash is None
        finally:
            release.set()
            await asyncio.sleep(0.2)
            runner.close()


class TestCli:
    """`causalmesh experiment run --run-timeout`: opt-in, and visible in the report."""

    def _cleanup(self, experiment_id: str) -> None:
        shutil.rmtree(REPO / "data" / "raw" / experiment_id, ignore_errors=True)
        shutil.rmtree(REPO / "data" / "work" / experiment_id, ignore_errors=True)

    @pytest.mark.parametrize("bad", ["0", "-3"])
    def test_a_non_positive_budget_is_a_usage_error(self, bad: str) -> None:
        result = CliRunner().invoke(
            app,
            ["experiment", "run", "--run-timeout", bad, "--root", str(REPO), "--id", "exp_cli_bad"],
        )
        assert result.exit_code == Exit.USAGE, result.stdout
        assert not (REPO / "data" / "raw" / "exp_cli_bad").exists()

    def test_the_flag_reaches_the_watchdog_and_the_report_counts_the_timeout(
        self, hung: None
    ) -> None:
        experiment_id = "exp_cli_timeout"
        self._cleanup(experiment_id)
        try:
            result = CliRunner().invoke(
                app,
                [
                    "experiment",
                    "run",
                    "--profile",
                    "smoke",
                    "--id",
                    experiment_id,
                    "--limit",
                    "1",
                    "--run-timeout",
                    "1",
                    "--no-contract",
                    "--root",
                    str(REPO),
                    "--json",
                ],
            )
            report = json.loads(result.stdout)
            assert report["timed_out"] == 1
            assert report["executed"] == 1
            assert report["completed"] == 0
            assert any("wall-clock budget" in e["error"] for e in report["errors"])
            run_dirs = list((REPO / "data" / "raw" / experiment_id).glob("*_r0000"))
            assert len(run_dirs) == 1
            artifact = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
            assert artifact["state"] == RunState.TIMED_OUT
        finally:
            self._cleanup(experiment_id)
