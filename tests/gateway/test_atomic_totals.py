"""A declared total is reserved before the handler runs, so callers cannot overspend.

The total used to be check-then-record: the gate read what the ledger had
recorded, allowed, the handler ran, and only then was the amount recorded. Two
callers could both read the same remainder and both spend it. A reservation
closes that window: the comparison and the hold are one ledger transaction, and
the hold is committed when the handler returns or released when it does not.

The race tests below use real threads (and, once, real processes) against a
real SQLite file and assert the invariant the feature exists for: exactly as
many calls succeed as the total allows, and the recorded total never exceeds it.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.policy import Contract, Gate, Resource
from causalmesh.policy.ledger import Ledger

CONTRACT = """
version: 1
roles:
  - agent_id: buyer
    archetype: spender
    allow: [api.example.com]
    budget:
      usd_total: "5.00"
      usd_per_call: "0.10"
policy:
  arm: {arm}
"""

NOW = 1_700_000_000_000_000
SPEND = Resource.spend(to="api.example.com", amount="0.10")


def _contract(tmp_path: Path, arm: str = "C3") -> Contract:
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT.replace("{arm}", arm), encoding="utf-8")
    return Contract.find(tmp_path)


def _mesh(
    tmp_path: Path, ledger: Ledger, handler: Any, *, arm: str = "C3", **tool_kwargs: Any
) -> CausalMesh:
    mesh = CausalMesh(
        agent_id="buyer",
        contract=_contract(tmp_path, arm),
        seed=b"atomic-totals-00000000000000000",
        ledger=ledger,
    )
    mesh.register_tool(
        Tool(
            name="pay",
            handler=handler,
            resource_args=["to"],
            resource_kind="spend",
            amount_arg="usd",
            **tool_kwargs,
        )
    )
    return mesh


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[Ledger]:
    with Ledger(tmp_path / "ledger.db", run_id="sdk") as led:
        yield led


def _total(ledger: Ledger) -> Decimal:
    return ledger.total(agent_id="buyer", resource=SPEND)


def _held(ledger: Ledger) -> Decimal:
    return ledger.held(agent_id="buyer", resource=SPEND)


PAY = {"to": "api.example.com", "usd": "0.10"}


# ---------------------------------------------------------------------------
# The race
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConcurrentCallers:
    def test_exactly_the_allowed_number_of_calls_succeed_under_threads(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        """5.00 at 0.10 a call is exactly 50 calls; 120 threads ask at once.

        The handler sleeps, so a check-then-record gate has every thread read
        the same empty ledger before any of them records: all 120 would run.
        """
        ran = 0
        ran_lock = threading.Lock()

        def handler(**_: Any) -> str:
            nonlocal ran
            with ran_lock:
                ran += 1
            time.sleep(0.005)
            return "paid"

        mesh = _mesh(tmp_path, ledger, handler)
        threads = 120
        start = threading.Barrier(threads)
        outcomes: list[Any] = []
        outcomes_lock = threading.Lock()

        def worker() -> None:
            start.wait()
            result = mesh.execute(tool="pay", arguments=dict(PAY))
            with outcomes_lock:
                outcomes.append(result)

        pool = [threading.Thread(target=worker) for _ in range(threads)]
        for thread in pool:
            thread.start()
        for thread in pool:
            thread.join(timeout=120)
        assert not any(thread.is_alive() for thread in pool)

        executed = [r for r in outcomes if r.executed]
        denied = [r for r in outcomes if r.denied]
        assert len(outcomes) == threads
        assert len(executed) == 50
        assert len(denied) == threads - 50
        assert {r.rule for r in denied} == {"budget"}
        assert ran == 50, "a refused call must never reach the handler"
        assert _total(ledger) == Decimal("5.00")
        assert _held(ledger) == 0, "every hold was committed or released"
        assert len(ledger.entries()) == 50

    def test_the_recorded_total_never_exceeds_the_cap_while_threads_run(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        """Watch the ledger from outside during the race, not only at the end."""

        def handler(**_: Any) -> str:
            time.sleep(0.002)
            return "paid"

        mesh = _mesh(tmp_path, ledger, handler)
        done = threading.Event()
        worst = Decimal(0)

        def watch() -> None:
            nonlocal worst
            while not done.is_set():
                seen = _total(ledger) + _held(ledger)
                worst = max(worst, seen)

        watcher = threading.Thread(target=watch)
        watcher.start()
        pool = [
            threading.Thread(target=lambda: mesh.execute(tool="pay", arguments=dict(PAY)))
            for _ in range(80)
        ]
        for thread in pool:
            thread.start()
        for thread in pool:
            thread.join(timeout=120)
        done.set()
        watcher.join(timeout=10)

        assert _total(ledger) == Decimal("5.00")
        # recorded + held can dip when a hold moves to an entry; it never rises above the cap
        assert worst <= Decimal("5.00")

    def test_ledgers_over_one_file_share_the_allowance(self, tmp_path: Path) -> None:
        """Two `Ledger` objects on one file stand in for two callers' processes."""
        database = tmp_path / "shared.db"
        with Ledger(database, run_id="r") as first, Ledger(database, run_id="r") as second:
            granted = 0
            for ledger in (first, second) * 30:
                outcome = ledger.reserve(
                    agent_id="buyer", resource=SPEND, limit=Decimal("5.00"), now_us=NOW
                )
                granted += outcome.granted
            assert granted == 50
            assert first.held(agent_id="buyer", resource=SPEND) == Decimal("5.00")


