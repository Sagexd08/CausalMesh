"""The offline chain verifier (spec §26).

Takes a log, a public key ring and optional anchors — and nothing else. No
relay, no database, no network. That constraint is the whole point: evidence
that can only be checked by the system that produced it is not evidence, and
§82 requires verification to succeed on another machine from an export alone.

The verifier is deliberately *total*: it never raises on a malformed log. A
tampered log is entitled to contain garbage, and a verifier that crashes on
the first corrupt record cannot report how much of the log survived. Every
problem becomes a located `VerificationFailure` instead.

It re-derives everything it checks. Nothing recorded in the log is trusted:
digests are recomputed from canonical bytes, signatures are checked against
the key ring rather than against the public key the record carries, and
sequence ordering is validated independently of any claim the log makes about
itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..crypto.chain import GENESIS_HASH, ChainedEvent, compute_chain_hash
from ..crypto.keys import PublicKeyRing, verify_signature
from ..events.schema import SCHEMA_VERSION, Event, EventIdentity, EventType
from .result import AnchorStatus, FailureKind, VerificationFailure, VerificationResult

__all__ = [
    "SUPPORTED_SCHEMA_VERSIONS",
    "load_chain",
    "parse_record",
    "verify_chain",
]


# Schema versions this verifier can faithfully interpret. A log written by a
# newer protocol is refused rather than checked against rules that may no
# longer describe it (§29).
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})

_REQUIRED_RECORD_FIELDS = frozenset(
    {"actor_public_key", "chain_hash", "event", "previous_hash", "signature"}
)


def parse_record(record: dict[str, Any]) -> ChainedEvent:
    """Rebuild a `ChainedEvent` from its persisted form.

    Raises `ValueError` on anything structurally unusable; `verify_chain`
    catches that and records it as a `MALFORMED_RECORD` failure rather than
    letting it escape.
    """
    if not isinstance(record, dict):
        raise ValueError(f"record must be an object, got {type(record).__name__}")

    missing = _REQUIRED_RECORD_FIELDS - set(record)
    if missing:
        raise ValueError(f"record is missing required fields: {sorted(missing)}")

    payload = record["event"]
    if not isinstance(payload, dict):
        raise ValueError(f"event must be an object, got {type(payload).__name__}")

    identity_data = payload.get("identity")
    if not isinstance(identity_data, dict):
        raise ValueError("event.identity must be an object")

    try:
        identity = EventIdentity(
            experiment_id=identity_data["experiment_id"],
            task_id=identity_data["task_id"],
            run_id=identity_data["run_id"],
            agent_id=identity_data["agent_id"],
            arm=identity_data["arm"],
        )
        event = Event(
            event_id=payload["event_id"],
            identity=identity,
            event_type=EventType(payload["event_type"]),
            sequence=payload["sequence"],
            timestamp_us=payload["timestamp_us"],
            paths=tuple(payload.get("paths", ())),
            references=tuple(payload.get("references", ())),
            parent_id=payload.get("parent_id"),
            payload=payload.get("payload", {}),
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"event could not be reconstructed: {exc}") from exc

    for name in ("actor_public_key", "chain_hash", "previous_hash", "signature"):
        if not isinstance(record[name], str):
            raise ValueError(f"{name} must be a string")

    return ChainedEvent(
        event=event,
        previous_hash=record["previous_hash"],
        chain_hash=record["chain_hash"],
        signature=record["signature"],
        actor_public_key=record["actor_public_key"],
    )


def load_chain(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL chain file into raw records.

    Records are returned undecoded so that `verify_chain` can report a
    malformed line at its real index instead of failing the whole load.
    """
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError:
                # Preserved as an explicitly unparseable marker so the index
                # of every later record stays correct.
                records.append({"__unparseable__": stripped[:200]})
    return records


