"""An operator's interrupt must not become a permanent FAILED run.

`FAILED` is terminal and never retried, so recording it for a Ctrl-C would
remove a run that should have been resumed from the experiment's denominator.
The claim under test: a cancelled collection leaves the in-flight run
`RUNNING`, the next startup resumes it, and it completes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tests.integration.test_scheduler_loop import FIXTURES, SEED, TASK_PATH, build_runner

from causalmesh.scheduler import ExperimentRunner, RunEnvironment, RunState, loop as scheduler_loop
from causalmesh.tasks import TaskDefinition

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture(scope="module")
def task() -> TaskDefinition:
    return TaskDefinition.from_yaml(TASK_PATH)


@pytest.mark.parametrize("interrupt", [asyncio.CancelledError, KeyboardInterrupt])
async def test_an_interrupt_leaves_the_run_resumable_and_it_completes(
    task: TaskDefinition,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt: type[BaseException],
) -> None:
    runner, plan, environment = build_runner(task, tmp_path, experiment_id="exp_interrupt")
    runner.prepare()
    real_execute_task = scheduler_loop.execute_task

    async def interrupted(*args, **kwargs):
        raise interrupt()

    monkeypatch.setattr(scheduler_loop, "execute_task", interrupted)
    with pytest.raises(interrupt):
        await runner.run(limit=1)

    stuck = runner.index.runs("exp_interrupt", state=RunState.RUNNING)
    assert len(stuck) == 1, "the interrupted run must stay RUNNING, not be recorded as an outcome"
    run_id = stuck[0].run_id
    counts = runner.index.counts("exp_interrupt")
    assert counts[RunState.FAILED] == 0
    assert not (environment.raw_root / run_id / "run.json").exists(), (
        "no artifact may claim an outcome for a run that was only interrupted"
    )
    runner.close()

    # A new process: prepare() abandons whatever was left RUNNING, and the run resumes.
    monkeypatch.setattr(scheduler_loop, "execute_task", real_execute_task)
    resumed_runner = ExperimentRunner(
        plan=plan,
        tasks={task.task_id: task},
        environment=RunEnvironment(
            fixtures_root=FIXTURES,
            raw_root=environment.raw_root,
            workspace_root=environment.workspace_root,
            index_path=environment.index_path,
        ),
        master_seed=SEED,
    )
    with resumed_runner:
        resumed_runner.prepare()
        report = await resumed_runner.run(limit=1)
        assert report.resumed == 1
        record = resumed_runner.index.get(run_id)
        assert record.state == RunState.COMPLETED
        assert record.attempts == 2
