"""Ed25519 identity: deterministic derivation, signing and verification.

Spec §24 (signatures) and §40 (no hidden randomness).

Every actor that can append to the log — each agent, and the relay itself —
holds an Ed25519 keypair. Signatures are what make the log *attributable*:
without them a chain proves only that nobody edited history, not who wrote it.

Keys are derived deterministically from a master seed and an actor id rather
than generated randomly. That is a reproducibility requirement, not a
convenience: §84 asks that the same seed, task and configuration produce an
equivalent chain, which is impossible if every run invents fresh keys.

The tradeoff is stated plainly in `docs/security.md`: anyone holding the
master seed can forge any actor's signature. That is acceptable here because
the adversary model (§87) covers tampering with *recorded evidence* after the
fact, not a compromised operator. A deployment with genuinely mutually
distrusting participants would generate keys independently instead, which the
`KeyPair.generate` path supports.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

__all__ = [
    "DERIVATION_INFO",
    "KeyPair",
    "PublicKeyRing",
    "SignatureError",
    "derive_signing_key",
]


# Domain-separation string mixed into every derivation. It pins the derived
# keys to this protocol version, so a seed reused by some other component of
# the system can never yield the same signing key.
DERIVATION_INFO = b"causalmesh/ed25519/v1"

# Ed25519 private keys are exactly 32 bytes of seed material.
_SEED_LENGTH = 32


class SignatureError(ValueError):
    """Raised when a signature is malformed, unverifiable or unattributable."""


def derive_signing_key(master_seed: bytes, actor_id: str) -> Ed25519PrivateKey:
    """Derive an actor's Ed25519 private key from the master seed.

    HKDF-SHA256 is used with the actor id as salt and a fixed protocol info
    string. Two properties matter:

    - *Determinism*: the same (seed, actor) pair always yields the same key,
      so a run can be reproduced exactly.
    - *Independence*: knowing one actor's derived key reveals nothing about
      another's, because HKDF's output is indistinguishable from random
      without the seed. This keeps per-actor attribution meaningful even
      though the keys share an origin.
    """
    if not isinstance(master_seed, bytes) or len(master_seed) < 16:
        raise SignatureError(
            f"master_seed must be at least 16 bytes of entropy, got "
            f"{len(master_seed) if isinstance(master_seed, bytes) else type(master_seed).__name__}"
        )
    if not actor_id:
        raise SignatureError("actor_id must be a non-empty string")

    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=_SEED_LENGTH,
        salt=actor_id.encode("utf-8"),
        info=DERIVATION_INFO,
    ).derive(master_seed)
    return Ed25519PrivateKey.from_private_bytes(derived)


@dataclass(frozen=True, slots=True)
class KeyPair:
    """An actor's signing identity.

    Holds the private key, so it lives only inside the relay process. What
    leaves the process — and what the offline verifier consumes — is the
    public half, via `public_key_hex`.
    """

    actor_id: str
    _private_key: Ed25519PrivateKey

    @classmethod
    def derive(cls, master_seed: bytes, actor_id: str) -> KeyPair:
        """Deterministically derive an actor's keypair (the reproducible path)."""
        return cls(actor_id=actor_id, _private_key=derive_signing_key(master_seed, actor_id))

    @classmethod
    def generate(cls, actor_id: str) -> KeyPair:
        """Generate a fresh random keypair.

        Provided for deployments where participants must not share a seed
        origin. It is deliberately *not* used by the experiment harness,
        because a randomly keyed run cannot be reproduced.
        """
        return cls(actor_id=actor_id, _private_key=Ed25519PrivateKey.generate())

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._private_key.public_key()

    @property
    def public_key_hex(self) -> str:
        """The public key as lowercase hex — the form stored on every event."""
        return self.public_key.public_bytes_raw().hex()

    def sign(self, message: bytes) -> str:
        """Sign a message, returning a lowercase hex signature."""
        return self._private_key.sign(message).hex()

    def __repr__(self) -> str:
        # Never let a private key reach a log line or a traceback.
        return f"KeyPair(actor_id={self.actor_id!r}, public_key={self.public_key_hex[:16]}...)"


def verify_signature(public_key_hex: str, signature_hex: str, message: bytes) -> bool:
    """Check one signature against one public key.

    Returns a bool rather than raising for the invalid case: the verifier
    needs to *count* failures across a whole log, not abort on the first one.
    Malformed inputs are also a verification failure, not a crash — a tampered
    log is entitled to contain garbage.
    """
    try:
        key_bytes = bytes.fromhex(public_key_hex)
        signature = bytes.fromhex(signature_hex)
    except (ValueError, TypeError):
        return False

    if len(key_bytes) != 32 or len(signature) != 64:
        return False

    try:
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


@dataclass(frozen=True)
class PublicKeyRing:
    """The public keys an offline verifier needs, and nothing more (§26).

    This is the whole trust input to verification. It is deliberately a plain
    mapping of actor id to hex public key so it can be exported as JSON,
    carried to another machine and used with the relay permanently offline.
    """

    keys: dict[str, str]

    @classmethod
    def from_keypairs(cls, keypairs: dict[str, KeyPair]) -> PublicKeyRing:
        return cls(keys={actor: kp.public_key_hex for actor, kp in keypairs.items()})

    def public_key_for(self, actor_id: str) -> str | None:
        return self.keys.get(actor_id)

    def fingerprint(self) -> str:
        """A stable digest of the whole ring, for recording in manifests.

        Lets a manifest state exactly which set of keys a verification result
        was produced against, so a later re-verification with a different ring
        is detectable rather than silently different.
        """
        material = "".join(f"{actor}:{self.keys[actor]};" for actor in sorted(self.keys))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, str]:
        return dict(self.keys)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> PublicKeyRing:
        return cls(keys=dict(data))
