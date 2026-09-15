"""Structured verification results (spec §26).

A verification result is evidence, so it is a data structure rather than a
boolean or a log line. It records what was checked, what failed and *where*,
so a failure can be traced to a specific link rather than reported as a bare
"invalid".

The shape mirrors the specification's example output and serializes directly
into `verification_certificate.json` (§59).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "AnchorStatus",
    "FailureKind",
    "VerificationFailure",
    "VerificationResult",
]


class FailureKind(StrEnum):
    """Why a link failed verification.

    These are the distinguishable causes. Keeping them apart matters: a broken
    hash means the content changed, while a broken signature with an intact
    hash means someone recomputed the chain without the private key. The two
    imply different things about the attacker.
    """

    CHAIN_BREAK = "chain_break"
    SIGNATURE_INVALID = "signature_invalid"
    ORDERING_INVALID = "ordering_invalid"
    UNKNOWN_ACTOR = "unknown_actor"
    KEY_MISMATCH = "key_mismatch"
    DUPLICATE_EVENT_ID = "duplicate_event_id"
    SCHEMA_UNSUPPORTED = "schema_unsupported"
    MALFORMED_RECORD = "malformed_record"
    ANCHOR_MISMATCH = "anchor_mismatch"
    ANCHOR_MISSING_EVENT = "anchor_missing_event"


class AnchorStatus(StrEnum):
    """Whether external anchors could confirm the chain head (§28)."""

    VERIFIED = "verified"
    MISMATCH = "mismatch"
    NOT_ANCHORED = "not_anchored"


@dataclass(frozen=True, slots=True)
class VerificationFailure:
    """One specific verification failure, located precisely."""

    kind: FailureKind
    index: int
    detail: str
    event_id: str | None = None
    sequence: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "event_id": self.event_id,
            "index": self.index,
            "kind": str(self.kind),
            "sequence": self.sequence,
        }


@dataclass(frozen=True)
class VerificationResult:
    """The outcome of verifying one chain.

    `valid` is true only when every check passed. Counts are reported
    separately so a partially damaged log can be characterised rather than
    merely rejected — which log was damaged, and how, is itself a finding.
    """

    events: int
    failures: tuple[VerificationFailure, ...] = ()
    anchor_status: AnchorStatus = AnchorStatus.NOT_ANCHORED
    unanchored_suffix: int = 0
    head_hash: str | None = None
    key_ring_fingerprint: str | None = None
    schema_versions: tuple[int, ...] = ()
    actors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def valid(self) -> bool:
        return not self.failures

    def count(self, kind: FailureKind) -> int:
        return sum(1 for failure in self.failures if failure.kind == kind)

    @property
    def chain_failures(self) -> int:
        return self.count(FailureKind.CHAIN_BREAK)

    @property
    def signature_failures(self) -> int:
        return self.count(FailureKind.SIGNATURE_INVALID)

    @property
    def ordering_failures(self) -> int:
        return self.count(FailureKind.ORDERING_INVALID)

    def to_dict(self) -> dict[str, Any]:
        """Serialize in the shape the specification's §26 example describes."""
        return {
            "actors": list(self.actors),
            "anchor_status": str(self.anchor_status),
            "chain_failures": self.chain_failures,
            "events": self.events,
            "failures": [failure.to_dict() for failure in self.failures],
            "head_hash": self.head_hash,
            "key_ring_fingerprint": self.key_ring_fingerprint,
            "ordering_failures": self.ordering_failures,
            "schema_versions": list(self.schema_versions),
            "signature_failures": self.signature_failures,
            "unanchored_suffix": self.unanchored_suffix,
            "valid": self.valid,
        }

    def summary(self) -> str:
        """A one-line human summary for CLI output."""
        if self.valid:
            return (
                f"VALID — {self.events} events, chain intact, "
                f"anchor={self.anchor_status}, unanchored_suffix={self.unanchored_suffix}"
            )
        kinds = ", ".join(
            f"{kind.value}={self.count(kind)}" for kind in FailureKind if self.count(kind)
        )
        return f"INVALID — {self.events} events, {len(self.failures)} failures ({kinds})"
