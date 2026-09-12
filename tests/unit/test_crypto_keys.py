"""Unit tests for Ed25519 identity (spec §24, §40).

Determinism is the load-bearing property here: if key derivation is not
reproducible, no run can be reproduced, and §84's reproducibility requirement
becomes unsatisfiable.
"""

from __future__ import annotations

import pytest

from causalmesh.crypto.keys import (
    KeyPair,
    PublicKeyRing,
    SignatureError,
    derive_signing_key,
    verify_signature,
)

pytestmark = pytest.mark.unit

SEED = b"causalmesh-test-master-seed-0001"
OTHER_SEED = b"causalmesh-test-master-seed-0002"


class TestDerivation:
    def test_same_seed_and_actor_yield_identical_keys(self) -> None:
        first = KeyPair.derive(SEED, "agent_a")
        second = KeyPair.derive(SEED, "agent_a")
        assert first.public_key_hex == second.public_key_hex

    def test_derivation_is_stable_across_many_calls(self) -> None:
        keys = {KeyPair.derive(SEED, "agent_a").public_key_hex for _ in range(20)}
        assert len(keys) == 1

    def test_different_actors_get_different_keys(self) -> None:
        a = KeyPair.derive(SEED, "agent_a")
        b = KeyPair.derive(SEED, "agent_b")
        assert a.public_key_hex != b.public_key_hex

    def test_different_seeds_get_different_keys(self) -> None:
        a = KeyPair.derive(SEED, "agent_a")
        b = KeyPair.derive(OTHER_SEED, "agent_a")
        assert a.public_key_hex != b.public_key_hex

    def test_public_key_is_32_bytes_of_hex(self) -> None:
        assert len(bytes.fromhex(KeyPair.derive(SEED, "agent_a").public_key_hex)) == 32

    def test_short_seed_is_rejected(self) -> None:
        # A short seed would silently weaken every derived key.
        with pytest.raises(SignatureError, match="at least 16 bytes"):
            derive_signing_key(b"tooshort", "agent_a")

    def test_non_bytes_seed_is_rejected(self) -> None:
        with pytest.raises(SignatureError):
            derive_signing_key("a-string-seed-long-enough", "agent_a")  # type: ignore[arg-type]

    def test_empty_actor_id_is_rejected(self) -> None:
        with pytest.raises(SignatureError, match="non-empty"):
            derive_signing_key(SEED, "")

    def test_generate_produces_distinct_keys(self) -> None:
        # The random path exists for non-reproducible deployments; confirm it
        # really is random rather than silently falling back to derivation.
        assert KeyPair.generate("agent_a").public_key_hex != KeyPair.generate("agent_a").public_key_hex


class TestSigning:
    def test_signature_verifies(self) -> None:
        kp = KeyPair.derive(SEED, "agent_a")
        message = b"an event digest"
        assert verify_signature(kp.public_key_hex, kp.sign(message), message)

    def test_signature_fails_for_modified_message(self) -> None:
        kp = KeyPair.derive(SEED, "agent_a")
        signature = kp.sign(b"original message")
        assert not verify_signature(kp.public_key_hex, signature, b"modified message")

    def test_signature_fails_for_wrong_public_key(self) -> None:
        signer = KeyPair.derive(SEED, "agent_a")
        other = KeyPair.derive(SEED, "agent_b")
        message = b"an event digest"
        assert not verify_signature(other.public_key_hex, signer.sign(message), message)

    def test_ed25519_signatures_are_deterministic(self) -> None:
        # Ed25519 is deterministic by construction; relying on it means a
        # reproduced run yields byte-identical signatures, not merely valid ones.
        kp = KeyPair.derive(SEED, "agent_a")
        assert kp.sign(b"message") == kp.sign(b"message")

    @pytest.mark.parametrize(
        "bad_signature",
        ["", "zz", "not-hex-at-all", "ab" * 63, "ab" * 65],
        ids=["empty", "too-short", "not-hex", "63-bytes", "65-bytes"],
    )
    def test_malformed_signature_is_a_failure_not_a_crash(self, bad_signature: str) -> None:
        # A tampered log is entitled to contain garbage; the verifier must
        # count it as a failure and keep going rather than abort the run.
        kp = KeyPair.derive(SEED, "agent_a")
        assert verify_signature(kp.public_key_hex, bad_signature, b"message") is False

    @pytest.mark.parametrize(
        "bad_key", ["", "zz", "ab" * 31, "ab" * 33], ids=["empty", "not-hex", "31-bytes", "33-bytes"]
    )
    def test_malformed_public_key_is_a_failure_not_a_crash(self, bad_key: str) -> None:
        kp = KeyPair.derive(SEED, "agent_a")
        assert verify_signature(bad_key, kp.sign(b"message"), b"message") is False

    def test_repr_does_not_leak_private_key(self) -> None:
        # A traceback or debug log must never expose signing material.
        kp = KeyPair.derive(SEED, "agent_a")
        text = repr(kp)
        assert "agent_a" in text
        assert kp._private_key.private_bytes_raw().hex() not in text


class TestPublicKeyRing:
    def test_round_trips_through_a_dict(self) -> None:
        ring = PublicKeyRing.from_keypairs(
            {"agent_a": KeyPair.derive(SEED, "agent_a"), "agent_b": KeyPair.derive(SEED, "agent_b")}
        )
        assert PublicKeyRing.from_dict(ring.to_dict()).keys == ring.keys

    def test_lookup_returns_none_for_unknown_actor(self) -> None:
        ring = PublicKeyRing.from_keypairs({"agent_a": KeyPair.derive(SEED, "agent_a")})
        assert ring.public_key_for("agent_zzz") is None

    def test_fingerprint_is_insertion_order_independent(self) -> None:
        a, b = KeyPair.derive(SEED, "agent_a"), KeyPair.derive(SEED, "agent_b")
        forward = PublicKeyRing.from_keypairs({"agent_a": a, "agent_b": b})
        reverse = PublicKeyRing.from_keypairs({"agent_b": b, "agent_a": a})
        assert forward.fingerprint() == reverse.fingerprint()

    def test_fingerprint_changes_when_a_key_changes(self) -> None:
        original = PublicKeyRing.from_keypairs({"agent_a": KeyPair.derive(SEED, "agent_a")})
        swapped = PublicKeyRing.from_keypairs({"agent_a": KeyPair.derive(OTHER_SEED, "agent_a")})
        assert original.fingerprint() != swapped.fingerprint()

    def test_fingerprint_changes_when_an_actor_is_added(self) -> None:
        one = PublicKeyRing.from_keypairs({"agent_a": KeyPair.derive(SEED, "agent_a")})
        two = PublicKeyRing.from_keypairs(
            {"agent_a": KeyPair.derive(SEED, "agent_a"), "agent_b": KeyPair.derive(SEED, "agent_b")}
        )
        assert one.fingerprint() != two.fingerprint()
