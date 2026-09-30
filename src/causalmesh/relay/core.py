"""The relay: ingestion, sequencing, signing, chaining and fan-out (spec §55).

The relay is the single point through which every event enters the record. It
owns sequence assignment, so agents never choose their own ordering; it owns
signing and chaining, so the log is tamper-evident by construction; and it
owns fan-out, so what each arm's agents can see is decided in exactly one
place rather than scattered through the runtime.

What the relay explicitly does **not** do (§55):

- modify agent code or reasoning
- judge whether a task was completed correctly
- rewrite or drop events it has accepted

That last one is the important restraint. A relay that silently corrected a
malformed event would be editing evidence. Ingestion either accepts an event
as given, or rejects it loudly and records the rejection.

Fan-out is where the experimental manipulation lives, but the relay does not
know about arms. It is handed a delivery policy, and the harness decides
which policy an arm gets. Keeping that knowledge out of the relay is what
stops "C0 got no information" from depending on a conditional buried in the
ingestion path.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..claims import ClaimOutcome, ClaimRegistry
from ..crypto.chain import GENESIS_HASH, ChainedEvent, link_event
from ..crypto.keys import KeyPair, PublicKeyRing
from ..events.schema import Event, EventIdentity, EventType
from .store import ChainStore

__all__ = [
    "DeliveryPolicy",
    "IngestError",
    "IngestResult",
    "NullDelivery",
    "Relay",
    "RelayStats",
]


class IngestError(ValueError):
    """Raised when an event cannot be admitted to the record."""


class DeliveryPolicy(Protocol):
    """Decides which peers see an event, and in what form.

    The relay calls this and does nothing else with the decision. Making it a
    protocol keeps the arm manipulation outside the ingestion path: C0's
    guarantee is then a property of which policy object was installed, not of
    a branch inside the relay that could be reached by accident.
    """

    def recipients(self, event: Event, participants: Iterable[str]) -> tuple[str, ...]:
        """Return the agent ids that should be notified of this event."""
        ...


@dataclass(frozen=True, slots=True)
class NullDelivery:
    """Deliver nothing to anyone — the C0 policy.

    Isolation is enforced by installing this object, so a C0 run cannot leak
    peer information even if every other component tried to send some.
    """

    def recipients(self, event: Event, participants: Iterable[str]) -> tuple[str, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class IngestResult:
    """The outcome of admitting one event.

    `delivered_to` is recorded rather than inferred so that "who could have
    known what, and when" is answerable directly from the record (§57, §96)
    instead of being reconstructed from arm configuration afterwards.
    """

    accepted: bool
    chained: ChainedEvent | None
    sequence: int | None
    delivered_to: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "chain_hash": self.chained.chain_hash if self.chained else None,
            "delivered_to": list(self.delivered_to),
            "reason": self.reason,
            "sequence": self.sequence,
        }


@dataclass
class RelayStats:
    """Counters for the relay's own overhead (§85).

    The specification is explicit that the coordination mechanism must not be
    claimed to be cheap without measuring it, so the relay measures itself.
    """

    events_ingested: int = 0
    events_rejected: int = 0
    deliveries: int = 0
    append_latency_us: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        latencies = sorted(self.append_latency_us)
        return {
            "append_latency_p50_us": _percentile(latencies, 50),
            "append_latency_p99_us": _percentile(latencies, 99),
            "deliveries": self.deliveries,
            "events_ingested": self.events_ingested,
            "events_rejected": self.events_rejected,
        }


def _percentile(sorted_values: list[int], percentile: int) -> int | None:
    """Nearest-rank percentile; None when there is nothing to report.

    Returning None rather than 0 for an empty series keeps "no measurements"
    distinguishable from "measured zero" in the metrics output.
    """
    if not sorted_values:
        return None
    rank = max(1, (percentile * len(sorted_values) + 99) // 100)
    return sorted_values[min(rank, len(sorted_values)) - 1]


class Relay:
    """Owns the authoritative event record for one run.

    Thread-safe: a single lock serializes ingestion so sequence assignment and
    chain extension cannot interleave. Two events sharing a sequence number,
    or a chain link computed against a stale head, would corrupt the record
    irrecoverably — and unlike a claim conflict, there would be no denial
    record to reveal it afterwards.
    """

    def __init__(
        self,
        *,
        run_id: str,
        keypairs: dict[str, KeyPair],
        store: ChainStore | None = None,
        delivery: DeliveryPolicy | None = None,
        claims: ClaimRegistry | None = None,
        participants: Iterable[str] = (),
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.run_id = run_id
        self._keypairs = dict(keypairs)
        self._store = store if store is not None else ChainStore()
        self._delivery: DeliveryPolicy = delivery if delivery is not None else NullDelivery()
        self._claims = claims
        self._participants = tuple(participants) or tuple(sorted(self._keypairs))
        self._clock = clock or _monotonic_micros

        self._lock = threading.Lock()
        self._sequence = 0
        self._head = GENESIS_HASH
        self._inboxes: dict[str, list[Event]] = {agent: [] for agent in self._participants}
        self._seen_event_ids: set[str] = set()
        self.stats = RelayStats()

    @property
    def head_hash(self) -> str:
        """The current chain head — what an anchor would record (§28)."""
        with self._lock:
            return self._head

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence

    @property
    def actors(self) -> tuple[str, ...]:
        """Every actor this relay can attribute events to, sorted."""
        return tuple(sorted(self._keypairs))

    def has_key(self, agent_id: str) -> bool:
        """Whether an event from `agent_id` could be signed and ingested.

        A question asked before acting, so a caller can refuse to run a call
        whose evidence the relay would then have to reject.
        """
        return agent_id in self._keypairs

    def key_ring(self) -> PublicKeyRing:
        """The public keys an offline verifier needs (§26)."""
        return PublicKeyRing.from_keypairs(self._keypairs)

    def ingest(
        self,
        *,
        event_id: str,
        agent_id: str,
        event_type: EventType,
        identity: EventIdentity,
        timestamp_us: int,
        paths: tuple[str, ...] = (),
        references: tuple[str, ...] = (),
        parent_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> IngestResult:
        """Admit one event: assign a sequence, chain it, sign it, persist, fan out.

        The relay assigns `sequence` itself. An agent-chosen sequence would
        let a fast agent claim an earlier position than it earned, which would
        misrepresent causality in exactly the way the staleness measurement
        (§23) depends on being correct.
        """
        started = self._clock()

        if agent_id not in self._keypairs:
            self.stats.events_rejected += 1
            return IngestResult(
                accepted=False,
                chained=None,
                sequence=None,
                reason=f"actor {agent_id!r} has no registered key; cannot attribute this event",
            )
        if identity.agent_id != agent_id:
            self.stats.events_rejected += 1
            return IngestResult(
                accepted=False,
                chained=None,
                sequence=None,
                reason=(
                    f"identity claims {identity.agent_id!r} but the event was submitted by "
                    f"{agent_id!r}; refusing to record a misattributed event"
                ),
            )
        if identity.run_id != self.run_id:
            self.stats.events_rejected += 1
            return IngestResult(
                accepted=False,
                chained=None,
                sequence=None,
                reason=(
                    f"event belongs to run {identity.run_id!r}, not {self.run_id!r}; "
                    "arms must not share a chain"
                ),
            )

        with self._lock:
            if event_id in self._seen_event_ids:
                self.stats.events_rejected += 1
                return IngestResult(
                    accepted=False,
                    chained=None,
                    sequence=None,
                    reason=f"duplicate event_id {event_id!r}",
                )

            sequence = self._sequence
            try:
                event = Event(
                    event_id=event_id,
                    identity=identity,
                    event_type=event_type,
                    sequence=sequence,
                    timestamp_us=timestamp_us,
                    paths=paths,
                    references=references,
                    parent_id=parent_id,
                    payload=payload or {},
                )
            except ValueError as exc:
                self.stats.events_rejected += 1
                return IngestResult(
                    accepted=False, chained=None, sequence=None, reason=f"invalid event: {exc}"
                )

            chained = link_event(event, self._head, self._keypairs[agent_id])
            self._store.append(chained)
            self._head = chained.chain_hash
            self._sequence += 1
            self._seen_event_ids.add(event_id)

            recipients = tuple(
                agent
                for agent in self._delivery.recipients(event, self._participants)
                if agent != agent_id and agent in self._inboxes
            )
            for agent in recipients:
                self._inboxes[agent].append(event)

            self.stats.events_ingested += 1
            self.stats.deliveries += len(recipients)
            self.stats.append_latency_us.append(max(0, self._clock() - started))

        return IngestResult(
            accepted=True,
            chained=chained,
            sequence=sequence,
            delivered_to=recipients,
            reason="accepted",
        )

    def resume(self, *, head_hash: str, next_sequence: int, event_ids: Iterable[str]) -> None:
        """Continue an existing chain instead of starting at genesis.

        For a relay whose store already holds records from an earlier process.
        The caller has verified those records (the SDK's `EvidenceStore` does,
        against this session's key ring); this method only moves the relay's
        head, sequence and duplicate-id set to where the chain left off, so the
        next event links to `head_hash` and takes `next_sequence`.

        Refuses on a relay that has already ingested anything, and on a head
        that is not a SHA-256 digest: continuing from a wrong head would sign a
        chain that does not join up, which is a failure only the verifier
        would find.
        """
        try:
            head_bytes = bytes.fromhex(head_hash)
        except (ValueError, TypeError) as exc:
            raise IngestError(f"resume head is not valid hex: {head_hash!r}") from exc
        if len(head_bytes) != 32:
            raise IngestError(f"resume head must be a 32-byte SHA-256 digest, got {head_hash!r}")
        if next_sequence < 1:
            raise IngestError(
                f"cannot resume at sequence {next_sequence}; an empty chain starts fresh"
            )
        with self._lock:
            if self._sequence != 0 or self._head != GENESIS_HASH:
                raise IngestError("resume() is only valid on a relay that has ingested nothing")
            self._head = head_hash
            self._sequence = next_sequence
            self._seen_event_ids = set(event_ids)

    def pending_for(self, agent_id: str) -> tuple[Event, ...]:
        """Peek at an agent's undelivered events without consuming them."""
        with self._lock:
            return tuple(self._inboxes.get(agent_id, ()))

    def drain(self, agent_id: str) -> tuple[Event, ...]:
        """Take and clear an agent's pending events."""
        with self._lock:
            pending = tuple(self._inboxes.get(agent_id, ()))
            if agent_id in self._inboxes:
                self._inboxes[agent_id] = []
            return pending

    def may_write(self, *, path: str, agent_id: str, now_us: int) -> ClaimOutcome:
        """Ask the claim gate whether a write is permitted.

        With no registry installed (C0, C1, C2) every write is permitted, and
        the reason says so explicitly rather than returning a bare True. The
        arm's behaviour is then visible in the record instead of being
        implied by a missing component.
        """
        if self._claims is None:
            return ClaimOutcome(True, None, "no claim registry installed for this arm")
        return self._claims.may_write(
            path=path, agent_id=agent_id, run_id=self.run_id, now_us=now_us
        )

    def export(self, destination: Path) -> dict[str, Path]:
        """Write the chain and key ring for offline verification (§26, §82).

        The export is deliberately self-contained: chain plus keys is
        everything the verifier needs, and nothing here refers back to the
        relay.
        """
        destination.mkdir(parents=True, exist_ok=True)
        chain_path = self._store.export(destination / "chain.jsonl")

        import json

        keyring_path = destination / "keyring.json"
        keyring_path.write_text(
            json.dumps(self.key_ring().to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {"chain": chain_path, "keyring": keyring_path}

    def records(self) -> list[dict[str, Any]]:
        """The chain in its persisted form, for in-process verification."""
        return self._store.records()

    def summary(self) -> dict[str, Any]:
        """A relay summary for `relay_summary.json` (§60)."""
        return {
            "head_hash": self.head_hash,
            "key_ring_fingerprint": self.key_ring().fingerprint(),
            "participants": list(self._participants),
            "run_id": self.run_id,
            "sequence": self.sequence,
            "stats": self.stats.to_dict(),
        }


def _monotonic_micros() -> int:
    """A monotonic clock in microseconds, for latency measurement only."""
    import time

    return time.monotonic_ns() // 1_000
