"""The whole-run watchdog and its cooperative deadline (`docs/backlog.md`,
"Timeout as a distinct run state").

These tests use hung work of each shape a run can hang in, because the
watchdog's whole job is the case where the run cannot help:

- an agent stuck in an `await` (cancellable);
- an agent blocking its own thread (`time.sleep`, a native call), which no
  timer scheduled on that thread could ever interrupt;
- an agent slow but not hung, which should unwind cleanly on its own.

Nothing here touches a real task or a real agent. The end-to-end tests with
a hung scripted agent are in `tests/integration/test_run_timeout.py`.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from causalmesh.experiments import plan_experiment, profile
from causalmesh.scheduler import ExperimentRunner, RunEnvironment, RunState, run_with_deadline
from causalmesh.tasks import HandoffDirective, RunDeadline, RunTimedOutError

pytestmark = pytest.mark.unit

LIMIT = 0.2
GRACE = 0.1


class TestRunDeadline:
    @pytest.mark.parametrize("bad", [0, -1, -0.5, True, "5", None])
    def test_a_non_positive_or_non_numeric_limit_is_refused(self, bad) -> None:
        # A zero limit would time every run out instantly and record a
        # collection of "results" that measured nothing.
        with pytest.raises(ValueError, match="positive number of seconds"):
            RunDeadline(bad)

    def test_it_expires_on_its_own_clock(self) -> None:
        now = [100.0]
        deadline = RunDeadline(5, clock=lambda: now[0])
        deadline.check("start")
        now[0] = 104.9
        assert not deadline.expired
        now[0] = 105.0
        assert deadline.expired
        with pytest.raises(RunTimedOutError, match="before turn 3"):
            deadline.check("before turn 3")

    def test_trip_expires_it_early_from_any_thread(self) -> None:
        deadline = RunDeadline(3600)
        assert not deadline.expired
        threading.Thread(target=deadline.trip).start()
        for _ in range(100):
            if deadline.expired:
                break
            time.sleep(0.01)
        assert deadline.expired

    def test_an_unbound_chain_is_unknown_not_empty(self) -> None:
        # A run that died before it built a relay produced no chain. That is
        # None, not [], or "no evidence" would read as "zero events".
        deadline = RunDeadline(1)
        assert deadline.chain_snapshot() is None
        deadline.bind_chain(lambda: [], lambda: None)
        assert deadline.chain_snapshot() == ([], None)


class TestRunWithDeadline:
    async def test_work_that_finishes_in_time_is_returned_untouched(self) -> None:
        async def quick(deadline: RunDeadline) -> int:
            return 5

        assert await run_with_deadline(quick, run_id="r", limit_s=5, grace_s=GRACE) == 5

    async def test_a_failure_before_the_limit_is_a_failure_not_a_timeout(self) -> None:
        """A harness error must stay FAILED, whatever the watchdog is doing."""

        async def explode(deadline: RunDeadline) -> None:
            raise KeyError("harness bug")

        with pytest.raises(KeyError, match="harness bug"):
            await run_with_deadline(explode, run_id="r", limit_s=5, grace_s=GRACE)

    async def test_a_run_stuck_in_an_await_is_cancelled(self) -> None:
        async def stuck(deadline: RunDeadline) -> None:
            deadline.bind_chain(lambda: [{"n": 1}], lambda: "head")
            await asyncio.sleep(60)

        started = time.monotonic()
        with pytest.raises(RunTimedOutError) as info:
            await run_with_deadline(stuck, run_id="r", limit_s=LIMIT, grace_s=GRACE)
        elapsed = time.monotonic() - started

        assert info.value.detected_by == "cancelled"
        assert not info.value.thread_abandoned
        assert info.value.limit_s == LIMIT
        # Bounded by limit + grace, not by the 60 seconds the agent wanted.
        assert elapsed < LIMIT + 4 * GRACE + 1.0
        # The evidence came from outside: the run never handed it over.
        assert info.value.partial is not None
        assert info.value.partial.head_hash == "head"

    async def test_a_run_blocking_its_own_thread_is_abandoned_and_says_so(self) -> None:
        release = threading.Event()

        async def blocked(deadline: RunDeadline) -> None:
            deadline.bind_chain(lambda: [{"n": 1}, {"n": 2}], lambda: "head2")
            # Blocks the worker's event loop itself: no await, so nothing
            # scheduled on that loop (a cancel included) can run.
            release.wait(30)

        started = time.monotonic()
        try:
            with pytest.raises(RunTimedOutError) as info:
                await run_with_deadline(blocked, run_id="r", limit_s=LIMIT, grace_s=GRACE)
            elapsed = time.monotonic() - started
        finally:
            release.set()

        assert info.value.detected_by == "abandoned"
        assert info.value.thread_abandoned is True
        assert elapsed < LIMIT + 4 * GRACE + 1.0
        assert info.value.partial is not None
        assert len(info.value.partial.records) == 2
        assert "abandoned" in info.value.partial.where

    async def test_the_scheduler_is_free_while_a_run_blocks_its_thread(self) -> None:
        """Why the run is on a worker thread at all.

        If a blocked run held the scheduler's own loop, the watchdog could
        never fire. A ticker on the scheduler's loop must keep ticking.
        """
        release = threading.Event()
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        async def blocked(deadline: RunDeadline) -> None:
            release.wait(30)

        task = asyncio.create_task(ticker())
        try:
            with pytest.raises(RunTimedOutError):
                await run_with_deadline(blocked, run_id="r", limit_s=LIMIT, grace_s=GRACE)
        finally:
            release.set()
            task.cancel()
        assert ticks >= 5

    async def test_a_slow_run_unwinds_on_its_own(self) -> None:
        async def slow(deadline: RunDeadline) -> None:
            for turn in range(1000):
                await asyncio.sleep(0.01)
                deadline.check(f"before turn {turn}")

        with pytest.raises(RunTimedOutError) as info:
            await run_with_deadline(slow, run_id="r", limit_s=LIMIT, grace_s=GRACE)
        assert info.value.detected_by == "deadline_check"
        assert not info.value.thread_abandoned
        assert info.value.elapsed_s is not None
        assert info.value.elapsed_s >= LIMIT

    async def test_a_result_after_the_limit_is_discarded(self) -> None:
        """A budget a slow enough run can talk its way past is not a budget."""

        async def limps(deadline: RunDeadline) -> str:
            time.sleep(LIMIT + 0.05)  # blocks the worker, then finishes normally
            return "finished"

        with pytest.raises(RunTimedOutError) as info:
            await run_with_deadline(limps, run_id="r", limit_s=LIMIT, grace_s=1.0)
        assert info.value.late_result_discarded is True
        assert not info.value.thread_abandoned

    async def test_a_negative_grace_is_refused(self) -> None:
        async def quick(deadline: RunDeadline) -> None:
            return None

        with pytest.raises(ValueError, match="grace_s"):
            await run_with_deadline(quick, run_id="r", limit_s=1, grace_s=-1)

    async def test_cancelling_the_scheduler_does_not_leave_the_run_going(self) -> None:
        stopped = threading.Event()

        async def stuck(deadline: RunDeadline) -> None:
            try:
                await asyncio.sleep(60)
            finally:
                stopped.set()

        outer = asyncio.create_task(run_with_deadline(stuck, run_id="r", limit_s=60, grace_s=GRACE))
        await asyncio.sleep(0.1)
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await outer
        assert await asyncio.to_thread(stopped.wait, 2)


def _runner(tmp_path: Path, **kwargs):
    plan = plan_experiment(
        experiment_id="exp_seq",
        profile=profile("smoke"),
        task_ids=["t1"],
        master_seed=b"causalmesh-watchdog-unit-seed-01",
    )
    environment = RunEnvironment(
        fixtures_root=tmp_path / "fixtures",
        raw_root=tmp_path / "raw",
        workspace_root=tmp_path / "work",
        index_path=tmp_path / "raw" / "index.db",
    )
    return ExperimentRunner(
        plan=plan,
        tasks={"t1": SimpleNamespace(content_hash=lambda: "hash")},
        environment=environment,
        master_seed=b"causalmesh-watchdog-unit-seed-01",
        **kwargs,
    )


def _fake_result() -> SimpleNamespace:
    return SimpleNamespace(
        records=[],
        to_dict=lambda: {},
        succeeded=True,
        task_hash="hash",
        head_hash=None,
        error=None,
    )


class TestSequentialExecution:
    """Sequential execution is a property, and this is the test that says so.

    `loop.py` gives the reason: runs share a machine, and a parallel loop
    would make the coordination-cost timings (§44) depend on what else was
    running. The watchdog moves each run onto a worker thread, which is
    exactly the change that could quietly break that, so it is pinned with
    and without a timeout.
    """

    @pytest.mark.parametrize("timeout", [None, 30.0])
    async def test_at_most_one_run_is_ever_in_flight(
        self, tmp_path: Path, monkeypatch, timeout
    ) -> None:
        import causalmesh.scheduler.loop as loop_module

        lock = threading.Lock()
        in_flight = 0
        peak = 0
        started = 0

        async def fake_execute(*args, **kwargs):
            nonlocal in_flight, peak, started
            with lock:
                in_flight += 1
                started += 1
                peak = max(peak, in_flight)
            await asyncio.sleep(0.02)  # a real chance for another run to overlap
            with lock:
                in_flight -= 1
            return _fake_result()

        monkeypatch.setattr(loop_module, "execute_task", fake_execute)
        runner = _runner(tmp_path, run_timeout_s=timeout)
        runner.prepare()
        report = await runner.run()
        runner.close()

        assert started == 4
        assert report.completed == 4
        assert peak == 1

    async def test_runs_are_taken_in_plan_order(self, tmp_path: Path, monkeypatch) -> None:
        import causalmesh.scheduler.loop as loop_module

        seen: list[str] = []

        async def fake_execute(task, config, **kwargs):
            seen.append(config.run_id)
            return _fake_result()

        monkeypatch.setattr(loop_module, "execute_task", fake_execute)
        runner = _runner(tmp_path, run_timeout_s=30.0)
        runner.prepare()
        await runner.run()
        expected = [r.run_id for r in sorted(runner.plan.runs, key=lambda r: r.order)]
        runner.close()
        assert seen == expected


class TestRunnerConfiguration:
    @pytest.mark.parametrize("bad", [0, -3, True, "10"])
    def test_a_bad_timeout_is_refused_at_construction(self, tmp_path: Path, bad) -> None:
        with pytest.raises(ValueError, match="run_timeout_s"):
            _runner(tmp_path, run_timeout_s=bad)

    def test_a_handoff_for_a_run_that_is_not_in_the_plan_is_refused(self, tmp_path: Path) -> None:
        directive = HandoffDirective("agent_b", "agent_b2", 1, "stalled")
        with pytest.raises(ValueError, match="not in the plan"):
            _runner(tmp_path, handoffs={"no_such_run": directive})

    async def test_a_run_that_times_out_is_terminal_and_not_retried(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The state machine's answer, exercised through the loop.

        A second pass over the same index must execute nothing: re-running
        a timeout until it finished in time would select on the outcome.
        """
        import causalmesh.scheduler.loop as loop_module

        async def hang(*args, **kwargs):
            await asyncio.sleep(60)

        monkeypatch.setattr(loop_module, "execute_task", hang)
        runner = _runner(tmp_path, run_timeout_s=LIMIT, timeout_grace_s=GRACE)
        runner.prepare()
        report = await runner.run(limit=1)
        assert report.timed_out == 1
        assert report.failed == 0

        monkeypatch.undo()
        counts = runner.index.counts("exp_seq")
        assert counts[RunState.TIMED_OUT] == 1
        assert counts[RunState.FAILED] == 0

        async def fine(*args, **kwargs):
            return _fake_result()

        monkeypatch.setattr(loop_module, "execute_task", fine)
        again = await runner.run()
        timed_out_id = next(
            r.run_id for r in runner.index.runs("exp_seq", state=RunState.TIMED_OUT)
        )
        # Three planned runs remained and ran; the timed-out one was left alone.
        assert again.executed == 3
        assert runner.index.get(timed_out_id).state == RunState.TIMED_OUT
        assert runner.index.get(timed_out_id).attempts == 1
        runner.close()
