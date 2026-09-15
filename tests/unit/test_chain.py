"""Unit tests for the signed hash chain (spec §24, §27).

These cover the chain rule and per-link verification. The full attack battery
(§58) lives in tests/adversarial/ and operates over whole logs; what is tested
here is the primitive those attacks are detected by.
"""

from __future__ import annotations

import dataclasses
import hashlib

import pytest

from causalmesh.crypto.chain import (
    GENESIS_HASH,
    ChainError,
    compute_chain_hash,
    link_event,
)
from causalmesh.crypto.keys import KeyPair
from causalmesh.events.schema import Event, EventIdentity, EventType

pytestmark = pytest.mark.unit

SEED = b"causalmesh-test-master-seed-0001"


def make_identity(agent_id: str = "agent_a") -> EventIdentity:
    return EventIdentity(
        experiment_id="exp_test",
        task_id="task_schema_handler",
        run_id="run_001",
        agent_id=agent_id,
        arm="C2",
    )


def make_event(
    sequence: int = 0,
    agent_id: str = "agent_a",
    event_type: EventType = EventType.WRITE,
    paths: tuple[str, ...] = ("src/schema.py",),
) -> Event:
    return Event(
        event_id=f"evt_{sequence:04d}",
        identity=make_identity(agent_id),
        event_type=event_type,
        sequence=sequence,
        timestamp_us=1_700_000_000_000_000 + sequence,
        paths=paths,
    )


class TestChainHash:
    def test_matches_the_specified_rule(self) -> None:
        # Recompute independently: SHA256(raw_prev_bytes || canonical(event)).
        event = make_event()
        expected = hashlib.sha256(bytes.fromhex(GENESIS_HASH) + event.canonical_bytes()).hexdigest()
        assert compute_chain_hash(GENESIS_HASH, event) == expected

    def test_is_deterministic(self) -> None:
        event = make_event()
        assert len({compute_chain_hash(GENESIS_HASH, event) for _ in range(20)}) == 1

    def test_depends_on_the_previous_hash(self) -> None:
        event = make_event()
        other = hashlib.sha256(b"a different history").hexdigest()
        assert compute_chain_hash(GENESIS_HASH, event) != compute_chain_hash(other, event)

    def test_depends_on_the_event(self) -> None:
        a = compute_chain_hash(GENESIS_HASH, make_event(sequence=0))
        b = compute_chain_hash(GENESIS_HASH, make_event(sequence=1))
        assert a != b

    def test_genesis_is_domain_separated(self) -> None:
        # Not 32 zero bytes: a chain from another system must never validate here.
        assert GENESIS_HASH != "00" * 32
        assert (
            bytes.fromhex(GENESIS_HASH) == hashlib.sha256(b"causalmesh/chain/genesis/v1").digest()
        )

    @pytest.mark.parametrize(
        "bad_previous", ["", "zz", "ab" * 31, "ab" * 33], ids=["empty", "not-hex", "short", "long"]
    )
    def test_malformed_previous_hash_is_rejected(self, bad_previous: str) -> None:
        with pytest.raises(ChainError):
            compute_chain_hash(bad_previous, make_event())


class TestLinking:
    def test_produces_a_verifiable_link(self) -> None:
        keypair = KeyPair.derive(SEED, "agent_a")
        linked = link_event(make_event(), GENESIS_HASH, keypair)
        assert linked.verify_hash()
        assert linked.verify_signature()

    def test_records_the_signing_actor_public_key(self) -> None:
        keypair = KeyPair.derive(SEED, "agent_a")
        linked = link_event(make_event(), GENESIS_HASH, keypair)
        assert linked.actor_public_key == keypair.public_key_hex

    def test_signing_a_peers_event_is_refused(self) -> None:
        # Would produce a log that verifies cryptographically while crediting
        # the wrong actor — a silently wrong attribution, not a loud failure.
        relay_key = KeyPair.derive(SEED, "relay")
        with pytest.raises(ChainError, match="actor mismatch"):
            link_event(make_event(agent_id="agent_a"), GENESIS_HASH, relay_key)

    def test_chain_of_three_links(self) -> None:
        keypair = KeyPair.derive(SEED, "agent_a")
        previous = GENESIS_HASH
        for sequence in range(3):
            linked = link_event(make_event(sequence=sequence), previous, keypair)
            assert linked.previous_hash == previous
            assert linked.verify_hash() and linked.verify_signature()
            previous = linked.chain_hash

    def test_signature_covers_history_not_just_the_event(self) -> None:
        # The same event at the same sequence in two different histories must
        # get different signatures, or an event could be lifted between chains.
        keypair = KeyPair.derive(SEED, "agent_a")
        event = make_event()
        first = link_event(event, GENESIS_HASH, keypair)
        second = link_event(event, hashlib.sha256(b"other history").hexdigest(), keypair)
        assert first.signature != second.signature


class TestTamperDetection:
    def test_mutating_the_event_breaks_the_hash(self) -> None:
        keypair = KeyPair.derive(SEED, "agent_a")
        linked = link_event(make_event(), GENESIS_HASH, keypair)
        tampered = dataclasses.replace(linked, event=make_event(paths=("src/other.py",)))
        assert not tampered.verify_hash()

    def test_mutating_the_chain_hash_breaks_the_signature(self) -> None:
        # An attacker who edits an event and recomputes its digest still
        # cannot produce a matching signature without the private key.
        keypair = KeyPair.derive(SEED, "agent_a")
        linked = link_event(make_event(), GENESIS_HASH, keypair)
        forged = dataclasses.replace(
            linked, chain_hash=compute_chain_hash(GENESIS_HASH, make_event(paths=("evil.py",)))
        )
        assert not forged.verify_signature()

    def test_relinking_to_a_different_predecessor_breaks_the_hash(self) -> None:
        keypair = KeyPair.derive(SEED, "agent_a")
        linked = link_event(make_event(), GENESIS_HASH, keypair)
        moved = dataclasses.replace(linked, previous_hash=hashlib.sha256(b"elsewhere").hexdigest())
        assert not moved.verify_hash()

    def test_substituting_another_actors_public_key_breaks_the_signature(self) -> None:
        signer = KeyPair.derive(SEED, "agent_a")
        linked = link_event(make_event(), GENESIS_HASH, signer)
        reattributed = dataclasses.replace(
            linked, actor_public_key=KeyPair.derive(SEED, "agent_b").public_key_hex
        )
        assert not reattributed.verify_signature()

    def test_corrupt_chain_hash_hex_is_a_failure_not_a_crash(self) -> None:
        keypair = KeyPair.derive(SEED, "agent_a")
        linked = link_event(make_event(), GENESIS_HASH, keypair)
        garbage = dataclasses.replace(linked, chain_hash="not-hex")
        assert garbage.verify_hash() is False
        assert garbage.verify_signature() is False


class TestSerialization:
    def test_to_dict_carries_every_verification_input(self) -> None:
        keypair = KeyPair.derive(SEED, "agent_a")
        record = link_event(make_event(), GENESIS_HASH, keypair).to_dict()
        assert set(record) == {
            "actor_public_key",
            "chain_hash",
            "event",
            "previous_hash",
            "signature",
        }

    def test_canonical_record_bytes_are_deterministic(self) -> None:
        keypair = KeyPair.derive(SEED, "agent_a")
        linked = link_event(make_event(), GENESIS_HASH, keypair)
        assert len({linked.canonical_record_bytes() for _ in range(10)}) == 1
