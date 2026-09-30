"""x402 payment orchestration: decide, reserve, pay through the operator's code, record.

`adapters/x402.py` parses a 402 challenge and asks the gate. This module is
the operator-facing half that was missing: the sequence that turns an
*allowed* decision into a payment without this project ever holding a wallet,
a private key, a crypto dependency or an HTTP client.

**What the library does and does not do.**

- It never signs and never touches the network. The operator supplies two
  callables: a `PaymentSigner` (forms the payment payload for their scheme and
  network) and a `send` function (retries the original request carrying the
  payment header, using whatever HTTP client the operator already has).
- It decides through the gate, refuses as data when the gate refuses, and
  calls the operator's code only when allowed.
- It records the spend, but never as a silent zero.

**Why this is reserve-then-commit and not "record afterward".** Recording
only after success cannot be made safe: if the process dies, the signer
raises or the network drops *after* money may have left, nothing would be
recorded and the budget would be under-counted with total confidence, which
`docs/backlog.md` calls the worst failure this project can have. So every
attempt goes through a `PaymentJournal` (SQLite, shared across processes):

1. `reserve`: one atomic transaction that (a) refuses a repeated idempotency
   key, and (b) refuses if the ledger's recorded spend plus every payment
   still in flight plus this amount would exceed the declared total. The
   reservation counts against the budget from this moment.
2. The operator's signer and `send` run.
3. The outcome is classified and committed to the journal, then to the
   `Ledger`:

   | outcome    | meaning                                            | ledger        |
   |------------|----------------------------------------------------|---------------|
   | `paid`     | 2xx from the server                                | recorded      |
   | `unknown`  | money may have moved, and we cannot tell           | recorded      |
   | `rejected` | the server answered 402 again: payment not accepted| not recorded  |
   | `not_sent` | the operator's code raised `PaymentNotSent`        | not recorded  |

   `unknown` is recorded at the full amount. Over-counting is the safe
   direction; the entry's `reference` (`x402:<key>:unknown`) says it is
   unconfirmed, and `PaymentJournal.resolve` lets an operator settle it once
   they have checked the chain. Any exception from the operator's signer or
   `send` other than `PaymentNotSent` is `unknown`, not `not_sent`: arbitrary
   operator code may have moved money before it failed, and only the operator
   can certify that it did not.

**Idempotency.** The caller supplies a key that names one logical purchase
(for example a hash of the resource URL plus the agent's own request id). A
second call with the same key never reaches the signer while the first is in
flight, paid or unknown. A key whose earlier attempt was `rejected` or
`not_sent` (certified: no money moved) may be retried.

**Limits, stated plainly.** This is not a transaction with the payment
network: a process killed between "money left" and the journal commit leaves a
`reserved` row, which stays counted against the budget until an operator
resolves it. The 2xx-means-paid and 402-means-rejected classification is an
assumption about servers that follow the x402 reference flow; anything else
(3xx, other 4xx, 5xx, a malformed return value) is `unknown`. Nothing here has
been exercised against a real facilitator or real funds. See
`docs/backlog.md`, "Spend is enforced, but nothing speaks x402".

**How an operator wires it.**

    class MySigner:                       # satisfies PaymentSigner
        def sign(self, requirement, *, x402_version):
            return my_scheme_specific_signature(requirement)   # header value

    def send(headers):                    # the operator's own HTTP call
        r = my_http.get(url, headers=headers)
        return PaymentResponse(r.status_code, dict(r.headers), r.content)

    outcome = pay_if_allowed(
        payment_required, gate=gate, ledger=ledger, journal=journal,
        signer=MySigner(), send=send, agent_id="buyer",
        idempotency_key="order-123", now_us=now_us,
    )

Attach the same `ledger` to the gate (`gate.attach_ledger(ledger)`), or let
`pay_if_allowed` do it when the gate has none: a total budget with no ledger
behind it is not enforced.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..policy.gate import Gate, Verdict
from ..policy.resource import Resource
from .x402 import (
    PAYMENT_RESPONSE_HEADER,
    PAYMENT_SIGNATURE_HEADER,
    X_PAYMENT_HEADER,
    X_PAYMENT_RESPONSE_HEADER,
    PaymentDecision,
    PaymentRequired,
    PaymentRequirement,
    decide_payment,
    resource_for,
)

if TYPE_CHECKING:
    from ..policy.ledger import Ledger

__all__ = [
    "JournalRecord",
    "PayStatus",
    "PaymentJournal",
    "PaymentNotSent",
    "PaymentOutcome",
    "PaymentResponse",
    "PaymentSigner",
    "Sender",
    "pay_if_allowed",
]

_BUDGET_KEY = "usd_total"  # what policy.contract._budget_key returns for a spend

# Journal states. `reserved` is in flight; `paid` and `unknown` block a retry
# and are (or are due to be) written to the ledger; `rejected` and `not_sent`
# certify that no money moved; `resolved_paid` / `resolved_unpaid` are an
# operator's later settlement of an `unknown` or stuck `reserved` row.
_BLOCKING_STATES = ("reserved", "paid", "unknown", "resolved_paid")
_COUNTED_STATES = ("paid", "unknown", "resolved_paid")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS x402_payments (
    idempotency_key TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    budget_key      TEXT NOT NULL,
    identity        TEXT NOT NULL,
    amount          TEXT NOT NULL,
    unit            TEXT NOT NULL DEFAULT '',
    network         TEXT NOT NULL DEFAULT '',
    scheme          TEXT NOT NULL DEFAULT '',
    state           TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 1,
    reference       TEXT,
    error_type      TEXT,
    ledger_recorded INTEGER NOT NULL DEFAULT 0,
    created_us      INTEGER NOT NULL,
    updated_us      INTEGER NOT NULL
);
"""


