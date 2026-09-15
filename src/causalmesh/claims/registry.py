"""The claim registry: transactional write leases (spec §19, §20 and §21).

This is the enforcement half of the experiment. C3 differs from C2 by exactly
one thing — before an agent may write to a path, it must hold a valid claim on
it — so the registry's correctness is what makes the C2→C3 contrast mean
"enforcement" rather than "noise".

The invariant (§20):

    at most one valid writer claim may exist for a path at any instant

"Valid" means granted, not released and not expired. Expiry is evaluated
against the caller-supplied clock at every read, so a lease whose deadline has
passed stops blocking others even if nothing has swept the table.

Storage is SQLite with `BEGIN IMMEDIATE` rather than an in-memory lock. The
specification requires this (§19) and the reason is not ceremony: agents run
as separate OS processes (§11), so an in-process lock would enforce nothing
across the very boundary the experiment puts them on. `BEGIN IMMEDIATE` takes
the database write lock at statement start, which makes check-then-acquire a
single atomic step instead of a race.

Time is always passed in as integer microseconds rather than read from the
clock inside these methods. Tests can then drive expiry deterministically, and
a run's recorded lease behaviour can be replayed exactly.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..events.canonical import normalize_text

__all__ = [
    "Claim",
    "ClaimDeniedError",
    "ClaimError",
    "ClaimOutcome",
    "ClaimRegistry",
    "ClaimStatus",
]


class ClaimStatus(StrEnum):
    """Terminal and live states a claim can be in.

    `EXPIRED` and `RELEASED` are kept distinct even though both free the path:
    a lease that ran out is a coordination signal (the holder was too slow, or
    crashed), while a release is orderly completion. Collapsing them would
    erase that difference from the measurements (§21).
    """

    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


class ClaimError(ValueError):
    """Raised when a claim operation is structurally invalid."""


@dataclass(frozen=True, slots=True)
class Claim:
    """A write lease on one path."""

    claim_id: str
    path: str
    agent_id: str
    run_id: str
    issued_at_us: int
    expires_at_us: int
    renewed_at_us: int | None = None
    released_at_us: int | None = None
    status: ClaimStatus = ClaimStatus.ACTIVE
    renewals: int = 0

    def is_valid_at(self, now_us: int) -> bool:
        """Whether this claim blocks other writers at the given instant."""
        return self.status == ClaimStatus.ACTIVE and now_us < self.expires_at_us

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "claim_id": self.claim_id,
            "expires_at_us": self.expires_at_us,
            "issued_at_us": self.issued_at_us,
            "path": self.path,
            "released_at_us": self.released_at_us,
            "renewals": self.renewals,
            "renewed_at_us": self.renewed_at_us,
            "run_id": self.run_id,
            "status": str(self.status),
        }


@dataclass(frozen=True, slots=True)
class ClaimOutcome:
    """The result of an acquisition attempt.

    A denial is data, not an exception: §20 requires recording who was blocked,
    by whom and why, and the C3 arm's whole measurement rests on those records
    being complete. Raising instead would push each call site into deciding
    what to log.
    """

    granted: bool
    claim: Claim | None
    reason: str
    holder: Claim | None = None
    waited_us: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "granted": self.granted,
            "claim": self.claim.to_dict() if self.claim else None,
            "holder": self.holder.to_dict() if self.holder else None,
            "reason": self.reason,
            "waited_us": self.waited_us,
        }


class ClaimDeniedError(RuntimeError):
    """Raised only where a caller has asked for a claim to be mandatory."""

    def __init__(self, outcome: ClaimOutcome) -> None:
        super().__init__(outcome.reason)
        self.outcome = outcome


_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id      TEXT PRIMARY KEY,
    path          TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    issued_at_us  INTEGER NOT NULL,
    expires_at_us INTEGER NOT NULL,
    renewed_at_us INTEGER,
    released_at_us INTEGER,
    status        TEXT NOT NULL,
    renewals      INTEGER NOT NULL DEFAULT 0
);

-- Lookups are always "the live claim on this path in this run".
CREATE INDEX IF NOT EXISTS idx_claims_path_run ON claims (run_id, path, status);

-- Every denial is retained: it is the primary measurement of enforcement (§20).
CREATE TABLE IF NOT EXISTS denials (
    denial_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT NOT NULL,
    path             TEXT NOT NULL,
    requesting_agent TEXT NOT NULL,
    holder_agent     TEXT,
    holder_claim_id  TEXT,
    reason           TEXT NOT NULL,
    timestamp_us     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_denials_run ON denials (run_id);
"""