def _verify_anchors(
    chain: list[ChainedEvent],
    anchors: dict[int, str] | None,
) -> tuple[AnchorStatus, int, list[VerificationFailure]]:
    """Check external chain-head anchors and compute suffix exposure (§28).

    An anchor pins the chain head at some sequence to an externally recorded
    digest. It is what closes the suffix-truncation gap: events after the
    highest matching anchor are unprotected, and that count is reported rather
    than glossed over.
    """
    if not anchors:
        # No anchor means the entire log could have been truncated undetectably.
        return AnchorStatus.NOT_ANCHORED, len(chain), []

    by_sequence = {link.event.sequence: (index, link) for index, link in enumerate(chain)}
    failures: list[VerificationFailure] = []
    matched: list[int] = []

    for sequence in sorted(anchors):
        expected = anchors[sequence]
        found = by_sequence.get(sequence)
        if found is None:
            # The anchor attests to an event the log no longer contains —
            # exactly the truncation (or deletion) an anchor exists to catch.
            failures.append(
                VerificationFailure(
                    kind=FailureKind.ANCHOR_MISSING_EVENT,
                    index=-1,
                    sequence=sequence,
                    detail=(
                        f"anchor pins sequence {sequence} to {expected[:16]}... "
                        "but the log contains no such event"
                    ),
                )
            )
            continue

        index, link = found
        if link.chain_hash != expected:
            failures.append(
                VerificationFailure(
                    kind=FailureKind.ANCHOR_MISMATCH,
                    index=index,
                    sequence=sequence,
                    event_id=link.event.event_id,
                    detail=(
                        f"anchor expects {expected[:16]}... at sequence {sequence}, "
                        f"log has {link.chain_hash[:16]}..."
                    ),
                )
            )
            continue
        matched.append(sequence)

    if failures:
        return AnchorStatus.MISMATCH, len(chain), failures

    highest = max(matched)
    unanchored = sum(1 for link in chain if link.event.sequence > highest)
    return AnchorStatus.VERIFIED, unanchored, []


