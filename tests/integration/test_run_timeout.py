"""Whole-run timeouts, end to end, with a deliberately hung scripted agent.

`RunState.TIMED_OUT` existed from the start and nothing ever assigned it.
These tests make a real run hang (real workspaces, real relay, real signed
chain) and check what the scheduler does about it: the state, the artifact,
what stays out of the signed chain, and that a timeout is never retried.

The hang is injected by wrapping `MockAgent.act`, so the run is genuinely
stuck inside agent code rather than faked at the `execute_task` boundary.
Three shapes, because they need three different answers: an agent stuck in
an `await`, an agent blocking its own thread, and an agent that is only
slow.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from causalmesh.agents import MockAgent
from causalmesh.crypto.keys import KeyPair, PublicKeyRing
from causalmesh.edges import edges_for_run
from causalmesh.experiments import derive_run_seed, plan_experiment, profile
from causalmesh.metrics import collect
from causalmesh.scheduler import ExperimentRunner, RunEnvironment, RunState
from causalmesh.tasks import TaskDefinition
from causalmesh.verifier import verify_chain

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
TASK_PATH = REPO / "tasks" / "schema_handler_widen.yaml"
FIXTURES = REPO / "fixtures"
SEED = b"causalmesh-run-timeout-seed-0001"

LIMIT = 0.5
GRACE = 0.2


@pytest.fixture(scope="module")
def task() -> TaskDefinition:
    return TaskDefinition.from_yaml(TASK_PATH)


def build_runner(task: TaskDefinition, root: Path, *, experiment_id: str = "exp_timeout", **kwargs):
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
    runner = ExperimentRunner(
        plan=plan,
        tasks={task.task_id: task},
        environment=environment,
        master_seed=SEED,
        **kwargs,
    )
    return runner, environment


def hang_agent_b(monkeypatch, *, mode: str, release: threading.Event | None = None) -> None:
    """Make agent_b hang once it has taken its first action.

    `async` waits on an awaitable and can be cancelled; `sync` blocks the
    thread it runs on; `slow` is neither, just too slow to finish in time.
    """
    original = MockAgent.act

    async def act(self, context):
        if self.agent_id == "agent_b" and len(self.turns) >= 1:
            if mode == "async":
                await asyncio.sleep(60)
            elif mode == "sync":
                assert release is not None
                release.wait(30)
            elif mode == "slow":
                time.sleep(0.3)
        return await original(self, context)

    monkeypatch.setattr(MockAgent, "act", act)


def read_artifact(environment: RunEnvironment, run_id: str) -> dict:
    return json.loads((environment.raw_root / run_id / "run.json").read_text(encoding="utf-8"))


def ring_for(chain: list[dict], run_id: str) -> PublicKeyRing:
    run_seed = derive_run_seed(SEED, run_id)
    agents = {r["event"]["identity"]["agent_id"] for r in chain}
    return PublicKeyRing.from_keypairs({agent: KeyPair.derive(run_seed, agent) for agent in agents})


class TestAHungAgentTimesTheRunOut:
    async def test_the_run_reaches_timed_out_not_failed(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        hang_agent_b(monkeypatch, mode="async")
        runner, environment = build_runner(
            task, tmp_path, run_timeout_s=LIMIT, timeout_grace_s=GRACE
        )
        runner.prepare()
        report = await runner.run(limit=1)

        assert report.timed_out == 1
        assert report.failed == 0
        assert report.completed == 0
        assert report.errors == []

        (record,) = runner.index.runs("exp_timeout", state=RunState.TIMED_OUT)
        assert record.state == RunState.TIMED_OUT
        # Unknown, not False: the run neither passed nor failed its task.
        assert record.succeeded is None
        assert record.task_hash == task.content_hash()
        assert record.artifact_path is not None
        states = [t["to_state"] for t in runner.index.transitions(record.run_id)]
        assert states[-2:] == [RunState.RUNNING, RunState.TIMED_OUT]
        runner.close()

    async def test_the_artifact_records_the_timeout_as_data(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        hang_agent_b(monkeypatch, mode="async")
        runner, environment = build_runner(
            task, tmp_path, run_timeout_s=LIMIT, timeout_grace_s=GRACE
        )
        runner.prepare()
        await runner.run(limit=1)
        (record,) = runner.index.runs("exp_timeout", state=RunState.TIMED_OUT)
        artifact = read_artifact(environment, record.run_id)

        assert artifact["state"] == RunState.TIMED_OUT
        assert artifact["timeout"]["limit_s"] == LIMIT
        assert artifact["timeout"]["detected_by"] in {"cancelled", "deadline_check"}
        assert artifact["timeout"]["thread_abandoned"] is False
        assert artifact["timeout"]["elapsed_s"] >= LIMIT
        # A run that was cut off has no outcome. A partial `result` block
        # would put a truncated run's costs beside completed ones in a mean.
        assert "result" not in artifact
        assert artifact["partial"]["chain_known"] is True
        assert artifact["partial"]["events"] == len(artifact["chain"])
        assert "no acceptance decision was made" in artifact["partial"]["note"]
        # Where a run is cut depends on the machine.
        assert artifact["reproducible"] is False
        runner.close()

    async def test_an_agent_that_never_returned_still_has_its_evidence_kept(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        hang_agent_b(monkeypatch, mode="async")
        runner, environment = build_runner(
            task, tmp_path, run_timeout_s=LIMIT, timeout_grace_s=GRACE
        )
        runner.prepare()
        await runner.run(limit=1)
        (record,) = runner.index.runs("exp_timeout", state=RunState.TIMED_OUT)
        artifact = read_artifact(environment, record.run_id)

        kinds = [
            (r["event"]["event_type"], r["event"]["identity"]["agent_id"])
            for r in artifact["chain"]
        ]
        # agent_b's first read and agent_a's write landed before b hung.
        assert ("READ", "agent_b") in kinds
        assert ("WRITE", "agent_a") in kinds
        assert ("WRITE", "agent_b") not in kinds
        # No acceptance decision: the run produced no outcome to decide on.
        assert all(kind != "ACCEPTANCE_DECIDED" for kind, _ in kinds)
        assert record.head_hash == artifact["chain"][-1]["chain_hash"]
        runner.close()


class TestTimingStaysOutOfTheSignedChain:
    async def test_the_chain_of_a_timed_out_run_is_a_prefix_of_the_full_run(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        """The reproducibility rule, applied to the watchdog.

        The same run, executed with no hang, produces a chain. The timed-out
        run's chain must be exactly the front of it: same events, same
        hashes, same signatures. If the watchdog wrote anything of its own
        into the chain, or anything wall-clock, this would not hold.
        """
        baseline, base_env = build_runner(task, tmp_path / "full", experiment_id="exp_prefix")
        baseline.prepare()
        await baseline.run(limit=1)
        (base_record,) = baseline.index.runs("exp_prefix", state=RunState.COMPLETED)
        full = read_artifact(base_env, base_record.run_id)["chain"]
        baseline.close()

        hang_agent_b(monkeypatch, mode="async")
        runner, environment = build_runner(
            task,
            tmp_path / "cut",
            experiment_id="exp_prefix",
            run_timeout_s=LIMIT,
            timeout_grace_s=GRACE,
        )
        runner.prepare()
        await runner.run(limit=1)
        (record,) = runner.index.runs("exp_prefix", state=RunState.TIMED_OUT)
        assert record.run_id == base_record.run_id  # same run, same seed
        cut = read_artifact(environment, record.run_id)["chain"]
        runner.close()

        assert 0 < len(cut) < len(full)
        assert cut == full[: len(cut)]

    async def test_no_wall_clock_or_watchdog_field_reaches_any_event(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        hang_agent_b(monkeypatch, mode="async")
        runner, environment = build_runner(
            task, tmp_path, run_timeout_s=LIMIT, timeout_grace_s=GRACE
        )
        runner.prepare()
        await runner.run(limit=1)
        (record,) = runner.index.runs("exp_timeout", state=RunState.TIMED_OUT)
        chain_text = json.dumps(read_artifact(environment, record.run_id)["chain"])
        for forbidden in ("timeout", "elapsed", "limit_s", "watchdog", "abandoned", "deadline"):
            assert forbidden not in chain_text
        runner.close()

    async def test_the_partial_chain_verifies_offline(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        """A prefix of a hash chain is a chain, so a cut-off run still verifies."""
        hang_agent_b(monkeypatch, mode="async")
        runner, environment = build_runner(
            task, tmp_path, run_timeout_s=LIMIT, timeout_grace_s=GRACE
        )
        runner.prepare()
        await runner.run(limit=1)
        (record,) = runner.index.runs("exp_timeout", state=RunState.TIMED_OUT)
        chain = read_artifact(environment, record.run_id)["chain"]
        report = verify_chain(chain, ring_for(chain, record.run_id))
        assert report.valid, report.summary()
        runner.close()

    async def test_a_completed_run_under_a_timeout_is_byte_identical_to_one_without(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        """Turning the watchdog on must not change a run that finishes in time."""
        plain, plain_env = build_runner(task, tmp_path / "plain", experiment_id="exp_same")
        plain.prepare()
        await plain.run(limit=1)
        guarded, guarded_env = build_runner(
            task, tmp_path / "guarded", experiment_id="exp_same", run_timeout_s=120
        )
        guarded.prepare()
        await guarded.run(limit=1)

        (a,) = plain.index.runs("exp_same", state=RunState.COMPLETED)
        (b,) = guarded.index.runs("exp_same", state=RunState.COMPLETED)
        assert a.run_id == b.run_id
        first = read_artifact(plain_env, a.run_id)
        second = read_artifact(guarded_env, b.run_id)
        assert first["chain"] == second["chain"]
        assert "timeout" not in second
        assert "partial" not in second
        assert a.head_hash == b.head_hash
        plain.close()
        guarded.close()


class TestATimeoutIsNotRetried:
    @pytest.mark.failure
    async def test_a_second_pass_leaves_the_timed_out_run_alone(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        hang_agent_b(monkeypatch, mode="async")
        runner, _ = build_runner(task, tmp_path, run_timeout_s=LIMIT, timeout_grace_s=GRACE)
        runner.prepare()
        await runner.run(limit=1)
        (timed_out,) = runner.index.runs("exp_timeout", state=RunState.TIMED_OUT)

        # Same collection, hang removed. The other three runs are still
        # planned and proceed; the timed-out one must not.
        monkeypatch.undo()
        again = await runner.run()
        assert again.executed == 3
        assert again.completed == 3
        after = runner.index.get(timed_out.run_id)
        assert after.state == RunState.TIMED_OUT
        assert after.attempts == 1
        assert runner.index.is_complete("exp_timeout")

        # And a fresh process over the same index agrees.
        runner.close()
        fresh, _ = build_runner(task, tmp_path)
        fresh.prepare()
        third = await fresh.run()
        assert third.executed == 0
        assert third.already_done == 4
        assert fresh.index.get(timed_out.run_id).state == RunState.TIMED_OUT
        fresh.close()

    async def test_the_collection_continues_past_a_timeout(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        """One hung run must not take the rest of the collection with it."""
        hang_agent_b(monkeypatch, mode="async")
        runner, _ = build_runner(task, tmp_path, run_timeout_s=LIMIT, timeout_grace_s=GRACE)
        runner.prepare()
        first = await runner.run(limit=1)
        assert first.timed_out == 1
        monkeypatch.undo()
        rest = await runner.run()
        assert rest.completed == 3
        counts = runner.index.counts("exp_timeout")
        assert counts[RunState.TIMED_OUT] == 1
        assert counts[RunState.COMPLETED] == 3
        runner.close()


class TestOtherHangShapes:
    async def test_an_agent_blocking_its_own_thread_is_abandoned_and_flagged(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        release = threading.Event()
        hang_agent_b(monkeypatch, mode="sync", release=release)
        runner, environment = build_runner(
            task, tmp_path, run_timeout_s=LIMIT, timeout_grace_s=GRACE
        )
        runner.prepare()
        started = time.monotonic()
        try:
            report = await runner.run(limit=1)
            elapsed = time.monotonic() - started
        finally:
            release.set()

        assert report.timed_out == 1
        assert report.threads_abandoned == 1
        assert report.to_dict()["threads_abandoned"] == 1
        # Bounded by the limit and two graces, not by the 30 seconds asked.
        assert elapsed < LIMIT + 2 * GRACE + 3.0

        (record,) = runner.index.runs("exp_timeout", state=RunState.TIMED_OUT)
        artifact = read_artifact(environment, record.run_id)
        assert artifact["timeout"]["thread_abandoned"] is True
        assert artifact["timeout"]["detected_by"] == "abandoned"
        # The run never returned control, so it could not summarise itself
        # and nothing is invented in its place. The chain was read from
        # outside.
        assert artifact["partial"]["agent_summaries"] == {}
        assert artifact["partial"]["chain_known"] is True
        assert len(artifact["chain"]) >= 1
        runner.close()

    async def test_a_slow_agent_unwinds_cleanly_and_keeps_its_summaries(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        hang_agent_b(monkeypatch, mode="slow")
        runner, environment = build_runner(task, tmp_path, run_timeout_s=0.2, timeout_grace_s=3.0)
        runner.prepare()
        report = await runner.run(limit=1)
        assert report.timed_out == 1
        assert report.threads_abandoned == 0

        (record,) = runner.index.runs("exp_timeout", state=RunState.TIMED_OUT)
        artifact = read_artifact(environment, record.run_id)
        assert artifact["timeout"]["detected_by"] == "deadline_check"
        assert artifact["timeout"]["thread_abandoned"] is False
        # It returned control at the between-turns check, so its agents can
        # still say what they did.
        assert set(artifact["partial"]["agent_summaries"]) == {"agent_a", "agent_b"}
        runner.close()


class TestReadersTolerateATimedOutArtifact:
    async def test_metrics_read_the_outcome_as_unknown(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        hang_agent_b(monkeypatch, mode="async")
        runner, environment = build_runner(
            task, tmp_path, run_timeout_s=LIMIT, timeout_grace_s=GRACE
        )
        runner.prepare()
        await runner.run(limit=1)
        (record,) = runner.index.runs("exp_timeout", state=RunState.TIMED_OUT)

        metrics = collect(environment.raw_root)
        run = next(
            r for arm in metrics.arms.values() for r in arm.runs if r.run_id == record.run_id
        )
        assert run.succeeded is None
        assert not run.outcome_known
        runner.close()

    async def test_the_edge_reader_reports_no_edges_rather_than_failing(
        self, task: TaskDefinition, tmp_path: Path, monkeypatch
    ) -> None:
        hang_agent_b(monkeypatch, mode="async")
        runner, environment = build_runner(
            task, tmp_path, run_timeout_s=LIMIT, timeout_grace_s=GRACE
        )
        runner.prepare()
        await runner.run(limit=1)
        (record,) = runner.index.runs("exp_timeout", state=RunState.TIMED_OUT)
        edges = edges_for_run(environment.raw_root / record.run_id)
        assert edges.edges == ()
        runner.close()
