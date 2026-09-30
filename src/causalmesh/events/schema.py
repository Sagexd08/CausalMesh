"""Versioned research event schema.

Spec §16 (typed event classes) and §29 (explicit, versioned schema).

An event records *what an agent did*, not what it said. Every event is
immutable once constructed, carries full experimental identity so it can never
be attributed by filename (§10), and serializes through
`causalmesh.events.canonical` so that its bytes — and therefore its hash and
signature — are reproducible.

Timestamps are integer microseconds since the Unix epoch, UTC. They are
deliberately not floats: float seconds would be rejected by canonicalization,
and integer microseconds keep ordering exact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .canonical import canonicalize, normalize_text

__all__ = [
    "SCHEMA_VERSION",
    "Event",
    "EventIdentity",
    "EventType",
    "EventValidationError",
    "micros_to_rfc3339",
    "utc_now_micros",
]


SCHEMA_VERSION = 1


class EventValidationError(ValueError):
    """Raised when an event is structurally invalid."""


class EventType(StrEnum):
    """The typed event vocabulary (spec §16).

    A StrEnum so the canonical form is the member's string value, giving
    stable bytes without any custom encoding.
    """

    INTENT = "INTENT"
    READ = "READ"
    WRITE = "WRITE"
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    RENAME = "RENAME"
    TEST = "TEST"
    CLAIM = "CLAIM"
    RELEASE = "RELEASE"
    COMMIT = "COMMIT"
    FAILURE = "FAILURE"
    POLICY_VERDICT = "POLICY_VERDICT"
    ACCEPTANCE_DECIDED = "ACCEPTANCE_DECIDED"
    CHECKPOINT_DECIDED = "CHECKPOINT_DECIDED"
    INTEGRATION_TEST_RESULT = "INTEGRATION_TEST_RESULT"


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def utc_now_micros() -> int:
    """Current UTC time as integer microseconds since the epoch."""
    return int(datetime.now(UTC).timestamp() * 1_000_000)


def micros_to_rfc3339(micros: int) -> str:
    """Render integer microseconds as an RFC 3339 UTC timestamp.

    Used for human-readable output and reports only. The canonical form keeps
    the integer, so display formatting can never perturb a digest.
    """
    return (
        datetime.fromtimestamp(micros / 1_000_000, UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _require_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.match(value):
        raise EventValidationError(
            f"{field_name} must match {_IDENTIFIER_PATTERN.pattern!r}, got {value!r}"
        )
    return value


@dataclass(frozen=True, slots=True)
class EventIdentity:
    """Immutable experimental identity carried by every event (spec §10).

    Identity is always explicit. Nothing here may be inferred from a filename
    or a directory layout, because a path can be moved, copied or renamed
    while the evidence it contains must stay attributable.
    """

    experiment_id: str
    task_id: str
    run_id: str
    agent_id: str
    arm: str

    def __post_init__(self) -> None:
        for name in ("experiment_id", "task_id", "run_id", "agent_id", "arm"):
            _require_identifier(getattr(self, name), name)

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "arm": self.arm,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
        }


@dataclass(frozen=True, slots=True)
class Event:
    """A single immutable research event.

    `sequence` is assigned by the relay, which owns ordering; agents never
    choose their own sequence numbers. `parent_id` records the causal
    predecessor an agent was reacting to, which is what makes it possible to
    reconstruct what an agent knew before it acted (§57).
    """

    event_id: str
    identity: EventIdentity
    event_type: EventType
    sequence: int
    timestamp_us: int
    paths: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    parent_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.event_id, "event_id")

        if not isinstance(self.event_type, EventType):
            raise EventValidationError(
                f"event_type must be an EventType, got {type(self.event_type).__name__}"
            )

        for name in ("sequence", "timestamp_us"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise EventValidationError(f"{name} must be an int, got {value!r}")
        if self.sequence < 0:
            raise EventValidationError(f"sequence must be non-negative, got {self.sequence}")
        if self.timestamp_us < 0:
            raise EventValidationError(
                f"timestamp_us must be non-negative, got {self.timestamp_us}"
            )

        for name in ("paths", "references"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                raise EventValidationError(
                    f"{name} must be a tuple (immutable), got {type(value).__name__}"
                )
            if not all(isinstance(item, str) for item in value):
                raise EventValidationError(f"{name} must contain only strings")

        if self.parent_id is not None:
            _require_identifier(self.parent_id, "parent_id")

        if not isinstance(self.payload, dict):
            raise EventValidationError(f"payload must be a dict, got {type(self.payload).__name__}")

    def to_canonical_dict(self) -> dict[str, Any]:
        """Return the exact structure that gets hashed and signed.

        Paths are NFC-normalized here so that the same file referenced with
        different Unicode spellings yields identical bytes. Paths are sorted
        because a set of touched paths has no inherent order, while
        `references` keeps its order, which is meaningful.
        """
        return {
            "event_id": self.event_id,
            "event_type": str(self.event_type),
            "identity": self.identity.to_canonical_dict(),
            "parent_id": self.parent_id,
            "paths": sorted(normalize_text(p) for p in self.paths),
            "payload": self.payload,
            "references": [normalize_text(r) for r in self.references],
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "timestamp_us": self.timestamp_us,
        }

    def canonical_bytes(self) -> bytes:
        """The canonical byte representation fed to the hash chain."""
        return canonicalize(self.to_canonical_dict())
