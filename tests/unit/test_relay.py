"""Unit tests for the relay (spec §55, §14, §31).

Two things are load-bearing here and get the most attention:

- **Sequencing and chaining under concurrency.** Two events sharing a
  sequence number, or a link computed against a stale head, would corrupt the
  record irrecoverably — and unlike a claim conflict, nothing would record
  that it happened.
- **Refusal to rewrite.** A relay that silently repaired a malformed or
  misattributed event would be editing evidence.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from causalmesh.claims import ClaimRegistry
from causalmesh.crypto.chain import GENESIS_HASH
from causalmesh.crypto.keys import KeyPair
from causalmesh.events.schema import EventIdentity, EventType
from causalmesh.relay import (
    BroadcastDelivery,
    ChainStore,
    NullDelivery,
    PathScopedDelivery,
    Relay,
    StoreError,
    policy_for_arm,
)
from causalmesh.verifier import verify_chain

pytestmark = pytest.mark.unit

SEED = b"causalmesh-relay-unit-seed-0001"
RUN = "run_001"
AGENTS = ("agent_a", "agent_b", "agent_c")
BASE_TIME = 1_700_000_000_000_000


@pytest.fixture
def keypairs() -> dict[str, KeyPair]:
    return {agent: KeyPair.derive(SEED, agent) for agent in AGENTS}


def make_relay(keypairs: dict[str, KeyPair], **kwargs) -> Relay:
    kwargs.setdefault("delivery", BroadcastDelivery())
    kwargs.setdefault("participants", AGENTS)
    return Relay(run_id=RUN, keypairs=keypairs, **kwargs)


def identity(agent: str = "agent_a", arm: str = "C2", run: str = RUN) -> EventIdentity:
    return EventIdentity(
        experiment_id="exp_unit", task_id="task_unit", run_id=run, agent_id=agent, arm=arm
    )


def ingest(relay: Relay, index: int, agent: str = "agent_a", **kwargs):
    kwargs.setdefault("event_type", EventType.WRITE)
    kwargs.setdefault("paths", ("src/schema.py",))
    return relay.ingest(
        event_id=f"evt_{index:04d}",
        agent_id=agent,
        identity=identity(agent),
        timestamp_us=BASE_TIME + index,
        **kwargs,
    )


class TestSequencing:
    def test_sequences_start_at_zero_and_increment(self, keypairs) -> None:
        relay = make_relay(keypairs)
        assert [ingest(relay, i).sequence for i in range(4)] == [0, 1, 2, 3]

    def test_the_relay_assigns_sequence_not_the_agent(self, keypairs) -> None:
        # An agent-chosen sequence would let a fast agent claim an earlier
        # position than it earned, misrepresenting causality.
        relay = make_relay(keypairs)
        result = ingest(relay, 0)
        assert result.chained is not None
        assert result.chained.event.sequence == 0

    def test_the_first_link_joins_genesis(self, keypairs) -> None:
        relay = make_relay(keypairs)
        result = ingest(relay, 0)
        assert result.chained is not None
        assert result.chained.previous_hash == GENESIS_HASH

    def test_the_head_advances_with_each_event(self, keypairs) -> None:
        relay = make_relay(keypairs)
        heads = [GENESIS_HASH]
        for i in range(3):
            ingest(relay, i)
            heads.append(relay.head_hash)
        assert len(set(heads)) == 4

    def test_concurrent_ingestion_produces_a_valid_chain(self, keypairs) -> None:
        """The failure this guards against is silent and unrecoverable."""
        relay = make_relay(keypairs)

        def submit(index: int) -> bool:
            return ingest(relay, index, agent=AGENTS[index % len(AGENTS)]).accepted

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert all(pool.map(submit, range(24)))

        result = verify_chain(relay.records(), relay.key_ring())
        assert result.valid, result.summary()
        assert result.events == 24

    def test_concurrent_ingestion_assigns_unique_sequences(self, keypairs) -> None:
        relay = make_relay(keypairs)

        def submit(index: int) -> int | None:
            return ingest(relay, index, agent=AGENTS[index % len(AGENTS)]).sequence

        with ThreadPoolExecutor(max_workers=8) as pool:
            sequences = list(pool.map(submit, range(24)))

        assert sorted(sequences) == list(range(24))


class TestRefusalToRewrite:
    """§55: the relay never silently corrects what it records."""

    def test_an_unregistered_actor_is_rejected(self, keypairs) -> None:
        relay = make_relay(keypairs)
        result = relay.ingest(
            event_id="evt_0000",
            agent_id="agent_unknown",
            event_type=EventType.WRITE,
            identity=identity("agent_unknown"),
            timestamp_us=BASE_TIME,
        )
        assert not result.accepted
        assert "no registered key" in result.reason

    def test_a_misattributed_event_is_rejected(self, keypairs) -> None:
        # Submitted by agent_a but claiming to be agent_b's work.
        relay = make_relay(keypairs)
        result = relay.ingest(
            event_id="evt_0000",
            agent_id="agent_a",
            event_type=EventType.WRITE,
            identity=identity("agent_b"),
            timestamp_us=BASE_TIME,
        )
        assert not result.accepted
        assert "misattributed" in result.reason

    def test_an_event_from_another_run_is_rejected(self, keypairs) -> None:
        # Arms must not share a chain (§2).
        relay = make_relay(keypairs)
        result = relay.ingest(
            event_id="evt_0000",
            agent_id="agent_a",
            event_type=EventType.WRITE,
            identity=identity("agent_a", run="run_other"),
            timestamp_us=BASE_TIME,
        )
        assert not result.accepted
        assert "run" in result.reason

    def test_a_duplicate_event_id_is_rejected(self, keypairs) -> None:
        relay = make_relay(keypairs)
        assert ingest(relay, 0).accepted
        assert not ingest(relay, 0).accepted

    def test_a_malformed_event_is_rejected_not_repaired(self, keypairs) -> None:
        relay = make_relay(keypairs)
        result = relay.ingest(
            event_id="evt_0000",
            agent_id="agent_a",
            event_type=EventType.WRITE,
            identity=identity(),
            timestamp_us=-1,  # invalid
        )
        assert not result.accepted
        assert "invalid event" in result.reason

    def test_rejections_do_not_advance_the_chain(self, keypairs) -> None:
        # A rejected event must leave no trace in the record.
        relay = make_relay(keypairs)
        ingest(relay, 0)
        head_before, sequence_before = relay.head_hash, relay.sequence
        ingest(relay, 0)  # duplicate
        assert relay.head_hash == head_before
        assert relay.sequence == sequence_before
        assert relay.stats.events_rejected == 1


class TestFanOut:
    def test_c0_delivers_nothing(self, keypairs) -> None:
        """§14: C0 must receive no coordination data at all."""
        relay = make_relay(keypairs, delivery=NullDelivery())
        result = ingest(relay, 0, agent="agent_a")
        assert result.delivered_to == ()
        assert relay.pending_for("agent_b") == ()
        assert relay.pending_for("agent_c") == ()

    def test_broadcast_reaches_every_peer(self, keypairs) -> None:
        relay = make_relay(keypairs, delivery=BroadcastDelivery())
        result = ingest(relay, 0, agent="agent_a")
        assert set(result.delivered_to) == {"agent_b", "agent_c"}

    def test_an_actor_never_receives_its_own_event(self, keypairs) -> None:
        # It already knows; counting it would inflate coordination volume.
        relay = make_relay(keypairs, delivery=BroadcastDelivery())
        ingest(relay, 0, agent="agent_a")
        assert relay.pending_for("agent_a") == ()

    def test_drain_consumes_the_inbox(self, keypairs) -> None:
        relay = make_relay(keypairs, delivery=BroadcastDelivery())
        ingest(relay, 0, agent="agent_a")
        assert len(relay.drain("agent_b")) == 1
        assert relay.drain("agent_b") == ()

    def test_peek_does_not_consume(self, keypairs) -> None:
        relay = make_relay(keypairs, delivery=BroadcastDelivery())
        ingest(relay, 0, agent="agent_a")
        assert len(relay.pending_for("agent_b")) == 1
        assert len(relay.pending_for("agent_b")) == 1

    def test_delivery_is_recorded_on_the_result(self, keypairs) -> None:
        # "Who could have known what, and when" must be answerable from the
        # record rather than reconstructed from arm configuration (§57, §96).
        relay = make_relay(keypairs, delivery=BroadcastDelivery())
        assert set(ingest(relay, 0).delivered_to) == {"agent_b", "agent_c"}

    def test_path_scoped_delivery_targets_interested_agents(self, keypairs) -> None:
        relay = make_relay(
            keypairs,
            delivery=PathScopedDelivery(
                interests={
                    "agent_b": frozenset({"src/schema.py"}),
                    "agent_c": frozenset({"src/other.py"}),
                }
            ),
        )
        assert ingest(relay, 0, paths=("src/schema.py",)).delivered_to == ("agent_b",)

    def test_path_scoped_delivery_broadcasts_pathless_events(self, keypairs) -> None:
        # INTENT and FAILURE carry run-level meaning; scoping them by path
        # would silently hide them.
        relay = make_relay(
            keypairs,
            delivery=PathScopedDelivery(interests={"agent_b": frozenset({"src/schema.py"})}),
        )
        result = ingest(relay, 0, event_type=EventType.INTENT, paths=())
        assert set(result.delivered_to) == {"agent_b", "agent_c"}


class TestArmPolicies:
    def test_c0_gets_the_null_policy(self) -> None:
        assert isinstance(policy_for_arm("C0"), NullDelivery)

    @pytest.mark.parametrize("arm", ["C1", "C2", "C3"])
    def test_informed_arms_get_broadcast(self, arm: str) -> None:
        assert isinstance(policy_for_arm(arm), BroadcastDelivery)

    def test_arm_names_are_case_insensitive(self) -> None:
        assert isinstance(policy_for_arm("c0"), NullDelivery)

    def test_an_unknown_arm_raises_rather_than_defaulting(self) -> None:
        # A silent default could hand C0 a broadcast policy and destroy the
        # isolation the experiment rests on.
        with pytest.raises(ValueError, match="unknown arm"):
            policy_for_arm("C9")


class TestClaimGate:
    def test_without_a_registry_every_write_is_permitted(self, keypairs) -> None:
        relay = make_relay(keypairs)
        outcome = relay.may_write(path="src/schema.py", agent_id="agent_a", now_us=0)
        assert outcome.granted
        # The arm's behaviour is visible in the record, not merely implied.
        assert "no claim registry" in outcome.reason

    def test_with_a_registry_a_held_path_is_denied(self, keypairs, tmp_path: Path) -> None:
        with ClaimRegistry(tmp_path / "claims.db") as claims:
            claims.acquire(
                claim_id="c1",
                path="src/schema.py",
                agent_id="agent_a",
                run_id=RUN,
                now_us=0,
                duration_us=120_000_000,
            )
            relay = make_relay(keypairs, claims=claims)
            assert not relay.may_write(
                path="src/schema.py", agent_id="agent_b", now_us=1_000_000
            ).granted


class TestStore:
    def test_records_are_appended_in_order(self, keypairs) -> None:
        relay = make_relay(keypairs)
        for i in range(3):
            ingest(relay, i)
        assert [r["event"]["sequence"] for r in relay.records()] == [0, 1, 2]

    def test_returned_records_are_copies(self, keypairs) -> None:
        # A caller mutating a returned dict must not alter the store.
        relay = make_relay(keypairs)
        ingest(relay, 0)
        relay.records()[0]["chain_hash"] = "tampered"
        assert relay.records()[0]["chain_hash"] != "tampered"

    def test_a_file_backed_store_persists_records(self, keypairs, tmp_path: Path) -> None:
        chain_file = tmp_path / "chain.jsonl"
        with ChainStore(chain_file) as store:
            relay = make_relay(keypairs, store=store)
            for i in range(3):
                ingest(relay, i)

        lines = chain_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        assert json.loads(lines[0])["event"]["sequence"] == 0

    def test_reopening_a_populated_chain_is_refused(self, tmp_path: Path) -> None:
        """§31: a run's raw log belongs to exactly one run."""
        chain_file = tmp_path / "chain.jsonl"
        chain_file.write_text('{"existing": "record"}\n', encoding="utf-8")
        with pytest.raises(StoreError, match="append-only"):
            ChainStore(chain_file)

    def test_the_store_exposes_no_mutation_api(self) -> None:
        # §31 is enforced by giving the code no way to express an update.
        forbidden = {"update", "delete", "remove", "replace", "clear", "pop", "insert"}
        assert not forbidden & {name for name in dir(ChainStore) if not name.startswith("_")}


