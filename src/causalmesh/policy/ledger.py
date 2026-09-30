"""What has already been consumed, recorded across processes.

**Why this is not a counter in memory.** Agents run as separate OS processes.
A per-process tally would let each one spend the whole budget independently,
and the total would be exceeded by exactly the number of agents — silently,
because every process would believe it was within limits. The same reasoning
put the claim registry in SQLite rather than behind a lock, and it applies
here for the same reason.

**Every entry is an action that happened.** The ledger records consumption,
not intent: a gate check that refused writes nothing, and a gate check that
allowed writes nothing either. Only the caller, having actually performed the
action, records it. That keeps totals measuring *work done* rather than
*questions asked* — the distinction `may_write` and `record_denial` already
draw in the claim registry.

**Reserve, then commit.** A check that reads the total and a record that adds
to it are two steps, and two callers can both pass the first before either
makes the second. So a declared total is enforced by a *reservation*: `reserve`
sums what is recorded and what is already held, compares against the limit and
inserts the hold inside one `BEGIN IMMEDIATE` transaction, which SQLite
serialises across threads and processes. The caller then acts and either
`commit`s (the hold becomes an entry, in one transaction) or `release`s it.
`total` is still only what happened; a hold is a promise that the money may
leave, counted against the allowance until it does or does not. A holder that
dies leaves its hold behind, which over-counts (fails closed) until an
operator calls `release_all`.

**Decimal end to end.** Amounts are stored as strings and compared as
`Decimal`. A float column would make a budget drift by fractions of a cent
until it did not hold, and money that rounds is money that is wrong.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from causalmesh.policy.resource import Resource

__all__ = ["Entry", "Ledger", "Reservation", "ReserveOutcome"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS consumption (
    entry_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    kind         TEXT NOT NULL,
    identity     TEXT NOT NULL,
    budget_key   TEXT NOT NULL,
    amount       TEXT NOT NULL,
    unit         TEXT NOT NULL DEFAULT '',
    reference    TEXT,
    timestamp_us INTEGER NOT NULL
);

-- The query the gate makes on every spend check.
CREATE INDEX IF NOT EXISTS idx_consumption_lookup
    ON consumption (run_id, agent_id, budget_key);

-- Live holds: amounts promised to a call that has not finished. A row here is
-- counted against the allowance until it is committed (moved to consumption)
-- or released (deleted).
CREATE TABLE IF NOT EXISTS reservation (
    reservation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL,
    agent_id       TEXT NOT NULL,
    kind           TEXT NOT NULL,
    identity       TEXT NOT NULL,
    budget_key     TEXT NOT NULL,
    amount         TEXT NOT NULL,
    unit           TEXT NOT NULL DEFAULT '',
    created_us     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reservation_lookup
    ON reservation (run_id, agent_id, budget_key);
"""


@dataclass(frozen=True, slots=True)
class Entry:
    """One recorded consumption."""

    agent_id: str
    amount: Decimal
    budget_key: str
    identity: str
    run_id: str
    timestamp_us: int
    unit: str = ""
    reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "amount": f"{self.amount:f}",
            "budget_key": self.budget_key,
            "identity": self.identity,
            "reference": self.reference,
            "run_id": self.run_id,
            "timestamp_us": self.timestamp_us,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class Reservation:
    """An amount held against an allowance while a call runs.

    Opaque to callers: hand it back to `Ledger.commit` or `Ledger.release`.
    """

    reservation_id: int
    agent_id: str
    budget_key: str
    resource: Resource


@dataclass(frozen=True, slots=True)
class ReserveOutcome:
    """What `Ledger.reserve` decided, as data.

    `reservation` is `None` when the hold was refused; `spent` and `held` are
    what the same transaction saw, so a refusal can name the numbers it was
    decided on rather than numbers read a moment later.
    """

    reservation: Reservation | None
    spent: Decimal
    held: Decimal

    @property
    def granted(self) -> bool:
        return self.reservation is not None


