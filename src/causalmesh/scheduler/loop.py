"""The experiment execution loop (spec §79, §80, §81).

One collection = one plan + one index + a loop that repeatedly claims the
next run, executes it, and records what happened. The loop is deliberately
small; the interesting decisions are about what it refuses to do.

**It never skips a run silently.** Every planned run reaches a terminal
state, and a run that raised is FAILED with its traceback recorded, not
absent. §81 is explicit that a failed run is evidence: the arm that fails
more is telling us something, and dropping failures would replace the
measurement with a survivorship curve.

**It never retries a failure.** ABANDONED runs (interrupted before they
could record a verdict) are resumed; FAILED and TIMED_OUT are left alone.
Retrying until a run passed would be selection on the outcome.

**It writes evidence before recording success.** The run artifact is
persisted first, then the index is updated. If the process dies between the
two, the run is found RUNNING at next startup, marked ABANDONED and
re-executed — which costs time but cannot lose evidence. The other order
could mark a run COMPLETED whose artifact was never written.

**Execution is sequential.** Runs share this machine, and a parallel
scheduler would make wall-clock timings depend on what else happened to be
running — a confound in the coordination-cost measurement (§44), which is
one of the outcomes. Parallelism is a tracked backlog item, not an
oversight: it needs per-run resource isolation before it can be honest.
"""

from __future__ import annotations

import json
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..experiments.randomization import RunPlan, derive_run_seed
from ..storage.index import RunIndex, RunRecord
from ..tasks import RunConfig, RunResult, TaskDefinition, execute_task
from .states import RunState

__all__ = ["ExperimentRunner", "LoopReport", "RunEnvironment"]


@dataclass(frozen=True)
class RunEnvironment:
    """Where a collection reads its inputs and writes its evidence.

    Grouped into one object so a caller cannot supply three of the four
    paths and let the fourth default to somewhere unintended — writing raw
    evidence into a temp directory that a later cleanup removes would be
    silent and unrecoverable.
    """

    fixtures_root: Path
    raw_root: Path
    workspace_root: Path
    index_path: Path

    @classmethod
    def under(cls, repository_root: Path, *, experiment_id: str) -> RunEnvironment:
        """The standard layout, matching the architecture in `docs/PLAN.md`."""
        root = Path(repository_root)
        return cls(
            fixtures_root=root / "fixtures",
            raw_root=root / "data" / "raw" / experiment_id,
            workspace_root=root / "experiments" / experiment_id,
            index_path=root / "data" / "raw" / experiment_id / "index.db",
        )


@dataclass
class LoopReport:
    """What one invocation of the loop did.

    Distinguishes `executed` (runs this invocation performed) from
    `already_done` (runs a previous invocation had finished), because a
    resume that executed nothing because everything was done and a resume
    that executed nothing because it crashed immediately must not look the
    same.
    """

    experiment_id: str
    planned: int
    executed: int = 0
    completed: int = 0
    failed: int = 0
    timed_out: int = 0
    already_done: int = 0
    resumed: int = 0
    succeeded_tasks: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    wall_clock_s: float = 0.0

    @property
    def is_complete(self) -> bool:
        return self.completed + self.failed + self.timed_out + self.already_done >= self.planned

    def to_dict(self) -> dict[str, Any]:
        return {
            "already_done": self.already_done,
            "completed": self.completed,
            "errors": self.errors,
            "executed": self.executed,
            "experiment_id": self.experiment_id,
            "failed": self.failed,
            "planned": self.planned,
            "resumed": self.resumed,
            "succeeded_tasks": self.succeeded_tasks,
            "timed_out": self.timed_out,
            "wall_clock_s": round(self.wall_clock_s, 3),
        }

    def summary(self) -> str:
        return (
            f"{self.experiment_id}: {self.executed} executed "
            f"({self.completed} completed, {self.failed} failed, "
            f"{self.timed_out} timed out), {self.already_done} already done, "
            f"{self.succeeded_tasks} task successes of {self.planned} planned"
        )


