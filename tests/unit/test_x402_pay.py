"""Unit tests for x402 payment orchestration (`adapters/x402_pay.py`).

Everything is offline. The "signer" and the "server" are fakes written here;
no wallet, key, network or real payment is involved, and none of these tests
says anything about how a real facilitator behaves.

The facts under test: an allowed payment pays and is recorded exactly once; a
refusal never reaches the operator's code; a failure after money may have left
is recorded as unknown (and counted), never as zero; a repeated idempotency
key never pays twice; and budgets hold while payments are still in flight.
"""

from __future__ import annotations

import json
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from causalmesh.adapters.x402 import (
    PaymentRequired,
    X402Error,
    parse_payment_required,
)
from causalmesh.adapters.x402_pay import (
    PaymentJournal,
    PaymentNotSent,
    PaymentResponse,
    PaymentSigner,
    PayStatus,
    pay_if_allowed,
)
from causalmesh.policy import Contract, Gate, Ledger, Resource

pytestmark = pytest.mark.unit

NOW = 1_000_000
PAYEE = "api.vendor.io"


def challenge(*, amount: str = "0.50", pay_to: str = PAYEE, version: int = 1) -> PaymentRequired:
    entry: dict[str, object] = {
        "scheme": "exact",
        "network": "base-sepolia",
        "resource": "https://api.vendor.io/data",
        "payTo": pay_to,
        "asset": "USDC",
        "maxTimeoutSeconds": 60,
    }
    if version == 1:
        entry["maxAmountRequired"] = amount
    else:
        entry["amount"] = amount
    body = json.dumps({"x402Version": version, "accepts": [entry]}).encode("utf-8")
    if version == 2:
        import base64

        header = base64.b64encode(body).decode("ascii")
        return parse_payment_required(headers={"PAYMENT-REQUIRED": header})
    return parse_payment_required(headers={}, body=body)


class FakeSigner:
    """Records calls; never signs anything real."""

    def __init__(self, *, raises: BaseException | None = None, value: object = "sig-abc") -> None:
        self.calls = 0
        self.raises = raises
        self.value = value

    def sign(self, requirement, *, x402_version):  # noqa: ANN001, ANN201
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.value


class FakeServer:
    """The operator's `send`: answers with a canned response and remembers what it saw."""

    def __init__(
        self,
        response: PaymentResponse | None = None,
        *,
        raises: BaseException | None = None,
        returns: object = None,
    ) -> None:
        self.response = response or PaymentResponse(200, {"PAYMENT-RESPONSE": "receipt-1"}, b"ok")
        self.raises = raises
        self.returns = returns
        self.seen: list[dict[str, str]] = []

    def __call__(self, headers):  # noqa: ANN001, ANN201
        self.seen.append(dict(headers))
        if self.raises is not None:
            raise self.raises
        if self.returns is not None:
            return self.returns
        return self.response


@pytest.fixture
def contract() -> Contract:
    return Contract.from_dict(
        {
            "version": 1,
            "roles": [
                {
                    "agent_id": "buyer",
                    "archetype": "spender",
                    "allow": [PAYEE],
                    "budget": {"usd_total": "2.00", "usd_per_call": "1.00"},
                },
            ],
            "policy": {"arm": "C3"},
        }
    )


@pytest.fixture
def ledger(tmp_path: Path):
    with Ledger(tmp_path / "ledger.db", run_id="run_pay") as opened:
        yield opened


@pytest.fixture
def journal(tmp_path: Path) -> PaymentJournal:
    return PaymentJournal(tmp_path / "journal.db")


@pytest.fixture
def gate(contract: Contract, ledger: Ledger) -> Gate:
    built = Gate(contract, run_id="run_pay")
    built.attach_ledger(ledger)
    return built


def pay(gate, ledger, journal, *, signer=None, server=None, key="order-1", pr=None, now=NOW):  # noqa: ANN001, ANN201
    return pay_if_allowed(
        pr or challenge(),
        gate=gate,
        ledger=ledger,
        journal=journal,
        signer=signer or FakeSigner(),
        send=server or FakeServer(),
        agent_id="buyer",
        idempotency_key=key,
        now_us=now,
    )


def spent(gate: Gate, amount: str = "0.01") -> Decimal:
    return gate.spent(agent_id="buyer", resource=Resource.spend(to=PAYEE, amount=amount))


