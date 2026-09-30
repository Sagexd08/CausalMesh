"""The logical clock: the signed timestamp is reproducible, the wall clock is not signed.

Before this, ``execute()`` without ``now_us`` signed ``utc_now_micros()``, so
two identical sessions could never share a head hash. These tests pin:

- the signed, gated and ledgered time is ``base + n * tick``;
- the wall clock of each call is recorded, apart from the chain;
- two sessions with one seed and one call sequence share a head hash;
- a caller-supplied ``now_us`` is still honoured, and the clock stays ordered
  behind it;
- the things that read the time (ledger rows, claim leases) keep working on
  it: a logical clock must not silently break them.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.claims import ClaimRegistry
from causalmesh.crypto.keys import KeyPair
from causalmesh.gateway.clock import DEFAULT_CLOCK_TICK_US, LogicalClock
from causalmesh.gateway.gateway import ToolGateway
from causalmesh.hooks.lifecycle import LifecycleBoundary
from causalmesh.hooks.policy_gate import ContractGate
from causalmesh.policy.contract import Contract
from causalmesh.policy.ledger import Ledger
from causalmesh.policy.resource import Resource
from causalmesh.relay import NullDelivery, Relay
from causalmesh.sdk.identity import make_identity

pytestmark = pytest.mark.unit

SEED = b"clock-seed-000000000000000000000"

CONTRACT = """\
version: 1
roles:
  - agent_id: alice
    archetype: writer
    owns: [src/]
  - agent_id: bob
    archetype: writer
    owns: [docs/]
  - agent_id: buyer
    archetype: spender
    allow: [api.example.com]
    budget:
      usd_total: "0.30"
      usd_per_call: "0.10"
policy:
  arm: C3
