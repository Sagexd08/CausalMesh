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

__all__ = ["Entry", "Ledger"]

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

    # -- recording ---------------------------------------------------------

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
        from causalmesh.policy.contract import _budget_key

        if resource.amount is None:
            raise ValueError(f"{resource.identity} has no amount to record")
        key = _budget_key(resource)
        if key is None:
            raise ValueError(f"{resource.kind} is not a consumable resource")

        entry = Entry(
            agent_id=agent_id,
            amount=resource.amount,
            budget_key=key,
            identity=resource.identity,
            reference=reference,
            run_id=self.run_id,
            timestamp_us=now_us,
            unit=resource.unit,
        )
        self._connection.execute(
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
        return entry

    # -- reading -----------------------------------------------------------

    def total(self, *, agent_id: str, resource: Resource) -> Decimal:
        """What this agent has consumed against this resource's allowance."""
        from causalmesh.policy.contract import _budget_key

        key = _budget_key(resource)
        if key is None:
            return Decimal(0)
        rows = self._connection.execute(
            "SELECT amount FROM consumption WHERE run_id = ? AND agent_id = ? AND budget_key = ?",
            (self.run_id, agent_id, key),
        ).fetchall()
        # Summed as Decimal rather than in SQL: SQLite would coerce the TEXT
        # column to a float to add it, reintroducing exactly the imprecision
        # the string storage exists to avoid.
        return sum((Decimal(row["amount"]) for row in rows), Decimal(0))

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
