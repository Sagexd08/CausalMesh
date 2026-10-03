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

**A run can be given a wall-clock budget.** With `run_timeout_s` set, each
run executes under a whole-run watchdog: when the budget lapses the run is
cancelled, its partial evidence is sealed and kept, and it is recorded
TIMED_OUT, a result that is never retried (like FAILED, retrying it would
select on the outcome). The budget is off by default, so an unconfigured
collection behaves, and reproduces, exactly as before. The watchdog is
cooperative: it lands where an agent awaits, so a run wedged in a blocking
call is beyond it (tracked in `docs/backlog.md`). Budget and elapsed time
are wall-clock values and live in the artifact's envelope, never in the
signed chain.

**Execution is sequential.** Runs share this machine, and a parallel
scheduler would make wall-clock timings depend on what else happened to be
running — a confound in the coordination-cost measurement (§44), which is
one of the outcomes. Parallelism is a tracked backlog item, not an
oversight: it needs per-run resource isolation before it can be honest.
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..experiments.randomization import RunPlan, derive_run_seed
from ..storage.index import RunIndex, RunRecord
from ..tasks import RunConfig, RunResult, TaskDefinition, execute_task
from .states import RunState

__all__ = ["DEFAULT_TIMEOUT_GRACE_S", "ExperimentRunner", "LoopReport", "RunEnvironment"]

# How long a cancelled run gets to seal its evidence before the scheduler
# stops waiting for it. Sealing is fast (hash-chain a handful of events and
# run the integration test), so this is generous; it exists so a run that
# swallows cancellation cannot hold the whole collection hostage.
DEFAULT_TIMEOUT_GRACE_S = 30.0


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


class _Watchdog:
    """Runs one awaitable under an optional wall-clock budget.

    Not `asyncio.wait_for`: that cancels and then *raises*, discarding
    whatever the cancelled coroutine might have returned, and the point here
    is to keep the partial evidence. So the run is its own task, waited on
    with a timeout; on expiry it is cancelled, given a grace period to seal
    its evidence and return, and its result (if any) is taken.

    With no budget it is a plain `await`, so the default path is unchanged.
    """

    def __init__(self, budget_s: float | None, grace_s: float) -> None:
        self.budget_s = budget_s
        self.grace_s = grace_s
        self.fired = False
        self.grace_expired = False
        self.failure: str | None = None
        self.elapsed_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_s": self.budget_s,
            "elapsed_s": None if self.elapsed_s is None else round(self.elapsed_s, 3),
            "grace_expired": self.grace_expired,
            "grace_s": self.grace_s,
            "run_failed_after_cancel": self.failure,
        }

    async def run(self, factory: Callable[[], Coroutine[Any, Any, RunResult]]) -> RunResult | None:
        if self.budget_s is None:
            return await factory()

        started = time.monotonic()
        task = asyncio.ensure_future(factory())
        try:
            done, _ = await asyncio.wait({task}, timeout=self.budget_s)
            if done:
                return task.result()

            self.fired = True
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=self.grace_s)
            self.elapsed_s = time.monotonic() - started
            if not done:
                # The run ignored cancellation. It cannot be killed from here;
                # it is left to finish or hang, and its eventual outcome is
                # consumed so asyncio does not log it as never retrieved.
                self.grace_expired = True
                task.add_done_callback(_consume)
                return None
            if task.cancelled():
                return None
            exc = task.exception()
            if exc is not None:
                self.failure = f"{type(exc).__name__}: {exc}"
                return None
            return task.result()
        except asyncio.CancelledError:
            # The scheduler itself is being cancelled (Ctrl-C): take the run
            # down with it rather than orphaning it.
            task.cancel()
            raise


