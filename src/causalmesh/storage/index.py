"""The operational run index (spec §42, §63, §80).

A SQLite table recording every planned run and the state it reached. This
is *operational* data, not evidence: the evidence is the signed chain and
the run artifacts under `data/raw/`. The index exists so a collection can
be resumed, so a duplicate execution can be refused, and so `causalmesh
experiment status` can answer "what is left" without walking the filesystem.

The distinction matters for §31. Raw evidence is immutable; this index is
mutable by design, because a run's *state* legitimately changes as it
progresses. Nothing here is an input to any reported number — the analysis
reads run artifacts, never this table — so mutating it cannot alter a
result. What it can do is prevent a result from being produced twice, which
is exactly its job.

Idempotency (§42) is enforced by the primary key plus the state machine:
recording a run that already exists is a no-op if nothing changed, and an
illegal transition (COMPLETED back to RUNNING, say) raises rather than
silently overwriting a finished result.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..scheduler.states import RunState, check_transition, is_retryable, is_terminal

__all__ = ["RunIndex", "RunRecord"]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    task_id       TEXT NOT NULL,
    arm           TEXT NOT NULL,
    repetition    INTEGER NOT NULL,
    plan_order    INTEGER NOT NULL,
    state         TEXT NOT NULL,
    -- Task outcome, kept separate from `state`: a run can be COMPLETED and
    -- have failed its task. Nullable because it is unknown until the run
    -- produces a verdict, and NULL must stay distinguishable from False.
    succeeded     INTEGER,
    task_hash     TEXT,
    head_hash     TEXT,
    error         TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    started_at_us  INTEGER,
    finished_at_us INTEGER,
    artifact_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_experiment ON runs (experiment_id, state);
CREATE INDEX IF NOT EXISTS idx_runs_cell ON runs (experiment_id, task_id, arm);

-- Every state change, retained. A run that was abandoned and resumed twice
-- looks identical in `runs` to one that ran cleanly, and the difference is
-- something an audit needs to see (§80).
CREATE TABLE IF NOT EXISTS transitions (
    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    from_state    TEXT,
    to_state      TEXT NOT NULL,
    at_us         INTEGER NOT NULL,
    note          TEXT
);

CREATE INDEX IF NOT EXISTS idx_transitions_run ON transitions (run_id);

-- One row per planned collection, so a resume can check it is resuming the
-- same plan rather than a re-planned one that happens to share an id.
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    profile       TEXT NOT NULL,
    plan_hash     TEXT NOT NULL,
    run_count     INTEGER NOT NULL,
    created_at_us INTEGER NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One run's operational status."""

    run_id: str
    experiment_id: str
    task_id: str
    arm: str
    repetition: int
    plan_order: int
    state: str
    succeeded: bool | None = None
    task_hash: str | None = None
    head_hash: str | None = None
    error: str | None = None
    attempts: int = 0
    started_at_us: int | None = None
    finished_at_us: int | None = None
    artifact_path: str | None = None

    @property
    def is_terminal(self) -> bool:
        return is_terminal(self.state)

    @property
    def is_retryable(self) -> bool:
        return is_retryable(self.state)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "artifact_path": self.artifact_path,
            "attempts": self.attempts,
            "error": self.error,
            "experiment_id": self.experiment_id,
            "finished_at_us": self.finished_at_us,
            "head_hash": self.head_hash,
            "plan_order": self.plan_order,
            "repetition": self.repetition,
            "run_id": self.run_id,
            "started_at_us": self.started_at_us,
            "state": self.state,
            "succeeded": self.succeeded,
            "task_hash": self.task_hash,
            "task_id": self.task_id,
        }

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> RunRecord:
        return cls(
            run_id=row["run_id"],
            experiment_id=row["experiment_id"],
            task_id=row["task_id"],
            arm=row["arm"],
            repetition=row["repetition"],
            plan_order=row["plan_order"],
            state=row["state"],
            # SQLite has no boolean type. The explicit None check keeps
            # "unknown" distinct from "failed"; `bool(row[...])` would
            # collapse them and make an unfinished run look like a failure.
            succeeded=None if row["succeeded"] is None else bool(row["succeeded"]),
            task_hash=row["task_hash"],
            head_hash=row["head_hash"],
            error=row["error"],
            attempts=row["attempts"],
            started_at_us=row["started_at_us"],
            finished_at_us=row["finished_at_us"],
            artifact_path=row["artifact_path"],
        )