"""

WALL_FLOOR_US = 1_600_000_000_000_000  # any real clock reading is above this

# A lease is held on a resource identity ("path:shared/file.txt"), not a bare path.
LEASED = Resource.path("shared/file.txt").identity


def _contract(tmp_path: Path) -> Contract:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT, encoding="utf-8")
    return Contract.find(tmp_path)


def _mesh(tmp_path: Path, **kwargs: Any) -> CausalMesh:
    kwargs.setdefault("seed", SEED)
    kwargs.setdefault("agent_id", "alice")
    mesh = CausalMesh(contract=_contract(tmp_path), **kwargs)
    mesh.register_tool(
        Tool(name="write", handler=lambda path: "ok", resource_args=["path"], kind="filesystem")
    )
    mesh.register_tool(
        Tool(
            name="pay",
            handler=lambda to, usd: "paid",
            resource_args=["to"],
            resource_kind="spend",
            amount_arg="usd",
        )
    )
    return mesh


def _stamps(mesh: CausalMesh) -> list[int]:
    return [int(r["event"]["timestamp_us"]) for r in mesh.audit_events()]


def _sequence(mesh: CausalMesh) -> None:
    mesh.execute(tool="write", arguments={"path": "src/a.py"})
    mesh.execute(tool="write", arguments={"path": "docs/x.md"})  # refused: bob's
    mesh.execute(tool="write", arguments={"path": "src/b.py"})


class TestTheClockItself:
    def test_it_issues_base_plus_n_ticks(self) -> None:
        clock = LogicalClock(base_us=100, tick_us=7)
        assert clock.now_us == 100
        assert [clock.tick() for _ in range(3)] == [100, 107, 114]
        assert clock.now_us == 114

    def test_a_supplied_time_is_kept_and_later_ticks_stay_after_it(self) -> None:
        clock = LogicalClock(base_us=0, tick_us=10)
        clock.tick()
        assert clock.observe(500) == 500
        assert clock.tick() == 510
        clock.observe(5)  # behind the clock: honoured for that call, never rewinds it
        assert clock.tick() == 520

    @pytest.mark.parametrize(
        ("base", "tick"), [(-1, 1), (0, 0), (0, -5), (1.5, 1), (0, 2.0), (True, 1)]
    )
    def test_nonsense_parameters_are_refused(self, base: Any, tick: Any) -> None:
        with pytest.raises(ValueError):
            LogicalClock(base_us=base, tick_us=tick)


class TestTheSignedTimestamp:
    def test_it_is_logical_not_the_wall_clock(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        _sequence(mesh)
        tick = DEFAULT_CLOCK_TICK_US
        assert _stamps(mesh) == [0, tick, 2 * tick]

    def test_base_and_tick_are_the_callers_to_choose(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path, clock_base_us=1_000, clock_tick_us=50)
        _sequence(mesh)
        assert _stamps(mesh) == [1_000, 1_050, 1_100]

    def test_two_sessions_with_one_seed_and_one_sequence_share_a_head_hash(
        self, tmp_path: Path
    ) -> None:
        a, b = _mesh(tmp_path / "a"), _mesh(tmp_path / "b")
        _sequence(a)
        time.sleep(0.01)  # the wall clock moves between them; the chain must not
        _sequence(b)
        assert a._relay.head_hash == b._relay.head_hash
        assert a.audit_events() == b.audit_events()

    def test_a_different_call_sequence_gives_a_different_head(self, tmp_path: Path) -> None:
        """The other half: a clock that ignored the calls would pass the test above."""
        a, b = _mesh(tmp_path / "a"), _mesh(tmp_path / "b")
        _sequence(a)
        _sequence(b)
        b.execute(tool="write", arguments={"path": "src/c.py"})
        assert a._relay.head_hash != b._relay.head_hash

    def test_the_async_path_uses_the_same_clock(self, tmp_path: Path) -> None:
        import asyncio

        mesh = _mesh(tmp_path)

        async def run() -> None:
            await mesh.execute_async(tool="write", arguments={"path": "src/a.py"})
            mesh.execute(tool="write", arguments={"path": "src/b.py"})
            await mesh.execute_async(tool="write", arguments={"path": "src/c.py"})

        asyncio.run(run())
        assert _stamps(mesh) == [0, DEFAULT_CLOCK_TICK_US, 2 * DEFAULT_CLOCK_TICK_US]

    def test_a_supplied_now_us_is_signed_as_given_and_the_clock_follows_it(
        self, tmp_path: Path
    ) -> None:
        mesh = _mesh(tmp_path)
        mesh.execute(tool="write", arguments={"path": "src/a.py"}, now_us=9_000_000_000)
        mesh.execute(tool="write", arguments={"path": "src/b.py"})
        assert _stamps(mesh) == [9_000_000_000, 9_000_000_000 + DEFAULT_CLOCK_TICK_US]

    def test_a_refused_and_an_unknown_tool_both_behave(self, tmp_path: Path) -> None:
        """A refusal consumes a tick (it is an event); a call that never starts does not."""
        from causalmesh.sdk.errors import ToolNotFoundError, UnknownAgentError

        mesh = _mesh(tmp_path)
        with pytest.raises(ToolNotFoundError):
            mesh.execute(tool="nope")
        with pytest.raises(UnknownAgentError):
            mesh.execute(agent_id="stranger", tool="write", arguments={"path": "src/a"})
        mesh.execute(tool="write", arguments={"path": "src/a.py"})
        assert _stamps(mesh) == [0]


class TestTheWallClock:
    def test_each_recorded_call_has_its_wall_time_outside_the_chain(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        before = time.time_ns() // 1_000
        _sequence(mesh)
        after = time.time_ns() // 1_000

        wall = mesh._gateway.wall_times()
        ids = [r["event"]["event_id"] for r in mesh.audit_events()]
        assert sorted(wall) == sorted(ids)
        assert all(before <= value <= after for value in wall.values())
        assert all(stamp < WALL_FLOOR_US for stamp in _stamps(mesh))

    def test_an_unrecorded_call_has_no_wall_time_rather_than_zero(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        relay = mesh._relay
        original = relay.ingest

        def refuse(**_: Any) -> Any:
            from causalmesh.relay.core import IngestResult

            return IngestResult(accepted=False, chained=None, sequence=None, reason="refused")

        relay.ingest = refuse  # type: ignore[method-assign]
        result = mesh.execute(tool="write", arguments={"path": "src/a.py"})
        relay.ingest = original  # type: ignore[method-assign]
        assert result.recorded is False
        assert mesh._gateway.wall_times() == {}


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[Ledger]:
    with Ledger(tmp_path / "ledger.db", run_id="sdk") as led:
        yield led


class TestLedgerOnTheLogicalClock:
    def test_rows_carry_the_logical_time_and_totals_are_unchanged(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        mesh = _mesh(tmp_path, agent_id="buyer", ledger=ledger)
        for _ in range(3):
            assert mesh.execute(
                tool="pay", arguments={"to": "api.example.com", "usd": "0.10"}
            ).executed
        entries = ledger.entries()
        assert [e.timestamp_us for e in entries] == [
            0,
            DEFAULT_CLOCK_TICK_US,
            2 * DEFAULT_CLOCK_TICK_US,
        ]
        assert sum((e.amount for e in entries), Decimal(0)) == Decimal("0.30")
        # the total still holds, and the refusal is the budget's, not the clock's
        over = mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": "0.01"})
        assert over.denied and over.rule == "budget"

    def test_a_ledger_row_is_linked_to_the_event_signed_at_the_same_time(
        self, tmp_path: Path, ledger: Ledger
    ) -> None:
        mesh = _mesh(tmp_path, agent_id="buyer", ledger=ledger)
        mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": "0.10"})
        (entry,) = ledger.entries()
        (record,) = mesh.audit_events()
        assert entry.reference == record["event"]["event_id"]
        assert entry.timestamp_us == record["event"]["timestamp_us"]

    def test_two_identical_sessions_have_identical_ledger_rows(self, tmp_path: Path) -> None:
        rows = []
        for name in ("a", "b"):
            with Ledger(tmp_path / f"{name}.db", run_id="sdk") as led:
                mesh = _mesh(tmp_path / name, agent_id="buyer", ledger=led)
                for _ in range(2):
                    mesh.execute(tool="pay", arguments={"to": "api.example.com", "usd": "0.10"})
                rows.append([e.to_dict() for e in led.entries()])
        assert rows[0] == rows[1]


class TestLeasesOnTheLogicalClock:
    """The SDK builds its gate without a claim registry today, so this wires one
    by hand: the gate reads the gateway's logical time, and a lease is only as
    good as the clock it was granted on."""

    def _gateway(self, tmp_path: Path, registry: ClaimRegistry) -> ToolGateway:
        contract = _contract(tmp_path)
        gate = ContractGate.build(contract, run_id="sdk", registry=registry, enforcing=True)
        relay = Relay(
            run_id="sdk",
            keypairs={a: KeyPair.derive(SEED, a) for a in ("alice", "bob")},
            delivery=NullDelivery(),
        )
        gateway = ToolGateway(
            boundary=LifecycleBoundary(gate=gate),
            relay=relay,
            agent_id="alice",
            identity_factory=lambda aid: make_identity(aid, contract=contract, run_id="sdk"),
            gate=gate,
        )
        gateway.register(
            Tool(name="touch", handler=lambda path: "ok", resource_args=["path"], kind="filesystem")
        )
        return gateway

    def test_a_lease_granted_on_the_logical_clock_blocks_then_expires(self, tmp_path: Path) -> None:
        registry = ClaimRegistry()
        try:
            gateway = self._gateway(tmp_path, registry)
            tick = gateway.clock.tick_us
            granted = registry.acquire(
                claim_id="c1",
                path=LEASED,
                agent_id="alice",
                run_id="sdk",
                now_us=gateway.clock.now_us,
                duration_us=3 * tick,  # three logical seconds: three calls
            )
            assert granted.granted

            verdicts = [
                gateway.execute("bob", "touch", {"path": "shared/file.txt"}).denied
                for _ in range(5)
            ]
            # Time starts at the lease's own moment (0): the first calls fall
            # inside [0, 3*tick) and are refused, then it expires.
            assert verdicts == [True, True, True, False, False]
        finally:
            registry.close()

    def test_a_lease_granted_on_the_wall_clock_never_expires_in_logical_time(
        self, tmp_path: Path
    ) -> None:
        """The hazard, pinned so nobody is surprised by it: a caller that still
        uses the wall clock for leases holds them far beyond any logical time."""
        registry = ClaimRegistry()
        try:
            gateway = self._gateway(tmp_path, registry)
            registry.acquire(
                claim_id="c1",
                path=LEASED,
                agent_id="alice",
                run_id="sdk",
                now_us=time.time_ns() // 1_000,
                duration_us=1_000_000,
            )
            results = [
                gateway.execute("bob", "touch", {"path": "shared/file.txt"}).denied
                for _ in range(10)
            ]
            assert all(results)
        finally:
            registry.close()

    def test_mesh_now_us_is_the_moment_to_grant_a_lease_at(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        assert mesh.now_us == 0
        mesh.execute(tool="write", arguments={"path": "src/a.py"})
        mesh.execute(tool="write", arguments={"path": "src/b.py"})
        assert mesh.now_us == DEFAULT_CLOCK_TICK_US