class ExperimentRunner:
    """Executes a planned collection, resumably.

    Holds no state about progress itself: everything lives in the index, so
    a second process — or the same process after a crash — sees exactly what
    the first did. An in-memory cursor would be lost on the crash it exists
    to survive.
    """

    def __init__(
        self,
        *,
        plan: RunPlan,
        tasks: dict[str, TaskDefinition],
        environment: RunEnvironment,
        master_seed: bytes,
        run_config: dict[str, Any] | None = None,
        clock: Callable[[], int] | None = None,
    ) -> None:
        missing = set(plan.task_ids) - set(tasks)
        if missing:
            raise ValueError(
                f"the plan names tasks that were not supplied: {sorted(missing)}. "
                "Running a collection with a missing task would produce an "
                "unbalanced design without saying so."
            )
        self.plan = plan
        self.tasks = tasks
        self.environment = environment
        self.master_seed = master_seed
        self.run_config = dict(run_config or {})
        # Wall-clock is used only for operational bookkeeping — when a run
        # started, how long the loop took. It never enters the signed chain,
        # where non-reproducible values break determinism.
        self._clock = clock or (lambda: time.time_ns() // 1000)

        self.environment.raw_root.mkdir(parents=True, exist_ok=True)
        self.index = RunIndex(self.environment.index_path)

    def close(self) -> None:
        self.index.close()

    def __enter__(self) -> ExperimentRunner:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def prepare(self) -> int:
        """Register the plan and recover anything a previous process left.

        Returns the number of runs newly registered. Safe to call
        repeatedly: registration is idempotent, and recovery only touches
        runs stuck in RUNNING, which by definition no live process owns
        (this loop is sequential and single-process).
        """
        now = self._clock()
        inserted = self.index.register_plan(self.plan, now_us=now)
        self.index.abandon_running(self.plan.experiment_id, now_us=now)
        return inserted

    async def run(self, *, limit: int | None = None) -> LoopReport:
        """Execute runs until the collection is done or `limit` is reached.

        `limit` exists for the smoke path and for tests; it stops the loop
        early without marking anything, so the remaining runs stay PLANNED
        and a later call picks them up.
        """
        started = time.monotonic()
        before = self.index.counts(self.plan.experiment_id)
        report = LoopReport(
            experiment_id=self.plan.experiment_id,
            planned=len(self.plan),
            already_done=(
                before[RunState.COMPLETED] + before[RunState.FAILED] + before[RunState.TIMED_OUT]
            ),
        )

        while limit is None or report.executed < limit:
            record = self.index.claim_next(self.plan.experiment_id, now_us=self._clock())
            if record is None:
                break
            if record.attempts > 1:
                report.resumed += 1
            await self._execute_one(record, report)

        report.wall_clock_s = time.monotonic() - started
        return report

    async def _execute_one(self, record: RunRecord, report: LoopReport) -> None:
        """Run one unit of work and record its outcome, whatever it is."""
        report.executed += 1
        task = self.tasks[record.task_id]
        artifact_path = self.environment.raw_root / record.run_id

        try:
            result = await execute_task(
                task,
                self._config_for(record),
                workspace_root=self.environment.workspace_root / record.run_id,
                fixtures_root=self.environment.fixtures_root,
            )
        except BaseException as exc:
            # Deliberately broad. A crash in the harness is exactly the
            # case §81 is about: the run must still leave a record saying
            # what happened, or the collection quietly shrinks. The
            # traceback is written to the artifact so the failure is
            # diagnosable rather than reduced to a class name.
            #
            # BaseException rather than Exception so a KeyboardInterrupt
            # still records the run before propagating — otherwise an
            # operator's Ctrl-C leaves a run stranded in RUNNING with no
            # evidence of why.
            detail = traceback.format_exc()
            self._write_artifact(
                artifact_path,
                {
                    "arm": record.arm,
                    "error": f"{type(exc).__name__}: {exc}",
                    "run_id": record.run_id,
                    "state": RunState.FAILED,
                    "task_id": record.task_id,
                    "traceback": detail,
                },
            )
            self.index.finish(
                record.run_id,
                state=RunState.FAILED,
                now_us=self._clock(),
                succeeded=None,
                error=f"{type(exc).__name__}: {exc}",
                artifact_path=str(artifact_path),
                note="harness raised",
            )
            report.failed += 1
            report.errors.append({"run_id": record.run_id, "error": f"{type(exc).__name__}: {exc}"})
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return

        # Evidence first, index second. A crash between the two leaves the
        # run RUNNING, which `prepare` turns into ABANDONED and re-executes;
        # the reverse order could mark a run COMPLETED with no artifact.
        self._write_artifact(artifact_path, self._artifact_for(result, record))

        # `error` set means the agent loop raised but the run still produced
        # an outcome and a chain. That is a completed run with a failed
        # task, not a harness failure: the evidence is intact.
        state = RunState.COMPLETED
        self.index.finish(
            record.run_id,
            state=state,
            now_us=self._clock(),
            succeeded=result.succeeded,
            task_hash=result.task_hash,
            head_hash=result.head_hash,
            error=result.error,
            artifact_path=str(artifact_path),
            note="agent error, outcome recorded" if result.error else "completed",
        )
        report.completed += 1
        if result.succeeded:
            report.succeeded_tasks += 1

    def _config_for(self, record: RunRecord) -> RunConfig:
        """Build the per-run configuration.

        The seed is derived from the master seed and the run id (§40), so a
        single run can be re-executed on its own and reproduce byte for
        byte without replaying the collection.
        """
        return RunConfig(
            experiment_id=record.experiment_id,
            run_id=record.run_id,
            arm=record.arm,
            master_seed=derive_run_seed(self.master_seed, record.run_id),
            **self.run_config,
        )

    def _artifact_for(self, result: RunResult, record: RunRecord) -> dict[str, Any]:
        """The full run artifact: everything the analysis will later read.

        The signed chain goes in whole. It is the evidence, and an artifact
        that summarised it would leave the verifier nothing to verify.
        """
        return {
            "arm": record.arm,
            "chain": result.records,
            "experiment_id": record.experiment_id,
            "plan_order": record.plan_order,
            # §30: which code, which machine, which operator. Kept in the
            # envelope rather than in the chain — the chain is
            # bit-reproducible, and a hostname inside it would break that.
            # `run_config` is whatever the caller supplied; an empty dict
            # records "not captured" rather than inventing a value.
            "provenance": dict(self.run_config),
            # A run is reproducible unless something nondeterministic drove
            # it. `agent_kind` is set only when a real coding-agent CLI was
            # connected; MockAgent leaves it unset, so the default is the
            # deterministic case and a live run has to declare itself.
            "reproducible": "agent_kind" not in self.run_config,
            "repetition": record.repetition,
            "result": result.to_dict(),
            "run_id": record.run_id,
            "state": RunState.COMPLETED,
            "task_id": record.task_id,
        }

    def _write_artifact(self, directory: Path, payload: dict[str, Any]) -> None:
        """Write a run artifact, refusing to overwrite one (§31).

        Raw evidence is immutable. If a path already holds an artifact, the
        run is being executed a second time, which means something upstream
        failed to enforce idempotency — better to fail loudly here than to
        overwrite the first run's evidence and leave no trace that two runs
        ever existed.
        """
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "run.json"
        if target.exists():
            raise FileExistsError(
                f"{target} already exists. Raw evidence is immutable (§31); "
                "a second execution of the same run id must not overwrite the "
                "first. Use a new experiment_id, or remove the directory "
                "deliberately."
            )
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def status(self) -> dict[str, Any]:
        """Current progress, read from the index rather than remembered."""
        counts = self.index.counts(self.plan.experiment_id)
        return {
            "complete": self.index.is_complete(self.plan.experiment_id),
            "counts": counts,
            "experiment_id": self.plan.experiment_id,
            "planned": len(self.plan),
            "plan_hash": self.plan.content_hash(),
            "profile": self.plan.profile,
        }
