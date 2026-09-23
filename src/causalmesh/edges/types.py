"""The causal-edge vocabulary (`docs/backlog.md`, "Causal edges over the chain").

The chain gives total order and hash linkage: event N's hash depends on
event N-1's, which proves *sequence*. It does not record *relationships* —
"which decision caused this write" requires reading the chain in order and
matching timestamps by eye. A `CausalEdge` names that relationship
explicitly, as a typed fact referencing two event ids.

This is additive to the chain. It does not change what is signed or how
verification works: an edge is never fed to `crypto.chain.compute_chain_hash`
and carries no signature of its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = ["CausalEdge", "EdgeValidationError", "RelationshipType"]


class EdgeValidationError(ValueError):
    """Raised when a `CausalEdge` is structurally invalid."""


class RelationshipType(StrEnum):
    """The typed relationship vocabulary named in the backlog entry.

    A StrEnum so the canonical form on disk is the member's string value,
    matching the convention `events.schema.EventType` already sets.
    """

    CAUSED = "CAUSED"
    REQUIRED = "REQUIRED"
    RECOVERED = "RECOVERED"
    SUPERSEDED = "SUPERSEDED"


# Same conservative pattern events.schema uses for event_id: identifiers
# appear in canonical bytes and database keys elsewhere in this codebase, so
# an edge endpoint is held to the same shape even though edges themselves are
# never hashed or signed.
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.match(value):
        raise EdgeValidationError(
            f"{field_name} must match {_IDENTIFIER_PATTERN.pattern!r}, got {value!r}"
        )


@dataclass(frozen=True, slots=True)
class CausalEdge:
    """A typed relationship from one event to another.

    `from_event_id` is the effect, `to_event_id` is the cause: "this write
    was CAUSED by that decision" reads as
    `CausalEdge(from_event_id=write_id, to_event_id=decision_id, relationship=CAUSED)`,
    matching how `Event.parent_id` already points from a later event back to
    its causal predecessor.

    Both ids are opaque strings, the same `event_id` values events already
    carry. Nothing here requires the referenced events to exist in any
    particular chain — the store is a sibling artifact, decoupled from any
    one `Relay` instance, so an edge can be recorded before, after, or
    without ever verifying the events it names.
    """

    from_event_id: str
    to_event_id: str
    relationship: RelationshipType
    note: str = ""

    def __post_init__(self) -> None:
        _require_identifier(self.from_event_id, "from_event_id")
        _require_identifier(self.to_event_id, "to_event_id")
        if self.from_event_id == self.to_event_id:
            raise EdgeValidationError(
                f"an edge cannot relate event {self.from_event_id!r} to itself"
            )
        if not isinstance(self.relationship, RelationshipType):
            raise EdgeValidationError(
                f"relationship must be a RelationshipType, got {type(self.relationship).__name__}"
            )
        if not isinstance(self.note, str):
            raise EdgeValidationError(f"note must be a string, got {type(self.note).__name__}")

    def to_dict(self) -> dict[str, str]:
        return {
            "from_event_id": self.from_event_id,
            "to_event_id": self.to_event_id,
            "relationship": str(self.relationship),
            "note": self.note,
        }

    @staticmethod
    def from_dict(record: dict[str, object]) -> CausalEdge:
        """Rebuild a `CausalEdge` from its persisted form.

        Raises `EdgeValidationError` on anything structurally unusable,
        matching `verifier.offline.parse_record`'s discipline of never
        trusting a stored record without reconstructing it through the
        validating constructor.
        """
        try:
            from_event_id = record["from_event_id"]
            to_event_id = record["to_event_id"]
            relationship = record["relationship"]
        except KeyError as exc:
            raise EdgeValidationError(f"edge record is missing field {exc}") from exc

        if not isinstance(from_event_id, str) or not isinstance(to_event_id, str):
            raise EdgeValidationError("from_event_id and to_event_id must be strings")
        if not isinstance(relationship, str):
            raise EdgeValidationError("relationship must be a string")

        try:
            relationship_value = RelationshipType(relationship)
        except ValueError as exc:
            raise EdgeValidationError(
                f"relationship {relationship!r} is not one of {[str(r) for r in RelationshipType]}"
            ) from exc

        note = record.get("note", "")
        if not isinstance(note, str):
            raise EdgeValidationError(f"note must be a string, got {type(note).__name__}")

        return CausalEdge(
            from_event_id=from_event_id,
            to_event_id=to_event_id,
            relationship=relationship_value,
            note=note,
        )