class PaymentNotSent(Exception):  # noqa: N818 - reads as a statement, like the docs' "not sent"
    """Raise from a signer or `send` to certify that no money left.

    Any other exception is treated as `unknown`, because operator code that
    fails in an unexpected way may already have moved funds. Raise this only
    when the code knows the payment never left (for example, no key is
    configured, or the request was never written to the socket).
    """


@runtime_checkable
class PaymentSigner(Protocol):
    """The operator's payment code for one scheme and network.

    Return the value of the payment header (already encoded the way the
    server expects: V1 `X-PAYMENT`, V2 `PAYMENT-SIGNATURE`). The library
    chooses the header name from the challenge's `x402_version`. It never
    inspects, logs or stores the returned value.
    """

    def sign(self, requirement: PaymentRequirement, *, x402_version: int) -> str: ...


@dataclass(frozen=True, slots=True)
class PaymentResponse:
    """What the operator's `send` returns for the retried request."""

    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None


Sender = Callable[[Mapping[str, str]], PaymentResponse]


class PayStatus(StrEnum):
    PAID = "paid"
    UNKNOWN = "unknown"
    REJECTED = "rejected"
    NOT_SENT = "not_sent"
    REFUSED = "refused"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class JournalRecord:
    idempotency_key: str
    agent_id: str
    budget_key: str
    identity: str
    amount: Decimal
    unit: str
    network: str
    scheme: str
    state: str
    attempts: int
    reference: str | None
    error_type: str | None
    ledger_recorded: bool
    created_us: int
    updated_us: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "amount": f"{self.amount:f}",
            "attempts": self.attempts,
            "budget_key": self.budget_key,
            "created_us": self.created_us,
            "error_type": self.error_type,
            "identity": self.identity,
            "idempotency_key": self.idempotency_key,
            "ledger_recorded": self.ledger_recorded,
            "network": self.network,
            "reference": self.reference,
            "scheme": self.scheme,
            "state": self.state,
            "unit": self.unit,
            "updated_us": self.updated_us,
        }


def _record_from_row(row: sqlite3.Row) -> JournalRecord:
    return JournalRecord(
        idempotency_key=row["idempotency_key"],
        agent_id=row["agent_id"],
        budget_key=row["budget_key"],
        identity=row["identity"],
        amount=Decimal(row["amount"]),
        unit=row["unit"],
        network=row["network"],
        scheme=row["scheme"],
        state=row["state"],
        attempts=row["attempts"],
        reference=row["reference"],
        error_type=row["error_type"],
        ledger_recorded=bool(row["ledger_recorded"]),
        created_us=row["created_us"],
        updated_us=row["updated_us"],
    )


@dataclass(frozen=True, slots=True)
class _Reservation:
    reserved: bool
    prior: JournalRecord | None = None
    over_budget: dict[str, str] | None = None