class Ledger:
    """Consumption for one run, shared across every process in it."""

    def __init__(self, database: Path | str, *, run_id: str) -> None:
        self.run_id = run_id
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self._database = str(database)
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self._connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, isolation_level=None, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @property
    def _connection(self) -> sqlite3.Connection:
        """This thread's connection.

        Per-thread for the same reason the claim registry is: a
        `sqlite3.Connection` may only be used by its creating thread, and
        passing `check_same_thread=False` would silence the error while
        leaving the connection genuinely unsafe.
        """
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = self._connect()
            self._local.connection = connection
            with self._lock:
                self._connections.append(connection)
        return connection

    def close(self) -> None:
        with self._lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            with suppress(sqlite3.Error):
                connection.close()
        self._local = threading.local()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def record(
        self,
        *,
        agent_id: str,
        resource: Resource,
        now_us: int,
        reference: str | None = None,
    ) -> Entry:
        """Record that this agent actually consumed this resource.

        Called after the action, never before. A recorded entry means the
        money left or the tokens were burned; recording on intent would make
        a refused action count against the budget it never touched.
        """
        key, amount = self._consumable(resource)
        entry = Entry(
            agent_id=agent_id,
            amount=amount,
            budget_key=key,
            identity=resource.identity,
            reference=reference,
            run_id=self.run_id,
            timestamp_us=now_us,
            unit=resource.unit,
        )
        self._insert(self._connection, entry, resource)
        return entry

    def reserve(
        self,
        *,
        agent_id: str,
        resource: Resource,
        limit: Decimal,
        now_us: int,
        enforce: bool = True,
    ) -> ReserveOutcome:
        """Hold this resource's amount against `limit`, atomically.

        The sum of recorded consumption and live holds is read, compared and
        the hold inserted under one write transaction (`BEGIN IMMEDIATE`), so
        callers racing on the same allowance, in any number of threads or
        processes, are admitted one at a time against the true remainder.
        Refused as data when `spent + held + amount` would exceed `limit`.

        `enforce=False` takes the hold anyway and still reports the numbers:
        an unenforced arm records what it spends and learns what it would
        have been refused.
        """
        key, amount = self._consumable(resource)
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            spent = self._sum(connection, "consumption", agent_id, key)
            held = self._sum(connection, "reservation", agent_id, key)
            if enforce and spent + held + amount > limit:
                connection.execute("COMMIT")
                return ReserveOutcome(None, spent, held)
            cursor = connection.execute(
                """
                INSERT INTO reservation
                    (run_id, agent_id, kind, identity, budget_key, amount, unit, created_us)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.run_id,
                    agent_id,
                    resource.kind.value,
                    resource.identity,
                    key,
                    f"{amount:f}",
                    resource.unit,
                    now_us,
                ),
            )
            connection.execute("COMMIT")
        except BaseException:
            with suppress(sqlite3.Error):
                connection.execute("ROLLBACK")
            raise
        assert cursor.lastrowid is not None
        return ReserveOutcome(Reservation(cursor.lastrowid, agent_id, key, resource), spent, held)

    def commit(
        self, reservation: Reservation, *, now_us: int, reference: str | None = None
    ) -> Entry:
        """The held amount was spent: turn the hold into a recorded entry.

        One transaction, so the amount is never counted twice and never
        dropped between the two tables. If the hold is already gone (an
        operator's `release_all`), the entry is written anyway: the money
        left, and the record follows what happened, not what was promised.
        """
        entry = self._entry(reservation, now_us=now_us, reference=reference)
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "DELETE FROM reservation WHERE reservation_id = ?", (reservation.reservation_id,)
            )
            self._insert(connection, entry, reservation.resource)
            connection.execute("COMMIT")
        except BaseException:
            with suppress(sqlite3.Error):
                connection.execute("ROLLBACK")
            raise
        return entry

    def release(self, reservation: Reservation) -> bool:
        """The held amount was not spent: give it back. `False` if already gone."""
        cursor = self._connection.execute(
            "DELETE FROM reservation WHERE reservation_id = ?", (reservation.reservation_id,)
        )
        return cursor.rowcount > 0

    def held(self, *, agent_id: str, resource: Resource) -> Decimal:
        """What is currently held, not yet spent, against this resource's allowance."""
        from causalmesh.policy.contract import _budget_key

        key = _budget_key(resource)
        if key is None:
            return Decimal(0)
        return self._sum(self._connection, "reservation", agent_id, key)

    def release_all(self) -> int:
        """Drop every live hold in this run; the count released.

        For an operator recovering from a holder that died mid-call. Only safe
        when nothing in the run is still executing.
        """
        cursor = self._connection.execute(
            "DELETE FROM reservation WHERE run_id = ?", (self.run_id,)
        )
        return cursor.rowcount

    def _sum(self, connection: sqlite3.Connection, table: str, agent_id: str, key: str) -> Decimal:
        # Decimal summed in Python: SQL SUM would coerce the string column to a float.
        rows = connection.execute(
            f"SELECT amount FROM {table} WHERE run_id = ? AND agent_id = ? AND budget_key = ?",  # noqa: S608 - table is one of two constants
            (self.run_id, agent_id, key),
        ).fetchall()
        return sum((Decimal(row["amount"]) for row in rows), Decimal(0))

    @staticmethod
    def _consumable(resource: Resource) -> tuple[str, Decimal]:
        from causalmesh.policy.contract import _budget_key

        if resource.amount is None:
            raise ValueError(f"{resource.identity} has no amount to record")
        key = _budget_key(resource)
        if key is None:
            raise ValueError(f"{resource.kind} is not a consumable resource")
        return key, resource.amount

    def _entry(self, reservation: Reservation, *, now_us: int, reference: str | None) -> Entry:
        resource = reservation.resource
        key, amount = self._consumable(resource)
        return Entry(
            agent_id=reservation.agent_id,
            amount=amount,
            budget_key=key,
            identity=resource.identity,
            reference=reference,
            run_id=self.run_id,
            timestamp_us=now_us,
            unit=resource.unit,
        )

    @staticmethod
    def _insert(connection: sqlite3.Connection, entry: Entry, resource: Resource) -> None:
        connection.execute(
            """
            INSERT INTO consumption
                (run_id, agent_id, kind, identity, budget_key, amount, unit,
                 reference, timestamp_us)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.run_id,
                entry.agent_id,
                resource.kind.value,
                entry.identity,
                entry.budget_key,
                f"{entry.amount:f}",
                entry.unit,
                entry.reference,
                entry.timestamp_us,
            ),
        )

    def total(self, *, agent_id: str, resource: Resource) -> Decimal:
        """What this agent has consumed against this resource's allowance.

        Recorded consumption only: live holds are `held`, and the gate counts
        both.
        """
        from causalmesh.policy.contract import _budget_key

        key = _budget_key(resource)
        if key is None:
            return Decimal(0)
        return self._sum(self._connection, "consumption", agent_id, key)

    def entries(self, *, agent_id: str | None = None) -> list[Entry]:
        """Everything recorded in this run, oldest first."""
        if agent_id is None:
            rows = self._connection.execute(
                "SELECT * FROM consumption WHERE run_id = ? ORDER BY timestamp_us, entry_id",
                (self.run_id,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM consumption WHERE run_id = ? AND agent_id = ?
                ORDER BY timestamp_us, entry_id
                """,
                (self.run_id, agent_id),
            ).fetchall()
        return [
            Entry(
                agent_id=row["agent_id"],
                amount=Decimal(row["amount"]),
                budget_key=row["budget_key"],
                identity=row["identity"],
                reference=row["reference"],
                run_id=row["run_id"],
                timestamp_us=row["timestamp_us"],
                unit=row["unit"],
            )
            for row in rows
        ]