class TestAllowedPayment:
    def test_pays_and_records_exactly_once(self, gate, ledger, journal) -> None:  # noqa: ANN001
        signer, server = FakeSigner(), FakeServer()
        outcome = pay(gate, ledger, journal, signer=signer, server=server)

        assert outcome.status is PayStatus.PAID
        assert signer.calls == 1
        assert len(server.seen) == 1
        entries = ledger.entries(agent_id="buyer")
        assert len(entries) == 1
        assert entries[0].amount == Decimal("0.50")
        assert entries[0].reference == "x402:order-1:paid"
        assert outcome.ledger_recorded and outcome.ledger_error is None
        assert spent(gate) == Decimal("0.50")

    def test_v1_uses_x_payment_header_and_v2_uses_payment_signature(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        v1_server, v2_server = FakeServer(), FakeServer()
        pay(gate, ledger, journal, server=v1_server, key="k1", pr=challenge(version=1))
        pay(gate, ledger, journal, server=v2_server, key="k2", pr=challenge(version=2))
        assert v1_server.seen == [{"X-PAYMENT": "sig-abc"}]
        assert v2_server.seen == [{"PAYMENT-SIGNATURE": "sig-abc"}]

    def test_the_settlement_receipt_is_kept_and_absence_is_none(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        with_receipt = pay(gate, ledger, journal, key="a")
        assert with_receipt.settlement == "receipt-1"
        bare = pay(gate, ledger, journal, key="b", server=FakeServer(PaymentResponse(200)))
        assert bare.status is PayStatus.PAID
        assert bare.settlement is None  # absent is unknown, not an empty string

    def test_amounts_stay_decimal_end_to_end(self, gate, ledger, journal) -> None:  # noqa: ANN001
        pay(gate, ledger, journal, key="a", pr=challenge(amount="0.10"))
        pay(gate, ledger, journal, key="b", pr=challenge(amount="0.20"))
        assert spent(gate) == Decimal("0.30")  # a float sum would be 0.30000000000000004
        record = journal.get("a")
        assert record is not None and record.amount == Decimal("0.10")

    def test_the_signer_protocol_is_satisfied_structurally(self) -> None:
        assert isinstance(FakeSigner(), PaymentSigner)


class TestRefusal:
    def test_a_refusal_never_reaches_the_signer_or_the_journal(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        signer, server = FakeSigner(), FakeServer()
        outcome = pay(
            gate, ledger, journal, signer=signer, server=server, pr=challenge(pay_to="evil.io")
        )
        assert outcome.status is PayStatus.REFUSED
        assert outcome.verdict is not None and outcome.verdict.rule == "allowlist"
        assert signer.calls == 0 and server.seen == []
        assert ledger.entries() == []
        assert journal.records() == []
        assert not outcome.money_may_have_moved

    def test_a_ceiling_refusal_is_data(self, gate, ledger, journal) -> None:  # noqa: ANN001
        outcome = pay(gate, ledger, journal, pr=challenge(amount="1.50"))
        assert outcome.status is PayStatus.REFUSED
        assert outcome.verdict is not None and outcome.verdict.rule == "ceiling"
        assert outcome.to_dict()["status"] == "refused"

    def test_a_refused_key_can_be_used_later(self, gate, ledger, journal) -> None:  # noqa: ANN001
        refused = pay(gate, ledger, journal, pr=challenge(amount="1.50"), key="same")
        assert refused.status is PayStatus.REFUSED
        allowed = pay(gate, ledger, journal, pr=challenge(amount="0.50"), key="same")
        assert allowed.status is PayStatus.PAID

    def test_an_empty_idempotency_key_is_a_programming_error(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        with pytest.raises(ValueError):
            pay(gate, ledger, journal, key="  ")

    def test_a_challenge_with_nothing_to_decide_between_raises(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        empty = PaymentRequired(x402_version=1, accepts=())
        with pytest.raises(X402Error):
            pay(gate, ledger, journal, pr=empty)

    def test_a_non_enforcing_gate_still_pays_but_journals(
        self,
        contract,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        relaxed = Gate(contract, run_id="run_pay", enforcing=False)
        relaxed.attach_ledger(ledger)
        outcome = pay(relaxed, ledger, journal, pr=challenge(pay_to="evil.io"))
        assert outcome.status is PayStatus.PAID
        assert outcome.decision is not None
        assert outcome.decision.verdict.detail.get("would_refuse") is True


class TestFailureIsNeverZero:
    def test_a_signer_that_raises_is_unknown_and_counted(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        server = FakeServer()
        outcome = pay(gate, ledger, journal, signer=FakeSigner(raises=RuntimeError("boom")))
        assert outcome.status is PayStatus.UNKNOWN
        assert outcome.money_may_have_moved
        assert "boom" in (outcome.error or "")
        assert server.seen == []
        entries = ledger.entries(agent_id="buyer")
        assert [e.amount for e in entries] == [Decimal("0.50")]
        assert entries[0].reference == "x402:order-1:unknown"
        assert spent(gate) == Decimal("0.50")

    def test_a_send_that_raises_is_unknown_and_counted(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        outcome = pay(gate, ledger, journal, server=FakeServer(raises=ConnectionResetError("rst")))
        assert outcome.status is PayStatus.UNKNOWN
        assert spent(gate) == Decimal("0.50")
        record = journal.get("order-1")
        assert record is not None and record.state == "unknown"
        assert record.error_type == "ConnectionResetError"

    def test_a_server_error_is_unknown_not_a_refund(self, gate, ledger, journal) -> None:  # noqa: ANN001
        outcome = pay(gate, ledger, journal, server=FakeServer(PaymentResponse(503)))
        assert outcome.status is PayStatus.UNKNOWN
        assert spent(gate) == Decimal("0.50")

    def test_garbage_from_the_operators_code_is_unknown(self, gate, ledger, journal) -> None:  # noqa: ANN001
        bad_signer = pay(gate, ledger, journal, signer=FakeSigner(value=None), key="a")
        assert bad_signer.status is PayStatus.UNKNOWN
        bad_send = pay(gate, ledger, journal, server=FakeServer(returns="200 OK"), key="b")
        assert bad_send.status is PayStatus.UNKNOWN
        assert spent(gate) == Decimal("1.00")

    def test_payment_not_sent_certifies_no_spend(self, gate, ledger, journal) -> None:  # noqa: ANN001
        outcome = pay(gate, ledger, journal, signer=FakeSigner(raises=PaymentNotSent("no key")))
        assert outcome.status is PayStatus.NOT_SENT
        assert not outcome.money_may_have_moved
        assert ledger.entries() == []
        assert spent(gate) == Decimal(0)

    def test_send_may_also_certify_not_sent(self, gate, ledger, journal) -> None:  # noqa: ANN001
        outcome = pay(gate, ledger, journal, server=FakeServer(raises=PaymentNotSent("offline")))
        assert outcome.status is PayStatus.NOT_SENT
        assert ledger.entries() == []

    def test_a_402_again_is_rejected_and_not_recorded(self, gate, ledger, journal) -> None:  # noqa: ANN001
        outcome = pay(gate, ledger, journal, server=FakeServer(PaymentResponse(402)))
        assert outcome.status is PayStatus.REJECTED
        assert ledger.entries() == []

    def test_a_ledger_failure_after_payment_is_reported_and_reconcilable(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        class BrokenLedger:
            def record(self, **kwargs):  # noqa: ANN003, ANN201
                raise OSError("disk full")

        outcome = pay_if_allowed(
            challenge(),
            gate=gate,
            ledger=BrokenLedger(),  # type: ignore[arg-type]
            journal=journal,
            signer=FakeSigner(),
            send=FakeServer(),
            agent_id="buyer",
            idempotency_key="k",
            now_us=NOW,
        )
        assert outcome.status is PayStatus.PAID
        assert not outcome.ledger_recorded
        assert "disk full" in (outcome.ledger_error or "")
        # The unrecorded payment still counts against the budget while pending...
        assert journal.pending_total(agent_id="buyer") == Decimal("0.50")
        # ...and reconcile writes it once the ledger is healthy again.
        assert len(journal.reconcile(ledger, now_us=NOW)) == 1
        assert spent(gate) == Decimal("0.50")
        assert journal.pending_total(agent_id="buyer") == Decimal(0)
        assert journal.reconcile(ledger, now_us=NOW) == []  # idempotent

    def test_an_interrupt_leaves_the_payment_in_flight_and_counted(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        with pytest.raises(KeyboardInterrupt):
            pay(gate, ledger, journal, server=FakeServer(raises=KeyboardInterrupt()))
        record = journal.get("order-1")
        assert record is not None and record.state == "reserved"
        assert journal.pending_total(agent_id="buyer") == Decimal("0.50")
        again = pay(gate, ledger, journal)
        assert again.status is PayStatus.DUPLICATE


class TestIdempotency:
    def test_the_same_key_never_pays_twice(self, gate, ledger, journal) -> None:  # noqa: ANN001
        signer = FakeSigner()
        first = pay(gate, ledger, journal, signer=signer)
        second = pay(gate, ledger, journal, signer=signer)
        assert first.status is PayStatus.PAID
        assert second.status is PayStatus.DUPLICATE
        assert second.prior is not None and second.prior.state == "paid"
        assert signer.calls == 1
        assert len(ledger.entries()) == 1

    def test_an_unknown_payment_blocks_a_replay(self, gate, ledger, journal) -> None:  # noqa: ANN001
        pay(gate, ledger, journal, server=FakeServer(raises=OSError("x")))
        signer = FakeSigner()
        replay = pay(gate, ledger, journal, signer=signer)
        assert replay.status is PayStatus.DUPLICATE
        assert signer.calls == 0

    def test_a_replay_with_different_terms_is_still_a_duplicate(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        pay(gate, ledger, journal, pr=challenge(amount="0.10"))
        signer = FakeSigner()
        replay = pay(gate, ledger, journal, signer=signer, pr=challenge(amount="0.90"))
        assert replay.status is PayStatus.DUPLICATE
        assert signer.calls == 0
        assert spent(gate) == Decimal("0.10")

    def test_a_not_sent_or_rejected_key_may_be_retried(self, gate, ledger, journal) -> None:  # noqa: ANN001
        first = pay(gate, ledger, journal, signer=FakeSigner(raises=PaymentNotSent("x")))
        assert first.status is PayStatus.NOT_SENT
        second = pay(gate, ledger, journal, server=FakeServer(PaymentResponse(402)))
        assert second.status is PayStatus.REJECTED
        third = pay(gate, ledger, journal)
        assert third.status is PayStatus.PAID
        record = journal.get("order-1")
        assert record is not None and record.attempts == 3
        assert len(ledger.entries()) == 1

    def test_concurrent_duplicates_pay_once(self, gate, ledger, journal) -> None:  # noqa: ANN001
        signer = FakeSigner()
        results: list[PayStatus] = []
        lock = threading.Lock()

        def worker() -> None:
            outcome = pay(gate, ledger, journal, signer=signer, key="race")
            with lock:
                results.append(outcome.status)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results.count(PayStatus.PAID) == 1
        assert results.count(PayStatus.DUPLICATE) == 5
        assert signer.calls == 1


class TestBudgetInterplay:
    def test_spending_up_to_the_total_then_refusing(self, gate, ledger, journal) -> None:  # noqa: ANN001
        for index in range(4):  # 4 x 0.50 == the 2.00 total
            assert (
                pay(gate, ledger, journal, key=f"k{index}", pr=challenge(amount="0.50")).status
                is PayStatus.PAID
            )
        signer = FakeSigner()
        over = pay(gate, ledger, journal, key="k4", signer=signer, pr=challenge(amount="0.50"))
        assert over.status is PayStatus.REFUSED
        assert over.verdict is not None and over.verdict.rule == "budget"
        assert signer.calls == 0
        assert spent(gate) == Decimal("2.00")

    def test_an_unknown_payment_consumes_budget(self, gate, ledger, journal) -> None:  # noqa: ANN001
        for index in range(4):
            pay(
                gate,
                ledger,
                journal,
                key=f"u{index}",
                pr=challenge(amount="0.50"),
                server=FakeServer(raises=OSError("net")),
            )
        blocked = pay(gate, ledger, journal, key="next", pr=challenge(amount="0.50"))
        assert blocked.status is PayStatus.REFUSED

    def test_in_flight_amount_is_what_makes_the_last_one_refuse(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        outcomes: list[PayStatus] = []

        def slow_send(headers):  # noqa: ANN001, ANN201
            for index in range(4):
                inner = pay(gate, ledger, journal, key=f"inner{index}", pr=challenge(amount="0.50"))
                outcomes.append(inner.status)
            return PaymentResponse(200)

        pay(gate, ledger, journal, key="outer", pr=challenge(amount="0.50"), server=slow_send)  # type: ignore[arg-type]
        # The ledger alone would allow the fourth inner payment (1.50 spent);
        # only the in-flight 0.50 makes it refuse.
        assert outcomes == [PayStatus.PAID, PayStatus.PAID, PayStatus.PAID, PayStatus.REFUSED]
        assert spent(gate) == Decimal("2.00")

    def test_concurrent_payments_cannot_overspend_together(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        results: list[PayStatus] = []
        lock = threading.Lock()

        def worker(index: int) -> None:
            outcome = pay(gate, ledger, journal, key=f"c{index}", pr=challenge(amount="0.50"))
            with lock:
                results.append(outcome.status)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results.count(PayStatus.PAID) == 4
        assert results.count(PayStatus.REFUSED) == 4
        assert spent(gate) == Decimal("2.00")

    def test_a_gate_without_a_ledger_gets_the_orchestrators_ledger(
        self,
        contract,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        bare = Gate(contract, run_id="run_pay")
        pay(bare, ledger, journal, key="a")
        assert bare.spent(agent_id="buyer", resource=Resource.spend(to=PAYEE, amount="0.01")) == (
            Decimal("0.50")
        )


class TestResolve:
    def test_resolving_unknown_as_paid_keeps_it_counted(self, gate, ledger, journal) -> None:  # noqa: ANN001
        pay(gate, ledger, journal, server=FakeServer(raises=OSError("net")))
        record = journal.resolve("order-1", paid=True, now_us=NOW + 1, reference="0xabc")
        assert record.state == "resolved_paid"
        assert record.reference == "0xabc"
        assert spent(gate) == Decimal("0.50")
        assert len(ledger.entries()) == 1
        assert pay(gate, ledger, journal).status is PayStatus.DUPLICATE

    def test_resolving_unknown_as_unpaid_makes_the_key_retryable(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        pay(gate, ledger, journal, server=FakeServer(raises=OSError("net")))
        journal.resolve("order-1", paid=False, now_us=NOW + 1)
        assert pay(gate, ledger, journal).status is PayStatus.PAID
        # The append-only ledger keeps the unconfirmed entry: over-counted, not zero.
        assert spent(gate) == Decimal("1.00")

    def test_only_unknown_or_reserved_can_be_resolved(self, gate, ledger, journal) -> None:  # noqa: ANN001
        pay(gate, ledger, journal)
        with pytest.raises(ValueError):
            journal.resolve("order-1", paid=True, now_us=NOW)
        with pytest.raises(KeyError):
            journal.resolve("nope", paid=True, now_us=NOW)

    def test_a_stuck_reservation_resolved_paid_is_reconciled_into_the_ledger(
        self,
        gate,
        ledger,
        journal,  # noqa: ANN001
    ) -> None:
        with pytest.raises(KeyboardInterrupt):
            pay(gate, ledger, journal, server=FakeServer(raises=KeyboardInterrupt()))
        journal.resolve("order-1", paid=True, now_us=NOW + 1)
        assert journal.pending_total(agent_id="buyer") == Decimal("0.50")
        journal.reconcile(ledger, now_us=NOW + 2)
        assert spent(gate) == Decimal("0.50")
        assert journal.pending_total(agent_id="buyer") == Decimal(0)


class TestJournalHygiene:
    def test_the_journal_never_stores_the_signature(self, gate, ledger, journal, tmp_path) -> None:  # noqa: ANN001
        pay(gate, ledger, journal, signer=FakeSigner(value="SECRET-SIGNATURE-VALUE"))
        pay(
            gate,
            ledger,
            journal,
            key="err",
            signer=FakeSigner(raises=RuntimeError("SECRET-IN-MESSAGE")),
        )
        raw = b"".join(p.read_bytes() for p in tmp_path.glob("journal.db*"))
        assert b"SECRET-SIGNATURE-VALUE" not in raw
        assert b"SECRET-IN-MESSAGE" not in raw  # only the exception type is persisted

    def test_journal_survives_reopening(self, gate, ledger, tmp_path) -> None:  # noqa: ANN001
        first = PaymentJournal(tmp_path / "j.db")
        pay(gate, ledger, first)
        reopened = PaymentJournal(tmp_path / "j.db")
        assert pay(gate, ledger, reopened).status is PayStatus.DUPLICATE
