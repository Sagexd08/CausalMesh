"""Event protocol: canonicalization, schema and typed event vocabulary.

This package defines the authoritative byte representation of an event. The
relay, the hash chain, every signature and the offline verifier all depend on
it, so it deliberately depends on nothing inside CausalMesh itself.
"""

from __future__ import annotations

from .canonical import (
    MAX_NESTING_DEPTH,
    CanonicalizationError,
    canonical_json,
    canonicalize,
    normalize_text,
)
from .schema import (
    SCHEMA_VERSION,
    Event,
    EventIdentity,
    EventType,
    EventValidationError,
    micros_to_rfc3339,
    utc_now_micros,
)

__all__ = [
    "MAX_NESTING_DEPTH",
    "SCHEMA_VERSION",
    "CanonicalizationError",
    "Event",
    "EventIdentity",
    "EventType",
    "EventValidationError",
    "canonical_json",
    "canonicalize",
    "micros_to_rfc3339",
    "normalize_text",
    "utc_now_micros",
]