class TestExportAndSummary:
    def test_export_writes_a_self_contained_bundle(self, keypairs, tmp_path: Path) -> None:
        relay = make_relay(keypairs)
        for i in range(3):
            ingest(relay, i)

        paths = relay.export(tmp_path / "export")
        assert paths["chain"].exists() and paths["keyring"].exists()

        # Chain plus keys is everything the verifier needs.
        records = [json.loads(line) for line in paths["chain"].read_text().splitlines()]
        ring = json.loads(paths["keyring"].read_text())
        assert verify_chain(records, relay.key_ring()).valid
        assert set(ring) == set(AGENTS)

    def test_the_summary_reports_head_and_stats(self, keypairs) -> None:
        relay = make_relay(keypairs)
        for i in range(3):
            ingest(relay, i)

        summary = relay.summary()
        assert summary["sequence"] == 3
        assert summary["head_hash"] == relay.head_hash
        assert summary["stats"]["events_ingested"] == 3

    def test_latency_percentiles_are_none_when_unmeasured(self, keypairs) -> None:
        # "No measurements" must stay distinguishable from "measured zero".
        relay = make_relay(keypairs)
        assert relay.summary()["stats"]["append_latency_p50_us"] is None

    def test_delivery_count_is_tracked(self, keypairs) -> None:
        relay = make_relay(keypairs, delivery=BroadcastDelivery())
        ingest(relay, 0, agent="agent_a")
        assert relay.stats.deliveries == 2
