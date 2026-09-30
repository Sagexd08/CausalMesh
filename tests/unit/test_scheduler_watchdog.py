"""The whole-run watchdog and the acceptance rule for interrupted runs.

The watchdog is the piece that can lose evidence if it is wrong, so it is
tested on its own against small coroutines that misbehave in each way a run
can: finish in time, hang cooperatively, ignore cancellation, and blow up
while being cancelled. The real thing, against a hung mock agent, is
`tests/integration/test_scheduler_timeout.py`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from causalmesh.experiments import plan_experiment, profile
from causalmesh.scheduler import ExperimentRunner, RunEnvironment
from causalmesh.scheduler.loop import _Watchdog
from causalmesh.tasks import AcceptanceVerdict, TaskOutcome, decide_acceptance

pytestmark = pytest.mark.unit


class TestWatchdog:
    async def test_no_budget_is_a_plain_await(self) -> None:
        async def work() -> str:
            return "done"

        watchdog = _Watchdog(None, grace_s=1.0)
        assert await watchdog.run(work) == "done"
        assert not watchdog.fired

    async def test_a_run_inside_its_budget_is_untouched(self) -> None:
        async def work() -> str:
            await asyncio.sleep(0)
            return "done"

        watchdog = _Watchdog(5.0, grace_s=1.0)
        assert await watchdog.run(work) == "done"
        assert not watchdog.fired
        assert watchdog.elapsed_s is None

    async def test_an_exception_inside_the_budget_propagates(self) -> None:
        async def work() -> str:
            raise RuntimeError("boom")

        watchdog = _Watchdog(5.0, grace_s=1.0)
        with pytest.raises(RuntimeError, match="boom"):
            await watchdog.run(work)
        assert not watchdog.fired

    async def test_a_hung_run_is_cancelled_and_its_partial_result_kept(self) -> None:
        async def work() -> str:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                return "partial"
            return "unreachable"

        watchdog = _Watchdog(0.05, grace_s=2.0)
        assert await watchdog.run(work) == "partial"
        assert watchdog.fired
        assert not watchdog.grace_expired
        assert watchdog.elapsed_s is not None

    async def test_a_run_that_does_not_handle_cancellation_yields_no_result(self) -> None:
        async def work() -> str:
            await asyncio.sleep(3600)
            return "unreachable"

        watchdog = _Watchdog(0.05, grace_s=2.0)
        assert await watchdog.run(work) is None
        assert watchdog.fired
        assert not watchdog.grace_expired

    @pytest.mark.failure
    async def test_a_run_that_ignores_cancellation_cannot_hold_the_collection(self) -> None:
        release = asyncio.Event()

        async def stubborn() -> str:
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue
            raise RuntimeError("released")

        watchdog = _Watchdog(0.05, grace_s=0.1)
        assert await watchdog.run(stubborn) is None
        assert watchdog.fired
        assert watchdog.grace_expired
        assert watchdog.to_dict()["grace_expired"] is True
        release.set()
        await asyncio.sleep(0.05)

    @pytest.mark.failure
    async def test_a_run_that_fails_while_being_cancelled_is_reported(self) -> None:
        async def work() -> str:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise RuntimeError("cleanup failed") from None
            return "unreachable"

        watchdog = _Watchdog(0.05, grace_s=2.0)
        assert await watchdog.run(work) is None
        assert watchdog.fired
        assert watchdog.failure == "RuntimeError: cleanup failed"

    async def test_cancelling_the_scheduler_takes_the_run_with_it(self) -> None:
        started = asyncio.Event()
        inner: list[asyncio.Task[str]] = []

        async def work() -> str:
            inner.append(asyncio.current_task())  # type: ignore[arg-type]
            started.set()
            await asyncio.sleep(3600)
            return "unreachable"

        watchdog = _Watchdog(60.0, grace_s=1.0)
        outer = asyncio.ensure_future(watchdog.run(work))
        await started.wait()
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await outer
        await asyncio.sleep(0)
        assert inner[0].cancelled()

    def test_the_envelope_carries_the_wall_clock_facts(self) -> None:
        watchdog = _Watchdog(1.5, grace_s=30.0)
        watchdog.elapsed_s = 1.50049
        assert watchdog.to_dict() == {
            "budget_s": 1.5,
            "elapsed_s": 1.5,
            "grace_expired": False,
            "grace_s": 30.0,
            "run_failed_after_cancel": None,
        }


class TestRunnerConfiguration:
    def _build(self, tmp_path: Path, **kwargs) -> ExperimentRunner:
        plan = plan_experiment(
            experiment_id="exp",
            profile=profile("smoke"),
            task_ids=["t1"],
            master_seed=b"causalmesh-watchdog-unit-seed-01",
        )
        environment = RunEnvironment.under(tmp_path, experiment_id="exp")
        return ExperimentRunner(
            plan=plan,
            tasks={"t1": object()},  # type: ignore[dict-item]
            environment=environment,
            master_seed=b"causalmesh-watchdog-unit-seed-01",
            **kwargs,
        )

    def test_no_timeout_is_the_default(self, tmp_path: Path) -> None:
        with self._build(tmp_path) as runner:
            assert runner.run_timeout_s is None

    @pytest.mark.parametrize("bad", [0, -1, float("nan")])
    def test_a_non_positive_budget_is_refused(self, tmp_path: Path, bad: float) -> None:
        # Zero would time out every run before it started: a collection of
        # nothing but TIMED_OUT, produced by a typo.
        with pytest.raises(ValueError, match="run_timeout_s"):
            self._build(tmp_path, run_timeout_s=bad)

    def test_a_non_positive_grace_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="timeout_grace_s"):
            self._build(tmp_path, run_timeout_s=1.0, timeout_grace_s=0)


class TestInterruptedAcceptance:
    def _outcome(self, *, succeeded: bool) -> TaskOutcome:
        return TaskOutcome(
            succeeded=succeeded,
            tests_passed=succeeded,
            divergence_absent=succeeded,
            evidence=("tests_exit_code=0",),
        )

    def test_the_default_rule_is_unchanged(self) -> None:
        assert decide_acceptance(self._outcome(succeeded=True)).verdict == AcceptanceVerdict.ACCEPT
        assert decide_acceptance(self._outcome(succeeded=False)).verdict == AcceptanceVerdict.REJECT

    def test_an_interrupted_run_is_never_accepted_even_if_its_partial_work_passes(self) -> None:
        decision = decide_acceptance(self._outcome(succeeded=True), interrupted=True)
        assert decision.verdict == AcceptanceVerdict.REJECT

    def test_the_decision_says_why_in_its_own_evidence(self) -> None:
        decision = decide_acceptance(self._outcome(succeeded=True), interrupted=True)
        assert "run_interrupted_before_completion" in decision.evidence
        assert "tests_exit_code=0" in decision.evidence