class ClaimRegistry:
    """A transactional registry of write leases.

    One registry serves a whole run. Paths are namespaced by `run_id` so
    concurrent runs sharing a database file cannot block one another — arms
    must not interfere (§2).
    """

    def __init__(self, database: Path | str = ":memory:") -> None:
        # ":memory:" is backed by a real file in a temporary directory rather
        # than by SQLite's in-memory mode. Two reasons, both about honesty:
        #
        # - A plain ":memory:" database is private to its connection, so
        #   threads would each get their own empty registry and the
        #   exclusivity tests would pass vacuously.
        # - The shared-cache in-memory form fixes that but uses table-level
        #   locking that fails immediately with "database table is locked"
        #   instead of honouring the busy timeout, so it behaves differently
        #   under contention than the file-backed path used in real runs.
        #
        # Using a temporary file means tests exercise exactly the code path
        # production uses, including WAL and the busy timeout.
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        if str(database) == ":memory:":
            self._temporary_directory = tempfile.TemporaryDirectory(
                prefix="causalmesh_claims_", ignore_cleanup_errors=True
            )
            self._database = str(Path(self._temporary_directory.name) / "claims.db")
        else:
            Path(database).parent.mkdir(parents=True, exist_ok=True)
            self._database = str(database)

        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()
        self._connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        """Open one connection with the settings every caller depends on."""
        # isolation_level=None puts transaction control in this class's hands,
        # so BEGIN IMMEDIATE means what it says rather than fighting sqlite3's
        # implicit transaction handling.
        connection = sqlite3.connect(self._database, isolation_level=None, timeout=30.0)
        connection.row_factory = sqlite3.Row
        # WAL lets readers proceed during a writer's transaction, which matters
        # once several agent processes share the file.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @property
    def _connection(self) -> sqlite3.Connection:
        """This thread's connection.

        A `sqlite3.Connection` may only be used by the thread that created it,
        so each thread gets its own rather than sharing one. Passing
        `check_same_thread=False` would silence the error while leaving the
        connection genuinely unsafe under concurrent use — the exclusivity
        invariant would then depend on luck.

        Serialization still happens where it belongs: in SQLite, through
        `BEGIN IMMEDIATE` on the database write lock, which works across
        threads and across processes alike.
        """
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = self._connect()
            self._local.connection = connection
            # Tracked so `close` can release connections opened by threads
            # that have since finished. Without this the registry leaks a file
            # handle per worker thread, which on Windows also makes the
            # database file undeletable.
            with self._connections_lock:
                self._connections.append(connection)
        return connection

    def close(self) -> None:
        """Close every connection this registry opened, from any thread."""
        with self._connections_lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            # A connection whose thread died mid-statement may refuse to
            # close; that must not prevent releasing the others.
            with suppress(sqlite3.Error):
                connection.close()
        self._local = threading.local()

        if self._temporary_directory is not None:
            # Windows can hold a handle briefly after the last connection
            # closes (WAL checkpointing on close), so removal may fail even
            # though every connection is shut. `ignore_cleanup_errors` leaves
            # the OS to reap the directory instead: a stray temp file is
            # cosmetic, whereas a `close` that raises would mask the real
            # outcome of whatever the caller was doing.
            self._temporary_directory.cleanup()
            self._temporary_directory = None

    def __enter__(self) -> ClaimRegistry:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Take the database write lock for the whole block.

        `BEGIN IMMEDIATE` acquires the lock up front rather than on first
        write. Without it, two callers could both read "no holder" before
        either inserted, and both would be granted the same path.
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

    @staticmethod
    def _row_to_claim(row: sqlite3.Row) -> Claim:
        return Claim(
            claim_id=row["claim_id"],
            path=row["path"],
            agent_id=row["agent_id"],
            run_id=row["run_id"],
            issued_at_us=row["issued_at_us"],
            expires_at_us=row["expires_at_us"],
            renewed_at_us=row["renewed_at_us"],
            released_at_us=row["released_at_us"],
            status=ClaimStatus(row["status"]),
            renewals=row["renewals"],
        )

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Canonicalize a path for comparison.

        Paths reach the registry from agents on different platforms, so
        separators are unified and Unicode is NFC-normalized. Without this,
        `src/a.py` and `src\\a.py` would be two different resources and the
        exclusivity invariant would silently not hold between them.
        """
        if not isinstance(path, str) or not path.strip():
            raise ClaimError(f"path must be a non-empty string, got {path!r}")
        return normalize_text(path.strip().replace("\\", "/"))

    def _live_holder(
        self, connection: sqlite3.Connection, run_id: str, path: str, now_us: int
    ) -> Claim | None:
        """Return the claim currently blocking this path, if any.

        Expiry is evaluated here rather than relying on a sweep, so a lease
        that has run out stops blocking immediately even if no one has tidied
        up. `expires_at_us > ?` makes expiry exclusive: a claim expiring
        exactly now is already free.
        """
        row = connection.execute(
            """
            SELECT * FROM claims
            WHERE run_id = ? AND path = ? AND status = ? AND expires_at_us > ?
            ORDER BY issued_at_us DESC LIMIT 1
            """,
            (run_id, path, str(ClaimStatus.ACTIVE), now_us),
        ).fetchone()
        return self._row_to_claim(row) if row else None

    @staticmethod
    def _expire_stale(connection: sqlite3.Connection, run_id: str, path: str, now_us: int) -> None:
        """Mark lapsed claims on a path as expired.

        Bookkeeping only — `_live_holder` already ignores them. Recording the
        transition is what makes expiries countable in the metrics (§21).
        """
        connection.execute(
            """
            UPDATE claims SET status = ?
            WHERE run_id = ? AND path = ? AND status = ? AND expires_at_us <= ?
            """,
            (str(ClaimStatus.EXPIRED), run_id, path, str(ClaimStatus.ACTIVE), now_us),
        )

    def acquire(
        self,
        *,
        claim_id: str,
        path: str,
        agent_id: str,
        run_id: str,
        now_us: int,
        duration_us: int,
    ) -> ClaimOutcome:
        """Attempt to acquire an exclusive write lease on a path.

        Check and insert happen inside one immediate transaction, which is
        what upholds the §20 invariant across processes.

        Re-acquisition by the current holder is granted and counted as a
        renewal rather than refused: an agent asking for a lease it already
        owns is not a conflict, and treating it as one would inflate the
        blocked-write rate that measures enforcement cost.
        """
        if duration_us <= 0:
            raise ClaimError(f"duration_us must be positive, got {duration_us}")
        normalized = self._normalize_path(path)

        with self._write_transaction() as connection:
            self._expire_stale(connection, run_id, normalized, now_us)
            holder = self._live_holder(connection, run_id, normalized, now_us)

            if holder is not None and holder.agent_id != agent_id:
                reason = (
                    f"path {normalized!r} is held by {holder.agent_id!r} until "
                    f"{holder.expires_at_us} (claim {holder.claim_id})"
                )
                connection.execute(
                    """
                    INSERT INTO denials
                        (run_id, path, requesting_agent, holder_agent, holder_claim_id,
                         reason, timestamp_us)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        normalized,
                        agent_id,
                        holder.agent_id,
                        holder.claim_id,
                        reason,
                        now_us,
                    ),
                )
                return ClaimOutcome(granted=False, claim=None, reason=reason, holder=holder)

            if holder is not None:
                # Same agent re-acquiring: extend rather than duplicate.
                connection.execute(
                    """
                    UPDATE claims
                    SET expires_at_us = ?, renewed_at_us = ?, renewals = renewals + 1
                    WHERE claim_id = ?
                    """,
                    (now_us + duration_us, now_us, holder.claim_id),
                )
                row = connection.execute(
                    "SELECT * FROM claims WHERE claim_id = ?", (holder.claim_id,)
                ).fetchone()
                return ClaimOutcome(
                    granted=True,
                    claim=self._row_to_claim(row),
                    reason="re-acquired by current holder",
                )

            try:
                connection.execute(
                    """
                    INSERT INTO claims
                        (claim_id, path, agent_id, run_id, issued_at_us, expires_at_us, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        normalized,
                        agent_id,
                        run_id,
                        now_us,
                        now_us + duration_us,
                        str(ClaimStatus.ACTIVE),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # A reused claim_id would make two leases indistinguishable in
                # the log, breaking idempotency (§42).
                raise ClaimError(f"claim_id {claim_id!r} already exists") from exc

            row = connection.execute(
                "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
            ).fetchone()
            return ClaimOutcome(granted=True, claim=self._row_to_claim(row), reason="granted")

    def renew(self, *, claim_id: str, agent_id: str, now_us: int, duration_us: int) -> ClaimOutcome:
        """Extend a lease the caller still holds.

        An expired lease cannot be renewed. Allowing it would let a crashed
        agent reclaim a path another agent had legitimately taken over, which
        is exactly the crash-recovery case §21 asks the lease engine to handle.
        """
        if duration_us <= 0:
            raise ClaimError(f"duration_us must be positive, got {duration_us}")

        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                return ClaimOutcome(False, None, f"no such claim {claim_id!r}")

            claim = self._row_to_claim(row)
            if claim.agent_id != agent_id:
                return ClaimOutcome(
                    False,
                    None,
                    f"claim {claim_id!r} belongs to {claim.agent_id!r}, not {agent_id!r}",
                    holder=claim,
                )
            if claim.status != ClaimStatus.ACTIVE:
                return ClaimOutcome(False, None, f"claim {claim_id!r} is {claim.status}")
            if now_us >= claim.expires_at_us:
                connection.execute(
                    "UPDATE claims SET status = ? WHERE claim_id = ?",
                    (str(ClaimStatus.EXPIRED), claim_id),
                )
                return ClaimOutcome(
                    False,
                    None,
                    f"claim {claim_id!r} expired at {claim.expires_at_us}; cannot renew",
                )

            connection.execute(
                """
                UPDATE claims
                SET expires_at_us = ?, renewed_at_us = ?, renewals = renewals + 1
                WHERE claim_id = ?
                """,
                (now_us + duration_us, now_us, claim_id),
            )
            renewed = connection.execute(
                "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
            ).fetchone()
            return ClaimOutcome(True, self._row_to_claim(renewed), "renewed")

    def release(self, *, claim_id: str, agent_id: str, now_us: int) -> ClaimOutcome:
        """Release a lease, freeing the path immediately."""
        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
            ).fetchone()
            if row is None:
                return ClaimOutcome(False, None, f"no such claim {claim_id!r}")

            claim = self._row_to_claim(row)
            if claim.agent_id != agent_id:
                return ClaimOutcome(
                    False,
                    None,
                    f"claim {claim_id!r} belongs to {claim.agent_id!r}, not {agent_id!r}",
                    holder=claim,
                )
            if claim.status != ClaimStatus.ACTIVE:
                # Idempotent: releasing twice is not an error (§42).
                return ClaimOutcome(True, claim, f"already {claim.status}")

            connection.execute(
                "UPDATE claims SET status = ?, released_at_us = ? WHERE claim_id = ?",
                (str(ClaimStatus.RELEASED), now_us, claim_id),
            )
            released = connection.execute(
                "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
            ).fetchone()
            return ClaimOutcome(True, self._row_to_claim(released), "released")

    def check(self, *, path: str, run_id: str, now_us: int) -> Claim | None:
        """Return the claim blocking this path right now, if any.

        Read-only, so the write gate can consult it without perturbing state.
        """
        normalized = self._normalize_path(path)
        return self._live_holder(self._connection, run_id, normalized, now_us)

    def may_write(self, *, path: str, agent_id: str, run_id: str, now_us: int) -> ClaimOutcome:
        """Ask whether this agent could write to this path. **Read-only.**

        A path with no live holder is writable. This is deliberate — claims are
        exclusive when held, not mandatory before every write — so the
        registry stays usable for the specific enforcement C3 defines rather
        than imposing a stricter regime the experiment never asked for.

        This method records nothing, and must not. It is an advisory query
        that callers may make speculatively and repeatedly; if it wrote a
        denial, the enforcement measurement would count *questions* rather
        than *blocks* and would depend on how often the gate happened to be
        consulted. `record_denial` is the separate, explicit act of saying
        "a real write attempt was refused".
        """
        holder = self.check(path=path, run_id=run_id, now_us=now_us)
        if holder is None:
            return ClaimOutcome(True, None, "no live claim on this path")
        if holder.agent_id == agent_id:
            return ClaimOutcome(True, holder, "caller holds the claim", holder=holder)
        return ClaimOutcome(
            False,
            None,
            (
                f"write to {holder.path!r} denied: held by {holder.agent_id!r} "
                f"until {holder.expires_at_us} (claim {holder.claim_id})"
            ),
            holder=holder,
        )

    def record_denial(
        self,
        *,
        path: str,
        requesting_agent: str,
        run_id: str,
        now_us: int,
        holder: Claim | None,
        reason: str,
    ) -> None:
        """Record that a real write attempt was refused (§20).

        Separate from `may_write` on purpose. `may_write` answers a
        question and may be asked speculatively; this states that a call
        actually reached the gate and was stopped. Merging them would make
        the denial count depend on how often the gate was consulted, and
        keeping them apart means the count measures blocked *work*.

        This exists because for several steps nothing called it: denials
        were written only by `acquire`, while the C3 gate refuses through
        `may_write`. Every block the gate performed was therefore invisible
        to `denials()` — the method whose own docstring calls it the core
        enforcement measurement. A real C3 run reported 2 claims held and 0
        denials while enforcement was working correctly. A measurement that
        cannot observe its subject is worse than a missing one, because it
        reports a confident zero.
        """
        with self._write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO denials
                    (run_id, path, requesting_agent, holder_agent, holder_claim_id,
                     reason, timestamp_us)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    self._normalize_path(path),
                    requesting_agent,
                    holder.agent_id if holder else None,
                    holder.claim_id if holder else None,
                    reason,
                    now_us,
                ),
            )

    def expire(self, *, run_id: str, now_us: int) -> int:
        """Sweep lapsed claims in a run, returning how many were expired."""
        with self._write_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE claims SET status = ?
                WHERE run_id = ? AND status = ? AND expires_at_us <= ?
                """,
                (str(ClaimStatus.EXPIRED), run_id, str(ClaimStatus.ACTIVE), now_us),
            )
            return cursor.rowcount

    def active_claims(self, *, run_id: str, now_us: int) -> list[Claim]:
        rows = self._connection.execute(
            """
            SELECT * FROM claims
            WHERE run_id = ? AND status = ? AND expires_at_us > ?
            ORDER BY issued_at_us
            """,
            (run_id, str(ClaimStatus.ACTIVE), now_us),
        ).fetchall()
        return [self._row_to_claim(row) for row in rows]

    def history(self, *, run_id: str) -> list[Claim]:
        """Every claim ever issued in a run, in issue order (§56 timeline)."""
        rows = self._connection.execute(
            "SELECT * FROM claims WHERE run_id = ? ORDER BY issued_at_us, claim_id", (run_id,)
        ).fetchall()
        return [self._row_to_claim(row) for row in rows]

    def denials(self, *, run_id: str) -> list[dict[str, Any]]:
        """Every blocked write in a run — the core enforcement measurement."""
        rows = self._connection.execute(
            "SELECT * FROM denials WHERE run_id = ? ORDER BY timestamp_us, denial_id", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]