def _consume(task: asyncio.Future[Any]) -> None:
    if not task.cancelled():
        task.exception()


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
        timeout_grace_s: float = DEFAULT_TIMEOUT_GRACE_S,
    ) -> None:
        if run_timeout_s is not None and not run_timeout_s > 0:
            raise ValueError(
                f"run_timeout_s must be positive or None (no timeout), got {run_timeout_s!r}"
            )
        if not timeout_grace_s > 0:
            raise ValueError(f"timeout_grace_s must be positive, got {timeout_grace_s!r}")
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
        self._clock = clock or (lambda: time.time_ns() // 1000)
        self.run_timeout_s = run_timeout_s
        self.timeout_grace_s = timeout_grace_s

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

        watchdog = _Watchdog(self.run_timeout_s, self.timeout_grace_s)
        decisions_before = len(self._handler_decisions())
        try:
            result = await watchdog.run(
                lambda: execute_task(
                    task,
                    self._config_for(record),
                    # Not `workspace_root / run_id`: `execute_task` already namespaces
                    # everything it makes by run id (`<run_id>/<agent>`,
                    # `<run_id>_integrated`, `<run_id>_claims.db`). Nesting it again put the
                    # run id in the path twice, and on Windows that alone pushed a
                    # checkout at an ordinary location past MAX_PATH.
                    workspace_root=self.environment.workspace_root,
                    fixtures_root=self.environment.fixtures_root,
                    preserve_evidence_on_cancel=self.run_timeout_s is not None,
                )
            )
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            # An operator's interrupt is not a verdict on the run. Record nothing:
            # the run stays RUNNING, the next startup marks it ABANDONED, and it
            # is resumed. Writing FAILED here (terminal, never retried) would turn
            # a Ctrl-C into a permanent failure in the denominator.
            raise
        except Exception as exc:
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
            return

        # A run that finished in the instant between the budget lapsing and the
        # cancellation landing has a real verdict; discarding it as TIMED_OUT
        # would throw away a measurement that was made.
        if watchdog.fired and (result is None or result.interrupted):
            self._record_timeout(record, report, result, watchdog, artifact_path)
            return
        if result is None:
            raise RuntimeError("execute_task returned nothing and the watchdog did not fire")

        self._write_artifact(
            artifact_path,
            self._artifact_for(
                result, record, checkpoint_decisions=self._handler_decisions()[decisions_before:]
            ),
        )

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

    def _record_timeout(
        self,
        record: RunRecord,
        report: LoopReport,
        result: RunResult | None,
        watchdog: _Watchdog,
        artifact_path: Path,
    ) -> None:
        """Record a run the watchdog cut short as TIMED_OUT.

        Whatever the run managed to seal is kept: the partial chain goes in
        the artifact whole, so it still verifies offline, and the partial
        workspace digests stay for the handoff work that will want them.
        The task outcome is recorded as unknown (`succeeded=None`), not
        False: the agents never finished, so the run has no verdict on the
        task, and counting it a failure would claim a measurement that was
        not made. The wall-clock facts go in `envelope`, outside anything
        signed.
        """
        message = (
            f"TimeoutError: run exceeded its {self.run_timeout_s:g}s wall-clock budget"
            if self.run_timeout_s is not None
            else "TimeoutError: run exceeded its wall-clock budget"
        )
        payload: dict[str, Any]
        if result is not None:
            payload = self._artifact_for(result, record)
            payload["state"] = RunState.TIMED_OUT
            # Where the cut landed depends on timing, so a timed-out run is
            # not bit-reproducible even when its mock agents are.
            payload["reproducible"] = False
            # `result.outcome.succeeded` is what every analysis reads as the
            # task result. A half-finished workspace scoring False there would
            # put a timed-out run in the failure column, a verdict nobody
            # measured, so the outcome is withdrawn (unknown) and the partial
            # score is kept under its own name.
            recorded = payload["result"]
            recorded["partial_outcome"] = recorded["outcome"]
            recorded["outcome"] = None
        else:
            payload = {
                "arm": record.arm,
                "evidence": (
                    "none: the run did not yield within the grace period, so no "
                    "partial chain could be sealed"
                    if watchdog.grace_expired
                    else "none: the run ended without producing a result"
                ),
                "run_id": record.run_id,
                "state": RunState.TIMED_OUT,
                "task_id": record.task_id,
            }
            if watchdog.failure is not None:
                payload["error"] = watchdog.failure
        payload["envelope"] = {"watchdog": watchdog.to_dict()}
        self._write_artifact(artifact_path, payload)
        self.index.finish(
            record.run_id,
            state=RunState.TIMED_OUT,
            now_us=self._clock(),
            succeeded=None,
            task_hash=result.task_hash if result is not None else None,
            head_hash=result.head_hash if result is not None else None,
            error=message,
            artifact_path=str(artifact_path),
            note="watchdog: budget exhausted"
            + (", no evidence sealed" if result is None else ", partial evidence kept"),
        )
        report.timed_out += 1
        report.errors.append({"run_id": record.run_id, "error": message})

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

    def _handler_decisions(self) -> list[dict[str, Any]]:
        """What an attached checkpoint handler has decided so far, if it keeps a log."""
        log = getattr(self.run_config.get("checkpoint_handler"), "decisions", None)
        return list(log()) if callable(log) else []

    def _artifact_for(
        self,
        result: RunResult,
        record: RunRecord,
        *,
        checkpoint_decisions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """The full run artifact: everything the analysis will later read.

        The signed chain goes in whole. It is the evidence, and an artifact
        that summarised it would leave the verifier nothing to verify.
        """
        provenance = dict(self.run_config)
        handler = provenance.pop("checkpoint_handler", None)
        reproducible = "agent_kind" not in self.run_config
        artifact: dict[str, Any] = {
            "arm": record.arm,
            "chain": result.records,
            "experiment_id": record.experiment_id,
            "plan_order": record.plan_order,
            "provenance": provenance,
            "repetition": record.repetition,
            "result": result.to_dict(),
            "run_id": record.run_id,
            "state": RunState.COMPLETED,
            "task_id": record.task_id,
        }
        if handler is not None:
            # The handler object is not data; its class is. A handler that
            # says it is not deterministic (a person at a terminal) makes the
            # run not reproducible from the seed, and its own log of what it
            # was asked rides in the envelope, outside the signed chain.
            provenance["checkpoint_handler"] = type(handler).__name__
            reproducible = reproducible and getattr(handler, "deterministic", True) is not False
            artifact["checkpoint_decisions"] = list(checkpoint_decisions or [])
        artifact["reproducible"] = reproducible
        return artifact

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
