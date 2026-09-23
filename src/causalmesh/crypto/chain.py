"""The signed hash chain (spec §24).

Each event is bound to the entire history that preceded it:

    h_0 = SHA256(GENESIS_LABEL || canonical(event_0))
    h_i = SHA256(h_(i-1) || canonical(event_i))

and `h_i` is then signed by the appending actor. Two distinct guarantees come
out of this, and it is worth keeping them apart because §87 forbids
overclaiming:

- The **chain** makes history tamper-*evident*. Changing, inserting, deleting
  or reordering any event changes every digest after it, so the chain stops
  linking. It does not prevent tampering; it makes tampering visible.
- The **signature** makes each link *attributable*. Recomputing a digest is
  free, so without signatures an attacker could rewrite history and simply
  recompute the chain. Signing the digest means forging a link also requires
  the actor's private key.

The known limitation is suffix truncation: dropping events from the end
leaves a shorter but internally consistent chain. Nothing inside the chain can
detect that, which is exactly why anchors (§28) exist. The adversarial suite
asserts this limitation explicitly rather than papering over it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..events.canonical import canonicalize
from ..events.schema import Event
from .keys import KeyPair, verify_signature

__all__ = [
    "GENESIS_HASH",
    "ChainError",
    "ChainedEvent",
    "compute_chain_hash",
    "link_event",
]


GENESIS_HASH = hashlib.sha256(b"causalmesh/chain/genesis/v1").hexdigest()


class ChainError(ValueError):
    """Raised when a chain link cannot be constructed or interpreted."""


def compute_chain_hash(previous_hash: str, event: Event) -> str:
    """Compute `h_i = SHA256(h_(i-1) || canonical(event_i))`.

    The previous hash is mixed in as raw bytes decoded from its hex form,
    not as hex text. Both are self-consistent, but the raw form is what the
    specification states, and pinning it here stops an independent verifier
    implementation from disagreeing on a detail that would invalidate the
    whole log.
    """
    try:
        previous_bytes = bytes.fromhex(previous_hash)
    except (ValueError, TypeError) as exc:
        raise ChainError(f"previous_hash is not valid hex: {previous_hash!r}") from exc

    if len(previous_bytes) != 32:
        raise ChainError(
            f"previous_hash must be a 32-byte SHA-256 digest, got {len(previous_bytes)} bytes"
        )

    digest = hashlib.sha256()
    digest.update(previous_bytes)
    digest.update(event.canonical_bytes())
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ChainedEvent:
    """An event together with its position in the signed chain.

    This is the unit that gets persisted to `data/raw/` and the unit the
    offline verifier consumes. It carries the actor's public key inline so
    verification needs only the log plus a key ring to check attribution —
    the key on the event says who *claims* to have signed it, and the ring
    says whether that actor's real key matches.
    """

    event: Event
    previous_hash: str
    chain_hash: str
    signature: str
    actor_public_key: str

    def verify_hash(self) -> bool:
        """Recompute this link's digest and compare (tamper detection)."""
        try:
            return compute_chain_hash(self.previous_hash, self.event) == self.chain_hash
        except ChainError:
            return False

    def verify_signature(self) -> bool:
        """Check the signature over this link's chain digest.

        Note what is signed: the *chain hash*, not the bare event. Signing the
        digest means each signature covers the entire history up to that
        point, so an event cannot be lifted from one chain and replayed into
        another position with its signature intact.
        """
        try:
            message = bytes.fromhex(self.chain_hash)
        except (ValueError, TypeError):
            return False
        return verify_signature(self.actor_public_key, self.signature, message)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence to the raw log."""
        return {
            "actor_public_key": self.actor_public_key,
            "chain_hash": self.chain_hash,
            "event": self.event.to_canonical_dict(),
            "previous_hash": self.previous_hash,
            "signature": self.signature,
        }

    def canonical_record_bytes(self) -> bytes:
        """Canonical bytes of the whole record, used when anchoring (§28)."""
        return canonicalize(self.to_dict())


def link_event(event: Event, previous_hash: str, keypair: KeyPair) -> ChainedEvent:
    """Chain and sign one event, producing the record that gets persisted.

    The signing actor must match the event's `agent_id`. Enforcing it here
    rather than at the call site means the relay cannot accidentally sign a
    peer's event with its own key, which would produce a log that verifies
    cryptographically while attributing work to the wrong actor — the exact
    failure the wrong-actor test in the adversarial suite looks for.
    """
    if keypair.actor_id != event.identity.agent_id:
        raise ChainError(
            f"actor mismatch: keypair belongs to {keypair.actor_id!r} but the event is "
            f"attributed to {event.identity.agent_id!r}; signing it would misattribute the work"
        )

    chain_hash = compute_chain_hash(previous_hash, event)
    signature = keypair.sign(bytes.fromhex(chain_hash))
    return ChainedEvent(
        event=event,
        previous_hash=previous_hash,
        chain_hash=chain_hash,
        signature=signature,
        actor_public_key=keypair.public_key_hex,
    )
