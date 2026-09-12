"""Unit tests for the offline verifier's own machinery (spec §26, §59).

Attack detection lives in `tests/adversarial/`. What is tested here is the
verifier's parsing, reporting and certificate output — the parts that must
behave correctly for a detection to be *reportable* rather than merely true.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from causalmesh.crypto.chain import GENESIS_HASH, link_event
from causalmesh.crypto.keys import KeyPair, PublicKeyRing
from causalmesh.events.schema import Event, EventIdentity, EventType
from causalmesh.verifier import (
    AnchorStatus,
    FailureKind,
    VerificationCertificate,
    VerificationResult,
    load_chain,
    parse_record,
    verify_chain,
    write_certificate,
)
from causalmesh.verifier.result import VerificationFailure

pytestmark = pytest.mark.unit

SEED = b"causalmesh-verifier-unit-seed-01"


@pytest.fixture
def keypair() -> KeyPair:
    return KeyPair.derive(SEED, "agent_a")


@pytest.fixture
def ring(keypair: KeyPair) -> PublicKeyRing:
    return PublicKeyRing.from_keypairs({"agent_a": keypair})


def make_event(sequence: int = 0) -> Event:
    return Event(
        event_id=f"evt_{sequence:04d}",
        identity=EventIdentity(
            experiment_id="exp_unit",
            task_id="task_unit",
            run_id="run_001",
            agent_id="agent_a",
            arm="C2",
        ),
        event_type=EventType.WRITE,
        sequence=sequence,
        timestamp_us=1_700_000_000_000_000 + sequence,
        paths=("src/schema.py",),
    )


def make_records(keypair: KeyPair, count: int = 3) -> list[dict[str, Any]]:
    records, previous = [], GENESIS_HASH
    for sequence in range(count):
        linked = link_event(make_event(sequence), previous, keypair)
        records.append(linked.to_dict())
        previous = linked.chain_hash
    return records


class TestParsing:
    def test_round_trips_a_persisted_record(self, keypair: KeyPair) -> None:
        original = link_event(make_event(), GENESIS_HASH, keypair)
        restored = parse_record(original.to_dict())
        assert restored.chain_hash == original.chain_hash
        assert restored.event.canonical_bytes() == original.event.canonical_bytes()
        assert restored.verify_hash() and restored.verify_signature()

    def test_survives_a_json_round_trip(self, keypair: KeyPair) -> None:
        # The record must reconstruct from text on disk, not just from a dict
        # that never left memory.
        original = link_event(make_event(), GENESIS_HASH, keypair)
        restored = parse_record(json.loads(json.dumps(original.to_dict())))
        assert restored.chain_hash == original.chain_hash
        assert restored.verify_signature()

    @pytest.mark.parametrize(
        "field", ["actor_public_key", "chain_hash", "event", "previous_hash", "signature"]
    )
    def test_missing_required_field_is_rejected(self, keypair: KeyPair, field: str) -> None:
        record = link_event(make_event(), GENESIS_HASH, keypair).to_dict()
        del record[field]
        with pytest.raises(ValueError, match="missing required fields"):
            parse_record(record)

    def test_non_object_record_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_record("not a record")  # type: ignore[arg-type]

    def test_missing_identity_is_rejected(self, keypair: KeyPair) -> None:
        record = link_event(make_event(), GENESIS_HASH, keypair).to_dict()
        del record["event"]["identity"]
        with pytest.raises(ValueError, match="identity"):
            parse_record(record)

    def test_unknown_event_type_is_rejected(self, keypair: KeyPair) -> None:
        record = link_event(make_event(), GENESIS_HASH, keypair).to_dict()
        record["event"]["event_type"] = "NOT_A_REAL_TYPE"
        with pytest.raises(ValueError):
            parse_record(record)

    def test_non_string_signature_is_rejected(self, keypair: KeyPair) -> None:
        record = link_event(make_event(), GENESIS_HASH, keypair).to_dict()
        record["signature"] = 12345
        with pytest.raises(ValueError, match="signature"):
            parse_record(record)


class TestLoading:
    def test_reads_a_jsonl_chain(self, tmp_path: Path, keypair: KeyPair) -> None:
        path = tmp_path / "chain.jsonl"
        records = make_records(keypair)
        path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
        )
        assert len(load_chain(path)) == 3

    def test_blank_lines_are_skipped(self, tmp_path: Path, keypair: KeyPair) -> None:
        path = tmp_path / "chain.jsonl"
        records = make_records(keypair, count=2)
        path.write_text(
            json.dumps(records[0]) + "\n\n" + json.dumps(records[1]) + "\n\n", encoding="utf-8"
        )
        assert len(load_chain(path)) == 2

    def test_an_unparseable_line_keeps_later_indices_correct(
        self, tmp_path: Path, keypair: KeyPair
    ) -> None:
        # If a corrupt line shifted the indices, every failure after it would
        # be reported at the wrong place.
        path = tmp_path / "chain.jsonl"
        records = make_records(keypair, count=2)
        path.write_text(
            json.dumps(records[0]) + "\n{{{ not json\n" + json.dumps(records[1]) + "\n",
            encoding="utf-8",
        )
        loaded = load_chain(path)
        assert len(loaded) == 3
        assert "__unparseable__" in loaded[1]


class TestVerification:
    def test_a_valid_chain_verifies(self, keypair: KeyPair, ring: PublicKeyRing) -> None:
        result = verify_chain(make_records(keypair), ring)
        assert result.valid
        assert result.events == 3

    def test_reports_schema_versions_and_actors(
        self, keypair: KeyPair, ring: PublicKeyRing
    ) -> None:
        result = verify_chain(make_records(keypair), ring)
        assert result.schema_versions == (1,)
        assert result.actors == ("agent_a",)

    def test_an_empty_chain_has_no_head(self, ring: PublicKeyRing) -> None:
        result = verify_chain([], ring)
        assert result.events == 0
        assert result.head_hash is None
        assert result.valid

    def test_a_wrong_genesis_is_a_chain_break(
        self, keypair: KeyPair, ring: PublicKeyRing
    ) -> None:
        # Guards the domain separation: a chain built for another protocol
        # must not validate here.
        result = verify_chain(make_records(keypair), ring, genesis="ab" * 32)
        assert not result.valid
        assert result.chain_failures >= 1

    def test_an_empty_key_ring_makes_every_actor_unknown(self, keypair: KeyPair) -> None:
        result = verify_chain(make_records(keypair), PublicKeyRing(keys={}))
        assert not result.valid
        assert result.count(FailureKind.UNKNOWN_ACTOR) == 3

    def test_one_corrupt_link_does_not_cascade(
        self, keypair: KeyPair, ring: PublicKeyRing
    ) -> None:
        """A single mutation must be reported once, not at every later index.

        The verifier advances on the *recorded* digest precisely so that a
        localized tamper stays localized in the report — otherwise a
        one-event edit would look like whole-log corruption and the actual
        point of damage would be lost.
        """
        records = make_records(keypair, count=5)
        records[2]["event"]["paths"] = ["src/tampered.py"]

        result = verify_chain(records, ring)
        breaks = [f for f in result.failures if f.kind == FailureKind.CHAIN_BREAK]
        assert len(breaks) == 1
        assert breaks[0].index == 2


class TestResultReporting:
    def test_counts_are_broken_out_by_kind(self) -> None:
        result = VerificationResult(
            events=3,
            failures=(
                VerificationFailure(FailureKind.CHAIN_BREAK, 1, "x"),
                VerificationFailure(FailureKind.CHAIN_BREAK, 2, "y"),
                VerificationFailure(FailureKind.SIGNATURE_INVALID, 2, "z"),
            ),
        )
        assert result.chain_failures == 2
        assert result.signature_failures == 1
        assert result.ordering_failures == 0
        assert not result.valid

    def test_to_dict_matches_the_documented_shape(
        self, keypair: KeyPair, ring: PublicKeyRing
    ) -> None:
        # §26 shows the expected keys; a report generator depends on them.
        data = verify_chain(make_records(keypair), ring).to_dict()
        assert {
            "valid",
            "events",
            "chain_failures",
            "signature_failures",
            "ordering_failures",
            "anchor_status",
        } <= set(data)

    def test_summary_states_the_verdict(self, keypair: KeyPair, ring: PublicKeyRing) -> None:
        assert verify_chain(make_records(keypair), ring).summary().startswith("VALID")
        broken = make_records(keypair)
        broken[1]["event"]["paths"] = ["x.py"]
        assert verify_chain(broken, ring).summary().startswith("INVALID")


class TestCertificate:
    def test_records_the_verification_and_its_context(
        self, tmp_path: Path, keypair: KeyPair, ring: PublicKeyRing
    ) -> None:
        result = verify_chain(make_records(keypair), ring)
        certificate = VerificationCertificate.create(
            result,
            run_id="run_001",
            chain_path=tmp_path / "chain.jsonl",
            software_version="0.1.0",
            anchors_supplied=0,
            inputs={"key_ring": "keyring.json"},
        )
        data = certificate.to_dict()
        assert data["kind"] == "verification"
        assert data["run_id"] == "run_001"
        assert data["software_version"] == "0.1.0"
        assert data["verification"]["valid"] is True
        # Context is what makes the verdict interpretable later.
        assert data["environment"]["python"]
        assert data["verification"]["key_ring_fingerprint"] == ring.fingerprint()

    def test_written_certificate_is_valid_json(
        self, tmp_path: Path, keypair: KeyPair, ring: PublicKeyRing
    ) -> None:
        certificate = VerificationCertificate.create(
            verify_chain(make_records(keypair), ring),
            run_id="run_001",
            chain_path="chain.jsonl",
            software_version="0.1.0",
        )
        path = write_certificate(certificate, tmp_path / "certs" / "verification.json")
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))["verification"]["events"] == 3

    def test_a_failed_verification_still_produces_a_certificate(
        self, tmp_path: Path, keypair: KeyPair, ring: PublicKeyRing
    ) -> None:
        # §81: a failure is evidence, not garbage. The certificate must record
        # it rather than being withheld.
        records = make_records(keypair)
        records[1]["event"]["paths"] = ["src/tampered.py"]
        certificate = VerificationCertificate.create(
            verify_chain(records, ring),
            run_id="run_001",
            chain_path="chain.jsonl",
            software_version="0.1.0",
        )
        path = write_certificate(certificate, tmp_path / "verification.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["verification"]["valid"] is False
        assert data["verification"]["failures"][0]["kind"] == "chain_break"


class TestAnchorAccounting:
    def test_no_anchor_reports_full_exposure(
        self, keypair: KeyPair, ring: PublicKeyRing
    ) -> None:
        result = verify_chain(make_records(keypair, count=4), ring)
        assert result.anchor_status == AnchorStatus.NOT_ANCHORED
        assert result.unanchored_suffix == 4

    def test_anchoring_the_head_reports_zero_exposure(
        self, keypair: KeyPair, ring: PublicKeyRing
    ) -> None:
        records = make_records(keypair, count=4)
        result = verify_chain(records, ring, anchors={3: records[3]["chain_hash"]})
        assert result.anchor_status == AnchorStatus.VERIFIED
        assert result.unanchored_suffix == 0

    def test_a_mid_chain_anchor_reports_the_remaining_exposure(
        self, keypair: KeyPair, ring: PublicKeyRing
    ) -> None:
        records = make_records(keypair, count=4)
        result = verify_chain(records, ring, anchors={1: records[1]["chain_hash"]})
        assert result.anchor_status == AnchorStatus.VERIFIED
        assert result.unanchored_suffix == 2
