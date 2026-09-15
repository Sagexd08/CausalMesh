"""The adversarial verification battery (spec §27, §58).

Every attack here operates on the serialized records — the same bytes that
land in `data/raw/` — because that is the surface an attacker with filesystem
access actually has.

The expected outcomes come straight from §27:

    mutation       -> detected
    insertion      -> detected
    deletion       -> detected
    reordering     -> detected
    attribution    -> detected
    suffix         -> undetected without anchor
    suffix         -> detected with anchor

The suffix rows are as important as the others. A battery that only
demonstrated successes would misrepresent what the chain guarantees, and §87
forbids claiming a property no test establishes.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from causalmesh.crypto.chain import GENESIS_HASH, link_event
from causalmesh.crypto.keys import KeyPair, PublicKeyRing
from causalmesh.events.schema import EventType
from causalmesh.verifier import AnchorStatus, FailureKind, verify_chain
from chain_fixtures import SEED, build_event

pytestmark = pytest.mark.adversarial


def kinds(result: Any) -> set[FailureKind]:
    return {failure.kind for failure in result.failures}


class TestBaseline:
    """The battery is meaningless unless the untampered chain verifies."""

    def test_clean_chain_is_valid(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        result = verify_chain(clean_records, key_ring)
        assert result.valid, result.summary()
        assert result.events == len(clean_records)
        assert result.chain_failures == 0
        assert result.signature_failures == 0
        assert result.ordering_failures == 0

    def test_clean_chain_reports_its_actors_and_head(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        result = verify_chain(clean_records, key_ring)
        assert result.actors == ("agent_a", "agent_b")
        assert result.head_hash == clean_records[-1]["chain_hash"]
        assert result.key_ring_fingerprint == key_ring.fingerprint()


class TestMutation:
    """§58: event mutation must be detected."""

    def test_changing_a_path_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        # The classic attack: rewrite history so a write appears to have
        # touched a different file than it did.
        tampered = copy.deepcopy(clean_records)
        tampered[1]["event"]["paths"] = ["src/somewhere_else.py"]

        result = verify_chain(tampered, key_ring)
        assert not result.valid
        assert FailureKind.CHAIN_BREAK in kinds(result)
        assert any(f.index == 1 for f in result.failures)

    def test_changing_an_event_type_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        tampered = copy.deepcopy(clean_records)
        tampered[1]["event"]["event_type"] = str(EventType.READ)
        assert FailureKind.CHAIN_BREAK in kinds(verify_chain(tampered, key_ring))

    def test_changing_a_timestamp_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        # Backdating an event would let an attacker fake what an agent could
        # have known at write time — the core staleness measurement (§23).
        tampered = copy.deepcopy(clean_records)
        tampered[2]["event"]["timestamp_us"] = 1
        assert FailureKind.CHAIN_BREAK in kinds(verify_chain(tampered, key_ring))

    def test_mutation_with_recomputed_digest_is_still_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        """A sophisticated attacker recomputes the chain after editing.

        Recomputing digests is free, so the chain alone would accept this.
        The signature is what stops it: the attacker cannot re-sign the new
        digest without the actor's private key.
        """
        from causalmesh.crypto.chain import compute_chain_hash

        tampered = copy.deepcopy(clean_records)
        tampered[1]["event"]["paths"] = ["src/evil.py"]

        # Rebuild every digest from the mutation onward so the chain links.
        previous = tampered[0]["chain_hash"]
        for record in tampered[1:]:
            event = build_event(
                record["event"]["sequence"],
                record["event"]["identity"]["agent_id"],
                EventType(record["event"]["event_type"]),
                tuple(record["event"]["paths"]),
            )
            record["previous_hash"] = previous
            record["chain_hash"] = compute_chain_hash(previous, event)
            previous = record["chain_hash"]

        result = verify_chain(tampered, key_ring)
        assert not result.valid
        # The chain now links, but the signatures no longer match.
        assert FailureKind.SIGNATURE_INVALID in kinds(result)


class TestInsertion:
    """§58: event insertion must be detected."""

    def test_inserting_a_forged_event_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        tampered = copy.deepcopy(clean_records)
        forged = copy.deepcopy(clean_records[1])
        forged["event"]["event_id"] = "evt_9999"
        forged["event"]["paths"] = ["src/injected.py"]
        tampered.insert(2, forged)

        result = verify_chain(tampered, key_ring)
        assert not result.valid
        assert kinds(result) & {FailureKind.CHAIN_BREAK, FailureKind.ORDERING_INVALID}

    def test_inserting_a_validly_signed_event_from_elsewhere_is_detected(
        self,
        clean_records: list[dict[str, Any]],
        keypairs: dict[str, KeyPair],
        key_ring: PublicKeyRing,
    ) -> None:
        """Replaying a genuinely signed event into a different position.

        The event and its signature are authentic — they were produced by the
        real actor with the real key. Only its *position* is a lie. This is
        caught because the signature covers the chain digest, which encodes
        the entire preceding history.
        """
        elsewhere = build_event(1, "agent_a", EventType.WRITE, ("src/schema.py",))
        genuine = link_event(elsewhere, GENESIS_HASH, keypairs["agent_a"])

        tampered = copy.deepcopy(clean_records)
        tampered.insert(3, genuine.to_dict())

        result = verify_chain(tampered, key_ring)
        assert not result.valid
        assert kinds(result) & {FailureKind.CHAIN_BREAK, FailureKind.ORDERING_INVALID}

    def test_duplicate_replay_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        # §58 lists duplicate replay separately: the same event appearing
        # twice would double-count work in the metrics.
        tampered = copy.deepcopy(clean_records)
        tampered.insert(2, copy.deepcopy(clean_records[1]))

        result = verify_chain(tampered, key_ring)
        assert not result.valid
        assert FailureKind.DUPLICATE_EVENT_ID in kinds(result)


class TestDeletion:
    """§58: event deletion must be detected."""

    @pytest.mark.parametrize("index", [0, 1, 2, 3])
    def test_deleting_any_interior_event_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing, index: int
    ) -> None:
        # Deleting an interior event is how an attacker would hide a
        # conflicting write or a stale read.
        tampered = copy.deepcopy(clean_records)
        del tampered[index]

        result = verify_chain(tampered, key_ring)
        assert not result.valid
        assert kinds(result) & {FailureKind.CHAIN_BREAK, FailureKind.ORDERING_INVALID}

    def test_deletion_leaves_a_sequence_gap(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        tampered = copy.deepcopy(clean_records)
        del tampered[2]
        result = verify_chain(tampered, key_ring)
        ordering = [f for f in result.failures if f.kind == FailureKind.ORDERING_INVALID]
        assert ordering
        assert "expected sequence 2" in ordering[0].detail


class TestReordering:
    """§58: event reordering must be detected."""

    def test_swapping_two_adjacent_events_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        # Reordering would misrepresent causality: it could make a read that
        # happened before a write appear to have happened after it.
        tampered = copy.deepcopy(clean_records)
        tampered[1], tampered[2] = tampered[2], tampered[1]

        result = verify_chain(tampered, key_ring)
        assert not result.valid
        assert kinds(result) & {FailureKind.CHAIN_BREAK, FailureKind.ORDERING_INVALID}

    def test_reversing_the_whole_chain_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        result = verify_chain(list(reversed(copy.deepcopy(clean_records))), key_ring)
        assert not result.valid
        assert FailureKind.ORDERING_INVALID in kinds(result)


class TestAttribution:
    """§58: non-consensual attribution must be detected."""

    def test_reassigning_an_event_to_another_actor_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        # Crediting agent_a's write to agent_b would corrupt every per-actor
        # measurement while leaving the work itself intact.
        tampered = copy.deepcopy(clean_records)
        tampered[1]["event"]["identity"]["agent_id"] = "agent_b"

        result = verify_chain(tampered, key_ring)
        assert not result.valid
        assert kinds(result) & {FailureKind.CHAIN_BREAK, FailureKind.KEY_MISMATCH}

    def test_reassigning_with_a_swapped_public_key_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        """The attacker also swaps the embedded key to match the new actor.

        This is why the verifier checks against the *ring* rather than the key
        the record carries: trusting the embedded key would make this attack
        succeed silently.
        """
        tampered = copy.deepcopy(clean_records)
        tampered[1]["event"]["identity"]["agent_id"] = "agent_b"
        tampered[1]["actor_public_key"] = key_ring.keys["agent_b"]

        result = verify_chain(tampered, key_ring)
        assert not result.valid
        assert FailureKind.SIGNATURE_INVALID in kinds(result)

    def test_an_event_from_an_unknown_actor_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        # An agent that never joined the relay cannot appear in the log
        # without the key ring flagging it.
        outsider = KeyPair.derive(SEED, "agent_intruder")
        event = build_event(5, "agent_intruder", EventType.WRITE, ("src/api.py",))
        linked = link_event(event, clean_records[-1]["chain_hash"], outsider)

        tampered = [*copy.deepcopy(clean_records), linked.to_dict()]
        result = verify_chain(tampered, key_ring)
        assert not result.valid
        assert FailureKind.UNKNOWN_ACTOR in kinds(result)

    def test_signature_substitution_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        tampered = copy.deepcopy(clean_records)
        tampered[1]["signature"] = clean_records[3]["signature"]
        assert FailureKind.SIGNATURE_INVALID in kinds(verify_chain(tampered, key_ring))


class TestSuffixTruncation:
    """§27, §58: the documented limitation, asserted in both directions."""

    def test_truncation_is_undetected_without_an_anchor(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        """The honest negative result.

        Dropping trailing events leaves a shorter, internally consistent
        chain. No in-chain mechanism can detect it, and the verifier says so
        by reporting the full remaining length as unanchored exposure rather
        than by pretending the log is intact.
        """
        truncated = copy.deepcopy(clean_records)[:3]

        result = verify_chain(truncated, key_ring)
        assert result.valid, "truncation genuinely is undetectable without an anchor"
        assert result.events == 3
        assert result.anchor_status == AnchorStatus.NOT_ANCHORED
        # The whole log is exposed, and the result states the exposure.
        assert result.unanchored_suffix == 3

    def test_truncation_is_detected_with_an_anchor(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        # An anchor recorded externally at the final sequence closes the gap.
        anchors = {4: clean_records[4]["chain_hash"]}
        truncated = copy.deepcopy(clean_records)[:3]

        result = verify_chain(truncated, key_ring, anchors=anchors)
        assert not result.valid
        assert FailureKind.ANCHOR_MISSING_EVENT in kinds(result)
        assert result.anchor_status == AnchorStatus.MISMATCH

    def test_an_intact_chain_verifies_against_its_anchor(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        anchors = {4: clean_records[4]["chain_hash"]}
        result = verify_chain(clean_records, key_ring, anchors=anchors)
        assert result.valid
        assert result.anchor_status == AnchorStatus.VERIFIED
        assert result.unanchored_suffix == 0

    def test_anchor_mismatch_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        # A log that has been rewritten wholesale still fails against an
        # externally recorded head.
        anchors = {4: "ff" * 32}
        result = verify_chain(clean_records, key_ring, anchors=anchors)
        assert not result.valid
        assert FailureKind.ANCHOR_MISMATCH in kinds(result)

    def test_partial_anchoring_reports_the_exposed_suffix(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        """Anchoring mid-chain protects only up to the anchor (§28).

        Events after the highest anchor remain truncatable, and the reported
        count is the honest measure of that exposure.
        """
        anchors = {2: clean_records[2]["chain_hash"]}
        result = verify_chain(clean_records, key_ring, anchors=anchors)
        assert result.valid
        assert result.anchor_status == AnchorStatus.VERIFIED
        assert result.unanchored_suffix == 2


class TestMalformedInput:
    """A tampered log is entitled to contain garbage; the verifier must not crash."""

    def test_an_empty_log_is_reported_not_crashed(self, key_ring: PublicKeyRing) -> None:
        result = verify_chain([], key_ring)
        assert result.events == 0
        assert result.head_hash is None

    @pytest.mark.parametrize(
        "garbage",
        [{}, {"event": "not-an-object"}, {"__unparseable__": "{{{"}, {"event": {}}],
        ids=["empty-object", "event-not-object", "unparseable-line", "empty-event"],
    )
    def test_malformed_records_are_reported_not_crashed(
        self, key_ring: PublicKeyRing, garbage: dict[str, Any]
    ) -> None:
        result = verify_chain([garbage], key_ring)
        assert not result.valid
        assert FailureKind.MALFORMED_RECORD in kinds(result)

    def test_a_corrupt_record_does_not_hide_the_valid_prefix(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        # How much of the log survived is itself a finding.
        tampered = [*copy.deepcopy(clean_records)[:2], {"__unparseable__": "{{{"}]
        result = verify_chain(tampered, key_ring)
        assert not result.valid
        assert result.events == 2
        assert FailureKind.MALFORMED_RECORD in kinds(result)

    def test_a_chain_not_starting_at_genesis_is_detected(
        self, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
    ) -> None:
        # Dropping the *prefix* rather than the suffix: unlike truncation from
        # the end, this is detectable, because the first link no longer joins
        # to genesis.
        result = verify_chain(copy.deepcopy(clean_records)[2:], key_ring)
        assert not result.valid
        assert FailureKind.CHAIN_BREAK in kinds(result)