def _reserve_in_a_process(database: str, attempts: int, queue: Any) -> None:
    with Ledger(database, run_id="r") as ledger:
        granted = sum(
            ledger.reserve(
                agent_id="buyer", resource=SPEND, limit=Decimal("5.00"), now_us=NOW
            ).granted
            for _ in range(attempts)
        )
    queue.put(granted)


@pytest.mark.integration
def test_separate_processes_cannot_overspend_one_ledger(tmp_path: Path) -> None:
    """The reason the ledger is SQLite: agents are OS processes, not threads."""
    database = str(tmp_path / "procs.db")
    with Ledger(database, run_id="r"):
        pass  # create the schema once
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    workers = [
        context.Process(target=_reserve_in_a_process, args=(database, 30, queue)) for _ in range(4)
    ]
    for worker in workers:
        worker.start()
    granted = sum(queue.get(timeout=120) for _ in workers)
    for worker in workers:
        worker.join(timeout=60)

    assert granted == 50
    with Ledger(database, run_id="r") as ledger:
        assert ledger.held(agent_id="buyer", resource=SPEND) == Decimal("5.00")


# ---------------------------------------------------------------------------
# Settling: commit, release, and what a raise means
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSettling:
    def test_a_successful_call_commits_its_hold(self, tmp_path: Path, ledger: Ledger) -> None:
        mesh = _mesh(tmp_path, ledger, lambda **_: "ok")
        assert mesh.execute(tool="pay", arguments=dict(PAY)).executed
        assert _total(ledger) == Decimal("0.10")
        assert _held(ledger) == 0

    def test_the_hold_is_taken_before_the_handler_runs(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        seen: list[tuple[Decimal, Decimal]] = []

        def handler(**_: Any) -> str:
            seen.append((_total(ledger), _held(ledger)))
            return "ok"

        mesh = _mesh(tmp_path, ledger, handler)
        mesh.execute(tool="pay", arguments=dict(PAY))
        assert seen == [(Decimal(0), Decimal("0.10"))]

    def test_a_handler_that_raises_releases_its_hold_and_records_nothing(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        def handler(**_: Any) -> str:
            raise RuntimeError("upstream exploded")

        mesh = _mesh(tmp_path, ledger, handler)
        result = mesh.execute(tool="pay", arguments=dict(PAY))
        assert result.failed
        assert _total(ledger) == 0
        assert _held(ledger) == 0
        assert ledger.entries() == []

    def test_a_failing_handler_does_not_eat_the_allowance(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        """Fifty failures must leave room for fifty successes."""
        fail = True

        def handler(**_: Any) -> str:
            if fail:
                raise RuntimeError("down")
            return "ok"

        mesh = _mesh(tmp_path, ledger, handler)
        for _ in range(60):
            assert mesh.execute(tool="pay", arguments=dict(PAY)).failed
        fail = False
        assert sum(mesh.execute(tool="pay", arguments=dict(PAY)).executed for _ in range(60)) == 50

    def test_an_interrupt_in_the_handler_releases_the_hold_and_propagates(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        def handler(**_: Any) -> str:
            raise KeyboardInterrupt

        mesh = _mesh(tmp_path, ledger, handler)
        with pytest.raises(KeyboardInterrupt):
            mesh.execute(tool="pay", arguments=dict(PAY))
        assert _held(ledger) == 0
        assert _total(ledger) == 0

    @pytest.mark.asyncio
    async def test_an_async_handler_that_raises_releases_its_hold(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        async def handler(**_: Any) -> str:
            raise RuntimeError("down")

        mesh = _mesh(tmp_path, ledger, handler)
        result = await mesh.execute_async(tool="pay", arguments=dict(PAY))
        assert result.failed
        assert _held(ledger) == 0
        assert _total(ledger) == 0

    @pytest.mark.asyncio
    async def test_an_async_success_commits(self, tmp_path: Path, ledger: Ledger) -> None:
        async def handler(**_: Any) -> str:
            return "ok"

        mesh = _mesh(tmp_path, ledger, handler)
        assert (await mesh.execute_async(tool="pay", arguments=dict(PAY))).executed
        assert _total(ledger) == Decimal("0.10")
        assert _held(ledger) == 0

    def test_a_refusal_later_in_the_same_call_releases_what_was_held(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        """Two destinations, the second not allowlisted: the first hold goes back."""
        ran: list[str] = []
        mesh = CausalMesh(
            agent_id="buyer",
            contract=_contract(tmp_path),
            seed=b"atomic-totals-00000000000000000",
            ledger=ledger,
        )
        mesh.register_tool(
            Tool(
                name="split",
                handler=lambda **kw: ran.append("x"),
                resource_args=["to", "fallback"],
                resource_kind="spend",
                amount_arg="usd",
            )
        )
        result = mesh.execute(
            tool="split",
            arguments={"to": "api.example.com", "fallback": "evil.example", "usd": "0.10"},
        )
        assert result.denied and result.rule == "allowlist"
        assert ran == []
        assert _held(ledger) == 0
        assert _total(ledger) == 0

    def test_both_resources_of_one_call_are_reserved_and_committed(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        mesh = CausalMesh(
            agent_id="buyer",
            contract=_contract(tmp_path),
            seed=b"atomic-totals-00000000000000000",
            ledger=ledger,
        )
        mesh.register_tool(
            Tool(
                name="split",
                handler=lambda **_: "ok",
                resource_args=["to", "fallback"],
                resource_kind="spend",
                amount_arg="usd",
            )
        )
        result = mesh.execute(
            tool="split",
            arguments={"to": "api.example.com", "fallback": "api.example.com", "usd": "0.10"},
        )
        assert result.executed
        assert _total(ledger) == Decimal("0.20")
        assert _held(ledger) == 0

    def test_a_refused_call_holds_nothing(self, tmp_path: Path, ledger: Ledger) -> None:
        mesh = _mesh(tmp_path, ledger, lambda **_: "ok")
        result = mesh.execute(tool="pay", arguments={"to": "evil.example", "usd": "0.10"})
        assert result.denied
        assert _held(ledger) == 0

    def test_the_refusal_names_what_is_held(self, tmp_path: Path, ledger: Ledger) -> None:
        """A call turned away by an in-flight one is told why, in its numbers."""
        gate = Gate(_contract(tmp_path), run_id="sdk")
        gate.attach_ledger(ledger)
        big = Resource.spend(to="api.example.com", amount="0.10")
        for _ in range(50):
            ledger.reserve(agent_id="buyer", resource=big, limit=Decimal("5.00"), now_us=NOW)
        verdict = gate.check(agent_id="buyer", resource=big, now_us=NOW)
        assert verdict.refused and verdict.rule == "budget"
        assert verdict.detail["held"] == "5.00"
        assert Decimal(verdict.detail["spent"]) == 0


@pytest.mark.unit
class TestSpendOnError:
    def test_default_a_raise_is_not_spent(self, tmp_path: Path, ledger: Ledger) -> None:
        def handler(**_: Any) -> str:
            raise RuntimeError("after the money left")

        mesh = _mesh(tmp_path, ledger, handler)
        assert mesh.execute(tool="pay", arguments=dict(PAY)).failed
        assert _total(ledger) == 0

    def test_opt_in_a_raise_counts_as_spent(self, tmp_path: Path, ledger: Ledger) -> None:
        def handler(**_: Any) -> str:
            raise RuntimeError("after the money left")

        mesh = _mesh(tmp_path, ledger, handler, spend_on_error=True)
        result = mesh.execute(tool="pay", arguments=dict(PAY))
        assert result.failed, "the outcome is still a failure"
        assert _total(ledger) == Decimal("0.10")
        assert _held(ledger) == 0
        assert len(ledger.entries()) == 1

    def test_opt_in_fills_the_allowance_with_failures(self, tmp_path: Path, ledger: Ledger) -> None:
        def handler(**_: Any) -> str:
            raise RuntimeError("down")

        mesh = _mesh(tmp_path, ledger, handler, spend_on_error=True)
        results = [mesh.execute(tool="pay", arguments=dict(PAY)) for _ in range(60)]
        assert sum(r.failed for r in results) == 50
        assert sum(r.denied for r in results) == 10

    def test_only_a_spend_or_budget_tool_may_ask_for_it(self) -> None:
        with pytest.raises(ValueError, match="spend_on_error"):
            Tool(name="write", handler=lambda **_: None, spend_on_error=True)


# ---------------------------------------------------------------------------
# The ledger and gate on their own
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLedgerReservations:
    def test_reserve_commit_release(self, ledger: Ledger) -> None:
        limit = Decimal("0.30")
        a = ledger.reserve(agent_id="buyer", resource=SPEND, limit=limit, now_us=NOW)
        b = ledger.reserve(agent_id="buyer", resource=SPEND, limit=limit, now_us=NOW)
        c = ledger.reserve(agent_id="buyer", resource=SPEND, limit=limit, now_us=NOW)
        d = ledger.reserve(agent_id="buyer", resource=SPEND, limit=limit, now_us=NOW)
        assert (a.granted, b.granted, c.granted, d.granted) == (True, True, True, False)
        assert (d.spent, d.held) == (0, Decimal("0.30"))

        assert a.reservation and b.reservation and c.reservation
        ledger.commit(a.reservation, now_us=NOW, reference="evt-1")
        assert ledger.release(b.reservation) is True
        assert ledger.release(b.reservation) is False, "releasing twice is harmless"
        assert _total(ledger) == Decimal("0.10")
        assert _held(ledger) == Decimal("0.10")
        # the released room is usable again
        assert ledger.reserve(agent_id="buyer", resource=SPEND, limit=limit, now_us=NOW).granted

    def test_amounts_are_exact_decimals(self, ledger: Ledger) -> None:
        nickel = Resource.spend(to="api.example.com", amount="0.05")
        granted = [
            ledger.reserve(
                agent_id="buyer", resource=nickel, limit=Decimal("5.00"), now_us=NOW
            ).granted
            for _ in range(101)
        ]
        assert granted.count(True) == 100, "floats reach 5.000000000000004 and refuse the last"
        assert ledger.held(agent_id="buyer", resource=nickel) == Decimal("5.00")

    def test_a_commit_is_one_transaction(self, ledger: Ledger) -> None:
        outcome = ledger.reserve(agent_id="buyer", resource=SPEND, limit=Decimal("1"), now_us=NOW)
        assert outcome.reservation is not None
        ledger.commit(outcome.reservation, now_us=NOW)
        assert _held(ledger) == 0 and _total(ledger) == Decimal("0.10")

    def test_holds_are_shared_across_ledger_objects_and_survive_a_close(
        self, tmp_path: Path
    ) -> None:
        database = tmp_path / "x.db"
        with Ledger(database, run_id="r") as first:
            first.reserve(agent_id="buyer", resource=SPEND, limit=Decimal("1"), now_us=NOW)
        with Ledger(database, run_id="r") as second:
            assert second.held(agent_id="buyer", resource=SPEND) == Decimal("0.10")
            assert second.release_all() == 1
            assert second.held(agent_id="buyer", resource=SPEND) == 0

    def test_a_dead_holder_over_counts_until_released(self, ledger: Ledger) -> None:
        """The stated limit: a hold nobody settles keeps counting, which fails closed."""
        limit = Decimal("0.10")
        assert ledger.reserve(agent_id="buyer", resource=SPEND, limit=limit, now_us=NOW).granted
        assert not ledger.reserve(agent_id="buyer", resource=SPEND, limit=limit, now_us=NOW).granted
        ledger.release_all()
        assert ledger.reserve(agent_id="buyer", resource=SPEND, limit=limit, now_us=NOW).granted

    def test_an_unenforced_reserve_takes_the_hold_anyway(self, ledger: Ledger) -> None:
        outcome = ledger.reserve(
            agent_id="buyer", resource=SPEND, limit=Decimal("0"), now_us=NOW, enforce=False
        )
        assert outcome.granted

    def test_total_is_recorded_consumption_only(self, ledger: Ledger) -> None:
        ledger.reserve(agent_id="buyer", resource=SPEND, limit=Decimal("1"), now_us=NOW)
        assert _total(ledger) == 0
        assert ledger.entries() == []


@pytest.mark.unit
class TestGateReservations:
    def _gate(self, tmp_path: Path, ledger: Ledger, *, arm: str = "C3") -> Gate:
        gate = Gate(_contract(tmp_path, arm), run_id="sdk", enforcing=arm == "C3")
        gate.attach_ledger(ledger)
        return gate

    def test_a_plain_check_reserves_nothing(self, tmp_path: Path, ledger: Ledger) -> None:
        gate = self._gate(tmp_path, ledger)
        assert gate.check(agent_id="buyer", resource=SPEND, now_us=NOW).allowed
        assert _held(ledger) == 0

    def test_a_check_with_holds_reserves_and_hands_the_hold_back(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        gate = self._gate(tmp_path, ledger)
        holds: list[Any] = []
        assert gate.check(agent_id="buyer", resource=SPEND, now_us=NOW, holds=holds).allowed
        assert len(holds) == 1
        assert _held(ledger) == Decimal("0.10")
        gate.release(holds)
        assert _held(ledger) == 0 and holds == []

    def test_a_plain_check_counts_what_is_in_flight(self, tmp_path: Path, ledger: Ledger) -> None:
        gate = self._gate(tmp_path, ledger)
        for _ in range(50):
            assert gate.check(agent_id="buyer", resource=SPEND, now_us=NOW, holds=[]).allowed
        verdict = gate.check(agent_id="buyer", resource=SPEND, now_us=NOW)
        assert verdict.refused and verdict.rule == "budget"

    def test_a_refused_check_with_holds_holds_nothing(self, tmp_path: Path, ledger: Ledger) -> None:
        gate = self._gate(tmp_path, ledger)
        holds: list[Any] = []
        over = Resource.spend(to="api.example.com", amount="0.50")
        assert gate.check(agent_id="buyer", resource=over, now_us=NOW, holds=holds).refused
        assert holds == [] and _held(ledger) == 0

    def test_an_unenforced_gate_still_reports_what_it_would_refuse(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        gate = self._gate(tmp_path, ledger, arm="C2")
        holds: list[Any] = []
        for _ in range(51):
            verdict = gate.check(agent_id="buyer", resource=SPEND, now_us=NOW, holds=holds)
            assert verdict.allowed
        assert verdict.detail.get("would_refuse") is True
        assert len(holds) == 51, "an unenforced arm still records what it spends"