def verify_chain(
    records: list[dict[str, Any]],
    key_ring: PublicKeyRing,
    anchors: dict[int, str] | None = None,
    *,
    genesis: str = GENESIS_HASH,
) -> VerificationResult:
    """Verify a chain from records, keys and optional anchors.

    Checks applied to every link, in order:

    1. the record parses into a well-formed event;
    2. its schema version is one this verifier understands;
    3. its recomputed digest matches the recorded `chain_hash`;
    4. it links to its predecessor (the first must link to genesis);
    5. its sequence increases by exactly one from the previous link;
    6. its actor is known to the key ring, and the key the record carries
       matches the ring's key for that actor;
    7. its signature verifies over the chain digest;
    8. its event id has not been seen before in this log.

    Check 6 is what makes attribution meaningful. Verifying against the key
    embedded in the record would be circular — an attacker who re-signs an
    event with their own key would also replace that field, and the log would
    verify perfectly while crediting the wrong actor.
    """
    failures: list[VerificationFailure] = []
    chain: list[ChainedEvent] = []
    seen_event_ids: dict[str, int] = {}
    schema_versions: set[int] = set()
    actors: set[str] = set()

    previous_hash = genesis
    expected_sequence: int | None = None

    for index, record in enumerate(records):
        try:
            link = parse_record(record)
        except (ValueError, TypeError) as exc:
            failures.append(
                VerificationFailure(kind=FailureKind.MALFORMED_RECORD, index=index, detail=str(exc))
            )
            # The chain cannot continue through an unparseable record: every
            # later link would be reported as broken for the wrong reason.
            break

        chain.append(link)
        event = link.event
        schema_versions.add(event.schema_version)
        actors.add(event.identity.agent_id)

        if event.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            failures.append(
                VerificationFailure(
                    kind=FailureKind.SCHEMA_UNSUPPORTED,
                    index=index,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    detail=(
                        f"schema version {event.schema_version} is not supported "
                        f"(this verifier understands {sorted(SUPPORTED_SCHEMA_VERSIONS)})"
                    ),
                )
            )

        # 3 + 4: recompute the digest over the *expected* predecessor, so a
        # relinked record is caught even if its own fields are self-consistent.
        try:
            recomputed: str | None = compute_chain_hash(previous_hash, event)
        except ValueError as exc:
            recomputed = None
            failures.append(
                VerificationFailure(
                    kind=FailureKind.CHAIN_BREAK,
                    index=index,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    detail=f"digest could not be recomputed: {exc}",
                )
            )

        if recomputed is not None and recomputed != link.chain_hash:
            if link.previous_hash != previous_hash:
                detail = (
                    f"link points at {link.previous_hash[:16]}... but the preceding "
                    f"record hashes to {previous_hash[:16]}...; history does not join up"
                )
            else:
                detail = (
                    f"recorded digest {link.chain_hash[:16]}... does not match "
                    f"recomputed {recomputed[:16]}...; the event content changed"
                )
            failures.append(
                VerificationFailure(
                    kind=FailureKind.CHAIN_BREAK,
                    index=index,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    detail=detail,
                )
            )

        # 5: sequences must be contiguous. A gap means a deletion; a repeat or
        # a step backwards means a reorder.
        if expected_sequence is not None and event.sequence != expected_sequence:
            failures.append(
                VerificationFailure(
                    kind=FailureKind.ORDERING_INVALID,
                    index=index,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    detail=f"expected sequence {expected_sequence}, got {event.sequence}",
                )
            )
        expected_sequence = event.sequence + 1

        # 6: attribution, checked against the ring rather than the record.
        known_key = key_ring.public_key_for(event.identity.agent_id)
        if known_key is None:
            failures.append(
                VerificationFailure(
                    kind=FailureKind.UNKNOWN_ACTOR,
                    index=index,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    detail=f"actor {event.identity.agent_id!r} is not in the key ring",
                )
            )
        elif known_key != link.actor_public_key:
            failures.append(
                VerificationFailure(
                    kind=FailureKind.KEY_MISMATCH,
                    index=index,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    detail=(
                        f"record carries key {link.actor_public_key[:16]}... for "
                        f"{event.identity.agent_id!r}, but the ring holds {known_key[:16]}..."
                    ),
                )
            )

        # 7: the signature must verify under the ring's key for this actor.
        verifying_key = known_key or link.actor_public_key
        try:
            message = bytes.fromhex(link.chain_hash)
            signature_ok = verify_signature(verifying_key, link.signature, message)
        except (ValueError, TypeError):
            signature_ok = False
        if not signature_ok:
            failures.append(
                VerificationFailure(
                    kind=FailureKind.SIGNATURE_INVALID,
                    index=index,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    detail=(
                        f"signature does not verify for actor {event.identity.agent_id!r} "
                        "over this link's digest"
                    ),
                )
            )

        # 8: duplicate event ids would make provenance ambiguous (§42).
        if event.event_id in seen_event_ids:
            failures.append(
                VerificationFailure(
                    kind=FailureKind.DUPLICATE_EVENT_ID,
                    index=index,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    detail=f"event_id first seen at index {seen_event_ids[event.event_id]}",
                )
            )
        else:
            seen_event_ids[event.event_id] = index

        # Advance using the *recorded* digest so that one corrupted link does
        # not cascade into a false break at every subsequent record.
        previous_hash = link.chain_hash

    anchor_status, unanchored_suffix, anchor_failures = _verify_anchors(chain, anchors)
    failures.extend(anchor_failures)

    return VerificationResult(
        events=len(chain),
        failures=tuple(failures),
        anchor_status=anchor_status,
        unanchored_suffix=unanchored_suffix,
        head_hash=chain[-1].chain_hash if chain else None,
        key_ring_fingerprint=key_ring.fingerprint(),
        schema_versions=tuple(sorted(schema_versions)),
        actors=tuple(sorted(actors)),
    )
