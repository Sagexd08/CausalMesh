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

**A run can be given a wall-clock limit** (`run_timeout_s`). Without one the
loop behaves exactly as it always did. With one, each run executes under the
watchdog in `watchdog.py`, and a run that overruns ends TIMED_OUT: a
distinct state, not FAILED, with its chain-so-far and a `timeout` block in
the artifact. Wall-clock facts (the limit, the elapsed time, how the overrun
was noticed) live in the artifact's envelope, next to `state` and
`provenance`, never in the signed chain, so a timed-out run's chain is a
plain prefix of what it would have been.

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

The watchdog's worker thread does not make this parallel: the loop awaits
each run before claiming the next, so at most one run is ever in flight
(`tests/unit/test_scheduler_watchdog.py::TestSequentialExecution` pins it).
The one exception is stated rather than hidden: a run whose thread had to be
abandoned keeps running in the background after it is recorded TIMED_OUT,
and the artifact says so (`timeout.thread_abandoned`).
"""

from __future__ import annotations

import json
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..experiments.randomization import RunPlan, derive_run_seed
from ..storage.index import RunIndex, RunRecord
from ..tasks import (
    HandoffDirective,
    RunConfig,
    RunResult,
    RunTimedOutError,
    TaskDefinition,
    execute_task,
)
from .states import RunState
from .watchdog import DEFAULT_GRACE_S, run_with_deadline

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
    threads_abandoned: int = 0
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
            "threads_abandoned": self.threads_abandoned,
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
        run_timeout_s: float | None = None,
        timeout_grace_s: float = DEFAULT_GRACE_S,
        handoffs: Mapping[str, HandoffDirective] | None = None,
    ) -> None:
        if run_timeout_s is not None and (
            isinstance(run_timeout_s, bool)
            or not isinstance(run_timeout_s, (int, float))
            or run_timeout_s <= 0
        ):
            raise ValueError(
                f"run_timeout_s must be a positive number of seconds or None, got {run_timeout_s!r}"
            )
        unknown = set(handoffs or ()) - {run.run_id for run in plan.runs}
        if unknown:
            raise ValueError(
                f"handoff directives name runs that are not in the plan: {sorted(unknown)}. "
                "A directive that can never fire is an operator's typo, not a no-op."
            )
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
        self.run_timeout_s = run_timeout_s
        self.timeout_grace_s = timeout_grace_s
        self.handoffs = dict(handoffs or {})
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
            result = await self._run_task(task, record)
        except RunTimedOutError as exc:
            self._record_timeout(record, task, exc, artifact_path, report)
            return
        except BaseException as exc:
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

        self._write_artifact(artifact_path, self._artifact_for(result, record))

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

    async def _run_task(self, task: TaskDefinition, record: RunRecord) -> RunResult:
        """Execute one run, under the watchdog if a limit is configured.

        With no `run_timeout_s` this is a plain `await execute_task(...)`,
        in the loop's own thread, exactly as before. Extra keyword arguments
        are passed only when they apply, so a run that uses neither a
        deadline nor a handoff calls `execute_task` with the arguments it
        always had.
        """
        config = self._config_for(record)
        extra: dict[str, Any] = {}
        directive = self.handoffs.get(record.run_id)
        if directive is not None:
            extra["handoff"] = directive
            extra["on_handoff"] = lambda phase, package: self._mirror_handoff(
                record, directive, phase
            )

        def execute(deadline: Any = None) -> Any:
            kwargs = dict(extra)
            if deadline is not None:
                kwargs["deadline"] = deadline
            return execute_task(
                task,
                config,
                # Not `workspace_root / run_id`: `execute_task` already namespaces
                # everything it makes by run id (`<run_id>/<agent>`,
                # `<run_id>_integrated`, `<run_id>_claims.db`). Nesting it again put the
                # run id in the path twice, and on Windows that alone pushed a
                # checkout at an ordinary location past MAX_PATH.
                workspace_root=self.environment.workspace_root,
                fixtures_root=self.environment.fixtures_root,
                **kwargs,
            )

        if self.run_timeout_s is None:
            return await execute()  # type: ignore[no-any-return]
        return await run_with_deadline(
            execute,
            run_id=record.run_id,
            limit_s=self.run_timeout_s,
            grace_s=self.timeout_grace_s,
        )

    def _mirror_handoff(self, record: RunRecord, directive: HandoffDirective, phase: str) -> None:
        """Reflect the two halves of a handoff in the run's recorded state.

        RUNNING to HANDED_OFF when the predecessor is relieved, back to
        RUNNING when the successor has taken over. The transition log keeps
        who and why, which is the audit trail an operator reads; the signed
        record of the same event is the HANDOFF event on the chain.
        """
        if phase == "relieved":
            self.index.transition(
                record.run_id,
                to_state=RunState.HANDED_OFF,
                now_us=self._clock(),
                note=f"{directive.from_agent} relieved for {directive.to_agent}: {directive.reason}",
            )
        else:
            self.index.transition(
                record.run_id,
                to_state=RunState.RUNNING,
                now_us=self._clock(),
                note=f"continues under {directive.to_agent}",
            )

    def _record_timeout(
        self,
        record: RunRecord,
        task: TaskDefinition,
        exc: RunTimedOutError,
        artifact_path: Path,
        report: LoopReport,
    ) -> None:
        """Record a run that overran its limit as TIMED_OUT, with what it had.

        The artifact is written first and the index second, the same order
        as every other terminal state. It carries no `result` block: there
        was no outcome to report, and a partial one would put a truncated
        run's costs beside completed runs' in every mean. What the run did
        produce is under `partial`.

        `succeeded` is left NULL. A run that ran out of time did not fail
        its task and did not pass it; it is unknown, and unknown is not 0.
        """
        partial = exc.partial
        self._write_artifact(
            artifact_path,
            {
                "arm": record.arm,
                "chain": partial.records if partial is not None else [],
                "experiment_id": record.experiment_id,
                "partial": {
                    "agent_summaries": partial.agent_summaries if partial is not None else {},
                    "chain_known": partial is not None,
                    "events": len(partial.records) if partial is not None else None,
                    "head_hash": partial.head_hash if partial is not None else None,
                    "note": (
                        "the run was cut off; the chain is a prefix of what it would "
                        "have been and no acceptance decision was made"
                    ),
                    "where": partial.where if partial is not None else "unknown",
                },
                "plan_order": record.plan_order,
                "provenance": dict(self.run_config),
                # Where a run is cut depends on the machine, so it cannot be
                # reproduced byte for byte the way a completed run can.
                "reproducible": False,
                "repetition": record.repetition,
                "run_id": record.run_id,
                "state": RunState.TIMED_OUT,
                "task_id": record.task_id,
                "timeout": {
                    "detected_by": exc.detected_by,
                    "elapsed_s": None if exc.elapsed_s is None else round(exc.elapsed_s, 3),
                    "late_result_discarded": exc.late_result_discarded,
                    "limit_s": exc.limit_s if exc.limit_s is not None else self.run_timeout_s,
                    "thread_abandoned": exc.thread_abandoned,
                },
            },
        )
        self.index.finish(
            record.run_id,
            state=RunState.TIMED_OUT,
            now_us=self._clock(),
            succeeded=None,
            task_hash=task.content_hash(),
            head_hash=partial.head_hash if partial is not None else None,
            error=str(exc),
            artifact_path=str(artifact_path),
            note=f"timed out ({exc.detected_by})",
        )
        report.timed_out += 1
        if exc.thread_abandoned:
            report.threads_abandoned += 1

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
            "provenance": dict(self.run_config),
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
