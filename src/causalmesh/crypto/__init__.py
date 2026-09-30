"""Cryptographic identity and the signed hash chain.

Spec §24. Depends only on `causalmesh.events` and the `cryptography` library,
so the offline verifier can import it without pulling in the relay (§26).
"""

from __future__ import annotations

from .chain import (
    GENESIS_HASH,
    ChainedEvent,
    ChainError,
    compute_chain_hash,
    link_event,
)
from .keyring import KeyRingError, load_key_ring
from .keys import (
    DERIVATION_INFO,
    KeyPair,
    PublicKeyRing,
    SignatureError,
    derive_signing_key,
    verify_signature,
)

__all__ = [
    "DERIVATION_INFO",
    "GENESIS_HASH",
    "ChainError",
    "ChainedEvent",
    "KeyPair",
    "KeyRingError",
    "PublicKeyRing",
    "SignatureError",
    "compute_chain_hash",
    "derive_signing_key",
    "link_event",
    "load_key_ring",
    "verify_signature",
]