class PaymentJournal:
    """Durable, cross-process record of every payment attempt, keyed by idempotency key.

    A separate SQLite file from the `Ledger`, deliberately: the ledger stays
    a record of consumption, and this holds the attempt state machine the
    ledger has no column for. Amounts are `Decimal` stored as strings and
    summed in Python, never in SQL.

    Each operation opens its own short-lived connection, so it is safe across
    threads and processes; `reserve` runs under `BEGIN IMMEDIATE`, which is
    what makes the duplicate check and the budget check atomic with the
    insert.
    """

    def __init__(self, database: Path | str) -> None:
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self._database = str(database)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._database, isolation_level=None, timeout=30.0)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn

    def get(self, idempotency_key: str) -> JournalRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM x402_payments WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def records(self, *, agent_id: str | None = None) -> list[JournalRecord]:
        with self._connect() as conn:
            if agent_id is None:
                rows = conn.execute("SELECT * FROM x402_payments ORDER BY created_us").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM x402_payments WHERE agent_id = ? ORDER BY created_us",
                    (agent_id,),
                ).fetchall()
        return [_record_from_row(row) for row in rows]

    def pending_total(self, *, agent_id: str, budget_key: str = _BUDGET_KEY) -> Decimal:
        """Money reserved or paid but not yet visible in the ledger."""
        with self._connect() as conn:
            return self._pending_total(conn, agent_id, budget_key)

    @staticmethod
    def _pending_total(conn: sqlite3.Connection, agent_id: str, budget_key: str) -> Decimal:
        rows = conn.execute(
            """
            SELECT amount FROM x402_payments
            WHERE agent_id = ? AND budget_key = ?
              AND (state = 'reserved'
                   OR (state IN ('paid', 'unknown', 'resolved_paid') AND ledger_recorded = 0))
            """,
            (agent_id, budget_key),
        ).fetchall()
        return sum((Decimal(row["amount"]) for row in rows), Decimal(0))

    def reserve(
        self,
        *,
        idempotency_key: str,
        agent_id: str,
        resource: Resource,
        requirement: PaymentRequirement,
        now_us: int,
        limit: Decimal | None,
        spent: Callable[[], Decimal],
    ) -> _Reservation:
        """Atomically claim this key and count the amount against the budget.

        `spent` is called *after* the pending total is read inside the same
        transaction. That order matters: a payment moving from pending into
        the ledger between the two reads is then counted twice (safe) rather
        than zero times (an under-count).
        """
        if resource.amount is None:
            raise ValueError("a payment reservation needs an amount")
        amount = f"{resource.amount:f}"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT * FROM x402_payments WHERE idempotency_key = ?", (idempotency_key,)
                ).fetchone()
                if existing is not None and existing["state"] in _BLOCKING_STATES:
                    conn.execute("ROLLBACK")
                    return _Reservation(reserved=False, prior=_record_from_row(existing))
                if limit is not None:
                    pending = self._pending_total(conn, agent_id, _BUDGET_KEY)
                    recorded = spent()
                    if recorded + pending + resource.amount > limit:
                        conn.execute("ROLLBACK")
                        return _Reservation(
                            reserved=False,
                            over_budget={
                                "in_flight": f"{pending:f}",
                                "limit": f"{limit:f}",
                                "requested": amount,
                                "spent": f"{recorded:f}",
                            },
                        )
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO x402_payments
                            (idempotency_key, agent_id, budget_key, identity, amount, unit,
                             network, scheme, state, attempts, ledger_recorded,
                             created_us, updated_us)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved', 1, 0, ?, ?)
                        """,
                        (
                            idempotency_key,
                            agent_id,
                            _BUDGET_KEY,
                            resource.identity,
                            amount,
                            resource.unit,
                            requirement.network,
                            requirement.scheme,
                            now_us,
                            now_us,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE x402_payments
                        SET state = 'reserved', attempts = attempts + 1, agent_id = ?,
                            budget_key = ?, identity = ?, amount = ?, unit = ?, network = ?,
                            scheme = ?, reference = NULL, error_type = NULL,
                            ledger_recorded = 0, updated_us = ?
                        WHERE idempotency_key = ?
                        """,
                        (
                            agent_id,
                            _BUDGET_KEY,
                            resource.identity,
                            amount,
                            resource.unit,
                            requirement.network,
                            requirement.scheme,
                            now_us,
                            idempotency_key,
                        ),
                    )
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        return _Reservation(reserved=True)

    def finish(
        self,
        idempotency_key: str,
        *,
        state: str,
        now_us: int,
        reference: str | None = None,
        error_type: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE x402_payments
                SET state = ?, reference = ?, error_type = ?, updated_us = ?
                WHERE idempotency_key = ?
                """,
                (state, reference, error_type, now_us, idempotency_key),
            )

    def mark_ledger_recorded(self, idempotency_key: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE x402_payments SET ledger_recorded = 1 WHERE idempotency_key = ?",
                (idempotency_key,),
            )

    def resolve(
        self, idempotency_key: str, *, paid: bool, now_us: int, reference: str | None = None
    ) -> JournalRecord:
        """Settle an `unknown` or stuck `reserved` payment after checking the chain.

        `paid=True` keeps it counted (and queues a ledger entry through
        `reconcile` if none exists). `paid=False` makes the key retryable, but
        an `unknown` payment's ledger entry is append-only and stays: the
        budget remains over-counted until the ledger supports an adjustment
        (see `docs/backlog.md`).
        """
        record = self.get(idempotency_key)
        if record is None:
            raise KeyError(f"no payment journaled under {idempotency_key!r}")
        if record.state not in ("unknown", "reserved"):
            raise ValueError(
                f"only an 'unknown' or 'reserved' payment can be resolved, not {record.state!r}"
            )
        self.finish(
            idempotency_key,
            state="resolved_paid" if paid else "resolved_unpaid",
            now_us=now_us,
            reference=reference if reference is not None else record.reference,
        )
        resolved = self.get(idempotency_key)
        if resolved is None:  # pragma: no cover - the row was just updated
            raise KeyError(idempotency_key)
        return resolved

    def reconcile(self, ledger: Ledger, *, now_us: int) -> list[JournalRecord]:
        """Write to the ledger any counted payment whose ledger write failed.

        Returns the records it recorded. Safe to call repeatedly: a record is
        marked as soon as its ledger entry exists.
        """
        recorded: list[JournalRecord] = []
        for record in self.records():
            if record.state in _COUNTED_STATES and not record.ledger_recorded:
                ledger.record(
                    agent_id=record.agent_id,
                    resource=Resource.spend(
                        to=record.identity.split(":", 1)[1], amount=record.amount, unit=record.unit
                    ),
                    now_us=now_us,
                    reference=f"x402:{record.idempotency_key}:{record.state}",
                )
                self.mark_ledger_recorded(record.idempotency_key)
                recorded.append(record)
        return recorded


@dataclass(frozen=True, slots=True)
class PaymentOutcome:
    """What `pay_if_allowed` did. Refusals and failures are data, never raised."""

    status: PayStatus
    idempotency_key: str
    decision: PaymentDecision | None = None
    verdict: Verdict | None = None
    response: PaymentResponse | None = None
    settlement: str | None = None
    prior: JournalRecord | None = None
    error: str | None = None
    ledger_recorded: bool = False
    ledger_error: str | None = None

    @property
    def money_may_have_moved(self) -> bool:
        """True for `paid` and `unknown`; `unknown` is never reported as no."""
        return self.status in (PayStatus.PAID, PayStatus.UNKNOWN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.to_dict() if self.decision else None,
            "error": self.error,
            "idempotency_key": self.idempotency_key,
            "ledger_error": self.ledger_error,
            "ledger_recorded": self.ledger_recorded,
            "money_may_have_moved": self.money_may_have_moved,
            "prior": self.prior.to_dict() if self.prior else None,
            "settlement": self.settlement,
            "status": self.status.value,
            "verdict": self.verdict.to_dict() if self.verdict else None,
        }


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _settlement_reference(headers: Mapping[str, str]) -> str | None:
    """The server's settlement receipt header, or None. Absent is unknown, not empty."""
    normalized = {key.upper(): value for key, value in headers.items()}
    return normalized.get(PAYMENT_RESPONSE_HEADER) or normalized.get(X_PAYMENT_RESPONSE_HEADER)


def pay_if_allowed(
    payment_required: PaymentRequired,
    *,
    gate: Gate,
    ledger: Ledger,
    journal: PaymentJournal,
    signer: PaymentSigner,
    send: Sender,
    agent_id: str,
    idempotency_key: str,
    now_us: int,
) -> PaymentOutcome:
    """Decide, reserve, pay through the operator's code, and record honestly.

    Never raises for a refusal or for a failure of the operator's code; both
    come back as a `PaymentOutcome`. It does raise `X402Error` for a
    challenge with nothing to decide between, and `ValueError` for an empty
    idempotency key (a programming error, not a payment outcome).
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("idempotency_key must be a non-empty string")

    prior = journal.get(idempotency_key)
    if prior is not None and prior.state in _BLOCKING_STATES:
        return PaymentOutcome(
            status=PayStatus.DUPLICATE,
            idempotency_key=idempotency_key,
            prior=prior,
            error=f"idempotency key already used (state: {prior.state}); signer not called",
        )

    if getattr(gate, "_ledger", None) is None:
        gate.attach_ledger(ledger)

    decision = decide_payment(payment_required, gate=gate, agent_id=agent_id, now_us=now_us)
    if decision.refused:
        return PaymentOutcome(
            status=PayStatus.REFUSED,
            idempotency_key=idempotency_key,
            decision=decision,
            verdict=decision.verdict,
        )

    requirement = decision.requirement
    resource = resource_for(requirement)
    limit = gate.contract.budget_for(agent_id, resource) if gate.enforcing else None
    reservation = journal.reserve(
        idempotency_key=idempotency_key,
        agent_id=agent_id,
        resource=resource,
        requirement=requirement,
        now_us=now_us,
        limit=limit,
        spent=lambda: gate.spent(agent_id=agent_id, resource=resource),
    )
    if not reservation.reserved:
        if reservation.prior is not None:
            return PaymentOutcome(
                status=PayStatus.DUPLICATE,
                idempotency_key=idempotency_key,
                decision=decision,
                prior=reservation.prior,
                error=(
                    f"idempotency key already used (state: {reservation.prior.state}); "
                    "signer not called"
                ),
            )
        detail = reservation.over_budget or {}
        verdict = Verdict(
            allowed=False,
            resource=resource,
            reason=(
                f"{resource.describe()} would take {agent_id!r} past a limit of "
                f"{detail.get('limit')} (spent {detail.get('spent')}, "
                f"in flight {detail.get('in_flight')})"
            ),
            rule="budget",
            detail=dict(detail),
        )
        return PaymentOutcome(
            status=PayStatus.REFUSED,
            idempotency_key=idempotency_key,
            decision=PaymentDecision(allowed=False, requirement=requirement, verdict=verdict),
            verdict=verdict,
        )

    status, response, settlement, error, error_type = _run_operator_code(
        payment_required, requirement, signer, send
    )
    journal.finish(
        idempotency_key,
        state=status.value,
        now_us=now_us,
        reference=settlement,
        error_type=error_type,
    )

    ledger_recorded = False
    ledger_error: str | None = None
    if status in (PayStatus.PAID, PayStatus.UNKNOWN):
        try:
            ledger.record(
                agent_id=agent_id,
                resource=resource,
                now_us=now_us,
                reference=f"x402:{idempotency_key}:{status.value}",
            )
            journal.mark_ledger_recorded(idempotency_key)
            ledger_recorded = True
        except Exception as exc:  # noqa: BLE001 - reported as data; reconcile() retries it
            ledger_error = _describe(exc)

    return PaymentOutcome(
        status=status,
        idempotency_key=idempotency_key,
        decision=decision,
        verdict=decision.verdict,
        response=response,
        settlement=settlement,
        error=error,
        ledger_recorded=ledger_recorded,
        ledger_error=ledger_error,
    )


def _run_operator_code(
    payment_required: PaymentRequired,
    requirement: PaymentRequirement,
    signer: PaymentSigner,
    send: Sender,
) -> tuple[PayStatus, PaymentResponse | None, str | None, str | None, str | None]:
    """Call the operator's signer and send; classify without ever assuming zero.

    Returns (status, response, settlement, error message, error type).
    """
    try:
        header_value = signer.sign(requirement, x402_version=payment_required.x402_version)
    except PaymentNotSent as exc:
        return PayStatus.NOT_SENT, None, None, _describe(exc), type(exc).__name__
    except Exception as exc:  # noqa: BLE001 - arbitrary operator code; failure is unknown
        return PayStatus.UNKNOWN, None, None, _describe(exc), type(exc).__name__

    if not isinstance(header_value, str) or not header_value:
        return (
            PayStatus.UNKNOWN,
            None,
            None,
            "signer returned no header value (expected a non-empty str)",
            "InvalidSignerResult",
        )

    header_name = (
        X_PAYMENT_HEADER if payment_required.x402_version == 1 else PAYMENT_SIGNATURE_HEADER
    )
    try:
        response = send({header_name: header_value})
    except PaymentNotSent as exc:
        return PayStatus.NOT_SENT, None, None, _describe(exc), type(exc).__name__
    except Exception as exc:  # noqa: BLE001 - the request may have reached the server
        return PayStatus.UNKNOWN, None, None, _describe(exc), type(exc).__name__

    if not isinstance(response, PaymentResponse):
        return (
            PayStatus.UNKNOWN,
            None,
            None,
            f"send returned {type(response).__name__}, expected PaymentResponse",
            "InvalidSendResult",
        )

    settlement = _settlement_reference(response.headers)
    if 200 <= response.status_code < 300:
        return PayStatus.PAID, response, settlement, None, None
    if response.status_code == 402:
        return (
            PayStatus.REJECTED,
            response,
            settlement,
            "server answered 402 again; payment not accepted",
            None,
        )
    return (
        PayStatus.UNKNOWN,
        response,
        settlement,
        f"unexpected status {response.status_code}; whether the payment settled is not known",
        None,
    )