class RunIndex:
    """A SQLite index of run states, safe across threads and processes."""

    def __init__(self, database: Path | str) -> None:
        # No ":memory:" special case here, unlike the claim registry: this
        # index is only meaningful when it outlives the process, since its
        # entire purpose is resume. Tests pass a tmp_path file, which is the
        # production path.
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self._database = str(database)
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()
        self._connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, isolation_level=None, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @property
    def _connection(self) -> sqlite3.Connection:
        """This thread's connection.

        Same rule as the claim registry: a connection belongs to the thread
        that opened it, and every connection is tracked so `close` can
        release the ones belonging to threads that have finished. Without
        that, Windows keeps the database file locked and a test's tmp_path
        cleanup fails with WinError 32.
        """
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = self._connect()
            self._local.connection = connection
            with self._connections_lock:
                self._connections.append(connection)
        return connection

    def close(self) -> None:
        with self._connections_lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            with suppress(sqlite3.Error):
                connection.close()
        self._local = threading.local()

    def __enter__(self) -> RunIndex:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """Take the write lock for the whole block.

        `BEGIN IMMEDIATE` for the same reason the claim registry uses it:
        claiming a run and marking it RUNNING must be one atomic step, or
        two workers could both read PLANNED and both execute it.
        """
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")

    # -- planning ---------------------------------------------------------

    def register_plan(self, plan: Any, *, now_us: int) -> int:
        """Record a plan and its runs. Returns how many rows were new.

        Idempotent (§42): re-registering the same plan inserts nothing and
        touches no existing state, so re-running `experiment plan` before a
        resume cannot reset progress. A plan whose hash differs from the
        stored one is refused, because silently adopting it would mean
        resuming a collection under a design that changed mid-flight.
        """
        with self._write() as connection:
            existing = connection.execute(
                "SELECT plan_hash FROM experiments WHERE experiment_id = ?",
                (plan.experiment_id,),
            ).fetchone()
            plan_hash = plan.content_hash()
            if existing is not None and existing["plan_hash"] != plan_hash:
                raise ValueError(
                    f"experiment {plan.experiment_id!r} already exists with a "
                    f"different plan (stored {existing['plan_hash'][:12]}, "
                    f"given {plan_hash[:12]}). Resuming under a changed design "
                    "would pool runs from two different experiments; use a new "
                    "experiment_id."
                )
            if existing is None:
                connection.execute(
                    "INSERT INTO experiments "
                    "(experiment_id, profile, plan_hash, run_count, created_at_us) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        plan.experiment_id,
                        plan.profile,
                        plan_hash,
                        len(plan.runs),
                        now_us,
                    ),
                )

            inserted = 0
            for run in plan.runs:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO runs "
                    "(run_id, experiment_id, task_id, arm, repetition, plan_order, state) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        run.run_id,
                        run.experiment_id,
                        run.task_id,
                        run.arm,
                        run.repetition,
                        run.order,
                        RunState.PLANNED,
                    ),
                )
                if cursor.rowcount:
                    inserted += 1
                    connection.execute(
                        "INSERT INTO transitions (run_id, from_state, to_state, at_us, note) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (run.run_id, None, RunState.PLANNED, now_us, "planned"),
                    )
            return inserted

    def plan_hash(self, experiment_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT plan_hash FROM experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        return row["plan_hash"] if row else None

    # -- claiming and finishing -------------------------------------------

    def claim_next(self, experiment_id: str, *, now_us: int) -> RunRecord | None:
        """Atomically take the next runnable run and mark it RUNNING.

        Selection follows `plan_order`, which is the randomized order fixed
        at plan time (§41). Taking runs in any other order — by task, or by
        arm — would reintroduce exactly the block structure the
        randomization removes.

        The whole select-then-update happens inside one IMMEDIATE
        transaction so two workers cannot claim the same run.
        """
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE experiment_id = ? AND state IN (?, ?) "
                "ORDER BY plan_order LIMIT 1",
                (experiment_id, RunState.PLANNED, RunState.ABANDONED),
            ).fetchone()
            if row is None:
                return None

            record = RunRecord._from_row(row)
            check_transition(record.state, RunState.RUNNING)
            connection.execute(
                "UPDATE runs SET state = ?, attempts = attempts + 1, started_at_us = ? "
                "WHERE run_id = ?",
                (RunState.RUNNING, now_us, record.run_id),
            )
            connection.execute(
                "INSERT INTO transitions (run_id, from_state, to_state, at_us, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.run_id,
                    record.state,
                    RunState.RUNNING,
                    now_us,
                    "resumed" if record.state == RunState.ABANDONED else "started",
                ),
            )
            return RunRecord._from_row(
                connection.execute(
                    "SELECT * FROM runs WHERE run_id = ?", (record.run_id,)
                ).fetchone()
            )

    def finish(
        self,
        run_id: str,
        *,
        state: str,
        now_us: int,
        succeeded: bool | None = None,
        task_hash: str | None = None,
        head_hash: str | None = None,
        error: str | None = None,
        artifact_path: str | None = None,
        note: str = "",
    ) -> RunRecord:
        """Move a run to a terminal state and record what it produced.

        `succeeded` is the *task* outcome and is independent of `state`: a
        COMPLETED run may have `succeeded=False`, which is a perfectly good
        result and must appear in the denominator (§81).
        """
        with self._write() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"no run {run_id!r} in the index")
            current = RunRecord._from_row(row)
            check_transition(current.state, state)
            connection.execute(
                "UPDATE runs SET state = ?, succeeded = ?, task_hash = ?, "
                "head_hash = ?, error = ?, finished_at_us = ?, artifact_path = ? "
                "WHERE run_id = ?",
                (
                    state,
                    None if succeeded is None else int(succeeded),
                    task_hash,
                    head_hash,
                    error,
                    now_us,
                    artifact_path,
                    run_id,
                ),
            )
            connection.execute(
                "INSERT INTO transitions (run_id, from_state, to_state, at_us, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, current.state, state, now_us, note or state),
            )
            return RunRecord._from_row(
                connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            )

    def abandon_running(self, experiment_id: str, *, now_us: int, note: str = "") -> int:
        """Mark every RUNNING run of this experiment ABANDONED.

        Called when a collection starts, to clean up after a previous
        process that was killed. A run left RUNNING by a crash is not a
        result — nothing recorded a verdict for it — so it becomes
        ABANDONED and is eligible for re-execution. Leaving it RUNNING
        would strand it forever, since `claim_next` skips that state.
        """
        with self._write() as connection:
            rows = connection.execute(
                "SELECT run_id FROM runs WHERE experiment_id = ? AND state = ?",
                (experiment_id, RunState.RUNNING),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE runs SET state = ? WHERE run_id = ?",
                    (RunState.ABANDONED, row["run_id"]),
                )
                connection.execute(
                    "INSERT INTO transitions (run_id, from_state, to_state, at_us, note) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        row["run_id"],
                        RunState.RUNNING,
                        RunState.ABANDONED,
                        now_us,
                        note or "found running at startup; previous process did not finish",
                    ),
                )
            return len(rows)

    # -- reading ----------------------------------------------------------

    def get(self, run_id: str) -> RunRecord | None:
        row = self._connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return RunRecord._from_row(row) if row else None

    def runs(self, experiment_id: str, *, state: str | None = None) -> list[RunRecord]:
        if state is None:
            rows = self._connection.execute(
                "SELECT * FROM runs WHERE experiment_id = ? ORDER BY plan_order",
                (experiment_id,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM runs WHERE experiment_id = ? AND state = ? ORDER BY plan_order",
                (experiment_id, state),
            ).fetchall()
        return [RunRecord._from_row(row) for row in rows]

    def transitions(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT from_state, to_state, at_us, note FROM transitions "
            "WHERE run_id = ? ORDER BY transition_id",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def counts(self, experiment_id: str) -> dict[str, int]:
        """How many runs sit in each state.

        Every state appears, including the zeroes. A status display that
        omitted empty states would make "no failures" look identical to
        "failures not counted".
        """
        rows = self._connection.execute(
            "SELECT state, COUNT(*) AS n FROM runs WHERE experiment_id = ? GROUP BY state",
            (experiment_id,),
        ).fetchall()
        counts = dict.fromkeys(sorted(RunState.ALL), 0)
        for row in rows:
            counts[row["state"]] = row["n"]
        return counts

    def is_complete(self, experiment_id: str) -> bool:
        """Whether every planned run has reached a terminal state."""
        row = self._connection.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE experiment_id = ? AND state NOT IN (?, ?, ?)",
            (
                experiment_id,
                RunState.COMPLETED,
                RunState.FAILED,
                RunState.TIMED_OUT,
            ),
        ).fetchone()
        return row["n"] == 0
